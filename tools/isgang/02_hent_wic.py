"""
Trinn 0, steg 2 — hent is/vann per satellittpass fra Copernicus (krever konto).

Kilde: CLMS HR-WSI «Water and Ice Cover» (WIC), etterfølgeren til RLIE/ARLIE
som ble lagt ned i 2025. Ligger som ferdig klassifisert raster i Copernicus
Data Space Ecosystem (CDSE) og hentes med Sentinel Hub Statistical API:
vi sender inn vannets polygon og får tilbake antall piksler vann / is / sky
per dag. Ingen bilder lastes ned.

  s2    WIC S2     20 m, optisk (Sentinel-2). Skyer gir hull.
  s1s2  WIC S1+S2  20 m, radar + optisk samme dag. Ser gjennom skyer.

Pikselverdier (dokumentert av CDSE): 1 = åpent vann, 100 = is (med eller
uten snø), 205 = sky/skygge, 254 = annet (land), 255 = ingen data,
200 = radarskygge (kun s1s2).

Forutsetning: fila .env i denne mappa med
    CDSE_CLIENT_ID=...
    CDSE_CLIENT_SECRET=...
(se .env.example og LESMEG.md). .env skal aldri deles eller legges ut.

Kjør:
  python 02_hent_wic.py --prov            ett vann, ett år: sjekk at alt virker og hva det koster
  python 02_hent_wic.py                   alle 16 vann, 2017–2026, kilde s2
  python 02_hent_wic.py --kilde begge     også radar+optisk
  python 02_hent_wic.py --torr            bygg forespørslene uten å sende noe (ingen konto nødvendig)

Svarene lagres i data/raa/, og et vann-år som allerede er hentet hentes ikke
på nytt. Det er trygt å avbryte og starte igjen. Forbruk av «processing
units» (PU) logges; gratiskvoten er 10 000 PU per måned.
"""
import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HER = os.path.dirname(os.path.abspath(__file__))
GRUNNLAG = os.path.join(HER, "grunnlag")
DATA = os.path.join(HER, "data")
RAA = os.path.join(DATA, "raa")

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
STAT_URLER = [
    "https://sh.dataspace.copernicus.eu/api/v1/statistics",
    "https://sh.dataspace.copernicus.eu/statistics/v1",       # ny sti fra mars 2026
]
KILDER = {
    "s2":   "byoc-4c770f75-303d-4b8e-bf6d-9ca148b34cfb",   # WIC S2 Europe 20m Daily V1
    "s1s2": "byoc-a0596412-1e04-4530-9e3e-931cf4a3b52e",   # WIC S1+S2 Europe 20m Daily V1
}
SESONG = ("03-01", "07-01")     # vindu 1. mars – 30. juni
AAR = list(range(2017, 2027))

