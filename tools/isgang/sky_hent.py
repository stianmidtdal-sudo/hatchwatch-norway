"""
Skyjobben — satellitt-isgang for hele områder, uten at PC-en må stå på.

Kjøres hver natt av GitHub Actions (.github/workflows/isgang.yml), men kan
også kjøres lokalt. Tar områdene i sky/plan.json i rekkefølge, henter hvert
vann-år som mangler (én forespørsel per vann og år — det billigste i kvote),
regner intervallet med den låste metoden (valgt_metode.json) med én gang, og
lagrer BARE resultatet. Rådataene kastes; de er for store for et repo.

Stopper når tidsbudsjettet er brukt (GitHub gir maks 6 timer per kjøring)
eller når månedens kvotetak er nådd. Alt den ikke rakk, tas neste natt.

  python sky_hent.py                        følg sky/plan.json
  python sky_hent.py nordmarka              ett område
  python sky_hent.py nordmarka --maks-vannaar 5    liten prøve

Innlogging: CDSE_CLIENT_ID / CDSE_CLIENT_SECRET fra miljøet (GitHub-
hemmeligheter) eller fra tools/isgang/.env lokalt.

Filer per område i sky/:
  vann_<id>.json     vannene (fra NVE Innsjødatabase, >= 10 ha i boksen)
  isgang_<id>.json   resultat per vann og år + kvoteforbruk per måned.
                     Per vann-år: status, intervall (lo/hi), antall pass og
                     klare pass, PU, og «p» = kompakt liste over alle pass
                     (dato og pikseltall) så metoden kan regnes om senere.
  status_<id>.md     lesbar oppsummering
"""
import argparse
import importlib.util
import io
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import date

HER = os.path.dirname(os.path.abspath(__file__))
SKY = os.path.join(HER, "sky")


def last(n, f):
    s = importlib.util.spec_from_file_location(n, os.path.join(HER, f))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


h = last("h", "02_hent_wic.py")
h4 = last("h4", "04_hent_s2.py")
v3 = last("v3", "03_valider.py")
v5 = last("v5", "05_valider_s2.py")
a7 = last("a7", "07_andre_steder.py")

NVE = "https://kart.nve.no/enterprise/rest/services/Innsjodatabase2/MapServer/5/query"
MIN_HA = 10.0
MAKS_HA = 3000.0           # Randsfjorden (14 000 ha) kostet 250 PU per år — store innsjøer holdes utenfor
AAR = list(range(2017, 2027))
MAKS_FORSOK = 3            # vann-år som feiler hos Copernicus prøves så mange netter
TIMER = 5.25               # tidsbudsjett per kjøring (GitHub-grensen er 6 t)
MAKS_PU_MND = 20000        # av 30 000 — resten holdes av til manuelle kjøringer


def nve(p):
    with urllib.request.urlopen(NVE + "?" + urllib.parse.urlencode(p), timeout=300) as r:
        return json.load(r)


def piksel(ha):
    return 20 if ha <= 150 else (40 if ha <= 600 else 60)


def vannliste(omr):
    sti = os.path.join(SKY, "vann_%s.json" % omr["id"])
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))["vann"]
    liste, offset = [], 0
    x0, y0, x1, y1 = omr["bbox"]
    while True:
        p = dict(where="areal_km2 >= %s AND areal_km2 <= %s" % (MIN_HA / 100.0, MAKS_HA / 100.0),
                 geometry="%f,%f,%f,%f" % tuple(omr["bbox"]), geometryType="esriGeometryEnvelope",
                 inSR="4326", spatialRel="esriSpatialRelIntersects",
                 outFields="vatnlnr,navn,hoyde,areal_km2", returnGeometry="true", outSR="4326",
                 geometryPrecision="3", f="json",
                 resultOffset=str(offset), resultRecordCount="1000", orderByFields="vatnlnr")
        r = nve(p)
        for f in r.get("features", []):
            a = f["attributes"]
            ring = f["geometry"]["rings"][0]
            cx = sum(pt[0] for pt in ring) / len(ring)
            cy = sum(pt[1] for pt in ring) / len(ring)
            if not (x0 <= cx <= x1 and y0 <= cy <= y1):
                continue                       # vann som bare så vidt berører boksen hører til naboområdet
            ha = round((a["areal_km2"] or 0) * 100, 1)
            liste.append({"vatnlnr": a["vatnlnr"], "navn": a["navn"], "moh": a["hoyde"], "areal_ha": ha, "piksel_m": piksel(ha)})
        if not r.get("exceededTransferLimit"):
            break
        offset += len(r.get("features", []))
    liste.sort(key=lambda v: -v["areal_ha"])
    os.makedirs(SKY, exist_ok=True)
    json.dump({"omraade": omr, "min_ha": MIN_HA, "hentet": date.today().isoformat(), "vann": liste},
              io.open(sti, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%s: %d vann >= %.0f ha funnet i NVE Innsjødatabase." % (omr["navn"], len(liste), MIN_HA))
    return liste


def polygoner(lnr_liste):
    ut = {}
    for i in range(0, len(lnr_liste), 200):
        p = dict(where="vatnlnr IN (%s)" % ",".join(str(x) for x in lnr_liste[i:i + 200]),
                 outFields="vatnlnr", returnGeometry="true", outSR="32633", f="geojson")
        for f in nve(p)["features"]:
            ut[f["properties"]["vatnlnr"]] = f["geometry"]
    return ut


def resultat_sti(omr_id):
    return os.path.join(SKY, "isgang_%s.json" % omr_id)


def les_resultat(omr_id, valg):
    sti = resultat_sti(omr_id)
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))
    return {"omraade": omr_id, "metode": valg, "terskel": v5.TERSKEL, "forbruk_pu": {}, "vann": {}}


