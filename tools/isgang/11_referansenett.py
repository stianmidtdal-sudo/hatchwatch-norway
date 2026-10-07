"""
Landsdekning, steg 1 — referansenett rundt lokasjonene.

Alle vann på minst MIN_HA hektar innenfor RADIUS_KM fra hver lokasjon i
dashboardet, med full satellitthistorikk 2017–2026. Dette gir nabo-regelen
(nabo.py) ekte naboer utenfor Nordmarka, og lar oss teste om regelen virker
når historikken kommer fra satellitten i stedet for fra manuell avlesning.

Kommandoer:
  python 11_referansenett.py tell            finn vannene, skriv referansenett.json (ingen kvote)
  python 11_referansenett.py hent [--del i/n] [--maks-pu N]
                                             hent 2017–2026, kan kjøres i flere parallelle deler
  python 11_referansenett.py isgang          intervall per vann og år med låst metode
  python 11_referansenett.py test            nabo-regel med satellitt-historikk mot de 30 fasit-vannene

Rådata: data/raa/l2a_ref/<vatnlnr>_<år>.json (hentes ikke på nytt).
Piksler: 20 m opptil 150 ha, 40 m opptil 600 ha, 60 m over det.
"""
import argparse
import csv
import importlib.util
import io
import json
import math
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date

HER = os.path.dirname(os.path.abspath(__file__))


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
nabo = last("nabo", "nabo.py")

MIN_HA = 10.0
RADIUS_KM = 15.0
AAR = list(range(2017, 2027))
NETT_FIL = os.path.join(HER, "referansenett.json")
RAA = os.path.join(h.RAA, "l2a_ref")
ISGANG_FIL = os.path.join(HER, "referansenett_isgang.json")
NVE = "https://kart.nve.no/enterprise/rest/services/Innsjodatabase2/MapServer/5/query"


def lokasjoner():
    """Unike punkter fra dashboard.html (lat, lon, id)."""
    import re
    html = io.open(os.path.join(HER, "..", "..", "dashboard.html"), encoding="utf-8").read()
    start = html.index("const LOCATIONS = {")
    blokk = html[start:html.index("\n};", start)]
    ut, sett = [], set()
    for m in re.finditer(r"\n    ([a-z_]+): \{\n(.*?)(?=\n    [a-z_]+: \{\n|\Z)", blokk, re.S):
        lid, kropp = m.group(1), m.group(2)
        p = re.search(r"lat:\s*([0-9.]+),\s*lon:\s*([0-9.]+)", kropp)
        if not p or "_test" in lid:
            continue
        key = (round(float(p.group(1)), 2), round(float(p.group(2)), 2))
        if key in sett:
            continue
        sett.add(key)
        ut.append({"id": lid, "lat": float(p.group(1)), "lon": float(p.group(2))})
    return ut


