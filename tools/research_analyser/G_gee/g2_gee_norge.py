"""
Oppgave G2 — den låste isgangsmetoden i Google Earth Engine, skrevet om til skala.

Samme regning som g1_gee_isgang.py (som ga identiske resultater som Copernicus på
Nordmarka), men ALLE vannpolygoner i en rute regnes i én operasjon per dag:

  g1:  per vann, per måned:  dagsmosaikk over vannet → reduceRegion (ett polygon)
  g2:  per rute, per måned:  dagsmosaikk over ruta   → reduceRegions (alle polygoner)

Hvorfor resultatet ikke endres:
  * Klassifiseringen per piksel er importert uendret fra g1 (s2_klassebilde).
  * Dagsregelen er den samme, server-side: bilder samme dag mosaikkeres med minst
    skyete (CLOUDY_PIXEL_PERCENTAGE) øverst. Mosaikk er per piksel, og et bilde som
    ikke dekker vannet er maskert der — så pikselverdiene over et vann er de samme
    enten samlingen er filtrert på vannet (g1) eller på ruta (g2).
  * reduceRegions bruker samme pikselvalg som reduceRegion (scale 20, EPSG:32633).
  * klare() og finn_isgang() er importert uendret (g1 → 03_valider.py).
  Det eneste som er nytt: bilder uten båndene B2/B3/B4/B11/SCL filtreres bort, og
  båndene velges FØR mosaikk. Det retter «incompatible bands» (Fjellsjøen 2018 i g1).
  Metadata per pass («baseline», «n_img») gjelder ruta, ikke vannet.

Kjør (fra denne mappa):
  python g2_gee_norge.py --torr                       sjekk filer, ingen innlogging
  python g2_gee_norge.py --port                       kvalitetsport: 16 Nordmarka-vann mot g1 (alltid 20 m)
  python g2_gee_norge.py --port --vindu 03-01:08-01   (g1 brukte dette vinduet; standard er 02-01:07-16)
  python g2_gee_norge.py --referansenett [--fortsett] vannene i tools/isgang/referansenett.json
  python g2_gee_norge.py --norge --fortsett --parallell 4 --budsjett-timer 85
                                                      hele Norge fylke for fylke etter norge_plan.json
  python g2_gee_norge.py --fylke 34 [--fortsett]      alle vann >= 10 ha i Innlandet (NVE kommnr 34xx)
  python g2_gee_norge.py --omrade 10.4,59.98,10.9,60.25   bbox lon/lat (som sky/omraader.json)
  python g2_gee_norge.py --vatnlnr 5170,5152          enkeltvann
  python g2_gee_norge.py --tell                       vann per fylke og pikselklasse + kost-estimat (ingen innlogging)
  python g2_gee_norge.py --eecu                       les EECU-forbruk siste 7 døgn (Cloud Monitoring)
  python g2_gee_norge.py --samle                      bygg isgang_norge_index.csv fra fylkesfilene (ingen innlogging)
  python g2_gee_norge.py --migrer-fylker              engangs: del det gamle isgang_norge.json i fylkesfiler (11. okt 2026)
  --aar 2017:2026   --min-ha 10   --maks-ha 3000   --navn <kjøringsnavn>   --project <id>   --parallell 4
  --budsjett-timer 85   --piksel-fast 20 (overstyr pikselvalg etter areal)   --lager <mappe> (lagerplass, til testing)
  --maks-minutter 330 (tidsvakt per kjøring; 0 = ingen grense)

Pikselstørrelse etter vannareal (som Copernicus-kjøringen i tools/isgang): 20 m <= 150 ha,
40 m for 150–600 ha, 60 m over 600 ha. Vann over --maks-ha (3000) droppes i Norge-/fylkeskjøringer.
--port bruker alltid 20 m (g1 regnet på 20 m, og porten sammenligner pass for pass).

Kvotevakt: EECU-kost anslås som 30 EECU-s per vann-år på 20 m for vinduet 03-01–07-16 (målt
10. okt 2026: 39,23 % av 150 t på ca. 6 650 vann-år), skalert med (20/piksel)^2 og med vinduets
lengde. Forbruket (estimat) føres per kalendermåned i norge_plan.json («kvote»), og kjøringen
stopper rent (mellomlagret per enhet) før en enhet som ville passere --budsjett-timer.

Resultat (fra 11. okt 2026, G4): ÉN fil per fylke i norge/ — isgang_<fylkesnr>_<navn>.json og .csv
(semikolon, UTF-8 BOM; samme skjema som det gamle isgang_norge.json/.csv), slått sammen over alle
kjøringer (per vatnLnr og år). Vann uten kommnr i NVE (grensesjøer) ligger i isgang_00_uten_fylke.
Lett samlefil isgang_norge_index.csv (vatnLnr, navn, fylke, aar, status, lo, hi, midt, bredde_d,
klasse — uten passlista) oppdateres etter hvert fylke og kan bygges på nytt med --samle. Kartet og
modellen leser indexfila; fylkesfilene har passlista og metadata. Norge-kjøringen overskriver ALDRI
eksisterende vann-år (referansenettet beholdes), og henter ikke vann som alt ligger inne for alle årene.
Rådata (per pass) i data/serier_<navn>.csv så kjøringen kan gjenopptas (--fortsett) og metoden
regnes om senere.
Lett fylkesfil (G5, 11. okt 2026): norge/lett/isgang_<nr>_<navn>.csv = fylkesfila uten passlista «p».
Skrives sammen med den fulle fila og av --samle. Det er den lette fila og indexfila som ligger i
git-repoet; de fulle fylkesfilene, data/ og vann/ er for store og holdes utenfor (GitHub-jobben
bærer dem som workflow-artifact mellom kjøringene — se RAPPORT_G5.md).
Ingen hemmeligheter i filer: prosjekt-id i ee_prosjekt.txt (gitignored), innlogging
via `earthengine authenticate` (gjort av Stian). I GitHub Actions (isgang_gee.yml) brukes
servicekonto: miljøvariabelen GEE_SERVICE_ACCOUNT_KEY (hele JSON-nøkkelen) + GEE_PROJECT.
Nøkkelen leses bare fra miljøet og skrives aldri til fil eller logg.
Tidsvakt: --maks-minutter (standard 330, 0 = ingen grense) stopper rent før GitHubs 6-timersgrense;
det som er i gang fullføres, framdrift og rådata er lagret per enhet, og --fortsett tar resten.
"""
import argparse
import concurrent.futures
import csv
import datetime as dt
import io
import json
import math
import os
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request

HER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HER)
import g1_gee_isgang as g1          # noqa: E402  klassifisering, klare(), v3.finn_isgang — uendret

ISGANG = g1.ISGANG
DATA = os.path.join(HER, "data")
VANN_DIR = os.path.join(HER, "vann")
STORE_JSON = os.path.join(HER, "isgang_norge.json")        # det GAMLE samlelageret (til 11. okt 2026); bare --migrer-fylker leser det
STORE_CSV = os.path.join(HER, "isgang_norge.csv")
NORGE_DIR = os.path.join(HER, "norge")                     # fylkesfilene isgang_<nr>_<navn>.json/.csv
INDEX_CSV = os.path.join(HER, "isgang_norge_index.csv")    # lett samlefil (uten passlista) — den kartet/modellen leser
NVE_GEOJSON = os.path.join(HER, "..", "I_arter_per_vann", "raa", "nve_innsjoer_10ha.geojson")
LOGG = os.path.join(HER, "kjorelogg_g2.json")
PLAN = os.path.join(HER, "norge_plan.json")
RAPPORT_NORGE = os.path.join(HER, "rapport_norge.md")
NVE = "https://kart.nve.no/enterprise/rest/services/Innsjodatabase2/MapServer/5/query"

VINDU = ("02-01", "07-16")          # 1. feb – 15. juli (til og med), som Copernicus-kjøringen. g1 brukte 03-01–08-01;
                                    # referansenettet (10. okt 2026) 03-01–07-16. Vestlandskystvann går isfrie i februar.
AAR = list(range(2017, 2027))
MIN_HA = 10.0
MAKS_HA = 3000.0                    # vann over dette droppes i Norge-/fylkeskjøringer (som sky_hent.MAKS_HA)
SKALA = 20                          # pikselstørrelse for vann <= 150 ha; se piksel()
MAKS_HJORNER = 60000                # per rute: holder forespørselen godt under GEEs 10 MB
MAKS_VANN_RUTE = 400
RUTE_M = 60000                      # rutenett i meter (EPSG:32633) som vannene grupperes i
BAND = ["B2", "B3", "B4", "B11", "SCL"]
FYLKE = {"03": "Oslo", "11": "Rogaland", "15": "Møre og Romsdal", "18": "Nordland", "31": "Østfold",
         "32": "Akershus", "33": "Buskerud", "34": "Innlandet", "39": "Vestfold", "40": "Telemark",
         "42": "Agder", "46": "Vestland", "50": "Trøndelag", "55": "Troms", "56": "Finnmark"}
FYLKE_NR = {navn: nr for nr, navn in FYLKE.items()}
# Rekkefølgen for Norge-kjøringen (Stian, 11. okt 2026): sør/øst først, Finnmark sist.
REKKEFOLGE = ["03", "32", "31", "33", "39", "40", "34", "50", "42", "11", "46", "15", "18", "55", "56"]


def sett_lager(mappe):
    """Flytter lagerplassen (gammelt samlelager, norge/ og indexfila) — til testing mot en kopi."""
    global STORE_JSON, STORE_CSV, NORGE_DIR, INDEX_CSV
    mappe = os.path.abspath(mappe)
    STORE_JSON = os.path.join(mappe, "isgang_norge.json")
    STORE_CSV = os.path.join(mappe, "isgang_norge.csv")
    NORGE_DIR = os.path.join(mappe, "norge")
    INDEX_CSV = os.path.join(mappe, "isgang_norge_index.csv")

# Kvotevakt. Målt 10. okt 2026: 30 EECU-s per vann-år på 20 m med vinduet 03-01–07-16 (137 dager).
EECU_SEK_20M = 30.0
EECU_VINDU_DAGER = 137
BUDSJETT_TIMER = 85.0

# Tidsvakt (G5): GitHub Actions dreper en jobb etter 6 timer. Kjøringen slutter å sende nye enheter når
# fristen er passert; de som er i gang fullføres (per enhet er alt mellomlagret), og --fortsett tar resten.
MAKS_MINUTTER = 330
FRIST = [None]                      # time.time() for fristen, None = ingen grense


def tid_ute():
    return FRIST[0] is not None and time.time() >= FRIST[0]


# ----------------------------------------------------------------- innlogging
_EE_CREDS = [None]                  # servicekonto-legitimasjon når den brukes (til eecu())


def ee_init(proj):
    """Servicekonto når GEE_SERVICE_ACCOUNT_KEY finnes i miljøet (GitHub Actions), ellers g1.ee_init
    (Stians brukerinnlogging via `earthengine authenticate`). Nøkkelen leses bare fra miljøet; e-posten
    tas fra JSON-ens client_email. Verken nøkkel eller feilmeldinger med nøkkelinnhold skrives noe sted."""
    nokkel = os.environ.get("GEE_SERVICE_ACCOUNT_KEY")
    if not nokkel:
        return g1.ee_init(proj)
    import ee
    try:
        epost = json.loads(nokkel).get("client_email")
    except ValueError:
        raise SystemExit("GEE_SERVICE_ACCOUNT_KEY er satt, men er ikke gyldig JSON (verdien vises ikke).")
    if not epost:
        raise SystemExit("GEE_SERVICE_ACCOUNT_KEY mangler feltet client_email.")
    proj = proj or os.environ.get("GEE_PROJECT") or None
    try:
        creds = ee.ServiceAccountCredentials(epost, key_data=nokkel)
    except Exception:                                       # noqa: BLE001
        # Feilteksten fra biblioteket kan gjengi nøkkelen — den skrives derfor IKKE.
        raise SystemExit("Kunne ikke lage legitimasjon av GEE_SERVICE_ACCOUNT_KEY for %s (ugyldig nøkkel-JSON? "
                         "Feilteksten holdes tilbake fordi den kan inneholde nøkkelen)." % epost)
    try:
        ee.Initialize(creds, project=proj)
    except Exception as e:                                  # noqa: BLE001
        tekst = str(e)[:300]
        if "private_key" in tekst or "PRIVATE KEY" in tekst:
            tekst = "(feiltekst holdt tilbake — kan inneholde nøkkelen)"
        raise SystemExit("Earth Engine med servicekontoen %s (prosjekt %s) feilet: %s\n"
                         "HTTP 403 betyr som regel at servicekontoen ikke er registrert for Earth Engine, eller mangler "
                         "rollen Earth Engine Resource Viewer på prosjektet — se RAPPORT_G5.md." % (epost, proj, tekst))
    _EE_CREDS[0] = creds
    logg("Earth Engine klar med servicekontoen %s (prosjekt %s)." % (epost, proj))
    return ee


