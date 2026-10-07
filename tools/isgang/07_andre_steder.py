"""
Trinn 1, steg 3 — én forbedring, så en uavhengig test utenfor Nordmarka.

PROTOKOLL, SKREVET FØR DE ANDRE VANNENE ER HENTET (5. okt 2026).

Forbedringen
  I 05_valider_s2.py ble et pass forkastet når Sentinel-2s skymaske merket
  over halve vannet som sky. Men skyer er lyse. Er vannet mørkt, er det åpent
  vann uansett hva skymasken sier. Ny regel «mørke pass teller alltid»:
  et pass der minst 80 % av pikslene er mørke brukes selv om skymasken
  flagger det. For alle andre pass gjelder skymasken som før.

Valg av metode («velg»)
  Kun på Nordmarkas treningsår (2017, 2019, 2021, 2023, 2025). 3 x 2 x 2
  kombinasjoner: mørk under 0,05/0,08/0,12, ndsi-skille 0,2/0,4, skyregel
  gammel/ny. Flest vann-år innen 3 d vinner; likt → smalest intervall.
  Valget lagres i valgt_metode.json og røres ikke etterpå.

Den uavhengige testen («hent», «test»)
  14 vann fra de andre lokasjonene i dashboardet, fra Østfold til Finnmark,
  10 til 1210 moh (andre_vann.json). Ingen av dem er brukt til noe tidligere.
  Fasit = isgangHistory for lokasjonen. Vindu 1. feb – 31. juli.
  Vann over 150 ha hentes med 40 m piksler for å spare kvote.

  Mål, bestemt nå:
    A. Samme krav som før: minst halvparten av vann-årene gir intervall,
       minst 70 % av dem har fasit innen 3 d av intervallet, skjevhet
       høyst 2 d, median bredde høyst 7 d (ellers «uavklart»).
    B. Midten av intervallet mot fasit (snittavvik). Dette er det mest
       rettferdige enkelttallet, fordi Stian har opplyst at fasit-datoen
       ofte er satt midt mellom to klare bilder.
    C. Sammenligning: historisk median for samme vann, med årets dato holdt
       utenfor. I Nordmarka var dagens hybridmodell omtrent like god som
       medianen, så medianen brukes som lista.

Kjør:  python 07_andre_steder.py velg | hent | test
"""
import csv
import importlib.util
import io
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

HER = os.path.dirname(os.path.abspath(__file__))
ROT = os.path.abspath(os.path.join(HER, "..", ".."))


def last(navn, fil):
    s = importlib.util.spec_from_file_location(navn, os.path.join(HER, fil))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


h = last("h", "02_hent_wic.py")
h4 = last("h4", "04_hent_s2.py")
v3 = last("v3", "03_valider.py")
v5 = last("v5", "05_valider_s2.py")

MORK_ANDEL = 0.80
VALG_FIL = os.path.join(HER, "valgt_metode.json")
RAA_ANDRE = os.path.join(h.RAA, "l2a_andre")
CSV_ANDRE = os.path.join(h.DATA, "s2_andre.csv")


def klare(obs, tv, tn, regel):
    ut = []
    for r in sorted(obs, key=lambda r: r["dato"]):
        n = int(r["n"])
        mork, lys_is, lys_annet = v5.klassifiser(r, tv, tn)
        if mork + lys_is < v3.MIN_PX:
            continue
        mork_pass = regel == "ny" and mork >= MORK_ANDEL * n
        if not mork_pass:
            if lys_annet >= 0.5 * n or int(r["scl_sky"]) >= 0.5 * n:
                continue
        ut.append((r["dato"], lys_is / float(mork + lys_is)))
    return ut


