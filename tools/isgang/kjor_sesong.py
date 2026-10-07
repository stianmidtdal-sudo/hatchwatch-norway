"""
Trinn A — ukentlig avlesning av isgang for sesongen, i én kommando.

Leser alle ankervannene (andre_vann.json), de 16 Nordmarka-vannene og
ekstravannene (Storøyungen) for ett år, med den låste metoden
(valgt_metode.json) og nabo-regelen (nabo.py) der det finnes naboer.

  python kjor_sesong.py              inneværende år
  python kjor_sesong.py 2026         et gitt år

Inneværende år hentes på nytt hver gang (nye pass kommer hele våren).
Tidligere år hentes bare hvis de mangler. Forbruk: noen titalls enheter.

Skriver sesong_<år>.md (til gjennomsyn) og sesong_<år>.json.
INGENTING legges inn i dashboard.html. Det gjør Stian etter gjennomsyn.
"""
import importlib.util
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

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
f8 = last("f8", "08_forslag.py")

USIKKER = 10


def polygoner(lnr_liste):
    ut = {}
    for i in range(0, len(lnr_liste), 200):
        p = dict(where="vatnlnr IN (%s)" % ",".join(str(x) for x in lnr_liste[i:i + 200]),
                 outFields="vatnlnr,areal_km2", returnGeometry="true", outSR="32633", f="geojson")
        with urllib.request.urlopen(a7.v_nve() + "?" + urllib.parse.urlencode(p), timeout=300) as r:
            for f in json.load(r)["features"]:
                ut[f["properties"]["vatnlnr"]] = f
    return ut


def hent_aar(token, geom, aar, res, sti, alltid):
    if os.path.exists(sti) and not alltid:
        return 0.0
    k = h4.bygg(geom, aar)
    k["aggregation"]["timeRange"] = {"from": "%d-02-01T00:00:00Z" % aar, "to": "%d-08-01T00:00:00Z" % aar}
    k["aggregation"]["resx"] = k["aggregation"]["resy"] = res
    svar, pu = h.send(token, k)
    json.dump(svar, io.open(sti, "w", encoding="utf-8"))
    return pu or 0.0


def serie(sti):
    return h4.flat_ut(json.load(io.open(sti, encoding="utf-8"))) if os.path.exists(sti) else None


