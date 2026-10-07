"""
Hvor godt treffer dagens ismodell de samme isgangsdatoene?

Dette er lista satellitten må over. Skriptet gjenskaper hybrid-ismodellen
fra dashboard.html i Python (simulateIce, calibrateIceModel,
predictIsgangIce, predictIsgangHybrid) og kjører den for hvert av de 16
Nordmarka-vannene og hvert år 2017–2026. Det endrer ingenting i dashboardet.

Slik gjøres det, og hvor det avviker fra appen:
  - Lufttemperatur fra Bjørnholt (SN18500) via hatchwatch.no/api/frost,
    høydekorrigert 0,6 °C per 100 m til vannets høyde, som i appen.
  - For hvert år holdes årets egen isgangsdato utenfor kalibrering og median
    (leave-one-year-out). Appen bruker bare tidligere år; her får modellen
    også senere år å lære av. Det er altså modellens BESTE tilfelle.
  - To tidspunkter: «1. april» (ekte varsel, resten av våren fylles med
    normaltemperatur) og «på isgangsdagen» (alt vær kjent).

Kjør:  python 06_dagens_modell.py
"""
import io
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

HER = os.path.dirname(os.path.abspath(__file__))
STASJON, STASJON_MOH = "SN18500", 380
ALPHAS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
BETAS = [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2]
TEST = {2018, 2020, 2022, 2024, 2026}


def hent_luft():
    sti = os.path.join(HER, "data", "frost_%s.json" % STASJON)
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))
    ut = {}
    for a in range(2015, 2027):                       # ett år per kall, som holder seg under Frost sine grenser
        q = urllib.parse.urlencode({"elements": "mean(air_temperature P1D)", "start": "%d-01-01" % a,
                                    "end": "%d-01-01" % (a + 1), "station": STASJON})
        req = urllib.request.Request("https://www.hatchwatch.no/api/frost?" + q, headers={"User-Agent": "hatchwatch-tools"})
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.load(r)
        sums, cnt = {}, {}
        for it in j.get("data", []):
            d = it["referenceTime"][:10]
            v = (it.get("observations") or [{}])[0].get("value")
            if v is None:
                continue
            sums[d] = sums.get(d, 0) + v
            cnt[d] = cnt.get(d, 0) + 1
        for d in sums:
            ut[d] = sums[d] / cnt[d]
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    json.dump(ut, io.open(sti, "w", encoding="utf-8"))
    return ut


def doy(d):
    return d.timetuple().tm_yday


def fra_doy(aar, n):
    return date(aar, 1, 1) + timedelta(days=n - 1)


def simuler(luft, alpha, beta, aar, til=None, normal=None):
    """Som simulateIce / predictIsgangIce: observert vær til «til», deretter normaltemperatur."""
    d = date(aar - 1, 11, 1)
    slutt = date(aar, 7, 31)
    kutt = date(aar, 2, 15)
    h, hadde_is = 0.0, False
    while d <= slutt:
        if til is None or d <= til:
            t = luft.get(d.isoformat())
        else:
            t = normal.get(doy(d), 0.0) if normal else None
        if t is not None:
            if t < 0:
                h = (h * h + alpha * alpha * abs(t)) ** 0.5
                hadde_is = True
            elif h > 0 and t > 0:
                h = max(0.0, h - beta * t)
            if hadde_is and h == 0 and d >= kutt:
                return d
        d += timedelta(days=1)
    return None


def kalibrer(hist, luft):
    best = None
    for a in ALPHAS:
        for b in BETAS:
            ss, n = 0.0, 0
            for aar, obs in hist.items():
                p = simuler(luft, a, b, aar)
                if not p:
                    continue
                ss += ((p - date.fromisoformat(obs)).days) ** 2
                n += 1
            if n < 2:
                continue
            rmse = (ss / n) ** 0.5
            if best is None or rmse < best[0]:
                best = (rmse, a, b)
    return best


def normaltemp(luft, uten_aar):
    s, c = {}, {}
    for d, v in luft.items():
        y = int(d[:4])
        if y == uten_aar or y < 2016:
            continue
        k = doy(date.fromisoformat(d))
        s[k] = s.get(k, 0) + v
        c[k] = c.get(k, 0) + 1
    return {k: s[k] / c[k] for k in s}


