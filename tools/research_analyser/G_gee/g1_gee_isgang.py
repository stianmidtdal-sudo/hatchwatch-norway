"""
Oppgave G — den låste satellitt-isgangsmetoden gjenskapt i Google Earth Engine.

Leser (kun lesing, ingenting i tools/isgang/ endres):
  ../../isgang/valgt_metode.json      tv, tn, skyregel (låst 5. okt 2026)
  ../../isgang/grunnlag/fasit.json    Stians isgangsdatoer, 16 Nordmarka-vann 2017–2026
  ../../isgang/grunnlag/vann.geojson  polygoner (EPSG:32633) fra NVE
  ../../isgang/isgang_s2.json         CDSE-intervallene, til direkte sammenligning
  ../../isgang/03_valider.py          finn_isgang() og avstand() importeres uendret

Klassifisering per piksel — nøyaktig som 04_hent_s2.py / 05_valider_s2.py:
  vis   = (B02 + B03 + B04) / 3            refleksjon 0–1 (GEE lagrer ×10 000)
  ndsi  = (B03 - B11) / (B03 + B11)        0 hvis B03 + B11 <= 0
  mørk       vis <  tv                     → åpent vann
  lys is     vis >= tv og ndsi >= tn       → is / snø på is
  lys annet  vis >= tv og ndsi <  tn       → sky
  scl_sky    SCL i {8, 9, 10}              (sky middels, sky høy, cirrus)
  n          piksler med data (dataMask)
Klart pass (regel «gammel» = skymasken brukes): lys_annet < 0,5 n, mørk + lys is >= 8,
scl_sky < 0,5 n. Isandel = lys is / (mørk + lys is). Isgang = første klare pass
med isandel < 0,20 bekreftet av neste klare pass, etter at det er sett is samme
vår (03_valider.finn_isgang). Intervall [siste is, første åpent].

Daglig mosaikk som i CDSE (mosaickingOrder leastCC, P1D): bilder samme dag
legges oppå hverandre med minst skyete øverst. Regnes i EPSG:32633 på 20 m.

Kjør (fra denne mappa):
  python g1_gee_isgang.py --torr                  ingen innlogging: bygger alt, sjekker filer
  python g1_gee_isgang.py --prov                  ett vann, ett år
  python g1_gee_isgang.py                         16 vann × 2017–2026 → tidsserie_gee.csv, rapport_gee.md
  python g1_gee_isgang.py --evaluer               bare regn på nytt fra lagret csv
  python g1_gee_isgang.py --modis --aar 2003:2012 MODIS-backfill (MOD09GA, bare vann >= 100 ha)
  --project <cloud-prosjekt-id>  eller miljøvariabel EE_PROJECT eller fila ee_prosjekt.txt her

Innlogging gjøres av Stian én gang: `earthengine authenticate` (nettleser).
Skriptet logger aldri inn på egen hånd.
"""
import argparse
import csv
import importlib.util
import io
import json
import os
import statistics
import sys
import time
from datetime import date, timedelta

HER = os.path.dirname(os.path.abspath(__file__))
ISGANG = os.path.abspath(os.path.join(HER, "..", "..", "isgang"))
GRUNNLAG = os.path.join(ISGANG, "grunnlag")
CSV_S2 = os.path.join(HER, "tidsserie_gee.csv")
CSV_MODIS = os.path.join(HER, "tidsserie_modis.csv")
LOGG = os.path.join(HER, "kjorelogg.json")

TERSKEL = 0.20                 # isandel under dette = åpent (03_valider.TERSKLER[0])
MORK_ANDEL = 0.80              # bare for skyregel «ny» (07_andre_steder.MORK_ANDEL)
VINDU = ("03-01", "08-01")     # 1. mars – 31. juli (oppgaveteksten); CDSE-Nordmarka brukte 03-01–07-01
TEST = {2018, 2020, 2022, 2024, 2026}
TRENING = {2017, 2019, 2021, 2023, 2025}
S2_START = date(2017, 3, 28)   # første dato i COPERNICUS/S2_SR_HARMONIZED
MODIS_MIN_HA = 100.0           # 500 m-piksler: under 1 km² gir det ingen mening
MODIS_MIN_PX = 4               # 03_valider krever 8 piksler; 500 m-piksler → 4 (flagget i rapporten)

_spec = importlib.util.spec_from_file_location("v3", os.path.join(ISGANG, "03_valider.py"))
v3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v3)


