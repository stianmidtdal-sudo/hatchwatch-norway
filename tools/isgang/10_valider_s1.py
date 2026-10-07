"""
Radar-eksperiment, steg 2 — hjelper Sentinel-1 til å tette skyhull?

PROTOKOLL, SKREVET FØR RADARDATAENE VAR FERDIG HENTET (6. okt 2026). Kun
Øyungen 2026 var sett (prøvekjøringen).

Radar brukes BARE som tegn på åpent vann, aldri som tegn på is:
  radar-åpent pass = minst P av pikslene har VV under T dB
    T i {-22, -19}      (bins b0, b0+b1 fra 09_hent_s1.py)
    P i {0,5, 0,7}
  To måter å bruke det på:
    bekreft   radar-åpent pass kan bare BEKREFTE et optisk åpent pass (være
              «neste klare pass»). Intervallets endepunkter er alltid optiske.
    fritt     radar-åpent pass teller som et vanlig åpent pass og kan også
              være «første åpent». Kan gi smalere intervall, men også falske
              tidlige isganger hvis våt is leses som vann.
  Optisk del: den låste metoden (valgt_metode.json). Isgang-regelen ellers
  uendret (03_valider.py).

Valg: de 8 kombinasjonene vurderes KUN på treningsårene (2017, 2019, 2021,
2023, 2025). Flest vann-år innen 3 d vinner; likt → smalest intervall.

Adopsjon avgjøres på TESTÅRENE, én gang, med kriterier satt nå:
  radar tas i bruk hvis (a) antall vann-år innen 3 d ikke faller med mer enn
  2 i forhold til bare optisk, OG (b) median intervallbredde blir minst 1 dag
  smalere. Ellers forkastes radar.

Kjør:  python 10_valider_s1.py
"""
import csv
import importlib.util
import io
import json
import os
import statistics
import sys

HER = os.path.dirname(os.path.abspath(__file__))


def last(n, f):
    s = importlib.util.spec_from_file_location(n, os.path.join(HER, f))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


v3 = last("v3", "03_valider.py")
v5 = last("v5", "05_valider_s2.py")
a7 = last("a7", "07_andre_steder.py")

T_VALG = [("-22", ("b0",)), ("-19", ("b0", "b1"))]
P_VALG = [0.5, 0.7]
MODUS = ["bekreft", "fritt"]
TERSKEL = v5.TERSKEL


def les_s1():
    ut = {}
    for r in csv.DictReader(io.open(os.path.join(HER, "data", "s1_tidsserie.csv"), encoding="utf-8-sig"), delimiter=";"):
        ut.setdefault((r["vann"], int(r["aar"])), []).append(r)
    return ut


def radar_aapne(obs, bins, p):
    ut = []
    for r in obs or []:
        n = int(r["n"])
        if n >= v3.MIN_PX and sum(int(r[b]) for b in bins) >= p * n:
            ut.append(r["dato"])
    return ut


def finn(optisk, radar, modus):
    """optisk: [(dato, isandel)], radar: [dato] åpne. Returnerer som finn_isgang."""
    alle = sorted([(d, f, "o") for d, f in optisk] + [(d, 0.0, "r") for d in radar])
    if not alle:
        return {"status": "ingen klare pass", "lo": None, "hi": None}
    for k in range(len(alle)):
        dato, f, kind = alle[k]
        if f >= TERSKEL:
            continue
        if modus == "bekreft" and kind == "r":
            continue                                        # radar kan ikke være «første åpent»
        if k + 1 >= len(alle):
            return {"status": "ubekreftet (siste pass i vinduet)", "lo": None, "hi": dato}
        if alle[k + 1][1] >= TERSKEL:
            continue
        tidligere = [j for j in range(k) if alle[j][1] >= TERSKEL]   # is kommer alltid fra optisk
        if not tidligere:
            return {"status": "åpent ved første klare pass", "lo": None, "hi": dato}
        return {"status": "ok", "lo": alle[tidligere[-1]][0], "hi": dato}
    return {"status": "is i hele vinduet", "lo": alle[-1][0], "hi": None}