def hybrid(luft, hist, aar, i_dag):
    kal = kalibrer(hist, luft)
    normal = normaltemp(luft, aar)
    stefan = simuler(luft, kal[1], kal[2], aar, til=i_dag, normal=normal) if kal else None
    doys = sorted(doy(date.fromisoformat(s)) for s in hist.values())
    median = doys[len(doys) // 2]
    obs, klim = [], []
    d = date(aar - 1, 11, 1)
    while d <= i_dag:
        t = luft.get(d.isoformat())
        if t is not None:
            obs.append(t)
        if doy(d) in normal:
            klim.append(normal[doy(d)])
        d += timedelta(days=1)
    anomali = (sum(obs) / len(obs) - sum(klim) / len(klim)) if len(obs) > 30 and len(klim) > 30 else 0.0
    klima_doy = round(median - anomali * 4)
    if stefan:
        return fra_doy(aar, round(0.5 * doy(stefan) + 0.5 * klima_doy))
    return fra_doy(aar, klima_doy)


def oppsummer(feil):
    a = [abs(x) for x in feil]
    return {"n": len(feil), "median": statistics.median(feil), "snitt_abs": statistics.mean(a),
            "median_abs": statistics.median(a), "innen3": sum(1 for x in a if x <= 3),
            "innen7": sum(1 for x in a if x <= 7)}


def main():
    fasit = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    gj = json.load(io.open(os.path.join(HER, "grunnlag", "vann.geojson"), encoding="utf-8"))
    moh = {f["properties"]["navn"]: f["properties"]["moh_kode"] for f in gj["features"]}
    raa = hent_luft()
    print("Lufttemperatur %s: %d døgn, %s til %s" % (STASJON, len(raa), min(raa), max(raa)))

    rader = []
    for vann, aar_map in fasit.items():
        luft = {d: v + (STASJON_MOH - moh[vann]) * 0.6 / 100.0 for d, v in raa.items()}
        for aar_s, fdato in aar_map.items():
            aar = int(aar_s)
            f = date.fromisoformat(fdato)
            hist = {int(a): d for a, d in aar_map.items() if int(a) != aar}
            p_apr = hybrid(luft, hist, aar, date(aar, 4, 1))
            p_dag = hybrid(luft, hist, aar, f)
            doys = sorted(doy(date.fromisoformat(s)) for s in hist.values())
            p_med = fra_doy(aar, doys[len(doys) // 2])
            rader.append({"vann": vann, "aar": aar, "fasit": fdato,
                          "apr": (p_apr - f).days, "dag": (p_dag - f).days, "median": (p_med - f).days})

    linjer = ["# Dagens ismodell mot fasiten (Nordmarka, 16 vann, 2017–2026)\n",
              "Feil = modellens dato minus fasit. Positiv = modellen er for sen. "
              "Modellen har fått lære av alle andre år, også senere, så dette er dens beste tilfelle.\n",
              "| Metode | Vann-år | Skjevhet (median) | Snittavvik | Median avvik | Innen 3 d | Innen 7 d |",
              "|---|---|---|---|---|---|---|"]
    for utvalg, navn in ((None, "alle år"), (TEST, "testårene")):
        rr = [r for r in rader if utvalg is None or r["aar"] in utvalg]
        for nokkel, tekst in (("median", "Bare historisk median"), ("apr", "Hybridmodell per 1. april"),
                              ("dag", "Hybridmodell på isgangsdagen")):
            o = oppsummer([r[nokkel] for r in rr])
            linjer.append("| %s, %s | %d | %+.1f d | %.1f d | %.1f d | %d (%.0f %%) | %d (%.0f %%) |" % (
                tekst, navn, o["n"], o["median"], o["snitt_abs"], o["median_abs"],
                o["innen3"], 100.0 * o["innen3"] / o["n"], o["innen7"], 100.0 * o["innen7"] / o["n"]))
    linjer.append("\n## Per år (hybridmodell på isgangsdagen)\n")
    linjer.append("| År | Skjevhet (median) | Snittavvik |")
    linjer.append("|---|---|---|")
    for aar in sorted({r["aar"] for r in rader}):
        f = [r["dag"] for r in rader if r["aar"] == aar]
        linjer.append("| %d | %+.1f d | %.1f d |" % (aar, statistics.median(f), statistics.mean(abs(x) for x in f)))
    io.open(os.path.join(HER, "rapport_dagens_modell.md"), "w", encoding="utf-8").write("\n".join(linjer) + "\n")
    json.dump(rader, io.open(os.path.join(HER, "data", "dagens_modell.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("\n".join(linjer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