# ----------------------------------------------------------------- grunnlag
def les_valg():
    sti = os.path.join(ISGANG, "valgt_metode.json")
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))
    return {"tv": 0.05, "tn": 0.4, "regel": "gammel", "grunnlag": "standard (valgt_metode.json manglet)"}


def les_fasit():
    return json.load(io.open(os.path.join(GRUNNLAG, "fasit.json"), encoding="utf-8"))


def les_vann():
    return json.load(io.open(os.path.join(GRUNNLAG, "vann.geojson"), encoding="utf-8"))["features"]


def les_cdse():
    sti = os.path.join(ISGANG, "isgang_s2.json")
    if not os.path.exists(sti):
        return {}
    return json.load(io.open(sti, encoding="utf-8")).get("isgang", {})


def les_cdse_pass():
    """Antall pass og klare pass per vann-år i CDSE-serien (for sammenligning)."""
    sti = os.path.join(ISGANG, "data", "s2_tidsserie.csv")
    ut = {}
    if not os.path.exists(sti):
        return ut
    for r in csv.DictReader(io.open(sti, encoding="utf-8-sig"), delimiter=";"):
        ut.setdefault((r["vann"], int(r["aar"])), []).append(r["dato"])
    return ut


def prosjekt(arg):
    if arg:
        return arg
    if os.environ.get("EE_PROJECT"):
        return os.environ["EE_PROJECT"]
    sti = os.path.join(HER, "ee_prosjekt.txt")
    if os.path.exists(sti):
        return io.open(sti, encoding="utf-8").read().strip() or None
    return None


def ee_init(proj):
    import ee
    try:
        if proj:
            ee.Initialize(project=proj)
        else:
            ee.Initialize()
    except Exception as e:                      # noqa: BLE001
        raise SystemExit(
            "Earth Engine er ikke klar: %s\n"
            "Stian må (1) registrere et Cloud-prosjekt for ikke-kommersiell bruk, "
            "(2) kjøre `earthengine authenticate`, (3) oppgi prosjekt-id med --project, "
            "EE_PROJECT eller fila ee_prosjekt.txt. Se RAPPORT_G.md." % str(e)[:300])
    return ee


# ----------------------------------------------------------------- Sentinel-2 i GEE
def ee_geom(ee, geom):
    """GeoJSON-polygon i EPSG:32633 → ee.Geometry (samme projeksjon, ikke geodetisk)."""
    return ee.Geometry(geom, "EPSG:32633", False)


def s2_klassebilde(ee, img, tv, tn):
    """Ett S2-bilde → 0/1-bånd som i evalscriptet i 04_hent_s2.py."""
    b = img.select(["B2", "B3", "B4", "B11"]).multiply(0.0001)       # harmonisert refleksjon 0–1
    scl = img.select("SCL")
    vis = b.select("B2").add(b.select("B3")).add(b.select("B4")).divide(3)
    sum_ = b.select("B3").add(b.select("B11"))
    ndsi = b.select("B3").subtract(b.select("B11")).divide(sum_).where(sum_.lte(0), 0)
    mork = vis.lt(tv)
    lys = vis.gte(tv)
    lys_is = lys.And(ndsi.gte(tn))
    lys_annet = lys.And(ndsi.lt(tn))
    sky = scl.eq(8).Or(scl.eq(9)).Or(scl.eq(10))
    skygge = scl.eq(3)
    gyldig = b.select("B2").mask().And(b.select("B11").mask()).And(scl.mask())
    ut = ee.Image.cat([
        ee.Image.constant(1).rename("n"), mork.rename("mork"), lys_is.rename("lys_is"),
        lys_annet.rename("lys_annet"), sky.rename("scl_sky"), skygge.rename("scl_skygge"),
        vis.rename("vis")]).updateMask(gyldig)
    return ut


def s2_dagsmosaikk(ee, geom, aar, vindu):
    """ImageCollection med ett bilde per dag (minst skyete øverst), som CDSE leastCC/P1D."""
    coll = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geom)
            .filterDate("%d-%s" % (aar, vindu[0]), "%d-%s" % (aar, vindu[1]))
            .map(lambda im: im.set("dato", ee.Date(im.get("system:time_start")).format("YYYY-MM-dd"))))
    datoer = coll.aggregate_array("dato").distinct().sort()

    def per_dag(d):
        d = ee.String(d)
        dag = coll.filter(ee.Filter.eq("dato", d)).sort("CLOUDY_PIXEL_PERCENTAGE", False)
        forst = ee.Image(dag.sort("CLOUDY_PIXEL_PERCENTAGE", True).first())
        return (dag.mosaic()
                .set("dato", d, "n_img", dag.size(),
                     "baseline", forst.get("PROCESSING_BASELINE"),
                     "tile", forst.get("MGRS_TILE")))
    return ee.ImageCollection.fromImages(datoer.map(per_dag)), datoer


