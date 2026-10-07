"""
Trinn 0, steg 3 — utled isgang fra satellittseriene og sammenlign med fasiten.

Leser data/wic_tidsserie.csv (fra steg 2) og grunnlag/fasit.json (fra steg 1).
Skriver rapport.md og isgang_satellitt.json. Rører ingenting annet.

REGLENE ER SATT FØR DATAENE BLE HENTET (se LESMEG.md) og skal ikke justeres
etter at vi har sett resultatet:

  Klart pass   minst halvparten av vannets piksler er klassifisert som vann
               eller is den dagen (resten er sky), og minst 8 piksler.
  Isandel      is / (is + vann) i et klart pass.
  Isgang       første klare pass med isandel under terskelen, der også neste
               klare pass er under terskelen, og der det er sett is tidligere
               samme vår. Rapporteres som intervall:
               [siste klare pass MED is, første klare pass UTEN is].
  Terskel      0,20 er hovedterskelen. 0,50 og 0,10 vises ved siden av for å
               se hvor følsomt resultatet er. Ingen terskel velges i etterkant.

  Bestått      (1) minst 70 % av vann-årene har fasit-datoen innenfor
                   intervallet eller høyst 3 dager utenfor,
               (2) skjevheten (median avstand med fortegn) er høyst 2 dager,
               (3) median intervallbredde er høyst 7 dager. Er intervallene
                   bredere, er testen uavklart, ikke bestått: da er det skyene
                   som «treffer», ikke algoritmen.

Fortegn: positiv avstand = fasiten ligger SENERE enn satellittens intervall.

Kjør:  python 03_valider.py            vanlig kjøring
       python 03_valider.py --selvtest sjekker regelen mot konstruerte serier
"""
import csv
import io
import json
import os
import statistics
import sys
from datetime import date

HER = os.path.dirname(os.path.abspath(__file__))
TERSKLER = [0.20, 0.50, 0.10]          # første er hovedterskelen
MIN_PX = 8
MIN_KLAR_ANDEL = 0.5
KRAV_ANDEL, KRAV_DAGER, KRAV_SKJEVHET, KRAV_BREDDE = 0.70, 3, 2, 7


def d(s):
    return date.fromisoformat(s)


def klare_pass(obs, n_ref):
    """obs: liste av (dato, vann_px, is_px). Returnerer [(dato, isandel)] for klare pass."""
    ut = []
    grense = max(MIN_PX, MIN_KLAR_ANDEL * n_ref)
    for dato, vann, is_ in sorted(obs):
        if vann + is_ >= grense:
            ut.append((dato, is_ / float(vann + is_)))
    return ut


def finn_isgang(klare, terskel):
    """Returnerer dict(status, lo, hi). lo/hi er ISO-datoer eller None."""
    if not klare:
        return {"status": "ingen klare pass", "lo": None, "hi": None}
    for k in range(len(klare)):
        dato, f = klare[k]
        if f >= terskel:
            continue
        if k + 1 >= len(klare):
            return {"status": "ubekreftet (siste pass i vinduet)", "lo": None, "hi": dato}
        if klare[k + 1][1] >= terskel:
            continue                                   # åpnet seg, men frøs/drev til igjen
        tidligere_is = [j for j in range(k) if klare[j][1] >= terskel]
        if not tidligere_is:
            return {"status": "åpent ved første klare pass", "lo": None, "hi": dato}
        return {"status": "ok", "lo": klare[tidligere_is[-1]][0], "hi": dato}
    return {"status": "is i hele vinduet", "lo": klare[-1][0], "hi": None}


def avstand(fasit, lo, hi):
    """Dager fra fasit til intervallet, med fortegn. 0 = innenfor."""
    f, a, b = d(fasit), d(lo), d(hi)
    if f > b:
        return (f - b).days
    if f < a:
        return -(a - f).days
    return 0