def piksel(ha):
    """Pikselstørrelse etter vannareal, som sky_hent.piksel (Copernicus-kjøringen)."""
    ha = ha or 0
    return 20 if ha <= 150 else (40 if ha <= 600 else 60)


def vindu_dager(bit):
    """Dager i en datobit («MM-DD», «MM-DD»), slutt eksklusiv (ikke-skuddår)."""
    d0 = dt.date(2021, int(bit[0][:2]), int(bit[0][3:]))
    d1 = dt.date(2021, int(bit[1][:2]), int(bit[1][3:]))
    return max(0, (d1 - d0).days)


def eecu_vannaar_sek(skala, vindu=VINDU):
    """Anslått EECU-sekunder per vann-år for en pikselstørrelse og et vindu."""
    return EECU_SEK_20M * (20.0 / skala) ** 2 * vindu_dager(vindu) / float(EECU_VINDU_DAGER)


def kost_estimat_sek(vann, n_aar, vindu=VINDU):
    return sum(eecu_vannaar_sek(v.get("skala") or piksel(v.get("areal_ha")), vindu) for v in vann) * n_aar

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                   # noqa: BLE001
    pass


def logg(*a):
    print(*a, flush=True)


# ----------------------------------------------------------------- NVE Innsjødatabase
def nve(p):
    with urllib.request.urlopen(NVE + "?" + urllib.parse.urlencode(p), timeout=300) as r:
        return json.load(r)


FELT = "vatnlnr,navn,hoyde,areal_km2,kommnr,kommune,objekttype,vassomr"


def nve_attributter(where, bbox=None):
    """Alle rader for et where-uttrykk (paginert, NVE gir maks 2000 per kall)."""
    ut, offset = [], 0
    while True:
        p = dict(where=where, outFields=FELT, returnGeometry="false", f="json",
                 orderByFields="vatnlnr", resultOffset=str(offset), resultRecordCount="2000")
        if bbox:
            p.update(geometry="%f,%f,%f,%f" % tuple(bbox), geometryType="esriGeometryEnvelope",
                     inSR="4326", spatialRel="esriSpatialRelIntersects")
        r = nve(p)
        feats = r.get("features", [])
        ut += [f["attributes"] for f in feats]
        if not r.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    return ut


def nve_polygoner(lnr_liste, bunt=100):
    """vatnlnr → GeoJSON-geometri i EPSG:32633 (samme uttrekk som sky_hent.polygoner)."""
    ut = {}
    for i in range(0, len(lnr_liste), bunt):
        p = dict(where="vatnlnr IN (%s)" % ",".join(str(x) for x in lnr_liste[i:i + bunt]),
                 outFields="vatnlnr", returnGeometry="true", outSR="32633", f="geojson")
        for f in nve(p)["features"]:
            ut[f["properties"]["vatnlnr"]] = f["geometry"]
    return ut


def utm33_til_wgs84(x, y):
    """EPSG:32633 → (lat, lon), stdlib. Nøyaktig nok for en posisjonskolonne (< 1 m)."""
    a, f = 6378137.0, 1 / 298.257223563
    k0, e2 = 0.9996, 2 * f - f * f
    ep2 = e2 / (1 - e2)
    lon0 = math.radians(15.0)
    x = x - 500000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                               + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = lon0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return round(math.degrees(lat), 5), round(math.degrees(lon), 5)


def tyngdepunkt(geom):
    ring = geom["coordinates"][0] if geom["type"] == "Polygon" else max(geom["coordinates"], key=lambda p: len(p[0]))[0]
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


def ringer(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    return [r for p in geom["coordinates"] for r in p]


def hjorner(geom):
    return sum(len(r) for r in ringer(geom))


def bbox_av(geom):
    xs = [p[0] for r in ringer(geom) for p in r]
    ys = [p[1] for r in ringer(geom) for p in r]
    return [min(xs), min(ys), max(xs), max(ys)]


def fylke_av(kommnr):
    return FYLKE.get((kommnr or "")[:2], (kommnr or "")[:2] or "")


# ----------------------------------------------------------------- vannlister
def vannliste_fil(navn):
    return os.path.join(VANN_DIR, "%s.json" % navn)


def bygg_vannliste(navn, attributter, polygoner=None, kilde=""):
    """Felles format: liste av {vatnlnr, navn, moh, areal_ha, kommune, fylke, lat, lon, geom}. Mellomlagres."""
    os.makedirs(VANN_DIR, exist_ok=True)
    sti = vannliste_fil(navn)
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))["vann"]
    lnr = [a["vatnlnr"] for a in attributter]
    if polygoner is None:
        logg("Henter %d polygoner fra NVE ..." % len(lnr))
        polygoner = nve_polygoner(lnr)
    ut = []
    for a in attributter:
        g = polygoner.get(a["vatnlnr"])
        if not g:
            logg("  mangler polygon i NVE: %s (%s)" % (a.get("navn"), a["vatnlnr"]))
            continue
        cx, cy = tyngdepunkt(g)
        lat, lon = utm33_til_wgs84(cx, cy)
        ut.append({"vatnlnr": a["vatnlnr"], "navn": a.get("navn") or "", "moh": a.get("hoyde"),
                   "areal_ha": round((a.get("areal_km2") or 0) * 100, 1) if a.get("areal_km2") is not None else a.get("areal_ha"),
                   "kommune": a.get("kommune") or "", "kommnr": a.get("kommnr") or "", "fylke": fylke_av(a.get("kommnr")),
                   "lat": lat, "lon": lon, "x": round(cx), "y": round(cy), "hjorner": hjorner(g), "bbox": bbox_av(g), "geom": g})
    json.dump({"navn": navn, "kilde": kilde, "hentet": dt.date.today().isoformat(), "vann": ut},
              io.open(sti, "w", encoding="utf-8"), ensure_ascii=False)
    logg("%s: %d vann med polygon (lagret i vann/%s.json)." % (navn, len(ut), navn))
    return ut


def vann_port():
    """De 16 Nordmarka-vannene med NØYAKTIG de polygonene g1 brukte (grunnlag/vann.geojson)."""
    feats = g1.les_vann()
    attr = [{"vatnlnr": f["properties"]["vatnlnr"], "navn": f["properties"]["navn"], "hoyde": f["properties"].get("moh_nve"),
             "areal_ha": f["properties"].get("areal_ha"), "kommnr": "0301", "kommune": "Oslo"} for f in feats]
    poly = {f["properties"]["vatnlnr"]: f["geometry"] for f in feats}
    return bygg_vannliste("port_nordmarka", attr, poly, "tools/isgang/grunnlag/vann.geojson")


def vann_referansenett():
    nett = json.load(io.open(os.path.join(ISGANG, "referansenett.json"), encoding="utf-8"))["vann"]
    lnr = [v["vatnlnr"] for v in nett]
    sti = vannliste_fil("referansenett")
    if os.path.exists(sti):
        return bygg_vannliste("referansenett", [])
    attr = []
    for i in range(0, len(lnr), 500):
        attr += nve_attributter("vatnlnr IN (%s)" % ",".join(str(x) for x in lnr[i:i + 500]))
    return bygg_vannliste("referansenett", attr, None, "tools/isgang/referansenett.json (%d vann) + NVE" % len(nett))


def vann_fylke(nr, min_ha):
    navn = "fylke_%s" % nr
    if os.path.exists(vannliste_fil(navn)):
        return bygg_vannliste(navn, [])
    attr = nve_attributter("kommnr LIKE '%s%%' AND areal_km2 >= %s" % (nr, min_ha / 100.0))
    logg("NVE: %d vann >= %.0f ha i fylke %s (%s)." % (len(attr), min_ha, nr, FYLKE.get(nr, "?")))
    return bygg_vannliste(navn, attr, None, "NVE Innsjødatabase, kommnr %sxx, >= %.0f ha" % (nr, min_ha))


def vann_omrade(bbox, min_ha):
    navn = "omrade_%s" % "_".join(str(b).replace(".", "p") for b in bbox)
    if os.path.exists(vannliste_fil(navn)):
        return bygg_vannliste(navn, [])
    x0, y0, x1, y1 = bbox
    attr = nve_attributter("areal_km2 >= %s" % (min_ha / 100.0), bbox)
    lnr = [a["vatnlnr"] for a in attr]
    poly = nve_polygoner(lnr)
    # som sky_hent: bare vann med midtpunkt i boksen
    behold, poly2 = [], {}
    for a in attr:
        g = poly.get(a["vatnlnr"])
        if not g:
            continue
        lat, lon = utm33_til_wgs84(*tyngdepunkt(g))
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            behold.append(a)
            poly2[a["vatnlnr"]] = g
    return bygg_vannliste(navn, behold, poly2, "NVE Innsjødatabase, bbox %s, >= %.0f ha" % (bbox, min_ha))


def vann_lnr(liste):
    navn = "lnr_" + "_".join(str(x) for x in liste[:6]) + ("_m%d" % len(liste) if len(liste) > 6 else "")
    if os.path.exists(vannliste_fil(navn)):
        return bygg_vannliste(navn, [])
    attr = nve_attributter("vatnlnr IN (%s)" % ",".join(str(x) for x in liste))
    return bygg_vannliste(navn, attr, None, "NVE etter vatnlnr")