def skriv_resultat(res):
    json.dump(res, io.open(resultat_sti(res["omraade"]), "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def passliste(obs, valg):
    """Kompakt liste over ALLE pass i vinduet, så metoden kan regnes om senere uten
    satellitten (Stian 2026-10-08: «vi bør få denne dataen så godt som mulig nå»).
    Format per pass: MMDD:n/mørk/lys_is/lys_annet/sky  — pikseltall med den låste
    lyshets- og ndsi-terskelen (tv, tn). Skilletegn «;». Med dette kan både
    klar-pass-regelen og isandel-terskelen endres i ettertid; bare tv/tn er låst."""
    ut = []
    for r in sorted(obs, key=lambda r: r["dato"]):
        mork, lys_is, lys_annet = v5.klassifiser(r, valg["tv"], valg["tn"])
        ut.append("%s:%d/%d/%d/%d/%d" % (r["dato"][5:7] + r["dato"][8:10], int(r["n"]), mork, lys_is, lys_annet, int(r["scl_sky"])))
    return ";".join(ut)


def ferdig(res, lnr, y):
    post = res["vann"].get(str(lnr), {}).get("aar", {}).get(str(y))
    if not post:
        return False
    if post["status"] == "feil":
        return post.get("forsok", 0) >= MAKS_FORSOK
    return "p" in post          # hentet før passlista kom med (natt 1) → hentes på nytt


def status_md(omr, vann, res):
    d = v3.d
    rader = [(int(y), p) for v in res["vann"].values() for y, p in v["aar"].items()]
    ok = [(y, (d(p["hi"]) - d(p["lo"])).days) for y, p in rader if p["status"] == "ok"]
    L = ["# Satellitt-isgang: %s\n" % omr["navn"],
         "Sist kjørt %s. %d vann på %.0f–%.0f ha med midtpunkt i boksen (NVE Innsjødatabase), %d år (2017–2026) = %d vann-år å hente.\n"
         % (date.today().isoformat(), len(vann), MIN_HA, MAKS_HA, len(AAR), len(vann) * len(AAR)),
         "| | |", "|---|---|",
         "| Vann-år hentet | %d av %d |" % (len(rader), len(vann) * len(AAR)),
         "| Med intervall | %d (%.0f %%) |" % (len(ok), 100.0 * len(ok) / len(rader) if rader else 0)]
    if ok:
        b = [x for _, x in ok]
        L += ["| Median bredde | %d d |" % statistics.median(b),
              "| Bredde <= 7 d | %.0f %% |" % (100.0 * sum(x <= 7 for x in b) / len(b)),
              "| Bredde > 14 d | %.0f %% |" % (100.0 * sum(x > 14 for x in b) / len(b))]
    feil = sum(1 for _, p in rader if p["status"] == "feil")
    L += ["| Feilet hos Copernicus | %d |" % feil,
          "| Kvote brukt | %s |" % ", ".join("%s: %.0f PU" % kv for kv in sorted(res["forbruk_pu"].items())), ""]
    L += ["## Per år\n", "| År | Vann-år | Med intervall | Median bredde | Median midtdato |", "|---|---|---|---|---|"]
    for y in AAR:
        ry = [p for yy, p in rader if yy == y]
        oy = [p for p in ry if p["status"] == "ok"]
        if not ry:
            continue
        if oy:
            br = statistics.median((d(p["hi"]) - d(p["lo"])).days for p in oy)
            midt = sorted(d(p["lo"]) + (d(p["hi"]) - d(p["lo"])) / 2 for p in oy)[len(oy) // 2].isoformat()
        else:
            br, midt = "–", "–"
        L.append("| %d | %d | %d | %s d | %s |" % (y, len(ry), len(oy), br, midt))
    L += ["", "Metode: `valgt_metode.json` (låst), isandel under %.2f = åpent, bekreftet av neste klare pass. "
          "Intervall = [siste pass med is, første pass åpent]. Ingenting her er lagt inn i dashboardet." % v5.TERSKEL]
    io.open(os.path.join(SKY, "status_%s.md" % omr["id"]), "w", encoding="utf-8").write("\n".join(L) + "\n")


def kjor(omr, start, timer, maks_pu_mnd, maks_vannaar):
    """Returnerer 'ferdig' når området er komplett, ellers 'stopp' (tid/kvote/prøvegrense)."""
    valg = json.load(io.open(a7.VALG_FIL, encoding="utf-8"))
    vann = vannliste(omr)
    res = les_resultat(omr["id"], valg)
    mnd = date.today().strftime("%Y-%m")
    trenger = [(v, y) for v in vann for y in AAR if not ferdig(res, v["vatnlnr"], y)]
    print("%s: %d vann, %d vann-år gjenstår." % (omr["navn"], len(vann), len(trenger)), flush=True)
    if not trenger:
        status_md(omr, vann, res)
        return "ferdig"
    geom = polygoner(sorted({v["vatnlnr"] for v, _ in trenger}))
    env = dict(os.environ)
    env.update(h.les_env())
    token = h.hent_token(env)
    ant, utfall, feil_paa_rad = 0, "ferdig", 0
    for v, y in trenger:
        if time.time() - start > timer * 3600:
            print("Tidsbudsjettet (%.2f t) er brukt. Resten tas neste gang." % timer, flush=True)
            utfall = "stopp"
            break
        if res["forbruk_pu"].get(mnd, 0) >= maks_pu_mnd:
            print("Månedens kvotetak (%d PU) er nådd. Fortsetter neste måned." % maks_pu_mnd, flush=True)
            utfall = "stopp"
            break
        if maks_vannaar and ant >= maks_vannaar:
            utfall = "stopp"
            break
        lnr = str(v["vatnlnr"])
        post_v = res["vann"].setdefault(lnr, {"navn": v["navn"], "moh": v["moh"], "areal_ha": v["areal_ha"], "aar": {}})
        g = geom.get(v["vatnlnr"])
        if not g:
            post_v["aar"][str(y)] = {"status": "feil", "forsok": MAKS_FORSOK, "feil": "mangler polygon i NVE"}
            continue
        k = h4.bygg(g, y)
        k["aggregation"]["timeRange"] = {"from": "%d-02-01T00:00:00Z" % y, "to": "%d-08-01T00:00:00Z" % y}
        k["aggregation"]["resx"] = k["aggregation"]["resy"] = v["piksel_m"]
        try:
            svar, pu = h.send(token, k)
        except SystemExit as e:
            tekst = str(e)
            # Tom kvote hos Copernicus (429/403) er ikke vannets feil: stopp kjøringen
            # uten å bruke opp vann-årets forsøk. Kontoen deler kvote med PC-kjøringene.
            if "HTTP 429" in tekst or "HTTP 403" in tekst or "quota" in tekst.lower():
                print("Copernicus avviser: kvoten er trolig brukt opp denne måneden. Stopper. (%s)" % tekst[:100], flush=True)
                utfall = "stopp"
                break
            gammel = post_v["aar"].get(str(y), {})
            post_v["aar"][str(y)] = {"status": "feil", "forsok": gammel.get("forsok", 0) + 1, "feil": tekst[:120]}
            print("  feilet: %s %d (%s)" % (v["navn"], y, tekst[:80]), flush=True)
            feil_paa_rad += 1
            if feil_paa_rad >= 5:
                print("Fem feil på rad — Copernicus har trolig problemer. Stopper for i natt.", flush=True)
                utfall = "stopp"
                break
            continue
        feil_paa_rad = 0
        obs = h4.flat_ut(svar)
        kl = a7.klare(obs, valg["tv"], valg["tn"], valg["regel"])
        r = v3.finn_isgang(kl, v5.TERSKEL)
        post = {"status": r["status"], "pass": len(obs), "klare": len(kl), "pu": round(pu or 0, 1),
                "p": passliste(obs, valg)}
        if r["status"] == "ok":
            post["lo"], post["hi"] = r["lo"], r["hi"]
        elif kl:
            post["siste_klare"] = kl[-1][0]
        post_v["aar"][str(y)] = post
        res["forbruk_pu"][mnd] = round(res["forbruk_pu"].get(mnd, 0) + (pu or 0), 1)
        ant += 1
        if ant % 25 == 0:
            skriv_resultat(res)
            print("  %d vann-år hentet, %.0f PU denne måneden (sist %s %d)" % (ant, res["forbruk_pu"][mnd], v["navn"], y), flush=True)
    skriv_resultat(res)
    status_md(omr, vann, res)
    print("%s: %d vann-år hentet i denne kjøringen." % (omr["navn"], ant), flush=True)
    return utfall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("omraade", nargs="?")
    ap.add_argument("--timer", type=float, default=TIMER)
    ap.add_argument("--maks-pu-mnd", type=float, default=MAKS_PU_MND)
    ap.add_argument("--maks-vannaar", type=int, default=0)
    a = ap.parse_args()
    start = time.time()
    omr = {o["id"]: o for o in json.load(io.open(os.path.join(SKY, "omraader.json"), encoding="utf-8"))["omraader"]}
    if a.omraade:
        rekke = [a.omraade]
    else:
        rekke = json.load(io.open(os.path.join(SKY, "plan.json"), encoding="utf-8"))["rekkefolge"]
    for oid in rekke:
        if oid not in omr:
            raise SystemExit("Ukjent område: %s (se sky/omraader.json)" % oid)
        if kjor(omr[oid], start, a.timer, a.maks_pu_mnd, a.maks_vannaar) == "stopp":
            break
    print("Brukt %.1f min." % ((time.time() - start) / 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
