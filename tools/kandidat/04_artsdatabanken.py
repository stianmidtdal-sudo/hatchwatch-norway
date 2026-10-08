"""
Kandidatmodell — steg 4: den strenge prøven. Artsdatabankens vulgata-funn
(936 rader, hele landet) brukt BARE som test, aldri som kalibrering.

Terskelen er låst fra steg 2 (K2: varmesum fra 1. april, base 0, terskel 450;
K1: fra 1. januar, terskel 490). For hvert sted og år tas FØRSTE funn som
«første sett»-dato. Den ligger etter den egentlige starten med ukjent
forsinkelse, så vi måler både snittfeil og hvor mye modellen ligger FORAN.

Sted = funn innenfor samme 0,05°-rute (ca. 3×5 km). Høyde: open-meteo
elevation (90 m terrengmodell) i funnpunktet. Vær: ERA5 i rutenettet,
høydekorrigert til punktet. Alt dette finnes også i Sverige.

  python 04_artsdatabanken.py            (henter vær for hvert sted; tar tid)
"""
import collections
import csv
import importlib.util
import io
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime

HER = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m2", os.path.join(HER, "02_modeller.py"))
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)
g1 = m2.g1
KILDE = os.path.join(g1.DATA, "artsdatabanken_vulgata_2026.csv")   # åpne data fra Artsdatabanken (kopi i repoet)
CACHE = os.path.join(g1.DATA, "artsdatabanken_steder.json")
TERSKEL = {"K2 varmesum fra 1. april": 450, "K1b0 varmesum fra 1. jan, base 0": 490}


def les():
    t = io.open(KILDE, encoding="utf-8-sig").read()
    sep = ";" if t.count(";") > t.count(",") else ","
    ut = []
    for r in csv.DictReader(io.StringIO(t), delimiter=sep):
        if r["validScientificName"] != "Ephemera vulgata" or r.get("absent") == "True":
            continue
        try:
            dt = datetime.strptime(r["dateTimeCollected"][:10], "%d.%m.%Y").date()
            lat = float(r["latitude"].replace(",", "."))
            lon = float(r["longitude"].replace(",", "."))
            u = float((r["coordinateUncertaintyInMeters"] or "0").replace(",", ".") or 0)
        except Exception:
            continue
        if dt.year < 2003 or dt.year > 2026 or not (4 <= dt.month <= 8) or u > 3000:
            continue
        ut.append({"dato": dt, "lat": lat, "lon": lon, "fylke": r["county"], "kommune": r["municipality"],
                   "lok": r["locality"][:50], "antall": r["individualCount"], "notat": (r.get("notes") or "")[:40]})
    return ut


def hoyde(lat, lon):
    p = dict(latitude=lat, longitude=lon)
    for i in range(4):
        try:
            with urllib.request.urlopen("https://api.open-meteo.com/v1/elevation?" + urllib.parse.urlencode(p), timeout=60) as r:
                return json.load(r)["elevation"][0]
        except Exception:
            time.sleep(10 * (i + 1))
    return None


