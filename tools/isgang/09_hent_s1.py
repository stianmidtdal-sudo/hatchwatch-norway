"""
Radar-eksperiment, steg 1 — hent rå Sentinel-1-målinger per vann.

Radaren ser gjennom skyer, men ser ruhet, ikke farge: stille åpent vann er
mørkt, tørr is med snø er lys, våt snø og smeltevann på isen er også mørkt,
og vind gjør åpent vann lyst. Derfor skal radar her bare brukes som
BEKREFTELSE på åpent vann, aldri som bevis på is (se 10_valider_s1.py).

Per piksel: VV-tilbakespredning i dB, telt i fem trinn
  b0 < -22   b1 -22..-19   b2 -19..-16   b3 -16..-13   b4 >= -13
Terskelen for «mørkt» velges i etterkant, kun på treningsårene.

Kjør:  python 09_hent_s1.py --prov | python 09_hent_s1.py
Svar lagres i data/raa/s1/ og hentes ikke på nytt.
"""
import argparse
import csv
import importlib.util
import io
import json
import os
import sys

HER = os.path.dirname(os.path.abspath(__file__))
_s = importlib.util.spec_from_file_location("h", os.path.join(HER, "02_hent_wic.py"))
h = importlib.util.module_from_spec(_s)
_s.loader.exec_module(h)

BINS = ["b0", "b1", "b2", "b3", "b4"]
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["VV", "VH", "dataMask"] }],
    output: [
      { id: "db", bands: ["vv", "vh"], sampleType: "FLOAT32" },
      { id: "bin", bands: ["b0", "b1", "b2", "b3", "b4"], sampleType: "UINT8" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  var vv = 10 * Math.log10(Math.max(s.VV, 1e-6));
  var vh = 10 * Math.log10(Math.max(s.VH, 1e-6));
  var b = [0, 0, 0, 0, 0];
  b[vv < -22 ? 0 : vv < -19 ? 1 : vv < -16 ? 2 : vv < -13 ? 3 : 4] = 1;
  return { db: [vv, vh], bin: b, dataMask: [s.dataMask] };
}
"""


def bygg(geom, aar):
    k = h.bygg_foresporsel(geom, "s2", aar)
    k["input"]["data"] = [{
        "type": "sentinel-1-grd",
        "dataFilter": {"acquisitionMode": "IW", "polarization": "DV"},
        "processing": {"orthorectify": True, "backCoeff": "SIGMA0_ELLIPSOID", "demInstance": "COPERNICUS_30"},
    }]
    k["aggregation"]["evalscript"] = EVALSCRIPT
    return k


def flat_ut(svar):
    ut = []
    for d in svar.get("data", []):
        o = d.get("outputs", {})
        bb = o.get("bin", {}).get("bands", {})
        if not bb:
            continue
        st0 = bb["b0"]["stats"]
        n = (st0.get("sampleCount") or 0) - (st0.get("noDataCount") or 0)
        if n <= 0:
            continue
        rad = {"dato": d["interval"]["from"][:10], "n": n}
        for b in BINS:
            m = bb[b]["stats"].get("mean")
            rad[b] = int(round(m * n)) if m is not None and m == m else 0
        for navn in ("vv", "vh"):
            m = o.get("db", {}).get("bands", {}).get(navn, {}).get("stats", {}).get("mean")
            rad[navn] = round(m, 2) if m is not None and m == m else None
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
    mappe = os.path.join(h.RAA, "s1")
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
            print("  %-22s %d: %3d pass  (%.1f PU)" % (pr["navn"], y, len(flat_ut(svar)), pu or 0), flush=True)
    print("Hentet %d nye vann-år. Forbruk: %.1f PU." % (nye, pu_sum))
    if a.prov and nye:
        print("Anslag full kjøring: ca. %.0f PU." % (pu_sum / nye * 160))
    per_lnr = {f["properties"]["vatnlnr"]: f["properties"]["navn"] for f in gj["features"]}
    kol = ["vann", "vatnlnr", "aar", "dato", "n", "vv", "vh"] + BINS
    ant = 0
    with io.open(os.path.join(h.DATA, "s1_tidsserie.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=kol, delimiter=";")
        w.writeheader()
        for fil in sorted(os.listdir(mappe)):
            lnr, y = fil[:-5].split("_")
            for rad in flat_ut(json.load(io.open(os.path.join(mappe, fil), encoding="utf-8"))):
                rad.update({"vann": per_lnr.get(int(lnr), lnr), "vatnlnr": lnr, "aar": y})
                w.writerow(rad)
                ant += 1
    print("Skrevet data/s1_tidsserie.csv (%d rader)." % ant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