# Hver utgang er 0/1 per piksel, så snittet over polygonet = andelen piksler.
# Piksler uten data (255) holdes utenfor via dataMask.
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["WIC", "dataMask"] }],
    output: [
      { id: "kl", bands: ["vann", "is", "sky", "annet"], sampleType: "UINT8" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  var v = s.WIC;
  var gyldig = (s.dataMask === 1 && v !== 255) ? 1 : 0;
  return {
    kl: [v === 1 ? 1 : 0, v === 100 ? 1 : 0, (v === 205 || v === 200) ? 1 : 0, v === 254 ? 1 : 0],
    dataMask: [gyldig]
  };
}
"""


def les_env():
    """Nøkler fra tools/isgang/.env, ellers fra miljøet (GitHub-hemmeligheter i
    skyjobben). Rettet 2026-10-08: re-innloggingen i send() leste bare .env,
    så skyjobben stoppet etter første utløpte token."""
    ut = {k: os.environ[k] for k in ("CDSE_CLIENT_ID", "CDSE_CLIENT_SECRET") if os.environ.get(k)}
    sti = os.path.join(HER, ".env")
    if not os.path.exists(sti):
        return ut
    for linje in io.open(sti, encoding="utf-8-sig"):
        linje = linje.strip()
        if not linje or linje.startswith("#") or "=" not in linje:
            continue
        k, v = linje.split("=", 1)
        ut[k.strip()] = v.strip().strip('"').strip("'")
    return ut


def hent_token(env):
    cid, sec = env.get("CDSE_CLIENT_ID"), env.get("CDSE_CLIENT_SECRET")
    if not cid or not sec:
        raise SystemExit("Mangler CDSE_CLIENT_ID / CDSE_CLIENT_SECRET i tools/isgang/.env. Se LESMEG.md.")
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials", "client_id": cid, "client_secret": sec,
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=60) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        # Vis aldri hemmeligheten — bare statuskoden og Copernicus sin feiltekst.
        raise SystemExit("Innlogging hos Copernicus feilet (HTTP %s): %s"
                         % (e.code, e.read().decode("utf-8", "replace")[:300]))


def bygg_foresporsel(geom, kilde, aar):
    return {
        "input": {
            "bounds": {
                "geometry": geom,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/32633"},
            },
            "data": [{"type": KILDER[kilde], "dataFilter": {}}],
        },
        "aggregation": {
            "timeRange": {"from": "%d-%sT00:00:00Z" % (aar, SESONG[0]),
                          "to": "%d-%sT00:00:00Z" % (aar, SESONG[1])},
            "aggregationInterval": {"of": "P1D"},
            "evalscript": EVALSCRIPT,
            "resx": 20, "resy": 20,
        },
        "calculations": {"default": {}},
    }


_gjeldende_token = None


def send(token, kropp, forsok=4):
    """Sender én Statistical API-forespørsel. Innloggingen varer én time; ved
    401 logges det inn på nytt og forsøket gjentas, så lange kjøringer ikke
    stopper (lagt til 2026-10-06)."""
    global _gjeldende_token
    if _gjeldende_token is None:
        _gjeldende_token = token
    sist = None
    for url in STAT_URLER:
        for i in range(forsok):
            req = urllib.request.Request(
                url, data=json.dumps(kropp).encode(),
                headers={"Authorization": "Bearer " + _gjeldende_token, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    pu = r.headers.get("x-processingunits-spent")
                    return json.load(r), float(pu) if pu else None
            except urllib.error.HTTPError as e:
                tekst = e.read().decode("utf-8", "replace")[:400]
                sist = "HTTP %s: %s" % (e.code, tekst)
                if e.code == 404:
                    break                      # prøv neste sti
                if e.code == 401 and i < forsok - 1:
                    _gjeldende_token = hent_token(les_env())   # utløpt — logg inn på nytt
                    continue
                if e.code == 429 or e.code >= 500:
                    time.sleep(5 * (i + 1))    # for mange kall / midlertidig feil
                    continue
                raise SystemExit("Copernicus avviste forespørselen. " + sist)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                # nettverksfeil eller lesing som tidsavbrøt mens Copernicus-køen var lang
                sist = str(getattr(e, "reason", e))
                time.sleep(5 * (i + 1))
    raise SystemExit("Fikk ikke svar fra Copernicus. Siste feil: %s" % sist)


def flat_ut(svar):
    """Statistical API-svar → liste av (dato, vann, is, sky, annet, gyldige piksler)."""
    rader = []
    for d in svar.get("data", []):
        dato = d["interval"]["from"][:10]
        b = d.get("outputs", {}).get("kl", {}).get("bands", {})
        if not b:
            continue
        def n(navn):
            st = b.get(navn, {}).get("stats", {})
            gyld = (st.get("sampleCount") or 0) - (st.get("noDataCount") or 0)
            snitt = st.get("mean")
            if gyld <= 0 or snitt is None or snitt != snitt:      # NaN-sjekk
                return 0, 0
            return int(round(snitt * gyld)), gyld
        vann, gyld = n("vann")
        is_, _ = n("is")
        sky, _ = n("sky")
        annet, _ = n("annet")
        if gyld > 0:
            rader.append((dato, vann, is_, sky, annet, gyld))
    return rader


def main():
    ap = argparse.ArgumentParser(description="Hent WIC is/vann-tidsserier per vann fra Copernicus.")
    ap.add_argument("--kilde", choices=["s2", "s1s2", "begge"], default="s2")
    ap.add_argument("--prov", action="store_true", help="Bare første vann og siste år.")
    ap.add_argument("--torr", action="store_true", help="Bygg forespørsler uten å sende.")
    ap.add_argument("--vann", help="Bare dette vannet (navn slik det står i koden).")
    a = ap.parse_args()

    gj = json.load(io.open(os.path.join(GRUNNLAG, "vann.geojson"), encoding="utf-8"))
    vannliste = gj["features"]
    if a.vann:
        vannliste = [f for f in vannliste if f["properties"]["navn"] == a.vann]
        if not vannliste:
            raise SystemExit("Fant ikke vannet «%s» i grunnlag/vann.geojson." % a.vann)
    kilder = ["s2", "s1s2"] if a.kilde == "begge" else [a.kilde]
    aar = AAR
    if a.prov:
        vannliste, aar = vannliste[:1], AAR[-1:]

    if a.torr:
        f = vannliste[0]
        kropp = bygg_foresporsel(f["geometry"], kilder[0], aar[-1])
        ring = f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon" \
            else f["geometry"]["coordinates"][0][0]
        print("Tørrkjøring: %d vann x %d år x %d kilde(r) = %d forespørsler."
              % (len(vannliste), len(aar), len(kilder), len(vannliste) * len(aar) * len(kilder)))
        print("Eksempel: %s, %s, %d. Polygon med %d punkter. Kropp %d tegn. Ingenting sendt."
              % (f["properties"]["navn"], kilder[0], aar[-1], len(ring), len(json.dumps(kropp))))
        return 0

    token = hent_token(les_env())
    print("Logget inn hos Copernicus.")
    pu_sum, nye, hoppet = 0.0, 0, 0
    for kilde in kilder:
        os.makedirs(os.path.join(RAA, kilde), exist_ok=True)
        for f in vannliste:
            pr = f["properties"]
            for y in aar:
                sti = os.path.join(RAA, kilde, "%s_%d.json" % (pr["vatnlnr"], y))
                if os.path.exists(sti):
                    hoppet += 1
                    continue
                svar, pu = send(token, bygg_foresporsel(f["geometry"], kilde, y))
                json.dump(svar, io.open(sti, "w", encoding="utf-8"))
                nye += 1
                pu_sum += pu or 0
                print("  %-5s %-22s %d: %3d dager med data%s"
                      % (kilde, pr["navn"], y, len(flat_ut(svar)),
                         "  (%.2f PU)" % pu if pu is not None else ""))
    print("Hentet %d nye vann-år, %d lå allerede lagret. Forbruk denne kjøringen: %.1f PU."
          % (nye, hoppet, pu_sum))
    if a.prov and nye:
        fullt = len(gj["features"]) * len(AAR)
        print("Anslag for full kjøring (%d vann-år, én kilde): ca. %.0f PU av 10 000 per måned."
              % (fullt, pu_sum / nye * fullt))

    # Samle alt som ligger lagret til én CSV.
    os.makedirs(DATA, exist_ok=True)
    ut = os.path.join(DATA, "wic_tidsserie.csv")
    per_lnr = {f["properties"]["vatnlnr"]: f["properties"]["navn"] for f in gj["features"]}
    antall = 0
    with io.open(ut, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["kilde", "vann", "vatnlnr", "aar", "dato", "vann_px", "is_px", "sky_px", "annet_px", "gyldige_px"])
        for kilde in sorted(KILDER):
            mappe = os.path.join(RAA, kilde)
            if not os.path.isdir(mappe):
                continue
            for fil in sorted(os.listdir(mappe)):
                lnr, y = fil[:-5].split("_")
                svar = json.load(io.open(os.path.join(mappe, fil), encoding="utf-8"))
                for rad in flat_ut(svar):
                    w.writerow([kilde, per_lnr.get(int(lnr), lnr), lnr, y] + list(rad))
                    antall += 1
    print("Skrevet data/wic_tidsserie.csv (%d rader)." % antall)
    return 0


if __name__ == "__main__":
    sys.exit(main())