def main():
    funn = les()
    print("Vulgata-funn brukbare: %d" % len(funn))
    # grupper i ruter
    steder = collections.defaultdict(list)
    for f in funn:
        k = "%.2f_%.2f" % (round(f["lat"] / 0.05) * 0.05, round(f["lon"] / 0.05) * 0.05)
        steder[k].append(f)
    print("Steder (0,05°-ruter): %d" % len(steder))
    cache = json.load(io.open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    rader = []
    for i, (k, fs) in enumerate(sorted(steder.items())):
        lat = statistics.mean(f["lat"] for f in fs)
        lon = statistics.mean(f["lon"] for f in fs)
        if k not in cache:
            cache[k] = {"lat": lat, "lon": lon, "moh": hoyde(lat, lon), "fylke": fs[0]["fylke"]}
            json.dump(cache, io.open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
            time.sleep(1.5)
        st = cache[k]
        if st["moh"] is None:
            continue
        navn = "ad_" + k
        m2.STEDER[navn] = {"lat": lat, "lon": lon, "moh": st["moh"]}
        g1.STEDER[navn] = (lat, lon, st["moh"])
        # Bare årene stedet har funn (værtjenesten bremser ved lange serier)
        aar_med = sorted({f["dato"].year for f in fs})
        try:
            m2._vaer[navn] = g1.hent_vaer(navn, lat, lon, "%d-01-01" % aar_med[0], "%d-08-31" % aar_med[-1])
        except SystemExit:
            print("  hoppet over", navn)
            continue
        time.sleep(0.5)
        per_aar = collections.defaultdict(list)
        for f in fs:
            per_aar[f["dato"].year].append(f)
        for y, fl in per_aar.items():
            forste = min(f["dato"] for f in fl)
            o = {"omr": navn, "aar": y, "moh": st["moh"], "dato": forste.isoformat(), "klasse": "start", "lok": fs[0]["lok"]}
            rad = {"sted": k, "fylke": st["fylke"], "kommune": fs[0]["kommune"], "lok": fs[0]["lok"], "moh": st["moh"],
                   "aar": y, "n_funn": len(fl), "forste_sett": forste.isoformat()}
            kand = m2.lag_kandidater(None)
            for navn_k, G in TERSKEL.items():
                p = kand[navn_k][0](o, G)
                rad[navn_k] = p.isoformat() if p else None
                rad[navn_k + " feil"] = (p - forste).days if p else None
            rader.append(rad)
        if (i + 1) % 20 == 0:
            print("  %d steder ferdig" % (i + 1), flush=True)

    json.dump(rader, io.open(os.path.join(g1.DATA, "artsdatabanken_test.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    L = ["# Artsdatabanken-prøven: vulgata, hele landet, terskel låst på forhånd\n",
         "Kjørt %s. %d funn → %d sted-år (første funn per sted og år). Modellen har aldri sett disse. "
         "Feil = prognose − første sett; negativt = modellen ligger foran (ventet, siden «første sett» er etter start).\n"
         % (date.today().isoformat(), len(funn), len(rader))]
    for navn_k in TERSKEL:
        e = [r[navn_k + " feil"] for r in rader if r[navn_k + " feil"] is not None]
        if not e:
            continue
        L.append("## %s (terskel %d)\n" % (navn_k, TERSKEL[navn_k]))
        L.append("| | Alle | Steder med ≥ 3 funn samme år |")
        L.append("|---|---|---|")
        e3 = [r[navn_k + " feil"] for r in rader if r[navn_k + " feil"] is not None and r["n_funn"] >= 3]
        def rad(x):
            if not x:
                return "–"
            return "n=%d, MAE %.1f d, median feil %+.0f d, innen ±7 d %.0f %%, innen ±14 d %.0f %%" % (
                len(x), sum(abs(v) for v in x) / len(x), statistics.median(x),
                100.0 * sum(abs(v) <= 7 for v in x) / len(x), 100.0 * sum(abs(v) <= 14 for v in x) / len(x))
        L.append("| Sted-år | %s | %s |" % (rad(e), rad(e3)))
        L.append("\nPer fylke (alle):\n")
        L.append("| Fylke | n | MAE | median feil | innen ±7 d |")
        L.append("|---|---|---|---|---|")
        per = collections.defaultdict(list)
        for r in rader:
            if r[navn_k + " feil"] is not None:
                per[r["fylke"]].append(r[navn_k + " feil"])
        for fy, x in sorted(per.items(), key=lambda kv: -len(kv[1])):
            L.append("| %s | %d | %.1f | %+.0f | %.0f %% |" % (fy, len(x), sum(abs(v) for v in x) / len(x), statistics.median(x),
                                                        100.0 * sum(abs(v) <= 7 for v in x) / len(x)))
        L.append("")
    # referanse: gjett én dato for alle (median av første-sett i selve prøven — snillere enn rettferdig)
    alle = [m2.doy(date.fromisoformat(r["forste_sett"])) for r in rader]
    med = statistics.median(alle)
    e0 = [int(round(med)) - a for a in alle]
    L.append("Referanse, gjett samme dato overalt (medianen av prøven selv, %s): MAE %.1f d, innen ±7 d %.0f %%.\n"
             % (m2.dato_av(2025, med).isoformat()[5:], sum(abs(v) for v in e0) / len(e0), 100.0 * sum(abs(v) <= 7 for v in e0) / len(e0)))
    io.open(os.path.join(HER, "KANDIDATMODELL_artsdatabanken.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
