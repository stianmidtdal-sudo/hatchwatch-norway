"""
Trinn 1, steg 1 — hent rå Sentinel-2-målinger per vann (egen klassifisering).

Bakgrunn: trinn 0 viste at det ferdige WIC-produktet melder åpent vann uker
før isen går (se KONKLUSJON_trinn0.md). Her henter vi i stedet selve
refleksjonen fra Sentinel-2 L2A for hvert vannpolygon og hvert pass, og
klassifiserer selv i 05_valider_s2.py.

For hver piksel regnes to tall:
  vis   = snitt av blått, grønt og rødt (B02, B03, B04). Hvor lyst det er.
  ndsi  = (B03 - B11) / (B03 + B11). Snø og is er lyse i synlig lys men
          mørke i kortbølget infrarødt (høy ndsi). Skyer er lyse i begge
          (lav ndsi). Brukes KUN til å skille lys is fra lys sky, aldri
          alene: åpent vann har også høy ndsi.

Pikslene telles i en tabell med 6 lyshetstrinn x 3 ndsi-trinn. Da kan
tersklene velges i etterkant uten å hente data på nytt, og de velges kun på
treningsårene (se 05_valider_s2.py).

Kjør:
  python 04_hent_s2.py --prov     ett vann, ett år
  python 04_hent_s2.py            alle 16 vann, 2017–2026
Svar lagres i data/raa/l2a/ og hentes ikke på nytt.
"""
import argparse
import csv
import importlib.util
import io
import json
import os
import sys

HER = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("hent_wic", os.path.join(HER, "02_hent_wic.py"))
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)

VIS_KANTER = [0.05, 0.08, 0.12, 0.20, 0.40]     # 6 trinn: v0 (mørkest) … v5 (lysest)
NDSI_KANTER = [0.2, 0.4]                         # 3 trinn: n0 (lav) … n2 (høy)
BINS = ["v%dn%d" % (v, n) for v in range(6) for n in range(3)]
SCL = ["sky", "skygge", "sno", "vann", "annet"]

EVALSCRIPT = """//VERSION=3
var VK = %s, NK = %s;
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "B11", "SCL", "dataMask"] }],
    output: [
      { id: "ref", bands: ["vis", "b11"], sampleType: "FLOAT32" },
      { id: "bin", bands: %s, sampleType: "UINT8" },
      { id: "scl", bands: %s, sampleType: "UINT8" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function trinn(x, kanter) { var i = 0; while (i < kanter.length && x >= kanter[i]) i++; return i; }
function evaluatePixel(s) {
  var vis = (s.B02 + s.B03 + s.B04) / 3;
  var sum = s.B03 + s.B11;
  var ndsi = sum > 0 ? (s.B03 - s.B11) / sum : 0;
  var bin = new Array(18).fill(0);
  bin[trinn(vis, VK) * 3 + trinn(ndsi, NK)] = 1;
  var c = s.SCL;
  var scl = [(c === 8 || c === 9 || c === 10) ? 1 : 0, c === 3 ? 1 : 0, c === 11 ? 1 : 0, c === 6 ? 1 : 0, 0];
  if (scl[0] + scl[1] + scl[2] + scl[3] === 0) scl[4] = 1;
  return { ref: [vis, s.B11], bin: bin, scl: scl, dataMask: [s.dataMask] };
}
""" % (json.dumps(VIS_KANTER), json.dumps(NDSI_KANTER), json.dumps(BINS), json.dumps(SCL))


def bygg(geom, aar):
    k = h.bygg_foresporsel(geom, "s2", aar)
    k["input"]["data"] = [{"type": "sentinel-2-l2a", "dataFilter": {"mosaickingOrder": "leastCC"}}]
    k["aggregation"]["evalscript"] = EVALSCRIPT
    return k


def flat_ut(svar):
    """→ liste av dict per dato: gyldige piksler, snitt-lyshet, tellinger per bin og SCL-gruppe."""
    ut = []
    for d in svar.get("data", []):
        o = d.get("outputs", {})
        bb = o.get("bin", {}).get("bands", {})
        if not bb:
            continue
        st0 = bb[BINS[0]]["stats"]
        n = (st0.get("sampleCount") or 0) - (st0.get("noDataCount") or 0)
        if n <= 0:
            continue
        def tell(gruppe, navn):
            m = o.get(gruppe, {}).get("bands", {}).get(navn, {}).get("stats", {}).get("mean")
            return int(round(m * n)) if m is not None and m == m else 0
        vis = o.get("ref", {}).get("bands", {}).get("vis", {}).get("stats", {}).get("mean")
        rad = {"dato": d["interval"]["from"][:10], "n": n,
               "vis": round(vis, 4) if vis is not None and vis == vis else None}
        for b in BINS:
            rad[b] = tell("bin", b)
        for c in SCL:
            rad["scl_" + c] = tell("scl", c)
        ut.append(rad)
    return ut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prov", action="store_true")
    a = ap.parse_args()
    gj = json.load(io.open(os.path.join(h.GRUNNLAG, "vann.geojson"), encoding="utf-8"))
    vann, aar = gj["features"], h.AAR
    if a.prov:
        vann, aar = vann[:1], aar[-1:]
    mappe = os.path.join(h.RAA, "l2a")
    os.makedirs(mappe, exist_ok=True)
    token = h.hent_token(h.les_env())
    print("Logget inn hos Copernicus.")
    pu_sum, nye = 0.0, 0
    for f in vann:
        pr = f["properties"]
        for y in aar:
            sti = os.path.join(mappe, "%s_%d.json" % (pr["vatnlnr"], y))
            if os.path.exists(sti):
                continue
            svar, pu = h.send(token, bygg(f["geometry"], y))
            json.dump(svar, io.open(sti, "w", encoding="utf-8"))
            nye += 1
            pu_sum += pu or 0
            print("  %-22s %d: %3d pass%s" % (pr["navn"], y, len(flat_ut(svar)),
                                              "  (%.2f PU)" % pu if pu is not None else ""), flush=True)
    print("Hentet %d nye vann-år. Forbruk: %.1f PU." % (nye, pu_sum))
    if a.prov and nye:
        print("Anslag for full kjøring (160 vann-år): ca. %.0f PU av 30 000 per måned." % (pu_sum / nye * 160))

    per_lnr = {f["properties"]["vatnlnr"]: f["properties"]["navn"] for f in gj["features"]}
    kol = ["vann", "vatnlnr", "aar", "dato", "n", "vis"] + BINS + ["scl_" + c for c in SCL]
    ant = 0
    with io.open(os.path.join(h.DATA, "s2_tidsserie.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=kol, delimiter=";")
        w.writeheader()
        for fil in sorted(os.listdir(mappe)):
            lnr, y = fil[:-5].split("_")
            for rad in flat_ut(json.load(io.open(os.path.join(mappe, fil), encoding="utf-8"))):
                rad.update({"vann": per_lnr.get(int(lnr), lnr), "vatnlnr": lnr, "aar": y})
                w.writerow(rad)
                ant += 1
    print("Skrevet data/s2_tidsserie.csv (%d rader)." % ant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
