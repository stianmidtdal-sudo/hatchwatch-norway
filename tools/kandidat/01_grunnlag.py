"""
Kandidatmodell (oktober 2026) — steg 1: datagrunnlag.

Spørsmålet: hvor god kan en klekkemodell bli som IKKE trenger lokale
observasjoner, altså en som kan flyttes til et vann ingen har sett på, i Norge
eller i Sverige? Den får bare bruke kilder som finnes overalt:
  - lufttemperatur og snødybde fra et globalt rutenett (ERA5 via open-meteo,
    åpent, ingen nøkkel, dekker Norge og Sverige likt)
  - høyde, bredde, vannets størrelse
  - isgang fra satellitt (2017–) der den finnes

Dette steget bygger tre tabeller i data/:
  steder.json   område -> punkt (lat, lon, moh) for været
  obs.json      klekkeobservasjoner fra klekkeobs_master.csv, klassifisert som
                «start» (direkte dato) eller «senest» (øvre grense: i gang,
                topp, spinnerfall ...). Kun start-fasene er direkte
                sammenlignbare (CLAUDE.md, regel 4).
  vaer/<sted>.json  ERA5 døgnverdier 2003–2026 (hentes én gang)
  isgang.json   isgang per område og år fra dashboard.html (2017–2026) og
                satellitt (tools/isgang)

MODELLEN OG NETTSIDEN RØRES IKKE. Alt her er analyse.
"""
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HER = os.path.dirname(os.path.abspath(__file__))
ROT = os.path.abspath(os.path.join(HER, "..", ".."))
DATA = os.path.join(HER, "data")
VAER = os.path.join(DATA, "vaer")
MASTER = r"C:\Users\stian\OneDrive\Dokumenter\Claude\Projects\Fiske\klekkeobs_master.csv"

# Punkt per område (lat, lon, moh). Lokasjonene i dashboardet bruker sine egne
# koordinater; de andre er satt etter kart (omtrentlig midt i området der
# forum-observasjonene kommer fra). moh = typisk høyde for fiskevannene der.
STEDER = {
    "Kautokeino":           (69.010, 23.040, 307),
    "Østmarka":             (59.700, 11.170, 170),
    "Nordmarka":            (59.940, 10.720, 381),
    "Leira/Nannestad":      (60.220, 11.000, 200),
    "Losbyvassdraget":      (59.900, 10.980, 200),
    "Romeriksåsen":         (60.156, 10.892, 330),
    "Romeriksåsen/Hurdal":  (60.330, 11.050, 330),
    "Mjøsa":                (60.800, 11.000, 123),
    "Trysil":               (61.300, 12.270, 360),
    "Bærumsmarka":          (59.930, 10.500, 250),
    "Røros":                (62.570, 11.390, 628),
    "Rena":                 (61.135, 11.650, 209),
    "Solør (Igletjernet)":  (60.694, 11.764, 200),
    "Blefjell":             (59.750, 9.300, 800),
    "Engeråa/Engerdal":     (61.750, 11.950, 500),
    "Vestfjella":           (59.300, 11.660, 180),
}

# Fase -> «start» (direkte) eller «senest» (øvre grense) eller None (ubrukelig)
def fase_klasse(f):
    f = (f or "").strip().lower()
    if not f or f.startswith("negativ") or f.startswith("sverming") or f.startswith("dårlig") \
       or f.startswith("omtalt") or f.startswith("registrert sjelden") or f.startswith("klekking juni") \
       or f.startswith("klekketopp") or f.startswith("klekking i juni") or f.startswith("klekketid"):
        return None
    if f.startswith("start") or f.startswith("første") or f.startswith("knapt") or f == "enkeltindivid" \
       or f.startswith("få individer") or f.startswith("sporadisk") or f.startswith("tidligste") \
       or f.startswith("klekking et par timer"):
        return "start"
    if f.startswith("i gang") or f.startswith("topp") or f.startswith("spinnerfall") or f.startswith("på hell") \
       or f.startswith("etterslep") or f.startswith("kraftig") or f.startswith("samtidig") or f.startswith("ujevn") \
       or f.startswith("klekking under"):
        return "senest"
    return None


def les_obs():
    r = list(csv.DictReader(io.open(MASTER, encoding="utf-8-sig"), delimiter=";"))
    ut = []
    for x in r:
        if x["type"] != "klekkeobs" or not x["dato"] or len(x["dato"]) < 10:
            continue
        art = x["art"].strip().lower()
        if art not in ("vulgata", "marginata", "vespertina", "marginata/vespertina", "danica"):
            continue
        kl = fase_klasse(x["fase"])
        if not kl:
            continue
        omr = x["vassdrag_omrade"].strip()
        if omr not in STEDER:
            continue
        moh = None
        if x["moh_ca"].strip():
            m = re.search(r"\d+", x["moh_ca"])
            moh = int(m.group()) if m else None
        if moh is None:
            m = re.search(r"(\d{3})\s*moh", x["lokalitet"])
            moh = int(m.group(1)) if m else None
        ut.append({"id": x["obs_id"], "art": art, "dato": x["dato"], "aar": int(x["dato"][:4]),
                   "klasse": kl, "fase": x["fase"], "omr": omr, "lok": x["lokalitet"],
                   "moh": moh if moh is not None else STEDER[omr][2], "kilde": x["kilde_niva"],
                   "presisjon": x["dato_presisjon"], "duplikat": x["duplikat_kandidat"]})
    return ut


