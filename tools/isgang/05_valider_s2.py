"""
Trinn 1, steg 2 — egen isgang-klassifisering fra rå Sentinel-2, testet mot fasit.

PROTOKOLLEN ER SKREVET FØR DATAENE BLE HENTET (5. okt 2026). Det eneste som
var sett på forhånd, var ett vann-år: Øyungen 2026 (prøvekjøringen).

Klassifisering per piksel (fra tabellen i data/s2_tidsserie.csv):
  mørk       vis <  tv                 → åpent vann
  lys is     vis >= tv og ndsi >= tn   → is eller snø på is
  lys annet  vis >= tv og ndsi <  tn   → sky

Et pass er «klart» når under halvparten av pikslene er «lys annet», og
(hvis bruk_scl) under halvparten er merket som sky i Sentinel-2s egen
skymaske. Isandel = lys is / (lys is + mørk).

Isgang-regelen er uendret fra trinn 0: første klare pass med isandel under
0,20 som bekreftes av neste klare pass, etter at det er sett is samme vår.
Rapporteres som intervall [siste is, første åpent].

Tre valg skal gjøres, og de gjøres KUN på treningsårene:
  tv        0,05 / 0,08 / 0,12   hvor mørkt vann må være
  tn        0,2 / 0,4            skillet mellom lys is og sky
  bruk_scl  nei / ja             om Sentinel-2s skymaske også skal brukes
Det gir 12 kombinasjoner. Den som gir flest treningsvann-år innen 3 dager
velges (vann-år uten intervall teller som bom; likt → smalest intervall).

  Trening  2017, 2019, 2021, 2023, 2025
  Test     2018, 2020, 2022, 2024, 2026   (røres ikke før valget er gjort)

Bestått vurderes på TESTÅRENE, med samme krav som i trinn 0:
  (0) minst halvparten av vann-årene gir et intervall,
  (1) minst 70 % av dem har fasit innenfor intervallet eller høyst 3 d utenfor,
  (2) skjevhet (median avstand med fortegn) høyst 2 d,
  (3) median intervallbredde høyst 7 d, ellers «uavklart».
Fortegn: positiv = fasiten ligger senere enn satellittens intervall.

Skriptet gjør også kontrollen av trinn 0-funnet: alle pass der WIC-produktet
sa «åpent» minst 5 dager før fasit-datoen, sjekket mot hvor lyst vannet
faktisk var den dagen.

Kjør:  python 05_valider_s2.py
"""
import csv
import importlib.util
import io
import json
import os
import random
import statistics
import sys
from datetime import timedelta

HER = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("v", os.path.join(HER, "03_valider.py"))
v3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v3)

VIS_KANTER = [0.05, 0.08, 0.12, 0.20, 0.40]
NDSI_KANTER = [0.2, 0.4]
TV = [0.05, 0.08, 0.12]
TN = [0.2, 0.4]
SCL_VALG = [False, True]
TERSKEL = 0.20
TRENING = {2017, 2019, 2021, 2023, 2025}
TEST = {2018, 2020, 2022, 2024, 2026}


def les_s2():
    serier = {}
    for r in csv.DictReader(io.open(os.path.join(HER, "data", "s2_tidsserie.csv"), encoding="utf-8-sig"), delimiter=";"):
        serier.setdefault((r["vann"], int(r["aar"])), []).append(r)
    return serier


def klassifiser(rad, tv, tn):
    """→ (mørk, lys is, lys annet) i antall piksler."""
    nv = sum(1 for k in VIS_KANTER if tv >= k)        # antall lyshetstrinn som regnes som mørke
    nn = sum(1 for k in NDSI_KANTER if tn >= k)       # antall ndsi-trinn som regnes som lave
    mork = sum(int(rad["v%dn%d" % (a, b)]) for a in range(nv) for b in range(3))
    lys_is = sum(int(rad["v%dn%d" % (a, b)]) for a in range(nv, 6) for b in range(nn, 3))
    lys_annet = sum(int(rad["v%dn%d" % (a, b)]) for a in range(nv, 6) for b in range(nn))
    return mork, lys_is, lys_annet


def klare(obs, tv, tn, bruk_scl):
    ut = []
    for r in sorted(obs, key=lambda r: r["dato"]):
        n = int(r["n"])
        mork, lys_is, lys_annet = klassifiser(r, tv, tn)
        if lys_annet >= 0.5 * n or mork + lys_is < v3.MIN_PX:
            continue
        if bruk_scl and int(r["scl_sky"]) >= 0.5 * n:
            continue
        ut.append((r["dato"], lys_is / float(mork + lys_is)))
    return ut