def _maanedsbiter(vindu):
    """Deler vinduet («MM-DD», «MM-DD») i måneds-biter for å holde hvert getInfo-kall under
    GEEs minnegrense (hele sesongen i ett kall ga «User memory limit exceeded» på store vann
    og på 2024–2026 med dobbelt så mange pass). Resultatet er identisk — bare flere kall."""
    m0, m1 = int(vindu[0][:2]), int(vindu[1][:2])
    kanter = ["%02d-01" % m for m in range(m0, m1 + 1)]
    if vindu[0] != kanter[0]:
        kanter[0] = vindu[0]
    if vindu[1] != kanter[-1]:
        kanter[-1] = vindu[1]
    return list(zip(kanter[:-1], kanter[1:]))


def s2_tidsserie(ee, geom, aar, tv, tn, vindu=VINDU, skala=20):
    """Server-side: per dag, pikseltall innenfor polygonet. Ett getInfo per måned per vann-år."""
    rader = []
    for bit in _maanedsbiter(vindu):
        rader += _s2_tidsserie_bit(ee, geom, aar, tv, tn, bit, skala)
    return rader


def _s2_tidsserie_bit(ee, geom, aar, tv, tn, vindu, skala):
    coll, _ = s2_dagsmosaikk(ee, geom, aar, vindu)

    def reduser(im):
        kl = s2_klassebilde(ee, im, tv, tn)
        teller = kl.select(["n", "mork", "lys_is", "lys_annet", "scl_sky", "scl_skygge"]).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=geom, scale=skala, crs="EPSG:32633", maxPixels=1e9)
        snitt = kl.select("vis").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geom, scale=skala, crs="EPSG:32633", maxPixels=1e9)
        meta = ee.Dictionary({"dato": im.get("dato"), "n_img": im.get("n_img"),
                              "baseline": im.get("baseline"), "tile": im.get("tile")})
        return ee.Feature(None, teller.combine(snitt).combine(meta))

    fc = ee.FeatureCollection(coll.map(reduser))
    svar = fc.getInfo()
    rader = []
    for f in svar.get("features", []):
        p = f["properties"]
        n = int(round(p.get("n") or 0))
        if n <= 0:
            continue
        rader.append({"dato": p["dato"], "n": n,
                      "mork": int(round(p.get("mork") or 0)), "lys_is": int(round(p.get("lys_is") or 0)),
                      "lys_annet": int(round(p.get("lys_annet") or 0)), "scl_sky": int(round(p.get("scl_sky") or 0)),
                      "scl_skygge": int(round(p.get("scl_skygge") or 0)),
                      "vis": round(p["vis"], 4) if p.get("vis") is not None else None,
                      "n_img": p.get("n_img"), "baseline": p.get("baseline"), "tile": p.get("tile")})
    return rader