def evaluer(serier, fasit, aarsett, tv, tn, regel):
    rader, uten, totalt = [], {}, 0
    for vann in fasit:
        for aar_s, fdato in fasit[vann].items():
            aar = int(aar_s)
            if aarsett is not None and aar not in aarsett:
                continue
            totalt += 1
            obs = serier.get((vann, aar))
            res = v3.finn_isgang(klare(obs, tv, tn, regel), v5.TERSKEL) if obs else {"status": "ingen data"}
            if res["status"] != "ok":
                uten[res["status"]] = uten.get(res["status"], 0) + 1
                continue
            lo, hi, f = v3.d(res["lo"]), v3.d(res["hi"]), v3.d(fdato)
            rader.append({"vann": vann, "aar": aar, "fasit": fdato, "lo": res["lo"], "hi": res["hi"],
                          "avst": v3.avstand(fdato, res["lo"], res["hi"]), "bredde": (hi - lo).days,
                          "midt": ((lo - f).days + (hi - f).days) / 2.0})
    return {"rader": rader, "uten": uten, "totalt": totalt,
            "innen": sum(1 for r in rader if abs(r["avst"]) <= v3.KRAV_DAGER),
            "skjev": statistics.median(r["avst"] for r in rader) if rader else None,
            "bredde": statistics.median(r["bredde"] for r in rader) if rader else None}


def velg():
    fasit = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    serier = v5.les_s2()
    alle = []
    for tv in v5.TV:
        for tn in v5.TN:
            for regel in ("gammel", "ny"):
                alle.append((tv, tn, regel, evaluer(serier, fasit, v5.TRENING, tv, tn, regel)))
    alle.sort(key=lambda x: (-x[3]["innen"], x[3]["bredde"] if x[3]["bredde"] is not None else 999))
    print("Nordmarka, TRENINGSÅRENE (80 vann-år):")
    print("  mørk<  ndsi  skyregel   innen 3 d   bredde   midt-avvik")
    for tv, tn, regel, e in alle:
        print("  %.2f   %.1f   %-7s    %2d av %d    %4.0f d   %4.1f d" % (
            tv, tn, regel, e["innen"], e["totalt"], e["bredde"],
            statistics.mean(abs(r["midt"]) for r in e["rader"])))
    tv, tn, regel, e = alle[0]
    json.dump({"tv": tv, "tn": tn, "regel": regel, "valgt": "2026-10-05", "grunnlag": "Nordmarka treningsår"},
              io.open(VALG_FIL, "w", encoding="utf-8"), indent=1)
    print("\nVALGT og låst: mørk under %.2f, ndsi %.1f, skyregel %s." % (tv, tn, regel))
    te = evaluer(serier, fasit, v5.TEST, tv, tn, regel)
    print("Nordmarka testårene med valgt metode (sett før, kun veiledende): %d av %d innen 3 d, bredde %.0f d, midt-avvik %.1f d"
          % (te["innen"], te["totalt"], te["bredde"], statistics.mean(abs(r["midt"]) for r in te["rader"])))


def les_fasit_andre():
    html = io.open(os.path.join(ROT, "dashboard.html"), encoding="utf-8").read()
    start = html.index("const LOCATIONS = {")
    blokk = html[start:html.index("\n};", start)]
    deler = re.split(r"\n    ([a-z_]+): \{\n", blokk)
    ut = {}
    for i in range(1, len(deler), 2):
        kropp = deler[i + 1].split("ofaLakes:")[0]
        m = re.search(r"\n\s{8}isgangHistory:\s*\{(.*?)\}", kropp, re.S)
        if m:
            ut[deler[i]] = dict(re.findall(r"(\d{4})\s*:\s*'(\d{4}-\d{2}-\d{2})'", m.group(1)))
    return ut