def main():
    aar = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year
    i_dag = date.today()
    valg = json.load(io.open(a7.VALG_FIL, encoding="utf-8"))
    gj = json.load(io.open(os.path.join(h.GRUNNLAG, "vann.geojson"), encoding="utf-8"))
    fasit_n = json.load(io.open(os.path.join(h.GRUNNLAG, "fasit.json"), encoding="utf-8"))
    kobling = json.load(io.open(os.path.join(HER, "andre_vann.json"), encoding="utf-8"))["vann"]
    dash = a7.les_fasit_andre()                     # det som alt ligger i dashboardet (per lokasjon)

    # Vannliste: (gruppe, visningsnavn, nøkkel i rådata, vatnlnr, mappe, res)
    liste = []
    for f in gj["features"]:
        pr = f["properties"]
        liste.append(("Nordmarka", pr["navn"], str(pr["vatnlnr"]), pr["vatnlnr"], os.path.join(h.RAA, "l2a"), 20))
    for k in kobling:
        liste.append(("Ankervann", "%s (%s)" % (k["lok"], k["navn"]), k["lok"], k["vatnlnr"], a7.RAA_ANDRE, None))
    for e in f8.EKSTRA:
        liste.append(("Uten fasit", "%s (%s)" % (e["lok"], e["navn"]), e["lok"], e["vatnlnr"], os.path.join(h.RAA, "l2a_ekstra"), None))

    geom = polygoner(sorted({x[3] for x in liste}))
    token = h.hent_token(h.les_env())
    print("Logget inn. Leser %d vann for %d." % (len(liste), aar))
    pu_sum = 0.0
    for gruppe, navn, nokkel, lnr, mappe, res in liste:
        g = geom.get(lnr)
        if not g:
            print("  mangler polygon:", navn)
            continue
        if res is None:
            ha = (g["properties"].get("areal_km2") or 0) * 100
            res = 20 if ha <= 150 else 40
        os.makedirs(mappe, exist_ok=True)
        sti = os.path.join(mappe, "%s_%d.json" % (nokkel, aar))
        pu_sum += hent_aar(token, g["geometry"], aar, res, sti, alltid=(aar == i_dag.year))
    print("Hentet. Forbruk: %.0f PU." % pu_sum)

    # Nabo-regel for Nordmarka: egne serier for alle år
    pos_n = {f["properties"]["navn"]: nabo.tyngdepunkt(f["geometry"]) for f in gj["features"]}
    klare_n = {}
    for f in gj["features"]:
        pr = f["properties"]
        for y in range(2017, aar + 1):
            s = serie(os.path.join(h.RAA, "l2a", "%s_%d.json" % (pr["vatnlnr"], y)))
            if s:
                klare_n[(pr["navn"], y)] = a7.klare(s, valg["tv"], valg["tn"], valg["regel"])

    L = ["# Isgang %d — satellittavlesning per %s\n" % (aar, i_dag.isoformat()),
         "Metode: `valgt_metode.json`, nabo-regel i Nordmarka. «Forslag» = midten av intervallet. "
         "Ingenting er lagt inn i dashboardet.\n",
         "| Gruppe | Vann | Status | Siste is | Første åpent | Forslag | Bredde | Kilde | I dashboardet |",
         "|---|---|---|---|---|---|---|---|---|"]
    ut = {}
    for gruppe, navn, nokkel, lnr, mappe, res in liste:
        s = serie(os.path.join(mappe, "%s_%d.json" % (nokkel, aar)))
        if not s:
            L.append("| %s | %s | ingen data | – | – | – | – | – | – |" % (gruppe, navn))
            continue
        egne = a7.klare(s, valg["tv"], valg["tn"], valg["regel"])
        r, kilde = None, "direkte"
        if gruppe == "Nordmarka":
            valgt = nabo.velg_nabo(navn, aar, fasit_n, pos_n)
            if valgt and klare_n.get((valgt[0], aar)):
                b, forsk, _ = valgt
                r = nabo.finn_isgang_med_kilde(nabo.laan_pass(egne, klare_n[(b, aar)], forsk, b), v5.TERSKEL)
                kilde = ("indirekte, lånt fra " + ", ".join(r.get("laant_fra", []))) if r.get("indirekte") else "direkte"
        if r is None:
            r = v3.finn_isgang(egne, v5.TERSKEL)
        i_dash = (fasit_n.get(navn, {}) if gruppe == "Nordmarka" else dash.get(nokkel, {})).get(str(aar), "–")
        if r["status"] == "ok":
            lo, hi = v3.d(r["lo"]), v3.d(r["hi"])
            b = (hi - lo).days
            m = (lo + timedelta(days=b // 2)).isoformat()
            st = "isgang" + (" (usikker, %d d)" % b if b > USIKKER else "")
            L.append("| %s | %s | %s | %s | %s | **%s** | %d d | %s | %s |" % (gruppe, navn, st, r["lo"], r["hi"], m, b, kilde, i_dash))
            ut[navn] = {"status": "ok", "lo": r["lo"], "hi": r["hi"], "forslag": m, "bredde": b, "kilde": kilde, "i_dashboardet": i_dash}
        else:
            siste = egne[-1][0] if egne else "–"
            L.append("| %s | %s | %s (siste klare pass %s) | – | – | – | – | %s | %s |" % (gruppe, navn, r["status"], siste, kilde, i_dash))
            ut[navn] = {"status": r["status"], "siste_klare_pass": siste, "i_dashboardet": i_dash}
    L.append("\nStatus «is i hele vinduet» betyr at satellitten ennå ikke har sett åpent vann. "
             "«ubekreftet» betyr ett åpent pass som venter på neste klare pass.\n")
    io.open(os.path.join(HER, "sesong_%d.md" % aar), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(ut, io.open(os.path.join(HER, "sesong_%d.json" % aar), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Skrevet sesong_%d.md og sesong_%d.json" % (aar, aar))
    print("\n".join(L[3:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