# ----------------------------------------------------------------- MODIS-backfill (2000–2016)
def modis_tidsserie(ee, geom, aar, tv, tn, vindu=VINDU, kilde="MOD09GA"):
    """Samme klassifisering på Terra MODIS (500 m). Bare vann >= MODIS_MIN_HA.

    MOD09GA: vis = (b03 blå + b04 grønn + b01 rød)/3, ndsi = (b04 − b06)/(b04 + b06),
             sky = state_1km bit 0–1 i {1, 2} (cloudy/mixed) eller bit 10 (intern skyflagg).
             Sky-kolonnen tar plassen til scl_sky i klar-pass-regelen.
    MOD10A1: ferdig snødekke, men innsjøer er klasse 237 «inland water» og får INGEN
             snø/is-verdi. Tas med bare for å dokumentere det: kolonnen «inland» teller
             slike piksler. Ventes ubrukelig for isgang.
    Tersklene tv/tn er satt for Sentinel-2 og er IKKE kalibrert for MODIS.
    """
    if kilde == "MOD09GA":
        coll = (ee.ImageCollection("MODIS/061/MOD09GA")
                .filterDate("%d-%s" % (aar, vindu[0]), "%d-%s" % (aar, vindu[1])))

        def kl(im):
            b = im.select(["sur_refl_b01", "sur_refl_b03", "sur_refl_b04", "sur_refl_b06"]).multiply(0.0001)
            vis = b.select("sur_refl_b01").add(b.select("sur_refl_b03")).add(b.select("sur_refl_b04")).divide(3)
            sum_ = b.select("sur_refl_b04").add(b.select("sur_refl_b06"))
            ndsi = b.select("sur_refl_b04").subtract(b.select("sur_refl_b06")).divide(sum_).where(sum_.lte(0), 0)
            st = im.select("state_1km")
            skytilstand = st.bitwiseAnd(3)
            sky = skytilstand.eq(1).Or(skytilstand.eq(2)).Or(st.rightShift(10).bitwiseAnd(1).eq(1))
            lys = vis.gte(tv)
            bilde = ee.Image.cat([
                ee.Image.constant(1).rename("n"), vis.lt(tv).rename("mork"),
                lys.And(ndsi.gte(tn)).rename("lys_is"), lys.And(ndsi.lt(tn)).rename("lys_annet"),
                sky.rename("scl_sky"), ee.Image.constant(0).rename("inland"), vis.rename("vis")]
            ).updateMask(b.select("sur_refl_b01").mask().And(b.select("sur_refl_b06").mask()))
            return bilde.set("dato", ee.Date(im.get("system:time_start")).format("YYYY-MM-dd"))
    elif kilde == "MOD10A1":
        coll = (ee.ImageCollection("MODIS/061/MOD10A1")
                .filterDate("%d-%s" % (aar, vindu[0]), "%d-%s" % (aar, vindu[1])))

        def kl(im):
            sn = im.select("NDSI_Snow_Cover")          # 0–100, maskert der klassekoden gjelder
            klasse = im.select("NDSI_Snow_Cover_Class")  # 237 inland water, 250 sky, …
            is_ = sn.gte(40).unmask(0)
            vann = sn.lt(40).unmask(0)
            sky = klasse.eq(250).unmask(0)
            inland = klasse.eq(237).unmask(0)
            bilde = ee.Image.cat([
                ee.Image.constant(1).rename("n"), vann.rename("mork"), is_.rename("lys_is"),
                sky.rename("lys_annet"), sky.rename("scl_sky"), inland.rename("inland"),
                sn.unmask(-1).rename("vis")])
            return bilde.set("dato", ee.Date(im.get("system:time_start")).format("YYYY-MM-dd"))
    else:
        raise ValueError(kilde)

    def reduser(im):
        teller = im.select(["n", "mork", "lys_is", "lys_annet", "scl_sky", "inland"]).reduceRegion(
            reducer=ee.Reducer.sum(), geometry=geom, scale=500, crs="EPSG:32633", maxPixels=1e9)
        snitt = im.select("vis").reduceRegion(
            reducer=ee.Reducer.mean(), geometry=geom, scale=500, crs="EPSG:32633", maxPixels=1e9)
        return ee.Feature(None, teller.combine(snitt).combine(ee.Dictionary({"dato": im.get("dato")})))

    svar = ee.FeatureCollection(coll.map(kl).map(reduser)).getInfo()
    rader = []
    for f in svar.get("features", []):
        p = f["properties"]
        n = int(round(p.get("n") or 0))
        if n <= 0:
            continue
        rader.append({"dato": p["dato"], "n": n,
                      "mork": int(round(p.get("mork") or 0)), "lys_is": int(round(p.get("lys_is") or 0)),
                      "lys_annet": int(round(p.get("lys_annet") or 0)), "scl_sky": int(round(p.get("scl_sky") or 0)),
                      "scl_skygge": int(round(p.get("inland") or 0)),
                      "vis": round(p["vis"], 4) if p.get("vis") is not None else None,
                      "n_img": 1, "baseline": kilde, "tile": ""})
    return rader


# ----------------------------------------------------------------- den låste regelen, lokalt
def klare(obs, tv_ubrukt, tn_ubrukt, regel, min_px=None):
    """Som 07_andre_steder.klare(), men pikseltallene er allerede klassifisert server-side."""
    min_px = v3.MIN_PX if min_px is None else min_px
    ut = []
    for r in sorted(obs, key=lambda r: r["dato"]):
        n, mork, lys_is, lys_annet = int(r["n"]), int(r["mork"]), int(r["lys_is"]), int(r["lys_annet"])
        if mork + lys_is < min_px:
            continue
        mork_pass = regel == "ny" and mork >= MORK_ANDEL * n
        if not mork_pass:
            if lys_annet >= 0.5 * n or int(r["scl_sky"]) >= 0.5 * n:
                continue
        ut.append((r["dato"], lys_is / float(mork + lys_is)))
    return ut