def selvtest():
    def k(*par):
        return [("2020-%s" % dd, f) for dd, f in par]
    tilfeller = [
        ("vanlig", k(("04-01", 1.0), ("04-10", 1.0), ("04-20", 0.6), ("04-24", 0.05), ("04-27", 0.0)),
         ("ok", "2020-04-20", "2020-04-24")),
        ("åpner og fryser til igjen", k(("04-01", 1.0), ("04-05", 0.1), ("04-09", 0.9), ("04-15", 0.0), ("04-18", 0.0)),
         ("ok", "2020-04-09", "2020-04-15")),
        ("aldri is", k(("04-01", 0.0), ("04-05", 0.0)), ("åpent ved første klare pass", None, "2020-04-01")),
        ("ubekreftet", k(("04-01", 1.0), ("04-05", 0.0)), ("ubekreftet (siste pass i vinduet)", None, "2020-04-05")),
        ("is hele vinduet", k(("04-01", 1.0), ("06-20", 0.8)), ("is i hele vinduet", "2020-06-20", None)),
        ("ingen pass", [], ("ingen klare pass", None, None)),
    ]
    feil = 0
    for navn, serie, (st, lo, hi) in tilfeller:
        r = finn_isgang(serie, 0.20)
        ok = (r["status"], r["lo"], r["hi"]) == (st, lo, hi)
        feil += 0 if ok else 1
        print("%-4s %-28s -> %s [%s, %s]" % ("OK" if ok else "FEIL", navn, r["status"], r["lo"], r["hi"]))
    for fa, lo, hi, vent in [("2020-04-22", "2020-04-20", "2020-04-24", 0),
                             ("2020-04-27", "2020-04-20", "2020-04-24", 3),
                             ("2020-04-18", "2020-04-20", "2020-04-24", -2)]:
        ok = avstand(fa, lo, hi) == vent
        feil += 0 if ok else 1
        print("%-4s avstand(%s, [%s, %s]) = %d" % ("OK" if ok else "FEIL", fa, lo, hi, avstand(fa, lo, hi)))
    kl = klare_pass([("2020-04-01", 3, 2), ("2020-04-02", 60, 40), ("2020-04-03", 20, 20)], 100)
    ok = kl == [("2020-04-02", 0.4)]
    feil += 0 if ok else 1
    print("%-4s skyfilter slipper bare gjennom pass med nok klare piksler" % ("OK" if ok else "FEIL"))
    print("%d feil" % feil)
    return 1 if feil else 0


