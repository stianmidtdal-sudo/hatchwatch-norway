"""
Forslag til isgangsdatoer for alle vannene i dashboardet.

For hvert vann og år: Stians dato (hvis den finnes) ved siden av satellittens
intervall [siste is, første åpent] og midtpunktet. Der Stian mangler dato,
foreslås midtpunktet. Metoden er den låste fra valgt_metode.json.

Vann uten egen fasit (Romeriksåsen: Storøyungen) hentes her hvis de ikke
ligger i data/raa/ fra før.

Skriver:
  forslag_isgang.md     tabellen, til gjennomsyn
  forslag_isgang.json   samme innhold maskinlesbart, pluss ferdige
                        isgangHistory-snutter for år som mangler

Ingenting legges inn i dashboard.html. Det gjør Stian etter gjennomsyn.

Kjør:  python 08_forslag.py
"""
import csv
import importlib.util
import io
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import timedelta

HER = os.path.dirname(os.path.abspath(__file__))


def last(navn, fil):
    s = importlib.util.spec_from_file_location(navn, os.path.join(HER, fil))
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


h = last("h", "02_hent_wic.py")
h4 = last("h4", "04_hent_s2.py")
v3 = last("v3", "03_valider.py")
v5 = last("v5", "05_valider_s2.py")
a7 = last("a7", "07_andre_steder.py")
nabo = last("nabo", "nabo.py")

EKSTRA = [  # vann uten fasit i dashboardet
    {"lok": "romeriksasen", "navn": "Storøyungen", "vatnlnr": 5035},
]
USIKKER_BREDDE = 10
AAR = list(range(2017, 2027))


def fyll_manglende(vannliste, mappe):
    """Henter rå Sentinel-2 for de årene i AAR som mangler i mappa."""
    os.makedirs(mappe, exist_ok=True)
    trenger = [e for e in vannliste if not all(os.path.exists(os.path.join(mappe, "%s_%d.json" % (e["lok"], y))) for y in AAR)]
    if trenger:
        p = dict(where="vatnlnr IN (%s)" % ",".join(str(e["vatnlnr"]) for e in trenger),
                 outFields="vatnlnr,navn,hoyde,areal_km2", returnGeometry="true", outSR="32633", f="geojson")
        with urllib.request.urlopen(a7.v_nve() + "?" + urllib.parse.urlencode(p), timeout=180) as r:
            per_lnr = {f["properties"]["vatnlnr"]: f for f in json.load(r)["features"]}
        token = h.hent_token(h.les_env())
        pu = 0.0
        for e in trenger:
            f = per_lnr[e["vatnlnr"]]
            res = 20 if (f["properties"].get("areal_km2") or 0) * 100 <= 150 else 40
            for y in AAR:
                sti = os.path.join(mappe, "%s_%d.json" % (e["lok"], y))
                if os.path.exists(sti):
                    continue
                k = h4.bygg(f["geometry"], y)
                k["aggregation"]["timeRange"] = {"from": "%d-02-01T00:00:00Z" % y, "to": "%d-08-01T00:00:00Z" % y}
                k["aggregation"]["resx"] = k["aggregation"]["resy"] = res
                svar, brukt = h.send(token, k)
                json.dump(svar, io.open(sti, "w", encoding="utf-8"))
                pu += brukt or 0
                print("  hentet %s %d (%.1f PU)" % (e["navn"], y, brukt or 0), flush=True)
        print("Forbruk: %.0f PU" % pu)


def hent_ekstra(valg):
    """Henter rå Sentinel-2 for EKSTRA-vannene hvis de mangler. Returnerer serier."""
    mappe = os.path.join(h.RAA, "l2a_ekstra")
    fyll_manglende(EKSTRA, mappe)
    serier = {}
    for fil in sorted(os.listdir(mappe)):
        lok, y = fil[:-5].rsplit("_", 1)
        for rad in h4.flat_ut(json.load(io.open(os.path.join(mappe, fil), encoding="utf-8"))):
            serier.setdefault((lok, int(y)), []).append(rad)
    return serier