def evaluer(serier, fasit, aarsett, valg, min_px=None):
    rader, uten, totalt = [], {}, 0
    for vann in fasit:
        for aar_s, fdato in fasit[vann].items():
            aar = int(aar_s)
            if aarsett is not None and aar not in aarsett:
                continue
            totalt += 1
            obs = serier.get((vann, aar))
            res = v3.finn_isgang(klare(obs, valg["tv"], valg["tn"], valg["regel"], min_px), TERSKEL) if obs else {"status": "ingen data"}
            if res["status"] != "ok":
                uten[res["status"]] = uten.get(res["status"], 0) + 1
                continue
            lo, hi, f = v3.d(res["lo"]), v3.d(res["hi"]), v3.d(fdato)
            rader.append({"vann": vann, "aar": aar, "fasit": fdato, "lo": res["lo"], "hi": res["hi"],
                          "avst": v3.avstand(fdato, res["lo"], res["hi"]), "bredde": (hi - lo).days,
                          "midt": ((lo - f).days + (hi - f).days) / 2.0})
    midt = [abs(r["midt"]) for r in rader]
    return {"rader": rader, "uten": uten, "totalt": totalt,
            "innen3": sum(1 for r in rader if abs(r["avst"]) <= v3.KRAV_DAGER),
            "skjev": statistics.median(r["avst"] for r in rader) if rader else None,
            "bredde": statistics.median(r["bredde"] for r in rader) if rader else None,
            "midt_snitt": statistics.mean(midt) if midt else None,
            "innen7": sum(1 for m in midt if m <= 7)}


def dom(e):
    if not e["rader"] or len(e["rader"]) < 0.5 * e["totalt"]:
        return "ikke bestått (for få vann-år ga intervall)"
    if e["bredde"] > v3.KRAV_BREDDE:
        return "uavklart (for brede intervaller)"
    if e["innen3"] / float(len(e["rader"])) >= v3.KRAV_ANDEL and abs(e["skjev"]) <= v3.KRAV_SKJEVHET:
        return "bestått"
    return "ikke bestått"


# ----------------------------------------------------------------- csv
KOL = ["vann", "vatnlnr", "aar", "dato", "n", "mork", "lys_is", "lys_annet", "scl_sky", "scl_skygge", "vis", "n_img", "baseline", "tile"]


def les_csv(sti):
    serier = {}
    if not os.path.exists(sti):
        return serier
    for r in csv.DictReader(io.open(sti, encoding="utf-8-sig"), delimiter=";"):
        serier.setdefault((r["vann"], int(r["aar"])), []).append(r)
    return serier