def main():
    if "--selvtest" in sys.argv:
        return selvtest()
    csvsti = os.path.join(HER, "data", "wic_tidsserie.csv")
    if not os.path.exists(csvsti):
        raise SystemExit("Fant ikke data/wic_tidsserie.csv. Kjør 02_hent_wic.py først.")
    fasit = json.load(io.open(os.path.join(HER, "grunnlag", "fasit.json"), encoding="utf-8"))
    gj = json.load(io.open(os.path.join(HER, "grunnlag", "vann.geojson"), encoding="utf-8"))
    areal = {f["properties"]["navn"]: f["properties"]["areal_ha"] for f in gj["features"]}

    serier = {}                                   # (kilde, vann, år) -> [(dato, vann_px, is_px)]
    for r in csv.DictReader(io.open(csvsti, encoding="utf-8-sig"), delimiter=";"):
        serier.setdefault((r["kilde"], r["vann"], int(r["aar"])), []).append(
            (r["dato"], int(r["vann_px"]), int(r["is_px"])))
    kilder = sorted({k[0] for k in serier})
    n_ref = {}                                    # (kilde, vann) -> største antall vann+is-piksler sett
    for (kilde, vann, _), obs in serier.items():
        n_ref[(kilde, vann)] = max(n_ref.get((kilde, vann), 0), max(v + i for _, v, i in obs))

    resultat, linjer = {}, []
    linjer.append("# Trinn 0: isgang fra Copernicus WIC mot fasit i dashboard.html\n")
    linjer.append("Regler og beståttkrav er satt på forhånd og står øverst i `03_valider.py`. "
                  "Fasiten er Stians egne avlesninger av Sentinel-bilder, så dette måler om "
                  "algoritmen er enig med øyet, ikke en uavhengig sannhet.\n")

    for kilde in kilder:
        resultat[kilde] = {}
        linjer.append("\n## Kilde: %s\n" % {"s2": "WIC S2 (optisk)", "s1s2": "WIC S1+S2 (radar + optisk)"}.get(kilde, kilde))
        linjer.append("| Terskel | Vann-år med fasit | Fikk intervall | Innenfor 3 d | Skjevhet (median) | Median bredde | Vurdering |")
        linjer.append("|---|---|---|---|---|---|---|")
        hovedrader = None
        for t in TERSKLER:
            rader, manglende = [], {}
            for vann in fasit:
                for aar, fdato in fasit[vann].items():
                    aar = int(aar)
                    obs = serier.get((kilde, vann, aar))
                    if not obs:
                        manglende["ingen data"] = manglende.get("ingen data", 0) + 1
                        continue
                    res = finn_isgang(klare_pass(obs, n_ref[(kilde, vann)]), t)
                    if t == TERSKLER[0]:
                        resultat[kilde].setdefault(vann, {})[aar] = res
                    if res["status"] != "ok":
                        manglende[res["status"]] = manglende.get(res["status"], 0) + 1
                        continue
                    rader.append({
                        "vann": vann, "aar": aar, "fasit": fdato, "lo": res["lo"], "hi": res["hi"],
                        "avst": avstand(fdato, res["lo"], res["hi"]),
                        "bredde": (d(res["hi"]) - d(res["lo"])).days,
                    })
            n_fasit = sum(len(v) for v in fasit.values())
            if rader:
                innen = sum(1 for r in rader if abs(r["avst"]) <= KRAV_DAGER) / float(len(rader))
                skjev = statistics.median(r["avst"] for r in rader)
                bredde = statistics.median(r["bredde"] for r in rader)
                if bredde > KRAV_BREDDE:
                    dom = "uavklart (for brede intervaller)"
                elif innen >= KRAV_ANDEL and abs(skjev) <= KRAV_SKJEVHET and len(rader) >= 0.5 * n_fasit:
                    dom = "bestått"
                elif len(rader) < 0.5 * n_fasit:
                    dom = "uavklart (for få vann-år ga intervall)"
                else:
                    dom = "ikke bestått"
                linjer.append("| %.2f%s | %d | %d | %.0f %% | %+.1f d | %.0f d | %s |" % (
                    t, " (hoved)" if t == TERSKLER[0] else "", n_fasit, len(rader),
                    innen * 100, skjev, bredde, dom))
            else:
                linjer.append("| %.2f | %d | 0 | – | – | – | uavklart (ingen intervaller) |" % (t, n_fasit))
            if t == TERSKLER[0]:
                hovedrader, hovedmangel = rader, manglende

        linjer.append("\nUten intervall ved hovedterskelen: " + (
            ", ".join("%s: %d" % kv for kv in sorted(hovedmangel.items())) or "ingen") + ".\n")
        linjer.append("### Per vann, hovedterskel 0,20\n")
        linjer.append("| Vann | Areal | Piksler | År med intervall | Innenfor 3 d | Skjevhet | Median bredde |")
        linjer.append("|---|---|---|---|---|---|---|")
        for vann in fasit:
            rr = [r for r in hovedrader if r["vann"] == vann]
            if rr:
                linjer.append("| %s | %.1f ha | %d | %d av %d | %d | %+.1f d | %.0f d |" % (
                    vann, areal.get(vann, 0), n_ref.get((kilde, vann), 0), len(rr), len(fasit[vann]),
                    sum(1 for r in rr if abs(r["avst"]) <= KRAV_DAGER),
                    statistics.median(r["avst"] for r in rr), statistics.median(r["bredde"] for r in rr)))
            else:
                linjer.append("| %s | %.1f ha | %d | 0 av %d | – | – | – |" % (
                    vann, areal.get(vann, 0), n_ref.get((kilde, vann), 0), len(fasit[vann])))
        linjer.append("\n### Alle vann-år, hovedterskel 0,20\n")
        linjer.append("| Vann | År | Fasit | Siste is | Første åpent | Avstand | Bredde |")
        linjer.append("|---|---|---|---|---|---|---|")
        for r in sorted(hovedrader, key=lambda r: (r["vann"], r["aar"])):
            linjer.append("| %s | %d | %s | %s | %s | %+d d | %d d |" % (
                r["vann"], r["aar"], r["fasit"], r["lo"], r["hi"], r["avst"], r["bredde"]))

    io.open(os.path.join(HER, "rapport.md"), "w", encoding="utf-8").write("\n".join(linjer) + "\n")
    json.dump(resultat, io.open(os.path.join(HER, "isgang_satellitt.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("Skrevet rapport.md og isgang_satellitt.json")
    for l in linjer:
        if l.startswith("| 0.") or l.startswith("## "):
            print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