def ruter(vann, piksel_fast=0):
    """Grupperer vannene i ruter (RUTE_M-rutenett i EPSG:32633 × pikselstørrelse), delt videre så
    ingen rute har over MAKS_VANN_RUTE vann eller MAKS_HJORNER polygonhjørner (forespørselsstørrelse).
    Hver rute har ÉN pikselstørrelse («skala»): 20/40/60 m etter vannareal, eller piksel_fast."""
    celler = {}
    for v in vann:
        s = piksel_fast or piksel(v.get("areal_ha"))
        v["skala"] = s
        celler.setdefault((int(v["x"] // RUTE_M), int(v["y"] // RUTE_M), s), []).append(v)
    ut = []
    for key in sorted(celler):
        gruppe = sorted(celler[key], key=lambda v: (v["y"], v["x"]))
        bit, hj = [], 0
        for v in gruppe:
            if bit and (len(bit) >= MAKS_VANN_RUTE or hj + v["hjorner"] > MAKS_HJORNER):
                ut.append(bit)
                bit, hj = [], 0
            bit.append(v)
            hj += v["hjorner"]
        if bit:
            ut.append(bit)
    return [{"id": "r%03d" % i, "vann": b, "skala": b[0]["skala"]} for i, b in enumerate(ut)]


# ----------------------------------------------------------------- GEE
def ee_fc(ee, vann):
    return ee.FeatureCollection([ee.Feature(ee.Geometry(v["geom"], "EPSG:32633", False), {"lnr": v["vatnlnr"]}) for v in vann])


def ee_boks(ee, vann):
    """Rutas omriss (EPSG:32633) regnet klient-side, med 100 m margin — brukes bare til filterBounds."""
    b = [min(v["bbox"][0] for v in vann) - 100, min(v["bbox"][1] for v in vann) - 100,
         max(v["bbox"][2] for v in vann) + 100, max(v["bbox"][3] for v in vann) + 100]
    return ee.Geometry.Rectangle(b, "EPSG:32633", False)


def s2_rute(ee, fc, omr, aar, bit, tv, tn, tile_scale=1, skala=SKALA):
    """Server-side: for hver dag i biten, dagsmosaikk over ruta (minst skyete øverst, som g1),
    klassifisering (g1.s2_klassebilde, uendret) og pikseltall per polygon i ÉN reduceRegions.
    skala = pikselstørrelse (20/40/60 m) for alle polygonene i ruta."""
    coll = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(omr)
            .filterDate("%d-%s" % (aar, bit[0]), "%d-%s" % (aar, bit[1]))
            .filter(ee.Filter.listContains("system:band_names", "B11"))
            .filter(ee.Filter.listContains("system:band_names", "SCL"))
            .select(BAND)                                   # samme bånd i alle bilder → mosaikk kan ikke feile
            .map(lambda im: im.set("dato", ee.Date(im.get("system:time_start")).format("YYYY-MM-dd"))))
    # Bildeliste (dato, baseline) hentes som ÉN aggregering for hele biten, i eget kall. Aggregeringer
    # per dag (dag.size(), aggregate_array) ga «Too many concurrent aggregations» i GEE.
    bilder = coll.reduceColumns(ee.Reducer.toList(2), ["dato", "PROCESSING_BASELINE"]).get("list")
    datoer = coll.aggregate_array("dato").distinct().sort()
    red = ee.Reducer.sum().combine(ee.Reducer.mean(), sharedInputs=True)
    tell = ["n", "mork", "lys_is", "lys_annet", "scl_sky", "scl_skygge"]

    def per_dag(d):
        d = ee.String(d)
        dag = coll.filter(ee.Filter.eq("dato", d)).sort("CLOUDY_PIXEL_PERCENTAGE", False)
        return dag.mosaic().set("dato", d)

    # Som g1: dagsmosaikkene som ImageCollection, og reduksjonen i en .map over den (ikke over en ee.List —
    # en liste med reduceRegions i hvert ledd evalueres parallelt og gir «Too many concurrent aggregations»).
    mosaikker = ee.ImageCollection.fromImages(datoer.map(per_dag))

    def reduser(im):
        d = im.get("dato")
        kl = g1.s2_klassebilde(ee, im, tv, tn)
        res = kl.reduceRegions(collection=fc, reducer=red, scale=skala, crs="EPSG:32633", tileScale=tile_scale)
        res = res.filter(ee.Filter.gt("n_sum", 0))

        def rydd(f):
            p = ee.Dictionary({"lnr": f.get("lnr"), "dato": d, "vis": f.get("vis_mean")})
            for k in tell:
                p = p.set(k, f.get(k + "_sum"))
            return ee.Feature(None, p)
        return res.map(rydd)

    return mosaikker.map(reduser).flatten(), bilder


def hent_bit(ee, vann, aar, bit, tv, tn, tile_scale=1, skala=SKALA):
    fc = ee_fc(ee, vann)
    rader_fc, bilder = s2_rute(ee, fc, ee_boks(ee, vann), aar, bit, tv, tn, tile_scale, skala)
    svar = rader_fc.getInfo()
    per_dag = {}
    for dato, bl in bilder.getInfo():
        per_dag.setdefault(dato, []).append(str(bl))
    rader = []
    for f in svar.get("features", []):
        p = f["properties"]
        n = int(round(p.get("n") or 0))
        if n <= 0:
            continue
        bl = per_dag.get(p["dato"], [])
        rader.append({"vatnlnr": int(p["lnr"]), "aar": aar, "dato": p["dato"], "n": n,
                      "mork": int(round(p.get("mork") or 0)), "lys_is": int(round(p.get("lys_is") or 0)),
                      "lys_annet": int(round(p.get("lys_annet") or 0)), "scl_sky": int(round(p.get("scl_sky") or 0)),
                      "scl_skygge": int(round(p.get("scl_skygge") or 0)),
                      "vis": round(p["vis"], 4) if p.get("vis") is not None else None,
                      "n_img": len(bl), "baseline": "|".join(sorted(set(bl)))})
    return rader


def del_bit(bit):
    """Deler en datobit («MM-DD», «MM-DD») i to omtrent like halvdeler. None hvis én dag."""
    d0 = dt.date(2021, int(bit[0][:2]), int(bit[0][3:]))
    d1 = dt.date(2021, int(bit[1][:2]), int(bit[1][3:]))
    dager = (d1 - d0).days
    if dager <= 1:
        return None
    m = d0 + dt.timedelta(days=dager // 2)
    return [(bit[0], m.strftime("%m-%d")), (m.strftime("%m-%d"), bit[1])]


def hent_enhet(ee, vann, aar, bit, tv, tn, teller, dybde=0, skala=SKALA):
    """Henter én rute-år-bit; ved minne-/tidsfeil deles først datoene, så vannlista. Resultatet
    er det samme uansett deling (hver dag og hvert polygon regnes uavhengig)."""
    t0 = time.time()
    try:
        rader = hent_bit(ee, vann, aar, bit, tv, tn, skala=skala)
        teller["kall"] += 1
        teller["sek"] += time.time() - t0
        return rader
    except Exception as e:                                  # noqa: BLE001
        teller["kall"] += 1
        teller["feil"] += 1
        teller["sek"] += time.time() - t0
        tekst = str(e)[:160].replace("\n", " ")
        if dybde >= 8:
            raise
        halv = del_bit(bit)
        if halv:
            logg("    deler datoer %s–%s (%s)" % (bit[0], bit[1], tekst))
            return hent_enhet(ee, vann, aar, halv[0], tv, tn, teller, dybde + 1, skala) + \
                hent_enhet(ee, vann, aar, halv[1], tv, tn, teller, dybde + 1, skala)
        if len(vann) > 1:
            logg("    deler vannlista (%d) for %s (%s)" % (len(vann), bit[0], tekst))
            k = len(vann) // 2
            return hent_enhet(ee, vann[:k], aar, bit, tv, tn, teller, dybde + 1, skala) + \
                hent_enhet(ee, vann[k:], aar, bit, tv, tn, teller, dybde + 1, skala)
        logg("    prøver tileScale 4 for %s %d %s (%s)" % (vann[0]["vatnlnr"], aar, bit[0], tekst))
        rader = hent_bit(ee, vann, aar, bit, tv, tn, tile_scale=4, skala=skala)
        teller["kall"] += 1
        return rader


# ----------------------------------------------------------------- rådata (mellomlagring, --fortsett)
RAA_KOL = ["vatnlnr", "aar", "dato", "n", "mork", "lys_is", "lys_annet", "scl_sky", "scl_skygge", "vis", "n_img", "baseline"]


def raa_sti(navn):
    return os.path.join(DATA, "serier_%s.csv" % navn)


def fremdrift_sti(navn):
    return os.path.join(DATA, "fremdrift_%s.json" % navn)


def les_raa(navn):
    serier = {}
    sti = raa_sti(navn)
    if not os.path.exists(sti):
        return serier
    for r in csv.DictReader(io.open(sti, encoding="utf-8-sig"), delimiter=";"):
        serier.setdefault((int(r["vatnlnr"]), int(r["aar"])), []).append(r)
    return serier


def apne_raa(navn):
    os.makedirs(DATA, exist_ok=True)
    sti = raa_sti(navn)
    ny = not os.path.exists(sti)
    fh = io.open(sti, "a", encoding="utf-8-sig" if ny else "utf-8", newline="")
    w = csv.DictWriter(fh, fieldnames=RAA_KOL, delimiter=";", extrasaction="ignore")
    if ny:
        w.writeheader()
    return fh, w


def les_fremdrift(navn):
    sti = fremdrift_sti(navn)
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))
    return {"ferdig": [], "vindu": None}


def skriv_fremdrift(navn, fr):
    os.makedirs(DATA, exist_ok=True)
    json.dump(fr, io.open(fremdrift_sti(navn), "w", encoding="utf-8"))


# ----------------------------------------------------------------- hovedløp for henting
def enhet_kost_sek(rute, bit):
    """Anslått EECU-sekunder for én enhet (rute × år × datobit)."""
    return len(rute["vann"]) * eecu_vannaar_sek(rute["skala"], bit)


def komplette_vannaar(rt, aar_liste, biter, ferdig):
    """(vatnlnr, år) der alle måneds-bitene for ruta er hentet."""
    ut = set()
    for r in rt:
        for y in aar_liste:
            if all("%s|%d|%s" % (r["id"], y, b[0]) in ferdig for b in biter):
                ut.update((v["vatnlnr"], y) for v in r["vann"])
    return ut


def hent_alle(ee, navn, vann, aar_liste, vindu, valg, fortsett, parallell=1, budsjett=None, piksel_fast=0):
    """Henter alle enheter for en vannliste. budsjett = {"timer": T, "brukt_sek": s, "lagre": f} er kvotevakten:
    før hver enhet legges enhetens estimat til brukt_sek; passerer summen T timer, sendes ingen flere
    enheter, de som er i gang fullføres, og posten får «stoppet_budsjett»: True. Framdrift lagres per enhet."""
    fr = les_fremdrift(navn) if fortsett else {"ferdig": [], "vindu": None}
    if fortsett and fr.get("vindu") and tuple(fr["vindu"]) != tuple(vindu):
        raise SystemExit("Kjøringen «%s» ble startet med vindu %s; kan ikke fortsette med %s." % (navn, fr["vindu"], list(vindu)))
    if not fortsett:
        for sti in (raa_sti(navn), fremdrift_sti(navn)):
            if os.path.exists(sti):
                os.remove(sti)
    fr["vindu"] = list(vindu)
    ferdig = set(fr["ferdig"])
    rt = ruter(vann, piksel_fast)
    biter = g1._maanedsbiter(vindu)
    enheter = [(r, y, b) for r in rt for y in aar_liste for b in biter]
    gjenstaar = [e for e in enheter if "%s|%d|%s" % (e[0]["id"], e[1], e[2][0]) not in ferdig]
    est_sek = sum(enhet_kost_sek(r, b) for r, _, b in gjenstaar)
    logg("%s: %d vann i %d ruter, %d år, %d biter per år → %d enheter, %d gjenstår." % (
        navn, len(vann), len(rt), len(aar_liste), len(biter), len(enheter), len(gjenstaar)))
    for r in rt:
        logg("  rute %s: %d vann, %d m piksel, %d hjørner, %.0f ha samlet" % (
            r["id"], len(r["vann"]), r["skala"], sum(v["hjorner"] for v in r["vann"]), sum(v["areal_ha"] or 0 for v in r["vann"])))
    logg("Kost-estimat for det som gjenstår: %.1f EECU-timer (%.0f EECU-s/vann-år på 20 m, vindu %s–%s = %d dager, "
         "(20/piksel)^2 for 40/60 m)." % (est_sek / 3600, EECU_SEK_20M, vindu[0], vindu[1], vindu_dager(vindu)))
    if budsjett:
        rest = budsjett["timer"] * 3600 - budsjett["brukt_sek"]
        logg("Kvotevakt: brukt %.1f t denne måneden (estimat), budsjett %.0f t → %.1f t igjen%s." % (
            budsjett["brukt_sek"] / 3600, budsjett["timer"], rest / 3600,
            "" if est_sek <= rest else "; kjøringen vil STOPPE før den er ferdig (trenger %.1f t)" % (est_sek / 3600)))
    fh, w = apne_raa(navn)
    teller = {"kall": 0, "sek": 0.0, "feil": 0, "rader": 0, "vannaar": 0}
    t_start = time.time()
    laas = threading.Lock()
    gjort = [0]
    feilede = []
    stoppet = [False]           # kvotevakten slo til
    stoppet_tid = [False]       # tidsvakten slo til

    def en(enhet):
        r, y, b = enhet
        t1 = time.time()
        rader = hent_enhet(ee, r["vann"], y, b, valg["tv"], valg["tn"], teller, skala=r["skala"])
        with laas:
            for rad in rader:
                w.writerow(rad)
            fh.flush()
            teller["rader"] += len(rader)
            ferdig.add("%s|%d|%s" % (r["id"], y, b[0]))
            fr["ferdig"] = sorted(ferdig)
            skriv_fremdrift(navn, fr)
            if budsjett and budsjett.get("lagre"):
                budsjett["lagre"](budsjett)
            gjort[0] += 1
            va_ferdig = len(komplette_vannaar(rt, aar_liste, biter, ferdig))
            logg("  %s %d %s–%s %dm: %4d rader (%d vann), %5.1f s   [enhet %d/%d, vann-år %d/%d, %.1f min%s]" % (
                r["id"], y, b[0], b[1], r["skala"], len(rader), len({x["vatnlnr"] for x in rader}), time.time() - t1,
                gjort[0], len(gjenstaar), va_ferdig, len(vann) * len(aar_liste), (time.time() - t_start) / 60,
                ", kvote %.1f t" % (budsjett["brukt_sek"] / 3600) if budsjett else ""))

    def kan_sende(enhet):
        if not budsjett:
            return True
        k = enhet_kost_sek(enhet[0], enhet[2])
        if budsjett["brukt_sek"] + k > budsjett["timer"] * 3600:
            return False
        budsjett["brukt_sek"] += k
        return True

    try:
        # Uavhengige enheter; GEE tillater 40 samtidige kall. Enheter sendes én og én så kvotevakten
        # kan stoppe rent; rådata skrives under lås. En enhet som feiler etter all deling logges og
        # blir liggende som ikke-ferdig (--fortsett prøver igjen).
        neste = iter(gjenstaar)
        ventende = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, parallell)) as ex:
            while True:
                while len(ventende) < max(1, parallell) and not stoppet[0] and not stoppet_tid[0]:
                    enhet = next(neste, None)
                    if enhet is None:
                        break
                    if tid_ute():
                        stoppet_tid[0] = True
                        logg("TIDSVAKT: fristen på %.0f min er passert (%.1f min brukt). Sender ikke flere enheter; venter på %d i gang. "
                             "Resten tas med --fortsett." % ((FRIST[0] - t_start) / 60 if FRIST[0] else 0, (time.time() - t_start) / 60, len(ventende)))
                        break
                    if not kan_sende(enhet):
                        stoppet[0] = True
                        logg("KVOTEVAKT: neste enhet (%s %d %s, %.0f EECU-s) ville passere budsjettet på %.0f t "
                             "(brukt %.1f t, estimat). Sender ikke flere; venter på %d i gang." % (
                                 enhet[0]["id"], enhet[1], enhet[2][0], enhet_kost_sek(enhet[0], enhet[2]),
                                 budsjett["timer"], budsjett["brukt_sek"] / 3600, len(ventende)))
                        break
                    ventende[ex.submit(en, enhet)] = enhet
                if not ventende:
                    break
                gjort_no, _ = concurrent.futures.wait(ventende, return_when=concurrent.futures.FIRST_COMPLETED)
                for f in gjort_no:
                    enhet = ventende.pop(f)
                    try:
                        f.result()
                    except Exception as e:                  # noqa: BLE001
                        feilede.append(enhet)
                        logg("  FEILET %s %d %s: %s" % (enhet[0]["id"], enhet[1], enhet[2][0], str(e)[:200].replace("\n", " ")))
                        print("FEILET %s %d %s: %s" % (enhet[0]["id"], enhet[1], enhet[2][0], str(e)[:500]), file=sys.stderr, flush=True)
    finally:
        fh.close()
    sek = time.time() - t_start
    teller["vannaar"] = len(vann) * len(aar_liste)
    komplett = komplette_vannaar(rt, aar_liste, biter, ferdig)
    post = {"navn": navn, "naar": dt.datetime.now().isoformat(timespec="seconds"), "vann": len(vann), "ruter": len(rt),
            "aar": [aar_liste[0], aar_liste[-1]], "vindu": list(vindu), "enheter": len(gjenstaar), "enheter_hentet": gjort[0],
            "enheter_feilet": len(feilede), "kall": teller["kall"], "feil_kall": teller["feil"], "sek": round(sek, 1),
            "sek_per_vannaar": round(sek / max(1, teller["vannaar"]), 2), "rader": teller["rader"],
            "vannaar_komplett": len(komplett), "eecu_estimat_timer": round(sum(enhet_kost_sek(r, b) for r, _, b in gjenstaar[:gjort[0] + len(feilede)]) / 3600, 2),
            "stoppet_budsjett": stoppet[0], "stoppet_tid": stoppet_tid[0], "piksel": sorted({r["skala"] for r in rt}),
            "start_utc": dt.datetime.fromtimestamp(t_start, dt.timezone.utc).isoformat(timespec="seconds"),
            "slutt_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    gammel = json.load(io.open(LOGG, encoding="utf-8")) if os.path.exists(LOGG) else {"kjoringer": []}
    gammel["kjoringer"].append(post)
    json.dump(gammel, io.open(LOGG, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    logg("%s: %d kall (%d feilet og ble delt, %d enheter gitt opp), %.1f min, %.2f s per vann-år, %d av %d vann-år komplette." % (
        "STOPPET AV KVOTEVAKTEN" if stoppet[0] else ("STOPPET AV TIDSVAKTEN" if stoppet_tid[0] else "Ferdig"), teller["kall"], teller["feil"], len(feilede), sek / 60,
        post["sek_per_vannaar"], len(komplett), teller["vannaar"]))
    post["komplett"] = komplett
    return post


# ----------------------------------------------------------------- per vann-år → datasettskjema
def passliste(obs):
    """Som sky_hent.passliste: MMDD:n/mørk/lys_is/lys_annet/sky, skilt med «;». Alle pass, også skyete."""
    return ";".join("%s:%d/%d/%d/%d/%d" % (r["dato"][5:7] + r["dato"][8:10], int(r["n"]), int(r["mork"]), int(r["lys_is"]),
                                           int(r["lys_annet"]), int(r["scl_sky"])) for r in sorted(obs, key=lambda r: r["dato"]))


STATUS = {"ok": "ok", "åpent ved første klare pass": "ingen_is_sett", "ingen klare pass": "ingen_data",
          "ubekreftet (siste pass i vinduet)": "ubekreftet", "is i hele vinduet": "is_hele_vinduet"}


def vannaar_post(obs, valg, n_piksler):
    """Ett vann-år etter skjemaet i oppgaven. obs = alle pass (rader) i vinduet, kan være tom."""
    obs = sorted(obs, key=lambda r: r["dato"])
    kl = g1.klare(obs, valg["tv"], valg["tn"], valg["regel"]) if obs else []
    res = g1.v3.finn_isgang(kl, g1.TERSKEL) if obs else {"status": "ingen klare pass", "lo": None, "hi": None}
    post = {"status": STATUS.get(res["status"], res["status"]), "lo": res["lo"], "hi": res["hi"], "midt": None,
            "bredde_d": None, "n_pass": len(obs), "n_klare": len(kl), "gap_for": None, "gap_etter": None,
            "n_piksler": n_piksler, "andel_gyldig": None, "is_sett": "ja" if any(f >= g1.TERSKEL for _, f in kl) else "nei",
            "baseline": sorted({b for r in obs for b in str(r.get("baseline") or "").split("|") if b}),
            "kilde": "S2", "p": passliste(obs), "klasse": "X"}
    if not obs:
        post["status"] = "ingen_data"
    elif n_piksler < g1.v3.MIN_PX:
        post["status"] = "for_faa_piksler"
    if obs and n_piksler:
        post["andel_gyldig"] = round(statistics.median(int(r["n"]) / float(n_piksler) for r in obs), 3)
    if res["status"] == "ok":
        lo, hi = g1.v3.d(res["lo"]), g1.v3.d(res["hi"])
        post["bredde_d"] = (hi - lo).days
        post["midt"] = (lo + (hi - lo) / 2).isoformat()
        post["klasse"] = "A" if post["bredde_d"] <= 5 else ("B" if post["bredde_d"] <= 10 else "C")
        datoer = [d for d, _ in kl]
        for_ = [d for d in datoer if d < res["lo"]]
        etter = [d for d in datoer if d > res["hi"]]
        post["gap_for"] = (lo - g1.v3.d(for_[-1])).days if for_ else None
        post["gap_etter"] = (g1.v3.d(etter[0]) - hi).days if etter else None
    return post


def bygg_resultat(vann, serier, aar_liste, valg, komplett=None):
    """vatnlnr → {meta, aar: {år: post}}. n_piksler = flest piksler sett i noe pass (hele polygonet).
    komplett = sett av (vatnlnr, år) som skal med (None = alle); vann uten noe komplett år utelates."""
    ut = {}
    for v in vann:
        aar_med = [y for y in aar_liste if komplett is None or (v["vatnlnr"], y) in komplett]
        if not aar_med:
            continue
        alle = [r for y in aar_med for r in serier.get((v["vatnlnr"], y), [])]
        n_px = max((int(r["n"]) for r in alle), default=0)
        post = {k: v.get(k) for k in ("navn", "moh", "areal_ha", "lat", "lon", "kommune", "fylke")}
        post["piksel_m"] = v.get("skala") or piksel(v.get("areal_ha"))
        post["aar"] = {str(y): vannaar_post(serier.get((v["vatnlnr"], y), []), valg, n_px) for y in aar_med}
        ut[str(v["vatnlnr"])] = post
    return ut


KOL = ["vatnLnr", "navn", "moh", "areal_ha", "lat", "lon", "kommune", "fylke", "aar", "status", "lo", "hi", "midt", "bredde_d",
       "n_pass", "n_klare", "gap_for", "gap_etter", "n_piksler", "andel_gyldig", "is_sett", "baseline", "kilde", "p", "klasse"]


KOL_LETT = [k for k in KOL if k != "p"]     # den lette fylkesfila (norge/lett/): alt unntatt passlista


def skriv_csv(sti, res, kol=KOL):
    """CSV etter skjemaet KOL (eller KOL_LETT uten «p»). Skrives via temp-fil og os.replace."""
    os.makedirs(os.path.dirname(sti), exist_ok=True)
    tmp = sti + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(kol)
        for lnr in sorted(res, key=int):
            v = res[lnr]
            for y in sorted(v["aar"]):
                p = v["aar"][y]
                rad = dict(zip(KOL, [lnr, v["navn"], v["moh"], v["areal_ha"], v["lat"], v["lon"], v["kommune"], v["fylke"], y, p["status"],
                                     p["lo"] or "", p["hi"] or "", p["midt"] or "", p["bredde_d"] if p["bredde_d"] is not None else "",
                                     p["n_pass"], p["n_klare"], p["gap_for"] if p["gap_for"] is not None else "",
                                     p["gap_etter"] if p["gap_etter"] is not None else "", p["n_piksler"],
                                     p["andel_gyldig"] if p["andel_gyldig"] is not None else "", p["is_sett"], ",".join(p["baseline"]),
                                     p["kilde"], p["p"], p["klasse"]]))
                w.writerow([rad[k] for k in kol])
    os.replace(tmp, sti)


STORE_KILDE = ("COPERNICUS/S2_SR_HARMONIZED i GEE, EPSG:32633. Piksel per vann i vann[lnr].piksel_m: referansenettet "
               "(10. okt 2026) alltid 20 m og vindu 03-01–07-16; Norge-kjøringen 20 m <= 150 ha, 40 m 150–600 ha, "
               "60 m > 600 ha, vindu 02-01–07-16 (vinduet per kjøring i kjoringer[].vindu).")


# ----------------------------------------------------------------- lageret: én fil per fylke + indexfil (G4, 11. okt 2026)
INDEX_KOL = ["vatnLnr", "navn", "fylke", "aar", "status", "lo", "hi", "midt", "bredde_d", "klasse"]
UTEN_FYLKE = "00"                   # vann uten kommnr i NVE (grensesjøer): isgang_00_uten_fylke.json


def slug(navn):
    """Filnavn-trygt: «Møre og Romsdal» → «more_og_romsdal», «Østfold» → «ostfold»."""
    t = (navn or "").lower()
    for a, b in (("æ", "ae"), ("ø", "o"), ("å", "a"), ("é", "e"), (" ", "_"), ("-", "_")):
        t = t.replace(a, b)
    return "".join(c for c in t if c.isalnum() or c == "_") or "uten_fylke"


def fylkesfil(nr, ext="json"):
    return os.path.join(NORGE_DIR, "isgang_%s_%s.%s" % (nr, slug(FYLKE.get(nr, "uten fylke")), ext))


def lettfil(nr):
    """Den lette fylkesfila (uten passlista «p») — den som ligger i git-repoet: norge/lett/isgang_<nr>_<navn>.csv."""
    return os.path.join(NORGE_DIR, "lett", "isgang_%s_%s.csv" % (nr, slug(FYLKE.get(nr, "uten fylke"))))


def fylkesnr_av_meta(meta):
    """Fylkesnr for en vannpost i lageret: fra «fylke»-navnet (NVE kommnr → FYLKE), ellers 00."""
    return meta.get("fylkesnr") or FYLKE_NR.get(meta.get("fylke") or "", UTEN_FYLKE)


def krev_migrert():
    """Det gamle samlelageret må være delt (--migrer-fylker) før noe skrives til fylkesfilene."""
    if os.path.exists(STORE_JSON):
        raise SystemExit("isgang_norge.json finnes fortsatt (det gamle samlelageret). Kjør `python g2_gee_norge.py --migrer-fylker` "
                         "først — ellers ville fylkesfilene og det gamle lageret sprike.")


def nytt_fylkeslager(nr, valg, vindu):
    return {"metode": valg, "terskel": g1.TERSKEL, "vindu": list(vindu), "kilde": STORE_KILDE, "skjema": KOL,
            "fylkesnr": nr, "fylke": FYLKE.get(nr, ""), "kjoringer": [], "vann": {}}


def les_fylkesfil(nr):
    sti = fylkesfil(nr)
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))
    return None


def skriv_fylkesfil(nr, store):
    """JSON + CSV for ett fylke (samme skjema som det gamle isgang_norge.json/.csv). Skrives via temp-fil og
    os.replace så en avbrutt skriving aldri etterlater en halv fil."""
    os.makedirs(NORGE_DIR, exist_ok=True)
    sti = fylkesfil(nr)
    tmp = sti + ".tmp"
    json.dump(store, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    os.replace(tmp, sti)
    skriv_csv(fylkesfil(nr, "csv"), store["vann"])
    skriv_csv(lettfil(nr), store["vann"], KOL_LETT)


def nokler_fylke(nr):
    """(vatnlnr, år) som alt ligger i fylkesfila — brukes til å hoppe over vann som er komplette."""
    store = les_fylkesfil(nr)
    if not store:
        return set()
    return {(int(lnr), int(y)) for lnr, v in store["vann"].items() for y in v["aar"]}


def fylkesfiler():
    """[(nr, sti)] for alle fylkesfiler som finnes, i Norge-rekkefølge (00 sist)."""
    if not os.path.isdir(NORGE_DIR):
        return []
    ut = []
    for nr in REKKEFOLGE + [UTEN_FYLKE]:
        if os.path.exists(fylkesfil(nr)):
            ut.append((nr, fylkesfil(nr)))
    return ut


def index_rader(vann):
    ut = []
    for lnr in sorted(vann, key=int):
        v = vann[lnr]
        for y in sorted(v["aar"]):
            p = v["aar"][y]
            ut.append([lnr, v["navn"], v.get("fylke") or "", y, p["status"], p["lo"] or "", p["hi"] or "", p["midt"] or "",
                       p["bredde_d"] if p["bredde_d"] is not None else "", p["klasse"]])
    return ut


def skriv_index(rader):
    rader.sort(key=lambda r: (int(r[0]), r[3]))
    tmp = INDEX_CSV + ".tmp"
    with io.open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(INDEX_KOL)
        w.writerows(rader)
    os.replace(tmp, INDEX_CSV)


def oppdater_index(nr, vann):
    """Bytter ut radene for ett fylke i isgang_norge_index.csv (radene kjennes på fylkesnavnet)."""
    navn = FYLKE.get(nr, "")
    rader = []
    if os.path.exists(INDEX_CSV):
        for r in csv.DictReader(io.open(INDEX_CSV, encoding="utf-8-sig"), delimiter=";"):
            if (r.get("fylke") or "") != navn:
                rader.append([r.get(k, "") for k in INDEX_KOL])
    rader += index_rader(vann)
    skriv_index(rader)


def samle():
    """Bygger isgang_norge_index.csv og de lette fylkesfilene (norge/lett/, uten «p») på nytt fra alle de fulle
    fylkesfilene. Returnerer (vann, vann-år, med intervall)."""
    rader, n_vann, n_ok = [], 0, 0
    for nr, sti in fylkesfiler():
        store = json.load(io.open(sti, encoding="utf-8"))
        r = index_rader(store["vann"])
        ok = sum(1 for x in r if x[4] == "ok")
        skriv_csv(lettfil(nr), store["vann"], KOL_LETT)
        logg("  %s %-16s %5d vann, %6d vann-år, %6d med intervall  (%s → lett/%s)" % (
            nr, store.get("fylke") or "uten fylke", len(store["vann"]), len(r), ok, os.path.basename(sti), os.path.basename(lettfil(nr))))
        rader += r
        n_vann += len(store["vann"])
        n_ok += ok
    skriv_index(rader)
    logg("%s: %d vann, %d vann-år, %d med intervall, fra %d fylkesfiler. Lette fylkesfiler i %s." % (
        os.path.basename(INDEX_CSV), n_vann, len(rader), n_ok, len(fylkesfiler()), os.path.join(NORGE_DIR, "lett")))
    return n_vann, len(rader), n_ok


def slaa_inn(store, res, behold_eksisterende):
    """Slår vannposter (res) inn i et fylkeslager. Standard: nyeste vinner. behold_eksisterende (Norge-kjøringen):
    vann-år som alt finnes røres ikke, og metadata fra første kjøring beholdes. Returnerer antall nye vann-år."""
    nye = 0
    for lnr, v in res.items():
        gammel = store["vann"].get(lnr, {})
        ny = {k: v[k] for k in v if k != "aar"}
        if behold_eksisterende and gammel:
            ny = {k: gammel[k] for k in gammel if k != "aar"}
        ny["aar"] = dict(gammel.get("aar", {}))
        for y, p in v["aar"].items():
            if behold_eksisterende and y in ny["aar"]:
                continue
            ny["aar"][y] = p
            nye += 1
        store["vann"][lnr] = ny
    return nye


def oppdater_store(res, valg, vindu, kjoring, behold_eksisterende=False):
    """Slår kjøringens resultat inn i fylkesfilene norge/isgang_<nr>_<navn>.json/.csv (per vatnLnr og år) og
    oppdaterer indexfila for de fylkene som ble rørt. Returnerer antall nye vann-år."""
    krev_migrert()
    per_fylke = {}
    for lnr, v in res.items():
        per_fylke.setdefault(fylkesnr_av_meta(v), {})[lnr] = v
    k = {kk: vv for kk, vv in kjoring.items() if kk != "komplett"}
    nye = 0
    for nr in sorted(per_fylke):
        store = les_fylkesfil(nr) or nytt_fylkeslager(nr, valg, vindu)
        store["kilde"] = STORE_KILDE
        n = slaa_inn(store, per_fylke[nr], behold_eksisterende)
        nye += n
        store["kjoringer"].append(dict(k, vann_i_dette_fylket=len(per_fylke[nr])))
        skriv_fylkesfil(nr, store)
        oppdater_index(nr, store["vann"])
        n_ok = sum(1 for v in store["vann"].values() for p in v["aar"].values() if p["status"] == "ok")
        n_alle = sum(len(v["aar"]) for v in store["vann"].values())
        logg("%s: %d vann, %d vann-år, %d med intervall (%d vann-år nye). Indexfila oppdatert." % (
            os.path.basename(fylkesfil(nr)), len(store["vann"]), n_alle, n_ok, n))
    return nye


def tell_vannaar_gammelt(store):
    return sum(len(v["aar"]) for v in store["vann"].values())


def migrer_fylker(valg, vindu):
    """Engangs (11. okt 2026): deler det gamle isgang_norge.json i fylkesfiler. Vann uten fylke slås opp på kommnr i
    NVE-geojsonen (I_arter_per_vann/raa); de som fortsatt mangler kommnr (grensesjøer) går til isgang_00_uten_fylke.
    Det gamle lageret døpes om til isgang_norge_for_deling_<dato>.json/.csv og røres ikke. Returnerer (før, etter)."""
    if not os.path.exists(STORE_JSON):
        logg("Ingen %s å migrere." % STORE_JSON)
        return None, None
    store = json.load(io.open(STORE_JSON, encoding="utf-8"))
    n_for = tell_vannaar_gammelt(store)
    logg("Gammelt lager: %d vann, %d vann-år, %d kjøringer." % (len(store["vann"]), n_for, len(store.get("kjoringer", []))))
    uten = [lnr for lnr, v in store["vann"].items() if fylkesnr_av_meta(v) == UTEN_FYLKE]
    if uten and os.path.exists(NVE_GEOJSON):
        kommnr = {}
        for f in json.load(io.open(NVE_GEOJSON, encoding="utf-8"))["features"]:
            p = f["properties"]
            if str(p.get("vatnlnr")) in uten and p.get("kommnr"):
                kommnr[str(p["vatnlnr"])] = p["kommnr"]
        for lnr in uten:
            if lnr in kommnr:
                store["vann"][lnr]["fylke"] = fylke_av(kommnr[lnr])
                store["vann"][lnr]["kommnr"] = kommnr[lnr]
        logg("%d vann uten fylke; %d fikk fylke fra NVE-geojsonens kommnr, %d går til isgang_%s_uten_fylke (uten kommnr i NVE)." % (
            len(uten), len(kommnr), len(uten) - len(kommnr), UTEN_FYLKE))
    per_fylke = {}
    for lnr, v in store["vann"].items():
        per_fylke.setdefault(fylkesnr_av_meta(v), {})[lnr] = v
    kj = store.get("kjoringer", [])
    n_etter = 0
    for nr in sorted(per_fylke):
        fs = les_fylkesfil(nr)
        if fs:
            # fylkesfila er nyere enn det gamle lageret: det som ligger der vinner, det gamle fyller bare hull
            slaa_inn(fs, per_fylke[nr], True)
        else:
            fs = nytt_fylkeslager(nr, store.get("metode", valg), store.get("vindu", list(vindu)))
            fs["terskel"] = store.get("terskel", g1.TERSKEL)
            fs["vann"] = per_fylke[nr]
            fs["kjoringer"] = [k for k in kj if not k.get("fylke") or k.get("fylke") == nr]
        skriv_fylkesfil(nr, fs)
        n = tell_vannaar_gammelt(fs)
        n_etter += n
        logg("  %-36s %5d vann, %6d vann-år" % (os.path.basename(fylkesfil(nr)), len(fs["vann"]), n))
    dato = dt.date.today().isoformat()
    for sti in (STORE_JSON, STORE_CSV):
        if os.path.exists(sti):
            ny = sti.replace("isgang_norge.", "isgang_norge_for_deling_%s." % dato)
            os.replace(sti, ny)
            logg("Døpte om %s → %s (sikkerhetskopi, røres ikke)." % (os.path.basename(sti), os.path.basename(ny)))
    logg("Bygger indexfila ...")
    _, n_index, _ = samle()
    logg("Vann-år før deling %d, i fylkesfilene etter %d, i indexfila %d." % (n_for, n_etter, n_index))
    if n_etter < n_for:
        logg("ADVARSEL: færre vann-år etter deling enn før!")
    return n_for, n_etter


# ----------------------------------------------------------------- kvalitetsport mot g1
def kvalitetsport(vann, serier, aar_liste, vindu, valg, kjoring, utfil="kvalitetsport.md"):
    """Vann-år for vann-år mot g1 (tidsserie_gee.csv): rå pikseltall per pass OG lo/hi fra samme klare/finn_isgang."""
    navn_av = {v["vatnlnr"]: v["navn"] for v in vann}
    g1_ser = g1.les_csv(g1.CSV_S2)
    cdse = g1.les_cdse()
    fasit = g1.les_fasit()
    L = ["# Kvalitetsport G2: rute-regning (reduceRegions) mot g1 (ett vann om gangen)\n",
         "Kjørt %s. Vindu %s–%s (g1: 03-01–08-01). 16 Nordmarka-vann × %d–%d. Samme polygoner (grunnlag/vann.geojson), "
         "samme klassifisering, samme `klare()` og `finn_isgang()` (importert fra g1 → 03_valider.py).\n"
         % (kjoring["naar"][:10], vindu[0], vindu[1], aar_liste[0], aar_liste[-1]),
         "Kravet: identiske lo/hi på alle vann-år. I tillegg sammenlignes rå pikseltall per pass "
         "(n, mørk, lys is, lys annet, scl_sky, scl_skygge) — strengere enn lo/hi.\n"]
    rader, n_id, n_avvik, n_g1_mangler = [], 0, 0, 0
    rad_like, rad_ulike, rad_bare_g1, rad_bare_g2 = 0, 0, 0, 0
    for v in vann:
        for y in aar_liste:
            a = g1_ser.get((v["navn"], y), [])
            b = serier.get((v["vatnlnr"], y), [])
            if vindu != ("03-01", "08-01"):
                a = [r for r in a if r["dato"] < "%d-%s" % (y, vindu[1]) and r["dato"] >= "%d-%s" % (y, vindu[0])]
            ra = g1.v3.finn_isgang(g1.klare(a, valg["tv"], valg["tn"], valg["regel"]), g1.TERSKEL) if a else {"status": "g1 feilet", "lo": None, "hi": None}
            rb = g1.v3.finn_isgang(g1.klare(b, valg["tv"], valg["tn"], valg["regel"]), g1.TERSKEL) if b else {"status": "ingen data", "lo": None, "hi": None}
            da = {r["dato"]: r for r in a}
            db = {r["dato"]: r for r in b}
            like = ulike = 0
            ulik_eks = []
            for d in sorted(set(da) | set(db)):
                if d in da and d in db:
                    x, z = da[d], db[d]
                    if all(int(x[k]) == int(z[k]) for k in ("n", "mork", "lys_is", "lys_annet", "scl_sky", "scl_skygge")):
                        like += 1
                    else:
                        ulike += 1
                        ulik_eks.append("%s g1 %s/%s/%s/%s/%s g2 %s/%s/%s/%s/%s" % (
                            d[5:], x["n"], x["mork"], x["lys_is"], x["lys_annet"], x["scl_sky"],
                            z["n"], z["mork"], z["lys_is"], z["lys_annet"], z["scl_sky"]))
                elif d in da:
                    rad_bare_g1 += 1
                else:
                    rad_bare_g2 += 1
            rad_like += like
            rad_ulike += ulike
            if not a:
                n_g1_mangler += 1
                merk = "g1 feilet («incompatible bands»); g2 ok, CDSE: [%s, %s]" % (
                    cdse.get(v["navn"], {}).get(str(y), {}).get("lo", "–"), cdse.get(v["navn"], {}).get(str(y), {}).get("hi", "–"))
                identisk = "–"
            elif (ra["status"], ra["lo"], ra["hi"]) == (rb["status"], rb["lo"], rb["hi"]):
                n_id += 1
                identisk = "ja"
                merk = "" if not ulike else "pikseltall ulike i %d pass: %s" % (ulike, "; ".join(ulik_eks[:3]))
            else:
                n_avvik += 1
                identisk = "**NEI**"
                merk = "; ".join(ulik_eks[:3])
            rader.append("| %s | %d | %s | %s | %s | %s | %s | %s | %d | %d | %d | %s | %s |" % (
                v["navn"], y, fasit.get(v["navn"], {}).get(str(y), "–"), ra["status"], ra["lo"] or "–", ra["hi"] or "–",
                rb["lo"] or "–", rb["hi"] or "–", len(a), len(b), like, identisk, merk))
    L += ["| | Verdi |", "|---|---|",
          "| Vann-år sammenlignet (g1 hadde resultat) | %d |" % (n_id + n_avvik),
          "| Identisk status + lo + hi | **%d** |" % n_id,
          "| Avvik | **%d** |" % n_avvik,
          "| Vann-år der g1 feilet (rettet i g2) | %d |" % n_g1_mangler,
          "| Pass med identiske pikseltall / ulike | %d / %d |" % (rad_like, rad_ulike),
          "| Pass bare i g1 / bare i g2 | %d / %d |" % (rad_bare_g1, rad_bare_g2),
          "| Kall til GEE / klokketid / per vann-år | %d / %.1f min / %.1f s |" % (kjoring["kall"], kjoring["sek"] / 60, kjoring["sek_per_vannaar"]),
          "", "**Port %s.**\n" % ("BESTÅTT" if n_avvik == 0 else "IKKE BESTÅTT — se avvikene under"),
          "| Vann | År | Fasit | g1 status | g1 siste is | g1 første åpent | g2 siste is | g2 første åpent | Pass g1 | Pass g2 | Like pass | Identisk | Merknad |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"] + rader
    io.open(os.path.join(HER, utfil), "w", encoding="utf-8").write("\n".join(L) + "\n")
    logg("\n".join(L[3:14]))
    return n_avvik == 0, n_id, n_avvik


# ----------------------------------------------------------------- sammenligning med Copernicus (referansenettet)
def sammenlign_referansenett(res, vindu):
    sti = os.path.join(ISGANG, "referansenett_isgang.json")
    nett = {v["vatnlnr"]: v for v in json.load(io.open(os.path.join(ISGANG, "referansenett.json"), encoding="utf-8"))["vann"]}
    if not os.path.exists(sti):
        return ["Fant ikke referansenett_isgang.json."]
    cop = json.load(io.open(sti, encoding="utf-8"))
    felles, like, lo_d, hi_d, bare_g2, bare_cop, status_ulik = 0, 0, [], [], 0, 0, 0
    per_px = {}
    rader_avvik = []
    vindu_forklart = 0          # ulike der Copernicus-intervallet starter før g2-vinduet eller slutter etter
    for lnr, v in res.items():
        c = cop.get(lnr, {}).get("aar", {})
        px = nett.get(int(lnr), {}).get("piksel_m", 20)
        for y, p in v["aar"].items():
            cy = c.get(y)
            if not cy:
                if p["status"] == "ok":
                    bare_g2 += 1
                continue
            if cy["status"] == "ok" and p["status"] == "ok":
                felles += 1
                d = per_px.setdefault(px, {"n": 0, "like": 0, "lo": [], "hi": []})
                d["n"] += 1
                dl = (g1.v3.d(p["lo"]) - g1.v3.d(cy["lo"])).days
                dh = (g1.v3.d(p["hi"]) - g1.v3.d(cy["hi"])).days
                lo_d.append(dl)
                hi_d.append(dh)
                d["lo"].append(dl)
                d["hi"].append(dh)
                if dl == 0 and dh == 0:
                    like += 1
                    d["like"] += 1
                else:
                    if cy["lo"] < "%s-%s" % (y, vindu[0]) or cy["hi"] >= "%s-%s" % (y, vindu[1]):
                        vindu_forklart += 1
                    if abs(dl) > 10 or abs(dh) > 10:
                        rader_avvik.append("| %s | %s | %s m | [%s, %s] | [%s, %s] | %+d / %+d |" % (
                            v["navn"] or "(uten navn)", y, px, cy["lo"], cy["hi"], p["lo"], p["hi"], dl, dh))
            elif cy["status"] == "ok":
                bare_cop += 1
            elif p["status"] == "ok":
                bare_g2 += 1
            else:
                status_ulik += 1
    L = ["| | Verdi |", "|---|---|",
         "| Vann-år med intervall i begge | %d |" % felles,
         "| Identisk intervall (lo og hi) | %d (%.0f %%) |" % (like, 100.0 * like / felles if felles else 0),
         "| «Siste is» g2 − Copernicus: median / snitt abs | %s |" % ("%+.1f d / %.1f d" % (statistics.median(lo_d), statistics.mean(abs(x) for x in lo_d)) if lo_d else "–"),
         "| «Første åpent» g2 − Copernicus: median / snitt abs | %s |" % ("%+.1f d / %.1f d" % (statistics.median(hi_d), statistics.mean(abs(x) for x in hi_d)) if hi_d else "–"),
         "| Intervall bare i g2 / bare i Copernicus | %d / %d |" % (bare_g2, bare_cop),
         "| Begge uten intervall | %d |" % status_ulik,
         "| Ulike intervaller i alt / av dem med Copernicus-intervall utenfor g2-vinduet | %d / %d |" % (felles - like, vindu_forklart),
         "| Ulike med over 10 d avvik i lo eller hi | %d (%.1f %% av felles) |" % (len(rader_avvik), 100.0 * len(rader_avvik) / felles if felles else 0), "",
         "Per pikselstørrelse Copernicus brukte (g2 bruker alltid 20 m; Copernicus brukte 40 m over 150 ha og 60 m over 600 ha, "
         "og vindu 1. feb–31. juli mot g2 %s–%s):\n" % (vindu[0], vindu[1]),
         "| Copernicus-piksel | Vann-år | Identiske | Snitt abs siste is | Snitt abs første åpent |", "|---|---|---|---|---|"]
    for px in sorted(per_px):
        d = per_px[px]
        L.append("| %d m | %d | %d (%.0f %%) | %.1f d | %.1f d |" % (px, d["n"], d["like"], 100.0 * d["like"] / d["n"],
                                                                  statistics.mean(abs(x) for x in d["lo"]), statistics.mean(abs(x) for x in d["hi"])))
    if rader_avvik:
        L += ["", "Vann-år med over 10 dagers avvik i lo eller hi (%d i alt, de første 40):" % len(rader_avvik), "",
              "| Vann | År | Cop.-piksel | Copernicus | g2 | Δlo / Δhi |", "|---|---|---|---|---|---|"] + rader_avvik[:40]
    return L


# ----------------------------------------------------------------- EECU via Cloud Monitoring
def eecu(proj, start_utc, slutt_utc):
    """Prøver å lese earthengine.googleapis.com/project/cpu/usage_time (EECU-sekunder) med samme legitimasjon.
    Returnerer (sum_eecu_sek, melding)."""
    try:
        import ee
        from google.auth.transport.requests import AuthorizedSession
        creds = _EE_CREDS[0] or ee.data.get_persistent_credentials()
        s = AuthorizedSession(creds)
        p = {"filter": 'metric.type="earthengine.googleapis.com/project/cpu/usage_time"',
             "interval.startTime": start_utc, "interval.endTime": slutt_utc,
             "aggregation.alignmentPeriod": "86400s", "aggregation.perSeriesAligner": "ALIGN_SUM",
             "aggregation.crossSeriesReducer": "REDUCE_SUM"}
        r = s.get("https://monitoring.googleapis.com/v3/projects/%s/timeSeries" % proj, params=p, timeout=60)
        if r.status_code != 200:
            try:
                feil = r.json()["error"]
                msg = feil.get("message", "")[:200]
                for d in feil.get("details", []):
                    if d.get("reason") == "SERVICE_DISABLED":
                        return None, ("Cloud Monitoring API er ikke aktivert på prosjektet (HTTP 403). Aktiver den (gratis, ett klikk) på "
                                      "%s — eller les EECU-forbruket i konsollen: console.cloud.google.com/earth-engine → Monitoring."
                                      % d.get("metadata", {}).get("activationUrl", ""))
            except Exception:                               # noqa: BLE001
                msg = r.text[:200]
            return None, "Cloud Monitoring svarte HTTP %d: %s" % (r.status_code, msg)
        total = 0.0
        for ts in r.json().get("timeSeries", []):
            for pt in ts.get("points", []):
                v = pt["value"]
                total += float(v.get("doubleValue", v.get("int64Value", 0)))
        return total, "Cloud Monitoring: %.1f EECU-sekunder (%.2f EECU-timer) i %s–%s." % (total, total / 3600, start_utc, slutt_utc)
    except Exception as e:                                  # noqa: BLE001
        return None, "Kunne ikke lese Cloud Monitoring: %s" % str(e)[:200]


# ----------------------------------------------------------------- tell
def nve_tell(where):
    return nve(dict(where=where, returnCountOnly="true", f="json")).get("count", 0)


def tell_fylke(nr, min_ha, maks_ha):
    """Antall vann i fylket per pikselklasse (NVE, bare tellinger): 20 m <= 150 ha, 40 m 150–600, 60 m 600–maks, droppet > maks."""
    base = "kommnr LIKE '%s%%' AND " % nr
    n20 = nve_tell(base + "areal_km2 >= %s AND areal_km2 <= 1.5" % (min_ha / 100.0))
    n40 = nve_tell(base + "areal_km2 > 1.5 AND areal_km2 <= 6")
    n60 = nve_tell(base + "areal_km2 > 6 AND areal_km2 <= %s" % (maks_ha / 100.0))
    nd = nve_tell(base + "areal_km2 > %s" % (maks_ha / 100.0))
    return {"nr": nr, "navn": FYLKE[nr], "n": n20 + n40 + n60 + nd, "n20": n20, "n40": n40, "n60": n60, "droppet_n": nd}


def estimat_timer_fra_tall(t, n_aar, vindu):
    sek = (t["n20"] * eecu_vannaar_sek(20, vindu) + t["n40"] * eecu_vannaar_sek(40, vindu) + t["n60"] * eecu_vannaar_sek(60, vindu)) * n_aar
    return sek / 3600


def tell(min_ha, maks_ha, aar_liste, vindu, budsjett_timer):
    logg("NVE Innsjødatabase, vann >= %.0f ha per fylke (kommnr-prefiks), i Norge-rekkefølge. Piksel 20 m <= 150 ha, "
         "40 m 150–600 ha, 60 m 600–%.0f ha; over %.0f ha droppes." % (min_ha, maks_ha, maks_ha))
    logg("Kost: %.0f EECU-s per vann-år på 20 m (vindu 03-01–07-16), ×(20/piksel)^2, × %d/%d dager for vinduet %s–%s, × %d år."
         % (EECU_SEK_20M, vindu_dager(vindu), EECU_VINDU_DAGER, vindu[0], vindu[1], len(aar_liste)))
    logg("  %s %-16s %6s %6s %6s %6s %5s %8s %8s" % ("nr", "fylke", "vann", "20m", "40m", "60m", "drop", "EECU-t", "kumul."))
    tot, kum, kumt = 0, 0.0, []
    for nr in REKKEFOLGE:
        t = tell_fylke(nr, min_ha, maks_ha)
        h = estimat_timer_fra_tall(t, len(aar_liste), vindu)
        kum += h
        tot += t["n"]
        kumt.append((nr, kum))
        logg("  %s %-16s %6d %6d %6d %6d %5d %8.1f %8.1f%s" % (nr, t["navn"], t["n"], t["n20"], t["n40"], t["n60"], t["droppet_n"], h, kum,
                                                            "" if kum <= budsjett_timer else "  (over %.0f t)" % budsjett_timer))
    alle = nve_tell("areal_km2 >= %s" % (min_ha / 100.0))
    logg("  sum fylker %d, hele basen %d (differansen har kommnr utenfor tabellen eller mangler). Hele Norge ca. %.0f EECU-t." % (tot, alle, kum))


# ----------------------------------------------------------------- Norge-planen og kvoteboka
def maaned_no():
    return dt.date.today().strftime("%Y-%m")


def les_plan():
    if os.path.exists(PLAN):
        return json.load(io.open(PLAN, encoding="utf-8"))
    return None


def skriv_plan(plan):
    json.dump(plan, io.open(PLAN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def kvotebok(plan, budsjett_timer):
    """Kvoteboka i planen: estimert forbruk per kalendermåned (GEE-kvoten nullstilles den 1.).
    Returnerer budsjett-objektet som hent_alle bruker; «lagre» skriver planen."""
    k = plan.setdefault("kvote", {})
    if k.get("maaned") != maaned_no():
        if k.get("maaned"):
            k.setdefault("historikk", []).append({"maaned": k["maaned"], "brukt_timer_estimat": round(k.get("brukt_sek", 0) / 3600, 2)})
        k["maaned"] = maaned_no()
        k["brukt_sek"] = 0.0
    k["budsjett_timer"] = budsjett_timer
    k["eecu_sek_per_vannaar_20m"] = EECU_SEK_20M
    k["merknad"] = ("Estimat, ikke avlest: %.0f EECU-s per vann-år på 20 m (vindu 03-01–07-16), skalert med (20/piksel)^2 og vinduslengde. "
                    "Stians eget forbruk før 11. okt 2026 (39,23 %% = 58,8 t) ligger IKKE her." % EECU_SEK_20M)

    def lagre(b):
        k["brukt_sek"] = round(b["brukt_sek"], 1)
        k["brukt_timer_estimat"] = round(b["brukt_sek"] / 3600, 2)
        skriv_plan(plan)
    b = {"timer": budsjett_timer, "brukt_sek": float(k.get("brukt_sek", 0.0)), "lagre": lagre}
    lagre(b)
    return b


def lag_plan(min_ha, maks_ha, aar_liste, vindu, budsjett_timer, kvote=None):
    logg("Lager norge_plan.json: teller vann per fylke i NVE ...")
    fylker = []
    for nr in REKKEFOLGE:
        t = tell_fylke(nr, min_ha, maks_ha)
        t.update({"status": "venter", "estimat_timer_nve": round(estimat_timer_fra_tall(t, len(aar_liste), vindu), 2)})
        fylker.append(t)
        logg("  %s %-16s %5d vann, %d droppes (> %.0f ha), estimat %.1f EECU-t" % (nr, t["navn"], t["n"], t["droppet_n"], maks_ha, t["estimat_timer_nve"]))
    plan = {"opprettet": dt.datetime.now().isoformat(timespec="seconds"), "min_ha": min_ha, "maks_ha": maks_ha,
            "aar": [aar_liste[0], aar_liste[-1]], "vindu": list(vindu), "piksel": "20 m <= 150 ha, 40 m 150-600 ha, 60 m > 600 ha",
            "rekkefolge": REKKEFOLGE, "fylker": fylker}
    if kvote:
        plan["kvote"] = kvote           # kvoteboka kan være eldre enn planen (andre kjøringer teller også)
    kvotebok(plan, budsjett_timer)
    skriv_plan(plan)
    return plan


def klasse_fordeling(res):
    f = {"A": 0, "B": 0, "C": 0, "X": 0}
    for v in res.values():
        for p in v["aar"].values():
            f[p["klasse"]] = f.get(p["klasse"], 0) + 1
    return f


def rapport_norge(plan):
    k = plan.get("kvote", {})
    L = ["# Isgang for hele Norge i GEE (g2) — framdrift per fylke\n",
         "Oppdatert %s. Vindu %s–%s, %d–%d, vann >= %.0f ha, vann over %.0f ha droppet. Piksel %s. "
         "Referansenettets vann-år (644 vann, 20 m, vindu 03-01–07-16) beholdes uendret; vann som alt lå inne for alle årene hentes ikke på nytt.\n"
         % (dt.datetime.now().isoformat(timespec="minutes"), plan["vindu"][0], plan["vindu"][1], plan["aar"][0], plan["aar"][1],
            plan["min_ha"], plan["maks_ha"], plan["piksel"]),
         "Kvote denne måneden (%s): brukt **%.1f EECU-t (estimat)** av budsjett %.0f t. %s\n" % (
             k.get("maaned", "?"), k.get("brukt_sek", 0) / 3600, k.get("budsjett_timer", 0), k.get("merknad", "")),
         "| nr | Fylke | Status | Vann NVE | Droppet > maks | Alt i datasettet | I kjøringen | Vann-år komplette / i alt | A | B | C | X | Estimat EECU-t (NVE) | Brukt EECU-t (estimat) | Start | Slutt |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    sum_est, sum_brukt = 0.0, 0.0
    for f in plan["fylker"]:
        kl = f.get("klasse", {})
        sum_est += f.get("estimat_timer_nve", 0)
        sum_brukt += f.get("brukt_timer_estimat", 0)
        L.append("| %s | %s | %s | %d | %d | %s | %s | %s | %s | %s | %s | %s | %.1f | %s | %s | %s |" % (
            f["nr"], f["navn"], f["status"], f["n"], f["droppet_n"], f.get("hoppet_over", ""), f.get("vann_i_kjoring", ""),
            "%s / %s" % (f.get("vannaar_komplett", ""), f.get("vannaar", "")) if f.get("vannaar") else "",
            kl.get("A", ""), kl.get("B", ""), kl.get("C", ""), kl.get("X", ""), f.get("estimat_timer_nve", 0),
            "%.1f" % f["brukt_timer_estimat"] if f.get("brukt_timer_estimat") is not None else "", f.get("start", "")[:16], f.get("slutt", "")[:16]))
    L.append("| | **Sum** | | %d | %d | | | | | | | | %.1f | %.1f | | |" % (
        sum(f["n"] for f in plan["fylker"]), sum(f["droppet_n"] for f in plan["fylker"]), sum_est, sum_brukt))
    dr = [(f["navn"], d) for f in plan["fylker"] for d in f.get("droppet", [])]
    if dr:
        L += ["", "Droppede vann (> %.0f ha):" % plan["maks_ha"], "", "| Fylke | vatnLnr | Navn | ha |", "|---|---|---|---|"]
        L += ["| %s | %s | %s | %.0f |" % (fy, d["vatnlnr"], d["navn"], d["areal_ha"]) for fy, d in dr]
    rest = [f for f in plan["fylker"] if f["status"] != "ferdig"]
    L += ["", "Lageret (fra 11. okt 2026): én fil per fylke i `norge/isgang_<fylkesnr>_<navn>.json` og `.csv` (samme skjema som "
          "det gamle `isgang_norge.json/.csv`; grensesjøer uten kommnr i `isgang_00_uten_fylke`), pluss den lette samlefila "
          "`isgang_norge_index.csv` (vatnLnr, navn, fylke, aar, status, lo, hi, midt, bredde_d, klasse — uten passlista). "
          "**Kartet og modellen leser `isgang_norge_index.csv`.** Den oppdateres etter hvert fylke; bygg den på nytt med "
          "`python g2_gee_norge.py --samle` (ingen innlogging)."]
    L += ["", "Gjenstår: %s (ca. %.0f EECU-t etter NVE-tellingen)." % (
        ", ".join("%s (%s)" % (f["navn"], f["status"]) for f in rest) or "ingenting", sum(f.get("estimat_timer_nve", 0) for f in rest)),
          "", "Gjenoppta (fra tools\\research_analyser\\G_gee): `python g2_gee_norge.py --norge --fortsett --parallell 4 --budsjett-timer %.0f`. "
          "Kvoteboka nullstilles automatisk når kalendermåneden skifter." % k.get("budsjett_timer", BUDSJETT_TIMER)]
    io.open(RAPPORT_NORGE, "w", encoding="utf-8").write("\n".join(L) + "\n")


def kjor_norge(a, valg, aar_liste, vindu, proj):
    """Fylke for fylke etter norge_plan.json. Hopper over «ferdig»; «venter»/«kjører»/«delvis» tas i rekkefølge.
    Rådata per fylke gjenopptas alltid (data/serier_fylke_NN.csv). Stopper når kvotevakten slår til."""
    plan = les_plan()
    if plan is None or not plan.get("fylker"):
        plan = lag_plan(a.min_ha, a.maks_ha, aar_liste, vindu, a.budsjett_timer, (plan or {}).get("kvote"))
    elif not a.fortsett:
        logg("norge_plan.json finnes alt; --norge uten --fortsett bruker den likevel (slett fila for å planlegge på nytt).")
    krev_migrert()
    budsjett = kvotebok(plan, a.budsjett_timer)
    rapport_norge(plan)
    ee = None
    for f in plan["fylker"]:
        if f["status"] == "ferdig":
            continue
        if tid_ute():
            logg("TIDSVAKT: fristen er passert før fylke %s %s ble startet. Gjenopptas med --norge --fortsett." % (f["nr"], f["navn"]))
            return 4
        if budsjett["brukt_sek"] >= budsjett["timer"] * 3600:
            logg("KVOTEVAKT: budsjettet (%.0f t) er brukt opp for %s (estimat %.1f t). Neste fylke: %s %s." % (
                budsjett["timer"], budsjett.get("maaned", maaned_no()), budsjett["brukt_sek"] / 3600, f["nr"], f["navn"]))
            break
        nr = f["nr"]
        logg("\n=== Fylke %s %s (%s) ===" % (nr, f["navn"], f["status"]))
        vann = vann_fylke(nr, a.min_ha)
        droppet = [v for v in vann if (v["areal_ha"] or 0) > a.maks_ha]
        vann = [v for v in vann if (v["areal_ha"] or 0) <= a.maks_ha]
        for d in droppet:
            logg("  dropper %s (%s), %.0f ha > %.0f" % (d["navn"] or "(uten navn)", d["vatnlnr"], d["areal_ha"], a.maks_ha))
        i_store = nokler_fylke(nr)          # vann-år som alt ligger i fylkesfila (referansenettet, tidligere kjøringer)
        hoppet = [v for v in vann if all((v["vatnlnr"], y) in i_store for y in aar_liste)]
        if hoppet:
            logg("  %d vann ligger alt i %s for alle år (referansenettet) og hentes ikke på nytt." % (len(hoppet), os.path.basename(fylkesfil(nr))))
        vann = [v for v in vann if not all((v["vatnlnr"], y) in i_store for y in aar_liste)]
        f.update({"status": "kjører", "start": f.get("start") or dt.datetime.now().isoformat(timespec="seconds"),
                  "droppet": [{"vatnlnr": d["vatnlnr"], "navn": d["navn"], "areal_ha": d["areal_ha"]} for d in droppet],
                  "hoppet_over": len(hoppet), "vann_i_kjoring": len(vann), "vannaar": len(vann) * len(aar_liste),
                  "estimat_timer_liste": round(kost_estimat_sek(vann, len(aar_liste), vindu) / 3600, 2)})
        skriv_plan(plan)
        if not vann:
            f.update({"status": "ferdig", "slutt": dt.datetime.now().isoformat(timespec="seconds"), "vannaar_komplett": 0, "klasse": {}})
            skriv_plan(plan)
            rapport_norge(plan)
            continue
        if ee is None:
            ee = ee_init(proj)
            logg("Earth Engine klar (prosjekt %s)." % (proj or os.environ.get("GEE_PROJECT")))
        brukt_for = budsjett["brukt_sek"]
        post = hent_alle(ee, "fylke_%s" % nr, vann, aar_liste, vindu, valg, True, max(1, a.parallell), budsjett)
        post["parallell"] = max(1, a.parallell)
        post["fylke"] = nr
        serier = les_raa("fylke_%s" % nr)
        res = bygg_resultat(vann, serier, aar_liste, valg, post["komplett"])
        nye = oppdater_store(res, valg, vindu, post, behold_eksisterende=True)
        kl = klasse_fordeling(res)
        hel = (len(post["komplett"]) >= len(vann) * len(aar_liste) and not post["stoppet_budsjett"] and not post["stoppet_tid"]
               and post["enheter_feilet"] == 0)
        f.update({"status": "ferdig" if hel else "delvis", "vannaar_komplett": len(post["komplett"]), "klasse": kl,
                  "brukt_timer_estimat": round(f.get("brukt_timer_estimat", 0) + (budsjett["brukt_sek"] - brukt_for) / 3600, 2),
                  "nye_vannaar_i_datasettet": f.get("nye_vannaar_i_datasettet", 0) + nye, "enheter_feilet": post["enheter_feilet"],
                  "slutt": dt.datetime.now().isoformat(timespec="seconds") if hel else ""})
        skriv_plan(plan)
        rapport_norge(plan)
        logg("Fylke %s %s: %s. Vann-år komplette %d/%d, klasse A %d B %d C %d X %d." % (
            nr, f["navn"], f["status"], len(post["komplett"]), len(vann) * len(aar_liste), kl["A"], kl["B"], kl["C"], kl["X"]))
        if post["stoppet_budsjett"]:
            logg("\nSTOPPET AV KVOTEVAKTEN: %.1f av %.0f EECU-t (estimat) brukt i %s. Fylke %s %s er «delvis». Gjenoppta når "
                 "kvoten er nullstilt (1. i måneden): python g2_gee_norge.py --norge --fortsett --parallell %d --budsjett-timer %.0f"
                 % (budsjett["brukt_sek"] / 3600, budsjett["timer"], budsjett.get("maaned", maaned_no()), nr, f["navn"], max(1, a.parallell), budsjett["timer"]))
            return 3
        if post["stoppet_tid"]:
            logg("\nSTOPPET AV TIDSVAKTEN (--maks-minutter). Fylke %s %s er «delvis»; framdrift og rådata er lagret per enhet. "
                 "Gjenoppta: python g2_gee_norge.py --norge --fortsett --parallell %d --budsjett-timer %.0f" % (
                     nr, f["navn"], max(1, a.parallell), budsjett["timer"]))
            return 4
        if post["enheter_feilet"]:
            logg("Fylke %s har %d enheter som feilet; status «delvis». Kjør --norge --fortsett igjen for å prøve dem på nytt." % (nr, post["enheter_feilet"]))
    rest = [f for f in plan["fylker"] if f["status"] != "ferdig"]
    logg("\nNorge-kjøringen: %d av %d fylker ferdige. %s" % (len(plan["fylker"]) - len(rest), len(plan["fylker"]),
                                                            "Gjenstår: " + ", ".join(f["navn"] for f in rest) if rest else "Alt ferdig."))
    return 0


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--torr", action="store_true")
    ap.add_argument("--port", action="store_true")
    ap.add_argument("--referansenett", action="store_true")
    ap.add_argument("--fylke")
    ap.add_argument("--omrade", help="lon0,lat0,lon1,lat1")
    ap.add_argument("--vatnlnr", help="kommaskilt")
    ap.add_argument("--norge", action="store_true", help="hele Norge fylke for fylke etter norge_plan.json")
    ap.add_argument("--tell", action="store_true")
    ap.add_argument("--eecu", action="store_true")
    ap.add_argument("--samle", action="store_true", help="bygg isgang_norge_index.csv på nytt fra fylkesfilene i norge/")
    ap.add_argument("--migrer-fylker", action="store_true", help="engangs: del det gamle isgang_norge.json i fylkesfiler")
    ap.add_argument("--lager", help="mappe for norge/, indexfila og det gamle samlelageret (standard: denne mappa; til testing)")
    ap.add_argument("--fortsett", action="store_true")
    ap.add_argument("--evaluer", action="store_true", help="bare regn fra lagrede rådata")
    ap.add_argument("--aar", default="2017:2026")
    ap.add_argument("--vindu", default="%s:%s" % VINDU, help="MM-DD:MM-DD, slutt eksklusiv")
    ap.add_argument("--min-ha", type=float, default=MIN_HA)
    ap.add_argument("--maks-ha", type=float, default=None,
                    help="dropp vann over dette i ha (standard %.0f for --norge/--fylke/--omrade, ingen grense ellers; 0 = ingen grense)" % MAKS_HA)
    ap.add_argument("--budsjett-timer", type=float, default=BUDSJETT_TIMER, help="kvotevakt: stopp når estimert EECU for måneden passerer dette")
    ap.add_argument("--piksel-fast", type=int, default=None, help="bruk denne pikselstørrelsen for alle vann (0 = etter areal; --port bruker 20 om ikke satt)")
    ap.add_argument("--navn", help="kjøringsnavn (rådata i data/serier_<navn>.csv)")
    ap.add_argument("--maks-vann", type=int, default=0, help="bare de N første vannene (prøve)")
    ap.add_argument("--parallell", type=int, default=1, help="samtidige kall til GEE (1–8; GEE tillater 40)")
    ap.add_argument("--project")
    ap.add_argument("--maks-minutter", type=float, default=MAKS_MINUTTER,
                    help="tidsvakt: send ingen nye enheter etter så mange minutter (standard %d, 0 = ingen grense)" % MAKS_MINUTTER)
    a = ap.parse_args()

    valg = g1.les_valg()
    vindu = tuple(a.vindu.split(":"))
    a0, a1 = (int(x) for x in a.aar.split(":"))
    aar_liste = list(range(a0, a1 + 1))
    proj = g1.prosjekt(a.project) or os.environ.get("GEE_PROJECT") or None
    if a.maks_minutter and a.maks_minutter > 0:
        FRIST[0] = time.time() + a.maks_minutter * 60
    if a.maks_ha is None:
        a.maks_ha = MAKS_HA if (a.norge or a.fylke or a.omrade) else 0
    if a.piksel_fast is None:
        a.piksel_fast = 20 if a.port else 0     # g1 regnet på 20 m; porten sammenligner pass for pass

    if a.lager:
        sett_lager(a.lager)
        logg("Lager: %s" % os.path.dirname(INDEX_CSV))
    if a.tell:
        return tell(a.min_ha, a.maks_ha or MAKS_HA, aar_liste, vindu, a.budsjett_timer)
    if a.migrer_fylker:
        n_for, n_etter = migrer_fylker(valg, vindu)
        return 0 if n_for is None or n_etter >= n_for else 2
    if a.samle:
        samle()
        return 0
    if a.norge:
        return kjor_norge(a, valg, aar_liste, vindu, proj)
    if a.eecu:
        now = dt.datetime.now(dt.timezone.utc)
        _, m = eecu(proj, (now - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"), now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        logg(m)
        return 0

    if a.port:
        vann, navn = vann_port(), a.navn or "port_nordmarka"
    elif a.referansenett:
        vann, navn = vann_referansenett(), a.navn or "referansenett"
    elif a.fylke:
        vann, navn = vann_fylke(a.fylke, a.min_ha), a.navn or "fylke_%s" % a.fylke
    elif a.omrade:
        bbox = [float(x) for x in a.omrade.split(",")]
        vann = vann_omrade(bbox, a.min_ha)
        navn = a.navn or "omrade_%s" % "_".join(str(b).replace(".", "p") for b in bbox)
    elif a.vatnlnr:
        liste = [int(x) for x in a.vatnlnr.split(",")]
        vann, navn = vann_lnr(liste), a.navn or "lnr"
    else:
        ap.print_help()
        return 1
    if a.maks_ha:
        for v in vann:
            if (v["areal_ha"] or 0) > a.maks_ha:
                logg("  dropper %s (%s), %.0f ha > %.0f" % (v["navn"] or "(uten navn)", v["vatnlnr"], v["areal_ha"], a.maks_ha))
        vann = [v for v in vann if (v["areal_ha"] or 0) <= a.maks_ha]
    if a.maks_vann:
        vann = vann[:a.maks_vann]
    if a.torr:
        rt = ruter(vann, a.piksel_fast)
        logg("Tørrkjøring: %d vann, %d ruter, %d biter × %d år = %d enheter. Metode tv=%.2f tn=%.1f regel=%s. Vindu %s–%s. "
             "Kost-estimat %.1f EECU-t." % (len(vann), len(rt), len(g1._maanedsbiter(vindu)), len(aar_liste),
                                           len(rt) * len(aar_liste) * len(g1._maanedsbiter(vindu)), valg["tv"], valg["tn"], valg["regel"],
                                           vindu[0], vindu[1], kost_estimat_sek(vann, len(aar_liste), vindu) / 3600))
        for r in rt:
            logg("  %s: %d vann, %d m, %d hjørner" % (r["id"], len(r["vann"]), r["skala"], sum(v["hjorner"] for v in r["vann"])))
        return 0

    kjoring = None
    if not a.evaluer:
        ee = ee_init(proj)
        logg("Earth Engine klar (prosjekt %s)." % proj)
        plan = les_plan() or {"fylker": []}
        budsjett = kvotebok(plan, a.budsjett_timer)         # alle GEE-kall teller i månedens kvotebok
        kjoring = hent_alle(ee, navn, vann, aar_liste, vindu, valg, a.fortsett, max(1, a.parallell), budsjett, a.piksel_fast)
        kjoring["parallell"] = max(1, a.parallell)
        sum_eecu, m = eecu(proj, kjoring["start_utc"], kjoring["slutt_utc"])
        kjoring["eecu_sek"] = sum_eecu
        kjoring["eecu_melding"] = m
        logg(m)
    else:
        fr = les_fremdrift(navn)
        kjoring = {"naar": dt.date.today().isoformat(), "kall": 0, "sek": 0, "sek_per_vannaar": 0, "vindu": fr.get("vindu")}
        for v in vann:
            v["skala"] = a.piksel_fast or piksel(v.get("areal_ha"))
    serier = les_raa(navn)
    if a.evaluer:
        # Rådata kan være hentet med et videre vindu; et smalere vindu kan regnes om uten ny henting.
        serier = {k: [r for r in v if "%d-%s" % (k[1], vindu[0]) <= r["dato"] < "%d-%s" % (k[1], vindu[1])] for k, v in serier.items()}
    komplett = kjoring.get("komplett") if kjoring.get("stoppet_budsjett") or kjoring.get("stoppet_tid") or kjoring.get("enheter_feilet") else None
    res = bygg_resultat(vann, serier, aar_liste, valg, komplett)

    if a.port:
        suffiks = "" if navn == "port_nordmarka" else "_" + navn
        ok, n_id, n_avvik = kvalitetsport(vann, serier, aar_liste, vindu, valg, kjoring,
                                          ("kvalitetsport%s.md" % suffiks) if not a.evaluer else "kvalitetsport_vindu_%s_%s%s.md" % (vindu + (suffiks,)))
        skriv_csv(os.path.join(HER, "kvalitetsport_nordmarka%s.csv" % suffiks), res)
        json.dump(res, io.open(os.path.join(HER, "kvalitetsport_nordmarka%s.json" % suffiks), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        logg("Port %s: %d identiske, %d avvik." % ("BESTÅTT" if ok else "IKKE BESTÅTT", n_id, n_avvik))
        return 0 if ok else 2

    oppdater_store(res, valg, vindu, kjoring)
    n_ok = sum(1 for v in res.values() for p in v["aar"].values() if p["status"] == "ok")
    logg("%s: %d vann, %d vann-år, %d med intervall." % (navn, len(res), sum(len(v["aar"]) for v in res.values()), n_ok))
    if a.referansenett:
        L = ["# Referansenettet i GEE (g2) mot Copernicus (referansenett_isgang.json)\n",
             "Kjørt %s. %d vann, %d–%d, vindu %s–%s. Kall %d, klokketid %.1f min, %.2f s per vann-år. %s\n" % (
                 kjoring["naar"][:10], len(res), aar_liste[0], aar_liste[-1], vindu[0], vindu[1], kjoring["kall"],
                 kjoring["sek"] / 60, kjoring["sek_per_vannaar"], kjoring.get("eecu_melding", ""))]
        L += sammenlign_referansenett(res, vindu)
        io.open(os.path.join(HER, "rapport_referansenett_g2.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
        logg("\n".join(L[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