def tell():
    lok = lokasjoner()
    vann = {}
    for u in lok:
        dlat = RADIUS_KM / 111.2
        dlon = RADIUS_KM / (111.2 * math.cos(math.radians(u["lat"])))
        p = dict(where="areal_km2 >= %s" % (MIN_HA / 100.0),
                 geometry="%f,%f,%f,%f" % (u["lon"] - dlon, u["lat"] - dlat, u["lon"] + dlon, u["lat"] + dlat),
                 geometryType="esriGeometryEnvelope", inSR="4326", spatialRel="esriSpatialRelIntersects",
                 outFields="vatnlnr,navn,hoyde,areal_km2", returnGeometry="true", outSR="4326",
                 geometryPrecision="4", f="json", resultRecordCount="4000")
        r = json.load(urllib.request.urlopen(NVE + "?" + urllib.parse.urlencode(p), timeout=180))
        n = 0
        for f in r.get("features", []):
            a = f["attributes"]
            ring = f["geometry"]["rings"][0]
            cx = sum(pt[0] for pt in ring) / len(ring)
            cy = sum(pt[1] for pt in ring) / len(ring)
            km = math.hypot((cx - u["lon"]) * math.cos(math.radians(u["lat"])) * 111.2, (cy - u["lat"]) * 111.2)
            if km > RADIUS_KM:
                continue
            n += 1
            v = vann.setdefault(a["vatnlnr"], {"vatnlnr": a["vatnlnr"], "navn": a["navn"], "moh": a["hoyde"],
                                               "areal_ha": round((a["areal_km2"] or 0) * 100, 1), "lok": []})
            v["lok"].append(u["id"])
        print("%-16s %3d vann >= %.0f ha innen %.0f km" % (u["id"], n, MIN_HA, RADIUS_KM))
    liste = sorted(vann.values(), key=lambda v: (v["lok"][0], -v["areal_ha"]))
    for v in liste:
        v["piksel_m"] = 20 if v["areal_ha"] <= 150 else (40 if v["areal_ha"] <= 600 else 60)
    json.dump({"min_ha": MIN_HA, "radius_km": RADIUS_KM, "vann": liste}, io.open(NETT_FIL, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    pu = sum(3.0 * (v["areal_ha"] / 40.0) * (20.0 / v["piksel_m"]) ** 2 for v in liste)   # grovt: Øyungen 75 ha ≈ 3 PU/år
    print("\nTotalt %d unike vann. Grovt kvoteanslag for 10 år: %.0f PU (kalibrert mot Nordmarka)." % (len(liste), 10 * pu))
    print("Skrevet referansenett.json")


FASIT_OMRAADER = {"kautokeino", "alta", "porsanger", "roros", "oslo", "ostmarka", "vestfjella", "mo_i_rana",
                  "borgefjell", "lierne", "trondheim", "rena", "finnemarka", "hardangervidda", "bergen"}


def hent(del_, maks_pu, aar=None, kun_fasit=False):
    """Copernicus behandler forespørslene i kø, så parallelle deler gir lite.
    Bruk heller --aar 2022-2026 --kun-fasit for en rask første runde."""
    nett = json.load(io.open(NETT_FIL, encoding="utf-8"))["vann"]
    i, n = (int(x) for x in del_.split("/")) if del_ else (1, 1)
    mine = [v for k, v in enumerate(nett) if k % n == i - 1]
    if kun_fasit:
        mine = [v for v in mine if any(l in FASIT_OMRAADER for l in v["lok"])]
    aarliste = AAR
    if aar:
        a, b = (int(x) for x in aar.split("-"))
        aarliste = list(range(a, b + 1))
    os.makedirs(RAA, exist_ok=True)
    trenger = [v for v in mine if not all(os.path.exists(os.path.join(RAA, "%s_%d.json" % (v["vatnlnr"], y))) for y in aarliste)]
    print("Del %d/%d: %d vann, %d trenger henting, år %d–%d." % (i, n, len(mine), len(trenger), aarliste[0], aarliste[-1]))
    if not trenger:
        return
    p = dict(where="vatnlnr IN (%s)" % ",".join(str(v["vatnlnr"]) for v in trenger),
             outFields="vatnlnr", returnGeometry="true", outSR="32633", f="geojson")
    with urllib.request.urlopen(NVE + "?" + urllib.parse.urlencode(p), timeout=300) as r:
        geom = {f["properties"]["vatnlnr"]: f["geometry"] for f in json.load(r)["features"]}
    token = h.hent_token(h.les_env())
    pu_sum, ant = 0.0, 0
    for v in trenger:
        g = geom.get(v["vatnlnr"])
        if not g:
            print("  mangler polygon:", v["navn"], v["vatnlnr"])
            continue
        for y in aarliste:
            sti = os.path.join(RAA, "%s_%d.json" % (v["vatnlnr"], y))
            if os.path.exists(sti):
                continue
            if maks_pu and pu_sum >= maks_pu:
                print("Stoppet ved kvotetak %.0f PU. Kjør igjen senere for resten." % maks_pu)
                return
            k = h4.bygg(g, y)
            k["aggregation"]["timeRange"] = {"from": "%d-02-01T00:00:00Z" % y, "to": "%d-08-01T00:00:00Z" % y}
            k["aggregation"]["resx"] = k["aggregation"]["resy"] = v["piksel_m"]
            try:
                svar, pu = h.send(token, k)
            except SystemExit as e:
                # Ett vann-år som Copernicus ikke klarer skal ikke stoppe hele kjøringen.
                print("  HOPPER OVER %s %d: %s" % (v["navn"], y, str(e)[:120]), flush=True)
                continue
            json.dump(svar, io.open(sti, "w", encoding="utf-8"))
            pu_sum += pu or 0
            ant += 1
            if ant % 25 == 0:
                print("  %d vann-år hentet, %.0f PU så langt (sist %s %d)" % (ant, pu_sum, v["navn"], y), flush=True)
    print("Ferdig: %d vann-år, %.0f PU." % (ant, pu_sum))


def les_ref():
    serier = {}
    if not os.path.isdir(RAA):
        return serier
    for fil in sorted(os.listdir(RAA)):
        lnr, y = fil[:-5].split("_")
        for rad in h4.flat_ut(json.load(io.open(os.path.join(RAA, fil), encoding="utf-8"))):
            serier.setdefault((int(lnr), int(y)), []).append(rad)
    return serier


def isgang():
    valg = json.load(io.open(a7.VALG_FIL, encoding="utf-8"))
    nett = json.load(io.open(NETT_FIL, encoding="utf-8"))["vann"]
    serier = les_ref()
    ut, n_ok = {}, 0
    for v in nett:
        per_aar = {}
        for y in AAR:
            obs = serier.get((v["vatnlnr"], y))
            if not obs:
                continue
            r = v3.finn_isgang(a7.klare(obs, valg["tv"], valg["tn"], valg["regel"]), v5.TERSKEL)
            per_aar[y] = r
            n_ok += r["status"] == "ok"
        if per_aar:
            ut[str(v["vatnlnr"])] = {"navn": v["navn"], "moh": v["moh"], "areal_ha": v["areal_ha"], "aar": per_aar}
    json.dump(ut, io.open(ISGANG_FIL, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Vann med data: %d. Vann-år med intervall: %d." % (len(ut), n_ok))


def midtdato(r):
    lo, hi = v3.d(r["lo"]), v3.d(r["hi"])
    return (lo + (hi - lo) / 2).isoformat()


def test(min_aar=None, maks_spredning=None):
    """Nabo-regel der naboenes historikk er satellittens egne midtpunkt, mot de 30 fasit-vannene.

    NB (6. okt 2026): referansenettet har foreløpig bare 2022–2026. Med årets
    dato holdt utenfor gir det høyst 4 felles år, så standardkravet på 5 kan
    aldri oppfylles. Første kjøring viste derfor «ingen nabo» nesten overalt —
    det var kravet, ikke regelen, som slo inn. Kjør med --min-aar 4 til hele
    historikken er hentet. Spredningskravet skal IKKE løsnes for å få treff;
    en løsere variant kan vises ved siden av, merket som det."""
    if min_aar is not None:
        nabo.MIN_FELLES_AAR = min_aar
    if maks_spredning is not None:
        nabo.MAKS_SPREDNING = maks_spredning
    valg = json.load(io.open(a7.VALG_FIL, encoding="utf-8"))
    nett = {v["vatnlnr"]: v for v in json.load(io.open(NETT_FIL, encoding="utf-8"))["vann"]}
    ref = json.load(io.open(ISGANG_FIL, encoding="utf-8"))
    ref_serier = les_ref()
    # Posisjoner for alle (32633-tyngdepunkt) — hent polygoner for nettet + fasitvann
    fasit_n = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    gj_n = json.load(io.open(os.path.join(HER, "grunnlag", "vann.geojson"), encoding="utf-8"))
    meta_a = {m["lok"]: m for m in json.load(io.open(os.path.join(HER, "grunnlag", "andre_vann_meta.json"), encoding="utf-8"))}
    fasit_a = {lok: a7.les_fasit_andre()[lok] for lok in meta_a}
    lnr_alle = sorted(set(nett) | {f["properties"]["vatnlnr"] for f in gj_n["features"]} | {m["vatnlnr"] for m in meta_a.values()})
    pos = {}
    for i in range(0, len(lnr_alle), 300):
        p = dict(where="vatnlnr IN (%s)" % ",".join(str(x) for x in lnr_alle[i:i + 300]),
                 outFields="vatnlnr", returnGeometry="true", outSR="32633", f="geojson")
        with urllib.request.urlopen(NVE + "?" + urllib.parse.urlencode(p), timeout=300) as r:
            for f in json.load(r)["features"]:
                pos[f["properties"]["vatnlnr"]] = nabo.tyngdepunkt(f["geometry"])

    # Satellitt-«fasit» for referansenettet: midtpunkt der status ok
    sat_hist = {}
    for lnr_s, v in ref.items():
        hist = {str(y): midtdato(r) for y, r in v["aar"].items() if r["status"] == "ok"}
        if hist:
            sat_hist[int(lnr_s)] = hist

    # Fasit-vannene (test-objektene): Nordmarka 16 + 14 andre
    objekter = []
    for f in gj_n["features"]:
        pr = f["properties"]
        objekter.append((pr["navn"], pr["vatnlnr"], fasit_n[pr["navn"]], v5.les_s2(), pr["navn"]))
    ser_a = {}
    for r in csv.DictReader(io.open(a7.CSV_ANDRE, encoding="utf-8-sig"), delimiter=";"):
        ser_a.setdefault((r["vann"], int(r["aar"])), []).append(r)
    for lok, m in meta_a.items():
        objekter.append(("%s (%s)" % (lok, m["navn"]), m["vatnlnr"], fasit_a[lok], ser_a, lok))

    linjer = ["# Nabo-regel med satellitt-historikk fra referansenettet\n",
              "Naboer: vann i referansenettet (%d vann med data). Historikk = satellittens egne midtpunkt. "
              "Sikringer som i nabo.py (≥%d felles år, spredning ≤ %.0f d, ≤ %.0f km). Objektenes egen fasit brukes "
              "bare til måling, aldri til valg av nabo.\n" % (len(sat_hist), nabo.MIN_FELLES_AAR, nabo.MAKS_SPREDNING, nabo.MAKS_AVSTAND_KM),
              "| Vann | Vann-år | Uten nabo: innen 3 d / bredde / midt-avvik | Med nabo: innen 3 d / bredde / midt-avvik | Indirekte | Nabo brukt |",
              "|---|---|---|---|---|---|"]
    sum_u, sum_m = [], []
    for navn, lnr, fasit, serier, nokkel in objekter:
        # egen satellitt-historikk (midtpunkt) for objektet, som del av "fasit"-settet nabo-regelen ser
        egen_hist = {}
        for y in AAR:
            obs = serier.get((nokkel, y))
            if obs:
                r = v3.finn_isgang(a7.klare(obs, valg["tv"], valg["tn"], valg["regel"]), v5.TERSKEL)
                if r["status"] == "ok":
                    egen_hist[str(y)] = midtdato(r)
        alle_hist = dict(sat_hist)
        alle_hist[lnr] = egen_hist
        posisjon = {k: pos[k] for k in alle_hist if k in pos}
        uten, med, ind, naboer = [], [], 0, set()
        for y_s, fd in fasit.items():
            y = int(y_s)
            obs = serier.get((nokkel, y))
            if not obs:
                continue
            egne = a7.klare(obs, valg["tv"], valg["tn"], valg["regel"])
            r0 = v3.finn_isgang(egne, v5.TERSKEL)
            if r0["status"] == "ok":
                uten.append((v3.avstand(fd, r0["lo"], r0["hi"]), (v3.d(r0["hi"]) - v3.d(r0["lo"])).days,
                             abs((v3.d(midtdato(r0)) - v3.d(fd)).days)))
            valgt = nabo.velg_nabo(lnr, y, alle_hist, posisjon)
            r1 = r0
            if valgt:
                b, forsk, _ = valgt
                nb = a7.klare(ref_serier.get((b, y), []), valg["tv"], valg["tn"], valg["regel"])
                if nb:
                    r1 = nabo.finn_isgang_med_kilde(nabo.laan_pass(egne, nb, forsk, str(b)), v5.TERSKEL)
                    naboer.add((nett[b]["navn"] if b in nett else None) or "lnr %s" % b)
            if r1["status"] == "ok":
                med.append((v3.avstand(fd, r1["lo"], r1["hi"]), (v3.d(r1["hi"]) - v3.d(r1["lo"])).days,
                            abs((v3.d(midtdato(r1)) - v3.d(fd)).days)))
                ind += 1 if r1.get("indirekte") else 0

        def s(x):
            if not x:
                return "–"
            return "%d av %d / %.0f d / %.1f d" % (sum(1 for a, _, _ in x if abs(a) <= 3), len(x),
                                                  statistics.median(b for _, b, _ in x), statistics.mean(c for _, _, c in x))
        linjer.append("| %s | %d | %s | %s | %d | %s |" % (navn, len(fasit), s(uten), s(med), ind, ", ".join(sorted(naboer)) or "–"))
        sum_u += uten
        sum_m += med
    linjer.append("| **Alle 30** | | %s | %s | | |" % (s(sum_u), s(sum_m)))
    navn_fil = "rapport_referansenett.md" if (min_aar is None and maks_spredning is None) else \
        "rapport_referansenett_minaar%s_spred%s.md" % (min_aar, maks_spredning)
    io.open(os.path.join(HER, navn_fil), "w", encoding="utf-8").write("\n".join(linjer) + "\n")
    print("\n".join(linjer[:4]))
    print(linjer[-1])
    print("Skrevet", navn_fil)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kommando", choices=["tell", "hent", "isgang", "test"])
    ap.add_argument("--del", dest="del_", default=None)
    ap.add_argument("--maks-pu", type=float, default=None)
    ap.add_argument("--aar", default=None, help="f.eks. 2022-2026")
    ap.add_argument("--kun-fasit", action="store_true", help="bare områdene som har fasit-vann")
    ap.add_argument("--min-aar", type=int, default=None, help="krav til felles år i nabo-regelen (test)")
    ap.add_argument("--maks-spredning", type=float, default=None, help="krav til spredning i nabo-regelen (test)")
    a = ap.parse_args()
    {"tell": tell, "hent": lambda: hent(a.del_, a.maks_pu, a.aar, a.kun_fasit), "isgang": isgang,
     "test": lambda: test(a.min_aar, a.maks_spredning)}[a.kommando]()