def evaluer(serier, fasit, aarsett, tv, tn, bruk_scl):
    rader, uten, totalt = [], {}, 0
    for vann in fasit:
        for aar, fdato in fasit[vann].items():
            aar = int(aar)
            if aar not in aarsett:
                continue
            totalt += 1
            obs = serier.get((vann, aar))
            res = v3.finn_isgang(klare(obs, tv, tn, bruk_scl), TERSKEL) if obs else {"status": "ingen data"}
            if res["status"] != "ok":
                uten[res["status"]] = uten.get(res["status"], 0) + 1
                continue
            rader.append({"vann": vann, "aar": aar, "fasit": fdato, "lo": res["lo"], "hi": res["hi"],
                          "avst": v3.avstand(fdato, res["lo"], res["hi"]),
                          "bredde": (v3.d(res["hi"]) - v3.d(res["lo"])).days})
    innen = sum(1 for r in rader if abs(r["avst"]) <= v3.KRAV_DAGER)
    return {"rader": rader, "uten": uten, "totalt": totalt, "innen": innen,
            "skjev": statistics.median(r["avst"] for r in rader) if rader else None,
            "bredde": statistics.median(r["bredde"] for r in rader) if rader else None}


def dom(e):
    if not e["rader"] or len(e["rader"]) < 0.5 * e["totalt"]:
        return "ikke bestått (for få vann-år ga intervall)"
    if e["bredde"] > v3.KRAV_BREDDE:
        return "uavklart (for brede intervaller)"
    if e["innen"] / float(len(e["rader"])) >= v3.KRAV_ANDEL and abs(e["skjev"]) <= v3.KRAV_SKJEVHET:
        return "bestått"
    return "ikke bestått"


def kontroll_trinn0(serier, fasit, linjer):
    """Var vannet faktisk lyst (islagt) de dagene WIC sa åpent lenge før fasit?"""
    wic = {}
    sti = os.path.join(HER, "data", "wic_tidsserie.csv")
    if not os.path.exists(sti):
        return
    for r in csv.DictReader(io.open(sti, encoding="utf-8-sig"), delimiter=";"):
        if r["kilde"] == "s2":
            wic.setdefault((r["vann"], int(r["aar"])), []).append((r["dato"], int(r["vann_px"]), int(r["is_px"])))
    n_ref = {}
    for (vann, _), obs in wic.items():
        n_ref[vann] = max(n_ref.get(vann, 0), max(a + b for _, a, b in obs))
    uenige = []
    for (vann, aar), obs in wic.items():
        f = fasit.get(vann, {}).get(str(aar))
        if not f:
            continue
        for dato, isandel in v3.klare_pass(obs, n_ref[vann]):
            if isandel < TERSKEL and v3.d(dato) <= v3.d(f) - timedelta(days=5):
                s2 = {r["dato"]: r for r in serier.get((vann, aar), [])}.get(dato)
                if s2:
                    n = int(s2["n"])
                    lyse = sum(int(s2["v%dn%d" % (a, b)]) for a in range(3, 6) for b in range(3))   # vis >= 0,12
                    uenige.append((vann, dato, f, isandel, float(s2["vis"] or 0), lyse / float(n)))
    linjer.append("\n## Kontroll av trinn 0-funnet\n")
    if not uenige:
        linjer.append("Ingen uenige pass funnet.\n")
        return
    islagt = sum(1 for u in uenige if u[5] >= 0.5)
    linjer.append("WIC-produktet meldte under 20 %% is minst 5 dager før fasit-datoen i **%d pass**. "
                  "I **%d av dem (%.0f %%)** var over halve vannet lyst (lyshet over 0,12) i det rå bildet "
                  "samme dag, altså islagt eller skydekt. Åpent vann har lyshet rundt 0,01.\n"
                  % (len(uenige), islagt, 100.0 * islagt / len(uenige)))
    random.seed(2026)
    utvalg = sorted(random.sample(uenige, min(20, len(uenige))))
    linjer.append("Tjue tilfeldig trukne (frø 2026):\n")
    linjer.append("| Vann | Dato | Fasit isgang | WIC isandel | Snittlyshet i bildet | Andel lyse piksler |")
    linjer.append("|---|---|---|---|---|---|")
    for vann, dato, f, isandel, vis, lys in utvalg:
        linjer.append("| %s | %s | %s | %.0f %% | %.2f | %.0f %% |" % (vann, dato, f, isandel * 100, vis, lys * 100))
    json.dump([{"vann": u[0], "dato": u[1]} for u in utvalg],
              io.open(os.path.join(HER, "data", "kontroll_utvalg.json"), "w", encoding="utf-8"), ensure_ascii=False)