def evaluer(opt, s1, fasit, aarsett, valg, bins, p, modus):
    rader, totalt = [], 0
    for vann in fasit:
        for aar_s, fdato in fasit[vann].items():
            aar = int(aar_s)
            if aar not in aarsett:
                continue
            totalt += 1
            o = opt.get((vann, aar))
            if not o:
                continue
            optisk = a7.klare(o, valg["tv"], valg["tn"], valg["regel"])
            radar = radar_aapne(s1.get((vann, aar)), bins, p) if modus else []
            res = finn(optisk, radar, modus or "bekreft")
            if res["status"] != "ok":
                continue
            rader.append({"vann": vann, "aar": aar, "fasit": fdato, "lo": res["lo"], "hi": res["hi"],
                          "avst": v3.avstand(fdato, res["lo"], res["hi"]),
                          "bredde": (v3.d(res["hi"]) - v3.d(res["lo"])).days})
    return {"rader": rader, "totalt": totalt,
            "innen": sum(1 for r in rader if abs(r["avst"]) <= v3.KRAV_DAGER),
            "bredde": statistics.median(r["bredde"] for r in rader) if rader else None,
            "skjev": statistics.median(r["avst"] for r in rader) if rader else None}


def main():
    valg = json.load(io.open(a7.VALG_FIL, encoding="utf-8"))
    fasit = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    opt, s1 = v5.les_s2(), les_s1()
    print("Radarpass per vann-år (snitt): %.0f" % (sum(len(v) for v in s1.values()) / float(len(s1))))

    basis_tr = evaluer(opt, s1, fasit, v5.TRENING, valg, (), 0, None)
    basis_te = evaluer(opt, s1, fasit, v5.TEST, valg, (), 0, None)
    alle = []
    for tn, bins in T_VALG:
        for p in P_VALG:
            for modus in MODUS:
                alle.append((tn, bins, p, modus, evaluer(opt, s1, fasit, v5.TRENING, valg, bins, p, modus)))
    alle.sort(key=lambda x: (-x[4]["innen"], x[4]["bredde"] if x[4]["bredde"] is not None else 999))

    L = ["# Radar-eksperiment: Sentinel-1 som bekreftelse på åpent vann\n",
         "Protokoll øverst i `10_valider_s1.py`, skrevet før dataene var hentet.\n",
         "## Treningsårene (valg av oppsett)\n",
         "| Oppsett | Innen 3 d | Fikk intervall | Median bredde | Skjevhet |", "|---|---|---|---|---|",
         "| bare optisk | %d av %d | %d | %.0f d | %+.1f d |" % (
             basis_tr["innen"], basis_tr["totalt"], len(basis_tr["rader"]), basis_tr["bredde"], basis_tr["skjev"])]
    for tn, bins, p, modus, e in alle:
        L.append("| VV < %s dB, %.0f %% av vannet, %s | %d av %d | %d | %.0f d | %+.1f d |" % (
            tn, p * 100, modus, e["innen"], e["totalt"], len(e["rader"]), e["bredde"], e["skjev"]))
    tn, bins, p, modus, _ = alle[0]
    te = evaluer(opt, s1, fasit, v5.TEST, valg, bins, p, modus)
    ok_a = te["innen"] >= basis_te["innen"] - 2
    ok_b = te["bredde"] is not None and te["bredde"] <= basis_te["bredde"] - 1
    dom = "RADAR TAS I BRUK" if (ok_a and ok_b) else "radar forkastes"
    L += ["\n## Testårene (én gang, valgt oppsett: VV < %s dB, %.0f %%, %s)\n" % (tn, p * 100, modus),
          "| | Innen 3 d | Fikk intervall | Median bredde | Skjevhet |", "|---|---|---|---|---|",
          "| bare optisk | %d av %d | %d | %.0f d | %+.1f d |" % (
              basis_te["innen"], basis_te["totalt"], len(basis_te["rader"]), basis_te["bredde"], basis_te["skjev"]),
          "| optisk + radar | %d av %d | %d | %.0f d | %+.1f d |" % (
              te["innen"], te["totalt"], len(te["rader"]), te["bredde"], te["skjev"]),
          "\nKrav (a) innen 3 d faller høyst 2: %s. Krav (b) minst 1 d smalere: %s. **%s.**\n" % (
              "oppfylt" if ok_a else "ikke oppfylt", "oppfylt" if ok_b else "ikke oppfylt", dom)]
    # Hvor mye forsinkelse til bekreftelse sparer radar? (tilleggsmål)
    io.open(os.path.join(HER, "rapport_radar.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump({"T": tn, "bins": bins, "p": p, "modus": modus, "adoptert": ok_a and ok_b},
              io.open(os.path.join(HER, "valgt_radar.json"), "w", encoding="utf-8"), indent=1)
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