def intervaller(serier, valg, nokler, fasit=None, posisjon=None):
    """Intervall per (vann, år). Med fasit+posisjon brukes nabo-regelen (nabo.py)."""
    klare = {}
    for n in nokler:
        obs = serier.get(n)
        klare[n] = a7.klare(obs, valg["tv"], valg["tn"], valg["regel"]) if obs else None
    ut = {}
    for n in nokler:
        vann, aar = n
        if klare[n] is None:
            ut[n] = {"status": "ingen data", "indirekte": False}
            continue
        egne = klare[n]
        if fasit is not None and posisjon is not None:
            valgt = nabo.velg_nabo(vann, aar, fasit, posisjon)
            if valgt and klare.get((valgt[0], aar)):
                b, forsk, _ = valgt
                res = nabo.finn_isgang_med_kilde(nabo.laan_pass(egne, klare[(b, aar)], forsk, b), v5.TERSKEL)
                res["nabo"] = "%s (%+d d)" % (b, forsk)
                ut[n] = res
                continue
        res = v3.finn_isgang(egne, v5.TERSKEL)
        res["indirekte"] = False
        ut[n] = res
    return ut


def midt(res):
    lo, hi = v3.d(res["lo"]), v3.d(res["hi"])
    return (lo + timedelta(days=(hi - lo).days // 2)).isoformat(), (hi - lo).days


def main():
    valg = json.load(io.open(a7.VALG_FIL, encoding="utf-8"))
    grupper = []   # (overskrift, [(vannnavn, fasit-dict, serier-nøkkel-funksjon)])

    # Nordmarka — med nabo-regelen (fasit + posisjoner finnes)
    fasit_n = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    ser_n = v5.les_s2()
    gj = json.load(io.open(os.path.join(HER, "grunnlag", "vann.geojson"), encoding="utf-8"))
    pos_n = {f["properties"]["navn"]: nabo.tyngdepunkt(f["geometry"]) for f in gj["features"]}
    grupper.append(("Nordmarka (nordmarka_dyn → ofaLakes), med nabo-regel", [(v, fasit_n[v], ser_n, v, fasit_n, pos_n) for v in fasit_n]))

    # Andre lokasjoner — år som mangler i fasiten ble ikke hentet i 07; hent dem nå.
    meta = {m["lok"]: m for m in json.load(io.open(os.path.join(HER, "grunnlag", "andre_vann_meta.json"), encoding="utf-8"))}
    alle_fasit = a7.les_fasit_andre()
    fyll_manglende([{"lok": m["lok"], "navn": m["navn"], "vatnlnr": m["vatnlnr"]} for m in meta.values()], a7.RAA_ANDRE)
    ser_a = {}
    for fil in sorted(os.listdir(a7.RAA_ANDRE)):
        lok, y = fil[:-5].rsplit("_", 1)
        for rad in h4.flat_ut(json.load(io.open(os.path.join(a7.RAA_ANDRE, fil), encoding="utf-8"))):
            ser_a.setdefault((lok, int(y)), []).append(rad)
    grupper.append(("Andre lokasjoner (isgangWater)", [("%s (%s)" % (lok, meta[lok]["navn"]), alle_fasit.get(lok, {}), ser_a, lok, None, None) for lok in meta]))

    # Ekstra uten fasit
    ser_e = hent_ekstra(valg)
    grupper.append(("Uten fasit i dag", [("%s (%s)" % (e["lok"], e["navn"]), {}, ser_e, e["lok"], None, None) for e in EKSTRA]))

    L = ["# Forslag til isgangsdatoer fra satellitt\n",
         "Metode: låst 5. okt 2026 (`valgt_metode.json`). «Midt» = midten av intervallet [siste is, første åpent]. "
         "Forslag gis for år uten dato. Intervall bredere enn %d dager er merket usikker. "
         "I Nordmarka brukes nabo-regelen (`nabo.py`): skyhull tettes med pass fra et vann som "
         "historisk går likt, og slike intervaller er merket «indirekte». "
         "Ingenting er lagt inn i dashboardet.\n" % USIKKER_BREDDE]
    ut = {"metode": valg, "vann": {}, "snutter": {}}
    sjekk = []
    for overskrift, liste in grupper:
        L.append("\n## %s\n" % overskrift)
        for navn, fasit, serier, nokkel, fasit_gruppe, pos_gruppe in liste:
            # Nabo-regelen trenger hele gruppas serier under samme nøkkelrom
            if fasit_gruppe is not None:
                nokler = [(v, y) for v in fasit_gruppe for y in AAR]
                res_alle = intervaller(serier, valg, nokler, fasit_gruppe, pos_gruppe)
                res = {(nokkel, y): res_alle[(nokkel, y)] for y in AAR}
            else:
                res = intervaller(serier, valg, [(nokkel, y) for y in AAR])
            L.append("\n### %s\n" % navn)
            L.append("| År | Din dato | Siste is | Første åpent | Midt | Bredde | Kilde | Avvik | Forslag / merknad |")
            L.append("|---|---|---|---|---|---|---|---|---|")
            rader, snutt = [], {}
            for y in AAR:
                r = res[(nokkel, y)]
                din = fasit.get(str(y))
                kilde = ("indirekte, lånt fra " + ", ".join(r.get("laant_fra", []))) if r.get("indirekte") else "direkte"
                if r["status"] == "ok":
                    m, b = midt(r)
                    avv = v3.avstand(din, r["lo"], r["hi"]) if din else None
                    if din:
                        merk = "" if abs(avv) <= 3 else ("**sjekk**: %+d d utenfor" % avv)
                        if abs(avv) > 7:
                            sjekk.append((navn, y, din, r["lo"], r["hi"], avv))
                    else:
                        merk = "forslag **%s**" % m + (" (usikker, %d d)" % b if b > USIKKER_BREDDE else "")
                        snutt[y] = m
                    L.append("| %d | %s | %s | %s | %s | %d d | %s | %s | %s |" % (
                        y, din or "–", r["lo"], r["hi"], m, b, kilde, ("%+d d" % avv) if din else "–", merk))
                    rader.append({"aar": y, "din": din, "lo": r["lo"], "hi": r["hi"], "midt": m, "bredde": b,
                                  "avvik": avv, "kilde": kilde})
                else:
                    L.append("| %d | %s | – | – | – | – | %s | – | %s |" % (y, din or "–", kilde, r["status"]))
                    rader.append({"aar": y, "din": din, "status": r["status"], "kilde": kilde})
            ut["vann"][navn] = rader
            if snutt:
                ut["snutter"][navn] = snutt
                L.append("\nSnutt for år som mangler (isgangHistory-format):\n")
                L.append("    " + ", ".join("%d: '%s'" % (y, d) for y, d in sorted(snutt.items())))
    L.append("\n## Vann-år der din dato og satellitten spriker mer enn 7 dager\n")
    if sjekk:
        L.append("| Vann | År | Din dato | Siste is | Første åpent | Avvik |")
        L.append("|---|---|---|---|---|---|")
        for s in sjekk:
            L.append("| %s | %d | %s | %s | %s | %+d d |" % s)
    else:
        L.append("Ingen.")
    L.append("\nIkke dekket: Narvik («Banjodalen» er ikke et vann), Ifjordfjellet, Dividalen og Bardu "
             "(vannet lot seg ikke identifisere entydig, se `andre_vann.json`).\n")
    io.open(os.path.join(HER, "forslag_isgang.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(ut, io.open(os.path.join(HER, "forslag_isgang.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Skrevet forslag_isgang.md og forslag_isgang.json")
    print("Vann med forslag for manglende år: %d. Vann-år som bør sjekkes (sprik > 7 d): %d." % (len(ut["snutter"]), len(sjekk)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