def hent_vaer(navn, lat, lon, start="2002-10-01", slutt="2026-09-30"):
    os.makedirs(VAER, exist_ok=True)
    sti = os.path.join(VAER, re.sub(r"[^a-z0-9]+", "_", navn.lower()) + ".json")
    if os.path.exists(sti):
        return json.load(io.open(sti, encoding="utf-8"))
    p = dict(latitude=lat, longitude=lon, start_date=start, end_date=slutt,
             daily="temperature_2m_mean,temperature_2m_max,temperature_2m_min,snow_depth_max,precipitation_sum",
             timezone="Europe/Oslo")
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(p)
    # open-meteo har en timekvote; ved 429 venter vi lenge heller enn å gi opp
    for i in range(30):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                j = json.load(r)
            break
        except Exception as e:
            if "429" in str(e):
                print("  værkvote brukt opp, venter 3 min (%s)" % navn, flush=True)
                time.sleep(180)
            else:
                print("  venter (%s)" % e, flush=True)
                time.sleep(15)
    else:
        raise SystemExit("Fikk ikke vær for " + navn)
    d = j["daily"]
    ut = {"elevation": j.get("elevation"), "lat": j.get("latitude"), "lon": j.get("longitude"),
          "dager": {t: {"tm": d["temperature_2m_mean"][i], "tx": d["temperature_2m_max"][i],
                        "tn": d["temperature_2m_min"][i], "sn": d["snow_depth_max"][i], "rr": d["precipitation_sum"][i]}
                    for i, t in enumerate(d["time"])}}
    json.dump(ut, io.open(sti, "w", encoding="utf-8"))
    return ut


def isgang_fra_dashboard():
    """Leser isgangHistory per lokasjon (og per vann for nordmarka_dyn)."""
    html = io.open(os.path.join(ROT, "dashboard.html"), encoding="utf-8").read()
    start = html.index("const LOCATIONS = {")
    blokk = html[start:html.index("\n};", start)]
    ut = {}
    for m in re.finditer(r"\n    ([a-z_]+): \{\n(.*?)(?=\n    [a-z_]+: \{\n|\Z)", blokk, re.S):
        lid, kropp = m.group(1), m.group(2)
        # per-vann (nordmarka_dyn)
        for v in re.finditer(r"name: '([^']+)',\s+altitude: (\d+), isgangHistory: \{(.*?)\}", kropp, re.S):
            navn, alt, hist = v.group(1), int(v.group(2)), v.group(3)
            ut["%s/%s" % (lid, navn)] = {"moh": alt, "aar": {int(y): d for y, d in re.findall(r"(\d{4}): '(\d{4}-\d\d-\d\d)'", hist)}}
        h = re.search(r"isgangHistory: \{(.*?)\n        \}", kropp, re.S)
        if h and "name:" not in h.group(1):
            ut[lid] = {"aar": {int(y): d for y, d in re.findall(r"(\d{4}): '(\d{4}-\d\d-\d\d)'", h.group(1))}}
    return ut


def main():
    os.makedirs(DATA, exist_ok=True)
    obs = les_obs()
    json.dump(obs, io.open(os.path.join(DATA, "obs.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Observasjoner brukbare: %d" % len(obs))
    import collections
    C = collections.Counter
    print("  per art/klasse:", C((o["art"], o["klasse"]) for o in obs))
    print("  per område:", C(o["omr"] for o in obs).most_common())
    print("  start-obs per art/område:", C((o["art"], o["omr"]) for o in obs if o["klasse"] == "start").most_common())
    print("  år med isgang (2017+):", C((o["art"], o["klasse"]) for o in obs if o["aar"] >= 2017))

    json.dump({k: {"lat": v[0], "lon": v[1], "moh": v[2]} for k, v in STEDER.items()},
              io.open(os.path.join(DATA, "steder.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for navn, (lat, lon, moh) in STEDER.items():
        v = hent_vaer(navn, lat, lon)
        print("  vær %-22s rutenett-høyde %5s m (vann %4d m), %d dager" % (navn, v["elevation"], moh, len(v["dager"])))

    isg = isgang_fra_dashboard()
    json.dump(isg, io.open(os.path.join(DATA, "isgang.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Isgang-serier fra dashboardet: %d (%s ...)" % (len(isg), ", ".join(list(isg)[:6])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