def hent():
    if not os.path.exists(VALG_FIL):
        raise SystemExit("Kjør «velg» først, så metoden er låst før testdataene hentes.")
    kobling = json.load(io.open(os.path.join(HER, "andre_vann.json"), encoding="utf-8"))["vann"]
    fasit = les_fasit_andre()
    p = dict(where="vatnlnr IN (%s)" % ",".join(str(k["vatnlnr"]) for k in kobling),
             outFields="vatnlnr,navn,hoyde,areal_km2", returnGeometry="true", outSR="32633", f="geojson")
    with urllib.request.urlopen(v_nve() + "?" + urllib.parse.urlencode(p), timeout=180) as r:
        gj = json.load(r)
    per_lnr = {f["properties"]["vatnlnr"]: f for f in gj["features"]}
    os.makedirs(RAA_ANDRE, exist_ok=True)
    token = h.hent_token(h.les_env())
    print("Logget inn hos Copernicus.")
    pu_sum, meta = 0.0, []
    for k in kobling:
        f = per_lnr.get(k["vatnlnr"])
        if not f:
            print("MANGLER polygon:", k["lok"])
            continue
        ha = (f["properties"].get("areal_km2") or 0) * 100
        res = 20 if ha <= 150 else 40
        meta.append({"lok": k["lok"], "navn": k["navn"], "vatnlnr": k["vatnlnr"], "areal_ha": round(ha, 1),
                     "moh": f["properties"].get("hoyde"), "piksel_m": res, "sikkerhet": k["sikkerhet"]})
        for aar_s in sorted(fasit.get(k["lok"], {})):
            aar = int(aar_s)
            sti = os.path.join(RAA_ANDRE, "%s_%d.json" % (k["lok"], aar))
            if os.path.exists(sti):
                continue
            kropp = h4.bygg(f["geometry"], aar)
            kropp["aggregation"]["timeRange"] = {"from": "%d-02-01T00:00:00Z" % aar, "to": "%d-08-01T00:00:00Z" % aar}
            kropp["aggregation"]["resx"] = kropp["aggregation"]["resy"] = res
            svar, pu = h.send(token, kropp)
            json.dump(svar, io.open(sti, "w", encoding="utf-8"))
            pu_sum += pu or 0
            print("  %-15s %-18s %d: %3d pass  (%.1f PU)" % (k["lok"], k["navn"], aar, len(h4.flat_ut(svar)), pu or 0), flush=True)
    json.dump(meta, io.open(os.path.join(HER, "grunnlag", "andre_vann_meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    kol = ["vann", "aar", "dato", "n", "vis"] + h4.BINS + ["scl_" + c for c in h4.SCL]
    ant = 0
    with io.open(CSV_ANDRE, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=kol, delimiter=";")
        w.writeheader()
        for fil in sorted(os.listdir(RAA_ANDRE)):
            lok, aar = fil[:-5].rsplit("_", 1)
            for rad in h4.flat_ut(json.load(io.open(os.path.join(RAA_ANDRE, fil), encoding="utf-8"))):
                rad.update({"vann": lok, "aar": aar})
                w.writerow(rad)
                ant += 1
    print("Forbruk: %.0f PU. Skrevet data/s2_andre.csv (%d rader)." % (pu_sum, ant))


def v_nve():
    return "https://kart.nve.no/enterprise/rest/services/Innsjodatabase2/MapServer/5/query"


def doy(d):
    return d.timetuple().tm_yday


def test():
    valg = json.load(io.open(VALG_FIL, encoding="utf-8"))
    meta = {m["lok"]: m for m in json.load(io.open(os.path.join(HER, "grunnlag", "andre_vann_meta.json"), encoding="utf-8"))}
    alle_fasit = les_fasit_andre()
    fasit = {lok: alle_fasit[lok] for lok in meta if lok in alle_fasit}
    serier = {}
    for r in csv.DictReader(io.open(CSV_ANDRE, encoding="utf-8-sig"), delimiter=";"):
        serier.setdefault((r["vann"], int(r["aar"])), []).append(r)
    e = evaluer(serier, fasit, None, valg["tv"], valg["tn"], valg["regel"])

    # C: historisk median for samme vann, årets dato holdt utenfor
    med = {}
    for lok, aar_map in fasit.items():
        for aar_s, fd in aar_map.items():
            andre = sorted(doy(date.fromisoformat(d)) for a, d in aar_map.items() if a != aar_s)
            if len(andre) >= 3:
                p = date(int(aar_s), 1, 1) + timedelta(days=andre[len(andre) // 2] - 1)
                med[(lok, int(aar_s))] = (p - date.fromisoformat(fd)).days

    n_int = len(e["rader"])
    if n_int < 0.5 * e["totalt"]:
        dom = "ikke bestått (for få vann-år ga intervall)"
    elif e["bredde"] > v3.KRAV_BREDDE:
        dom = "uavklart (for brede intervaller)"
    elif e["innen"] / float(n_int) >= v3.KRAV_ANDEL and abs(e["skjev"]) <= v3.KRAV_SKJEVHET:
        dom = "bestått"
    else:
        dom = "ikke bestått"
    midt = [r["midt"] for r in e["rader"]]
    felles = [(r["midt"], med[(r["vann"], r["aar"])]) for r in e["rader"] if (r["vann"], r["aar"]) in med]

    L = ["# Uavhengig test: 14 vann utenfor Nordmarka\n",
         "Metoden ble låst på Nordmarkas treningsår før disse vannene ble hentet: mørk under %.2f, ndsi %.1f, skyregel «%s». "
         "Protokollen står øverst i `07_andre_steder.py`.\n" % (valg["tv"], valg["tn"], valg["regel"]),
         "## A. Forhåndskravene\n",
         "| Vann-år med fasit | Fikk intervall | Innen 3 d av intervallet | Skjevhet | Median bredde | Vurdering |",
         "|---|---|---|---|---|---|",
         "| %d | %d | %d (%.0f %%) | %+.1f d | %.0f d | %s |" % (
             e["totalt"], n_int, e["innen"], 100.0 * e["innen"] / n_int if n_int else 0,
             e["skjev"] if n_int else 0, e["bredde"] if n_int else 0, dom),
         "\nUten intervall: " + (", ".join("%s: %d" % kv for kv in sorted(e["uten"].items())) or "ingen") + ".\n",
         "## B og C. Enkeltdato mot fasit, samme vann-år\n",
         "| Metode | Vann-år | Skjevhet (median) | Snittavvik | Median avvik | Innen 3 d | Innen 7 d |",
         "|---|---|---|---|---|---|---|"]

    def rad(navn, x):
        a = [abs(v) for v in x]
        return "| %s | %d | %+.1f d | %.1f d | %.1f d | %d (%.0f %%) | %d (%.0f %%) |" % (
            navn, len(x), statistics.median(x), statistics.mean(a), statistics.median(a),
            sum(1 for v in a if v <= 3), 100.0 * sum(1 for v in a if v <= 3) / len(a),
            sum(1 for v in a if v <= 7), 100.0 * sum(1 for v in a if v <= 7) / len(a))
    if felles:
        L.append(rad("Satellitt, midt i intervallet", [f[0] for f in felles]))
        L.append(rad("Historisk median (lista)", [f[1] for f in felles]))
    L.append("\n## Per vann\n")
    L.append("| Lokasjon | Vann | Areal | Høyde | Koblingen | År med intervall | Innen 3 d | Midt-avvik (snitt) | Median bredde | Median alene (snitt) |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for lok in fasit:
        rr = [r for r in e["rader"] if r["vann"] == lok]
        m = meta[lok]
        mm = [abs(med[(lok, int(a))]) for a in fasit[lok] if (lok, int(a)) in med]
        if rr:
            L.append("| %s | %s | %.0f ha | %s m | %s | %d av %d | %d | %.1f d | %.0f d | %s |" % (
                lok, m["navn"], m["areal_ha"], m["moh"], m["sikkerhet"], len(rr), len(fasit[lok]),
                sum(1 for r in rr if abs(r["avst"]) <= 3), statistics.mean(abs(r["midt"]) for r in rr),
                statistics.median(r["bredde"] for r in rr), "%.1f d" % statistics.mean(mm) if mm else "–"))
        else:
            L.append("| %s | %s | %.0f ha | %s m | %s | 0 av %d | – | – | – | – |" % (
                lok, m["navn"], m["areal_ha"], m["moh"], m["sikkerhet"], len(fasit[lok])))
    L.append("\n## Alle vann-år\n")
    L.append("| Lokasjon | År | Fasit | Siste is | Første åpent | Avstand | Bredde |")
    L.append("|---|---|---|---|---|---|---|")
    for r in sorted(e["rader"], key=lambda r: (r["vann"], r["aar"])):
        L.append("| %s | %d | %s | %s | %s | %+d d | %d d |" % (r["vann"], r["aar"], r["fasit"], r["lo"], r["hi"], r["avst"], r["bredde"]))
    io.open(os.path.join(HER, "rapport_andre_steder.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({r["vann"] + "_" + str(r["aar"]): {"lo": r["lo"], "hi": r["hi"]} for r in e["rader"]},
              io.open(os.path.join(HER, "isgang_andre.json"), "w", encoding="utf-8"), indent=1)
    print("\n".join(L[:40]))


if __name__ == "__main__":
    kommando = sys.argv[1] if len(sys.argv) > 1 else ""
    if kommando == "velg":
        velg()
    elif kommando == "hent":
        hent()
    elif kommando == "test":
        test()
    else:
        print(__doc__)