def main():
    fasit = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    serier = les_s2()
    linjer = ["# Trinn 1: egen isgang-klassifisering fra rå Sentinel-2\n",
              "Protokollen står øverst i `05_valider_s2.py` og ble skrevet før dataene ble hentet. "
              "Terskler er valgt på treningsårene og vurdert på testårene.\n"]

    alle = []
    for tv in TV:
        for tn in TN:
            for scl in SCL_VALG:
                tr = evaluer(serier, fasit, TRENING, tv, tn, scl)
                alle.append((tv, tn, scl, tr))
    # Valg: flest treningsvann-år innen 3 d; likt → smalest medianbredde.
    alle.sort(key=lambda x: (-x[3]["innen"], x[3]["bredde"] if x[3]["bredde"] is not None else 999))
    tv, tn, scl, tr = alle[0]
    te = evaluer(serier, fasit, TEST, tv, tn, scl)

    linjer.append("## Resultat\n")
    linjer.append("Valgt på treningsårene: mørkt vann under **%.2f**, is/sky-skille ved ndsi **%.1f**, "
                  "Sentinel-2s skymaske **%s**.\n" % (tv, tn, "brukt" if scl else "ikke brukt"))
    linjer.append("| | Vann-år | Fikk intervall | Innen 3 d | Skjevhet | Median bredde | Vurdering |")
    linjer.append("|---|---|---|---|---|---|---|")
    for navn, e in (("Trening", tr), ("**Test**", te)):
        if e["rader"]:
            linjer.append("| %s | %d | %d | %d (%.0f %%) | %+.1f d | %.0f d | %s |" % (
                navn, e["totalt"], len(e["rader"]), e["innen"], 100.0 * e["innen"] / len(e["rader"]),
                e["skjev"], e["bredde"], dom(e) if navn != "Trening" else "–"))
        else:
            linjer.append("| %s | %d | 0 | – | – | – | – |" % (navn, e["totalt"]))
    linjer.append("\nTest uten intervall: " + (", ".join("%s: %d" % kv for kv in sorted(te["uten"].items())) or "ingen") + ".\n")

    linjer.append("## Alle 12 kombinasjoner (for åpenhet)\n")
    linjer.append("| Mørk under | ndsi-skille | Skymaske | Trening innen 3 d | Trening bredde | Test innen 3 d | Test skjevhet | Test bredde |")
    linjer.append("|---|---|---|---|---|---|---|---|")
    for a, b, c, t in alle:
        e = evaluer(serier, fasit, TEST, a, b, c)
        linjer.append("| %.2f | %.1f | %s | %d av %d | %s | %d av %d | %s | %s |" % (
            a, b, "ja" if c else "nei", t["innen"], t["totalt"],
            "%.0f d" % t["bredde"] if t["bredde"] is not None else "–",
            e["innen"], e["totalt"],
            "%+.1f d" % e["skjev"] if e["skjev"] is not None else "–",
            "%.0f d" % e["bredde"] if e["bredde"] is not None else "–"))

    linjer.append("\n## Per vann, testårene\n")
    linjer.append("| Vann | År med intervall | Innen 3 d | Skjevhet | Median bredde |")
    linjer.append("|---|---|---|---|---|")
    for vann in fasit:
        rr = [r for r in te["rader"] if r["vann"] == vann]
        n_aar = sum(1 for a in fasit[vann] if int(a) in TEST)
        if rr:
            linjer.append("| %s | %d av %d | %d | %+.1f d | %.0f d |" % (
                vann, len(rr), n_aar, sum(1 for r in rr if abs(r["avst"]) <= v3.KRAV_DAGER),
                statistics.median(r["avst"] for r in rr), statistics.median(r["bredde"] for r in rr)))
        else:
            linjer.append("| %s | 0 av %d | – | – | – |" % (vann, n_aar))

    linjer.append("\n## Alle vann-år (trening og test)\n")
    linjer.append("| Vann | År | Sett | Fasit | Siste is | Første åpent | Avstand | Bredde |")
    linjer.append("|---|---|---|---|---|---|---|---|")
    for sett, e in (("trening", tr), ("test", te)):
        for r in sorted(e["rader"], key=lambda r: (r["vann"], r["aar"])):
            linjer.append("| %s | %d | %s | %s | %s | %s | %+d d | %d d |" % (
                r["vann"], r["aar"], sett, r["fasit"], r["lo"], r["hi"], r["avst"], r["bredde"]))

    kontroll_trinn0(serier, fasit, linjer)

    io.open(os.path.join(HER, "rapport_trinn1.md"), "w", encoding="utf-8").write("\n".join(linjer) + "\n")
    ut = {}
    for e in (tr, te):
        for r in e["rader"]:
            ut.setdefault(r["vann"], {})[r["aar"]] = {"lo": r["lo"], "hi": r["hi"]}
    json.dump({"valg": {"tv": tv, "tn": tn, "bruk_scl": scl}, "isgang": ut},
              io.open(os.path.join(HER, "isgang_s2.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Skrevet rapport_trinn1.md og isgang_s2.json\n")
    for l in linjer[2:9]:
        print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
