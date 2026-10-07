"""
Trinn 0, steg 1 — bygg grunnlaget (krever ingen konto).

  1. Leser fasiten (isgangHistory per vann) rett ut av dashboard.html,
     så vi aldri sammenligner mot en håndkopiert versjon.
  2. Henter polygonene for de samme vannene fra NVE Innsjødatabase
     (kart.nve.no, åpne data) i UTM33 (EPSG:32633).

Skriver:
  grunnlag/fasit.json     { vann: { år: 'YYYY-MM-DD' } }
  grunnlag/vann.geojson   ett polygon per vann, med navn, vatnLnr, høyde, areal

Kjør:  python 01_bygg_grunnlag.py
Bruker bare Pythons standardbibliotek.
"""
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HER = os.path.dirname(os.path.abspath(__file__))
ROT = os.path.abspath(os.path.join(HER, "..", ".."))
DASH = os.path.join(ROT, "dashboard.html")
UT = os.path.join(HER, "grunnlag")
NVE = "https://kart.nve.no/enterprise/rest/services/Innsjodatabase2/MapServer/5/query"


def les_fasit():
    """Plukker ofaLakes-blokka i nordmarka_dyn ut av dashboard.html."""
    html = io.open(DASH, encoding="utf-8").read()
    start = html.index("ofaLakes: [")
    slutt = html.index("],", start)
    blokk = html[start:slutt]
    fasit, hoyde = {}, {}
    for m in re.finditer(
        r"\{\s*name:\s*'([^']+)'\s*,\s*altitude:\s*(\d+)\s*,\s*isgangHistory:\s*\{(.*?)\}\s*\}",
        blokk, re.S,
    ):
        navn, moh, hist = m.group(1), int(m.group(2)), m.group(3)
        aar = {int(a): d for a, d in re.findall(r"(\d{4})\s*:\s*'(\d{4}-\d{2}-\d{2})'", hist)}
        fasit[navn] = dict(sorted(aar.items()))
        hoyde[navn] = moh
    return fasit, hoyde


def hent_nve(lnr_liste):
    p = dict(
        where="vatnlnr IN (%s)" % ",".join(str(x) for x in lnr_liste),
        outFields="vatnlnr,navn,hoyde,areal_km2,dybdekart",
        returnGeometry="true", outSR="32633", f="geojson",
    )
    with urllib.request.urlopen(NVE + "?" + urllib.parse.urlencode(p), timeout=120) as r:
        return json.load(r)


def tyngdepunkt_nord(geom):
    """Snitt av y-koordinatene i ytterringen(e) — nok til å skille nord fra sør."""
    ringer = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
    ys = [pt[1] for ring in ringer for pt in ring]
    return sum(ys) / len(ys)


def main():
    os.makedirs(UT, exist_ok=True)
    fasit, hoyde = les_fasit()
    print("Fasit lest fra dashboard.html: %d vann, %d vann-år"
          % (len(fasit), sum(len(v) for v in fasit.values())))

    kobling = json.load(io.open(os.path.join(HER, "vann.json"), encoding="utf-8"))["vann"]
    mangler = [k["navn"] for k in kobling if k["navn"] not in fasit]
    ekstra = [n for n in fasit if n not in {k["navn"] for k in kobling}]
    if mangler or ekstra:
        print("ADVARSEL: vann.json og dashboard.html er ikke i takt. Mangler i fasit: %s. "
              "Mangler i vann.json: %s" % (mangler, ekstra))

    lnr = set()
    for k in kobling:
        if k.get("vatnlnr"):
            lnr.add(k["vatnlnr"])
        lnr.update(k.get("kandidater", []))
    gj = hent_nve(sorted(lnr))
    per_lnr = {f["properties"]["vatnlnr"]: f for f in gj["features"]}
    print("Polygoner hentet fra NVE: %d av %d" % (len(per_lnr), len(lnr)))

    # Auretjern Nord/Sør: to polygoner med samme navn, skilles på plassering.
    aure = [k for k in kobling if k.get("kandidater")]
    if aure:
        kand = sorted(aure[0]["kandidater"], key=lambda n: tyngdepunkt_nord(per_lnr[n]["geometry"]))
        sor, nord = kand[0], kand[-1]
        for k in aure:
            k["vatnlnr"] = nord if "Nord" in k["navn"] else sor

    ut = {"type": "FeatureCollection", "crs_epsg": 32633, "features": []}
    print("\n%-22s %-22s %7s %7s %8s  %s" % ("Navn i koden", "Navn hos NVE", "kode", "NVE", "areal", "dybdekart"))
    for k in kobling:
        f = per_lnr.get(k["vatnlnr"])
        if not f:
            print("%-22s MANGLER hos NVE (lnr %s)" % (k["navn"], k["vatnlnr"]))
            continue
        pr = f["properties"]
        ha = (pr.get("areal_km2") or 0) * 100
        print("%-22s %-22s %5s m %5s m %6.1f ha  %s" % (
            k["navn"], pr.get("navn"), hoyde.get(k["navn"]), pr.get("hoyde"), ha,
            "ja" if pr.get("dybdekart") else "nei"))
        ut["features"].append({
            "type": "Feature",
            "properties": {
                "navn": k["navn"], "vatnlnr": k["vatnlnr"], "nve_navn": pr.get("navn"),
                "moh_kode": hoyde.get(k["navn"]), "moh_nve": pr.get("hoyde"),
                "areal_ha": round(ha, 2), "dybdekart": bool(pr.get("dybdekart")),
            },
            "geometry": f["geometry"],
        })

    json.dump(fasit, io.open(os.path.join(UT, "fasit.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(ut, io.open(os.path.join(UT, "vann.geojson"), "w", encoding="utf-8"),
              ensure_ascii=False)
    print("\nSkrevet: grunnlag/fasit.json og grunnlag/vann.geojson (%d vann)" % len(ut["features"]))

    # Hvor uavhengige er fasit-seriene? Like serier teller ikke som to observasjoner.
    sett = {}
    for navn, aar in fasit.items():
        sett.setdefault(json.dumps(aar, sort_keys=True), []).append(navn)
    like = [v for v in sett.values() if len(v) > 1]
    print("Ulike fasit-serier: %d av %d vann." % (len(sett), len(fasit)))
    for v in like:
        print("  Identiske datoer alle år: " + " = ".join(v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