def skriv_csv(sti, serier):
    with io.open(sti, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=KOL, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for (vann, aar) in sorted(serier):
            for r in sorted(serier[(vann, aar)], key=lambda r: r["dato"]):
                w.writerow(r)


# ----------------------------------------------------------------- rapport
def rapport(serier, fasit, valg, logg, cdse, cdse_pass, vann_meta, sti_ut, min_px=None, tittel="Sentinel-2 i GEE"):
    L = ["# Oppgave G: %s mot fasit (Nordmarka, 16 vann)\n" % tittel,
         "Metode: mørk under %.2f, ndsi-skille %.1f, skyregel «%s» (fra `valgt_metode.json`, uendret). "
         "Vindu %s–%s. Isandel under %.2f = åpent, bekreftet av neste klare pass.\n"
         % (valg["tv"], valg["tn"], valg["regel"], VINDU[0], VINDU[1], TERSKEL)]
    if logg:
        L.append("Kjøring: %d kall til GEE, %.1f min, %.1f s per vann-år i snitt (%s).\n"
                 % (logg.get("kall", 0), logg.get("sek", 0) / 60.0,
                    logg.get("sek", 0) / max(1, logg.get("kall", 1)), logg.get("naar", "")))
    L += ["## Samme mål som KONKLUSJON_samlet.md\n",
          "| Utvalg | Vann-år | Fikk intervall | Fasit innen 3 d av intervall | Skjevhet | Median bredde | Midt: snitt avvik | Midt innen 7 d | Formelt |",
          "|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for navn, sett in (("Testår (2018/20/22/24/26)", TEST), ("Treningsår", TRENING), ("Alle ti år", None)):
        e = evaluer(serier, fasit, sett, valg, min_px)
        res[navn] = e
        n = len(e["rader"])
        if n:
            L.append("| %s | %d | %d | %d (%.0f %%) | %+.1f d | %.0f d | %.1f d | %d (%.0f %%) | %s |" % (
                navn, e["totalt"], n, e["innen3"], 100.0 * e["innen3"] / n, e["skjev"], e["bredde"],
                e["midt_snitt"], e["innen7"], 100.0 * e["innen7"] / n, dom(e)))
        else:
            L.append("| %s | %d | 0 | – | – | – | – | – | – |" % (navn, e["totalt"]))
    te = res["Testår (2018/20/22/24/26)"]
    L.append("\nTestår uten intervall: " + (", ".join("%s: %d" % kv for kv in sorted(te["uten"].items())) or "ingen") + ".")
    L.append("CDSE-tallene å slå (KONKLUSJON_samlet, testår): midt snitt 4,0 d, 82 % innen 7 d, median bredde 13 d, 92 % innen 3 d av intervallet.\n")

    alle = evaluer(serier, fasit, None, valg, min_px)
    if cdse:
        L += ["## Direkte mot CDSE-intervallene (samme vann-år, `isgang_s2.json`)\n"]
        like, lo_d, hi_d, bare_gee, bare_cdse = 0, [], [], 0, 0
        gee_ok = {(r["vann"], r["aar"]): r for r in alle["rader"]}
        for vann in fasit:
            for aar_s in fasit[vann]:
                c = cdse.get(vann, {}).get(aar_s)
                g = gee_ok.get((vann, int(aar_s)))
                if c and g:
                    if c["lo"] == g["lo"] and c["hi"] == g["hi"]:
                        like += 1
                    lo_d.append((v3.d(g["lo"]) - v3.d(c["lo"])).days)
                    hi_d.append((v3.d(g["hi"]) - v3.d(c["hi"])).days)
                elif g:
                    bare_gee += 1
                elif c:
                    bare_cdse += 1
        n = len(lo_d)
        if n:
            L += ["| | Verdi |", "|---|---|",
                  "| Vann-år med intervall i begge | %d |" % n,
                  "| Identisk intervall (lo og hi) | %d (%.0f %%) |" % (like, 100.0 * like / n),
                  "| «Siste is» GEE − CDSE: median / snitt abs | %+.1f d / %.1f d |" % (statistics.median(lo_d), statistics.mean(abs(x) for x in lo_d)),
                  "| «Første åpent» GEE − CDSE: median / snitt abs | %+.1f d / %.1f d |" % (statistics.median(hi_d), statistics.mean(abs(x) for x in hi_d)),
                  "| Intervall bare i GEE / bare i CDSE | %d / %d |" % (bare_gee, bare_cdse), ""]
        else:
            L.append("Ingen felles vann-år ennå.\n")
    if cdse_pass:
        L += ["## Antall pass i vinduet, GEE mot CDSE\n", "| Vann | År | Pass GEE | Pass CDSE | Klare GEE | Første dato GEE | Første dato CDSE |", "|---|---|---|---|---|---|---|"]
        for (vann, aar) in sorted(serier):
            obs = serier[(vann, aar)]
            c = [d for d in cdse_pass.get((vann, aar), []) if "%d-%s" % (aar, VINDU[0]) <= d < "%d-%s" % (aar, VINDU[1])]
            L.append("| %s | %d | %d | %d | %d | %s | %s |" % (
                vann, aar, len(obs), len(c), len(klare(obs, valg["tv"], valg["tn"], valg["regel"], min_px)),
                min(r["dato"] for r in obs) if obs else "–", min(c) if c else "–"))
        L.append("")
    baselines = {}
    for obs in serier.values():
        for r in obs:
            baselines[str(r.get("baseline"))] = baselines.get(str(r.get("baseline")), 0) + 1
    if baselines:
        L.append("Prosesseringsbaseline i GEE-dataene (antall vann-dager): " + ", ".join("%s: %d" % kv for kv in sorted(baselines.items())) + ".\n")

    L += ["## Per vann, testårene\n", "| Vann | Areal | År med intervall | Innen 3 d | Skjevhet | Median bredde | Midt snitt |", "|---|---|---|---|---|---|---|"]
    for vann in fasit:
        rr = [r for r in te["rader"] if r["vann"] == vann]
        n_aar = sum(1 for a in fasit[vann] if int(a) in TEST)
        ha = vann_meta.get(vann, {}).get("areal_ha", 0)
        if rr:
            L.append("| %s | %.0f ha | %d av %d | %d | %+.1f d | %.0f d | %.1f d |" % (
                vann, ha, len(rr), n_aar, sum(1 for r in rr if abs(r["avst"]) <= 3),
                statistics.median(r["avst"] for r in rr), statistics.median(r["bredde"] for r in rr),
                statistics.mean(abs(r["midt"]) for r in rr)))
        else:
            L.append("| %s | %.0f ha | 0 av %d | – | – | – | – |" % (vann, ha, n_aar))
    L += ["\n## Alle vann-år\n", "| Vann | År | Sett | Fasit | Siste is | Første åpent | Avstand | Bredde | CDSE siste is | CDSE første åpent |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(alle["rader"], key=lambda r: (r["vann"], r["aar"])):
        c = cdse.get(r["vann"], {}).get(str(r["aar"]), {})
        L.append("| %s | %d | %s | %s | %s | %s | %+d d | %d d | %s | %s |" % (
            r["vann"], r["aar"], "test" if r["aar"] in TEST else "trening", r["fasit"], r["lo"], r["hi"],
            r["avst"], r["bredde"], c.get("lo", "–"), c.get("hi", "–")))
    io.open(sti_ut, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return L


# ----------------------------------------------------------------- hovedløp
def hent_alle(ee, vann, aar_liste, valg, serier, sti_csv, modis=None, prov=False):
    kall, t0, nye = 0, time.time(), 0
    for f in vann:
        pr = f["properties"]
        navn = pr["navn"]
        if modis and pr.get("areal_ha", 0) < MODIS_MIN_HA:
            continue
        for aar in aar_liste:
            if (navn, aar) in serier:
                continue
            t1 = time.time()
            try:
                if modis:
                    rader = modis_tidsserie(ee, ee_geom(ee, f["geometry"]), aar, valg["tv"], valg["tn"], kilde=modis)
                else:
                    rader = s2_tidsserie(ee, ee_geom(ee, f["geometry"]), aar, valg["tv"], valg["tn"])
            except Exception as e:                      # noqa: BLE001
                print("  FEIL %s %d: %s" % (navn, aar, str(e)[:200]), flush=True)
                continue
            kall += 1
            nye += 1
            for r in rader:
                r.update({"vann": navn, "vatnlnr": pr["vatnlnr"], "aar": aar})
            serier[(navn, aar)] = rader
            kl = klare(rader, valg["tv"], valg["tn"], valg["regel"], MODIS_MIN_PX if modis else None)
            res = v3.finn_isgang(kl, TERSKEL)
            print("  %-22s %d: %3d pass, %2d klare, %4.1f s  → %s %s" % (
                navn, aar, len(rader), len(kl), time.time() - t1, res["status"],
                "[%s, %s]" % (res["lo"], res["hi"]) if res["status"] == "ok" else ""), flush=True)
            if nye % 10 == 0:
                skriv_csv(sti_csv, serier)
            if prov:
                break
        if prov:
            break
    skriv_csv(sti_csv, serier)
    sek = time.time() - t0
    logg = {"kall": kall, "sek": round(sek, 1), "nye_vannaar": nye, "naar": date.today().isoformat(),
            "kilde": modis or "COPERNICUS/S2_SR_HARMONIZED"}
    gammel = json.load(io.open(LOGG, encoding="utf-8")) if os.path.exists(LOGG) else {}
    gammel.setdefault("kjoringer", []).append(logg)
    json.dump(gammel, io.open(LOGG, "w", encoding="utf-8"), indent=1)
    print("Ferdig: %d kall, %.1f min." % (kall, sek / 60.0))
    return logg


def torr(valg, fasit, vann):
    print("Tørrkjøring (ingen innlogging mot Earth Engine).")
    print("  Metode: tv=%.2f tn=%.1f regel=%s (%s)" % (valg["tv"], valg["tn"], valg["regel"], valg.get("grunnlag", "")))
    print("  Fasit: %d vann, %d vann-år." % (len(fasit), sum(len(v) for v in fasit.values())))
    print("  Polygoner: %d, EPSG:32633 antatt (første koordinat %s)." % (len(vann), vann[0]["geometry"]["coordinates"][0][0]))
    store = [f["properties"]["navn"] for f in vann if f["properties"]["areal_ha"] >= MODIS_MIN_HA]
    print("  Vann >= %.0f ha (MODIS-kandidater): %s" % (MODIS_MIN_HA, ", ".join(store) or "ingen"))
    print("  Vindu: %s–%s. S2_SR_HARMONIZED starter %s; CDSE-serien har pass fra tidlig mars 2017."
          % (VINDU[0], VINDU[1], S2_START.isoformat()))
    print("  Antall kall ved full kjøring: %d (ett per vann-år)." % (len(vann) * 10))
    cred = os.path.join(os.path.expanduser("~"), ".config", "earthengine", "credentials")
    print("  Legitimasjon (%s): %s" % (cred, "finnes" if os.path.exists(cred) else "MANGLER — kjør `earthengine authenticate`"))
    try:
        import ee  # noqa: F401
        print("  earthengine-api: installert.")
    except ImportError:
        print("  earthengine-api: MANGLER (python -m pip install earthengine-api).")
    # Selvtest av den lokale regelen mot konstruerte pikseltall.
    obs = [{"dato": "2020-04-01", "n": 100, "mork": 2, "lys_is": 95, "lys_annet": 3, "scl_sky": 0},
           {"dato": "2020-04-06", "n": 100, "mork": 10, "lys_is": 20, "lys_annet": 70, "scl_sky": 80},   # sky → forkastes
           {"dato": "2020-04-11", "n": 100, "mork": 40, "lys_is": 55, "lys_annet": 5, "scl_sky": 10},
           {"dato": "2020-04-16", "n": 100, "mork": 90, "lys_is": 8, "lys_annet": 2, "scl_sky": 0},
           {"dato": "2020-04-21", "n": 100, "mork": 97, "lys_is": 1, "lys_annet": 2, "scl_sky": 0}]
    r = v3.finn_isgang(klare(obs, valg["tv"], valg["tn"], valg["regel"]), TERSKEL)
    ok = (r["status"], r["lo"], r["hi"]) == ("ok", "2020-04-11", "2020-04-16")
    print("  Selvtest av regelen: %s (%s [%s, %s])" % ("OK" if ok else "FEIL", r["status"], r["lo"], r["hi"]))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--torr", action="store_true")
    ap.add_argument("--prov", action="store_true")
    ap.add_argument("--evaluer", action="store_true")
    ap.add_argument("--modis", nargs="?", const="MOD09GA", choices=["MOD09GA", "MOD10A1"])
    ap.add_argument("--aar", default="2017:2026", help="f.eks. 2003:2012")
    ap.add_argument("--vann", help="bare dette vannet (navn som i fasit.json)")
    ap.add_argument("--project")
    a = ap.parse_args()

    valg, fasit, vann = les_valg(), les_fasit(), les_vann()
    if a.vann:
        vann = [f for f in vann if f["properties"]["navn"] == a.vann]
        if not vann:
            raise SystemExit("Fant ikke vannet «%s»." % a.vann)
    a0, a1 = (int(x) for x in a.aar.split(":"))
    aar_liste = list(range(a0, a1 + 1))
    vann_meta = {f["properties"]["navn"]: f["properties"] for f in les_vann()}

    if a.torr:
        return torr(valg, fasit, vann)

    sti_csv = CSV_MODIS if a.modis else CSV_S2
    serier = les_csv(sti_csv)
    logg = None
    if not a.evaluer:
        ee = ee_init(prosjekt(a.project))
        print("Earth Engine klar. Henter %s." % (a.modis or "Sentinel-2 L2A (S2_SR_HARMONIZED)"))
        logg = hent_alle(ee, vann, aar_liste, valg, serier, sti_csv, modis=a.modis, prov=a.prov)
    if a.modis:
        # Backfill-årene har ingen fasit i fasit.json; skriv bare intervallene.
        ut, L = {}, ["# MODIS-backfill (%s), vann >= %.0f ha\n" % (a.modis, MODIS_MIN_HA),
                     "Tersklene er Sentinel-2-tersklene, ukalibrert for MODIS. MIN_PX senket til %d." % MODIS_MIN_PX,
                     "", "| Vann | År | Pass | Klare | Status | Siste is | Første åpent | Fasit |", "|---|---|---|---|---|---|---|---|"]
        for (v, y) in sorted(serier):
            obs = serier[(v, y)]
            kl = klare(obs, valg["tv"], valg["tn"], valg["regel"], MODIS_MIN_PX)
            r = v3.finn_isgang(kl, TERSKEL)
            ut.setdefault(v, {})[str(y)] = r
            L.append("| %s | %d | %d | %d | %s | %s | %s | %s |" % (v, y, len(obs), len(kl), r["status"], r["lo"], r["hi"], fasit.get(v, {}).get(str(y), "–")))
        io.open(os.path.join(HER, "rapport_modis.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
        json.dump(ut, io.open(os.path.join(HER, "isgang_modis.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n".join(L))
        return 0
    L = rapport(serier, fasit, valg, logg, les_cdse(), les_cdse_pass(), vann_meta, os.path.join(HER, "rapport_gee.md"))
    print("\n".join(L[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
