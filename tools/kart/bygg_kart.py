# -*- coding: utf-8 -*-
"""
Bygger kartdata for det nye HatchWatch-kartet (MapLibre).

  python tools/kart/bygg_kart.py            # alt: isgang, arter, elver, kartfliser
  python tools/kart/bygg_kart.py isgang     # bare isgangfilene (rask, kjør når skyjobben har levert mer)
  python tools/kart/bygg_kart.py arter      # bare artsfunn per vann
  python tools/kart/bygg_kart.py elver      # bare elvedata (laksesidene)
  python tools/kart/bygg_kart.py vann       # bare vannsidene (isgang + arter per vann; kjøres også av isgang/arter)
  python tools/kart/bygg_kart.py dybde      # bare dybdekart-tabellen fra NVE (data/kart/dybde.json)
  python tools/kart/bygg_kart.py finland    # finske vann (bygg_finland.py): fi/vann/*.json, fi/navn.json, finland.pmtiles
                                            # («finland-vann» = bare JSON-filene, sekunder)
  python tools/kart/bygg_kart.py isgang-lokal  # GitHub-jobben isgang-gee: fylkesfilene fra disk, bytter bare isgangen
                                               # i vannfilene (ingen geojson/shapely). Jobben EIER isgang_*.json og
                                               # vann/*.json i repoet; deploy_now.py laster dem bare opp første gang.

Utdata i data/kart/ (lastes opp av deploy_now.py):
  arter.json          — {vatnlnr: [[navn, gruppe, funn, siste_år, sikker], ...]} artsbestemte
                        døgn-/vårfluer m.m. koblet til vannet (GBIF/Artsdatabanken, rapport I).
  elver.json          — alle lakseførende elver (Miljødirektoratet) + for de 30 analyserte:
                        normalkurve per uke, beste vannføring/vanntemp, barometerstatus.
                        BARE aggregerte tall — rådata blir aldri lagt her.
  hatchwatch.pmtiles  — kartfliser: lag «vann» (alle NVE-vann >= 10 ha, samme liste som
                        isgangjobben) og lag «laks» (lakseførende strekninger, hele Norge).
  isgang_<år>.json    — {vatnlnr: [midt-dag-i-året, bredde_dager, klasse]} per år.
                        Ligger UTENFOR kartflisene med vilje: nye isgangdata krever bare at
                        denne delen kjøres på nytt, ikke at flisene bygges om.
  isgang_meta.json    — år, antall vann med data, kilde, tidspunkt.

Kilder:
  Vann:    tools/research_analyser/I_arter_per_vann/raa/nve_innsjoer_10ha.geojson
           (NVE Innsjødatabase2 lag 5, areal >= 0,10 km², 19 188 vann)
  Isgang:  GitHub-repoet, tools/research_analyser/G_gee/norge/lett/isgang_*.csv
           (skrives av Google Earth Engine-jobben; leses herfra så vi alltid får siste versjon)
  Laks:    Miljødirektoratet, anadrome_laksefisk/MapServer/4 (anadrome strekninger)

Avhengigheter: pip install shapely mapbox-vector-tile pmtiles mercantile
Innført 2026-10-14.
"""
import collections, csv, datetime, gzip, io, json, math, os, sys, time, urllib.parse, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "data", "kart")
VANN_SRC = os.path.join(ROOT, "tools", "research_analyser", "I_arter_per_vann", "raa", "nve_innsjoer_10ha.geojson")
ARTER_SRC = os.path.join(ROOT, "tools", "research_analyser", "I_arter_per_vann", "arter_per_vann.csv")
LAKS_DIR = os.path.join(ROOT, "..", "laksedata")          # utenfor repoet med vilje
GH_API = "https://api.github.com/repos/stianmidtdal-sudo/hatchwatch-norway/contents/tools/research_analyser/G_gee/norge/lett"
LAKS_URL = "https://kart.miljodirektoratet.no/arcgis/rest/services/anadrome_laksefisk/MapServer/4/query"
UA = {"User-Agent": "hatchwatch.no kartbygg"}
os.makedirs(OUT, exist_ok=True)


def gh_token():
    """Token for det private repoet (2026-10-17): GH_TOKEN/GITHUB_TOKEN i jobben, ellers «GitHub token.txt» på PC-en.
    Sendes bare til GitHub, aldri til de andre kildene."""
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if t:
        return t.strip()
    fil = os.path.join(ROOT, "GitHub token.txt")
    if os.path.exists(fil):
        with open(fil, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def hent(url, params=None, raw=False):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    hoder = dict(UA)
    if url.startswith(("https://api.github.com/", "https://raw.githubusercontent.com/")):
        t = gh_token()
        if t:
            hoder["Authorization"] = "token " + t
    for forsok in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hoder), timeout=120) as r:
                b = r.read()
                return b if raw else json.loads(b.decode("utf-8"))
        except Exception as e:
            if forsok == 3:
                raise
            time.sleep(2 + forsok * 3)


# ── Isgang ───────────────────────────────────────────────────────────────
LETT_LOKAL = os.path.join(ROOT, "tools", "research_analyser", "G_gee", "norge", "lett")


def bygg_isgang(lokal=False):
    """lokal=True: les fylkesfilene fra repoet på disk (GitHub-jobben isgang-gee, etter --samle).
    Ellers hentes de fra GitHub, så PC-en alltid får siste versjon."""
    if lokal:
        filer = [{"name": fn, "sti": os.path.join(LETT_LOKAL, fn)} for fn in sorted(os.listdir(LETT_LOKAL)) if fn.endswith(".csv")]
    else:
        filer = [f for f in hent(GH_API) if f["name"].endswith(".csv")]
    per_aar, vann_med = {}, set()
    rader = 0
    for f in filer:
        if lokal:
            tekst = open(f["sti"], encoding="utf-8-sig").read()
        else:
            tekst = hent(f["download_url"], raw=True).decode("utf-8-sig")
        for r in csv.DictReader(io.StringIO(tekst), delimiter=";"):
            rader += 1
            if r.get("status") != "ok" or not r.get("midt"):
                continue
            d = datetime.date.fromisoformat(r["midt"])
            doy = d.timetuple().tm_yday
            bredde = int(float(r["bredde_d"])) if r.get("bredde_d") else None
            aar = int(r["aar"])
            per_aar.setdefault(aar, {})[r["vatnLnr"]] = [doy, bredde, r.get("klasse") or ""]
            vann_med.add(r["vatnLnr"])
    # Sperre: færre vann enn før betyr at noe er galt med kildefilene — skriv ingenting
    gammel = os.path.join(OUT, "isgang_meta.json")
    if os.path.exists(gammel):
        før = json.load(open(gammel, encoding="utf-8")).get("vann_med_data", 0)
        if len(vann_med) < 0.95 * før:
            raise SystemExit(f"isgang: bare {len(vann_med)} vann mot {før} før — avbryter uten å skrive (sjekk fylkesfilene)")
    for aar, data in per_aar.items():
        with open(os.path.join(OUT, f"isgang_{aar}.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
    # Ikke tidsstempel i meta: fila skal bare endre seg når dataene gjør det (ellers commit hver 6. time)
    meta = {"aar": sorted(per_aar), "vann_med_data": len(vann_med), "rader_lest": rader,
            "per_aar": {a: len(v) for a, v in sorted(per_aar.items())},
            "kilde": "Sentinel-2 via Google Earth Engine (HatchWatch, låst metode), midt i observert intervall",
            "fylkesfiler": [f["name"] for f in filer]}
    with open(os.path.join(OUT, "isgang_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(f"isgang: {len(vann_med)} vann med minst ett år, {rader} rader lest, år {meta['aar'][0]}–{meta['aar'][-1]}")
    for a, n in meta["per_aar"].items():
        print(f"   {a}: {n} vann")


# ── Artsfunn per vann (GBIF/Artsdatabanken) ──────────────────────────────
GRUPPE_KODE = {"døgnflue": "d", "vårflue": "v", "marflo": "m", "skjoldkreps": "s"}


def bygg_arter():
    per = {}
    with open(ARTER_SRC, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            if r.get("rang") != "art":
                continue
            navn = r["art"]
            norsk = (r.get("norsk_navn") or "").strip()
            per.setdefault(r["vatnLnr"], []).append([
                navn, GRUPPE_KODE.get(r["gruppe"], "a"), int(r["n_funn"] or 0),
                int(r["siste_aar"]) if r.get("siste_aar") else None,
                1 if int(r.get("n_sikre") or 0) > 0 else 0, norsk])
    for k in per:
        per[k].sort(key=lambda x: (x[1], -x[2]))
    with open(os.path.join(OUT, "arter.json"), "w", encoding="utf-8") as fh:
        json.dump(per, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"arter: {len(per)} vann med artsbestemte funn, {os.path.getsize(os.path.join(OUT, 'arter.json')) // 1024} kB")


# ── Elver (laksesidene) ──────────────────────────────────────────────────
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def bygg_elver():
    st = os.path.join(LAKS_DIR, "stasjoner")
    an = os.path.join(LAKS_DIR, "analyse")

    def les(p):
        with open(p, encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh, delimiter=";"))

    elver = {}
    for r in les(os.path.join(st, "mdir_lakseelver.csv")):
        elver[r["vassdragsnr"]] = {
            "id": r["vassdragsnr"], "navn": r["navn"], "nasjonalt": r["nasjonalt_laksevassdrag"] == "Ja",
            "km": _f(r["anadrom_km"]), "kommuner": r["kommuner"],
            "lat": _f(r["utlop_lat"]), "lon": _f(r["utlop_lon"]),
            "lat2": _f(r["ovre_lat"]), "lon2": _f(r["ovre_lon"]),
            "url": r["lakseregister_url"]}

    # 2026-10-14: H_alle_* (analyse_H.py --alle: alle elver i laksedataene, samme låste kriterier) når de
    # finnes, ellers topp-30-filene. Bare elver med fangstkurve (>= 4 normalår og halv-fangst-dato) og som
    # finnes i Lakseregisteret (ellers har vi verken strekning på kartet eller side) tas med.
    pref = "H_alle_" if os.path.exists(os.path.join(an, "H_alle_oversikt_elv.csv")) else "H_"
    oversikt = {r["elv_nokkel"]: r for r in les(os.path.join(an, pref + "oversikt_elv.csv"))
                if r.get("normal_n_aar") and int(r["normal_n_aar"]) >= 4 and r.get("halv_fangst_dato")}
    utenfor = [o["navn"] for k, o in oversikt.items() if k not in elver]
    oversikt = {k: o for k, o in oversikt.items() if k in elver}
    if utenfor:
        print(f"elver: {len(utenfor)} med fangstkurve, men ikke i Lakseregisteret (utelatt): {', '.join(utenfor)}")
    kurver = collections.defaultdict(list)
    for r in les(os.path.join(an, pref + "normalkurve.csv")):
        kurver[r["elv_nokkel"]].append(r)

    for nk, o in oversikt.items():
        e = elver[nk]
        e["fangstnavn"] = o["navn"]
        k = sorted(kurver.get(nk, []), key=lambda r: int(r["uke_2027"]))
        e["kurve"] = {
            "uker": [[int(r["uke_2027"]), r["uke_fra_2027"], r["uke_til_2027"], _f(r["andel_snitt"]),
                      _f(r["andel_p10"]), _f(r["andel_p90"]), _f(r["andel_aar_blant_3_beste_uker"])] for r in k],
            "n_aar": int(o["normal_n_aar"] or 0), "aar": o["normal_aar"], "utvalg": o["normal_utvalg"],
            "halv": o["halv_fangst_dato"], "halv_doy": _f(k[0]["halv_fangst_doy"]) if k else None,
            "bom50": _f(o["bom_1av2_aar_dager"]), "bom90": _f(o["bom_9av10_aar_dager"]),
            "innen7": _f(o["andel_aar_innen_7d"]),
            "tidligst": o["tidligste_halv_dato"], "senest": o["seneste_halv_dato"],
            "beste_uke": int(o["beste_uke_2027"]) if o.get("beste_uke_2027") else None,
            "beste_uke_dato": o["beste_uke_fra_til"], "beste_uke_andel": _f(o["beste_uke_andel"]),
            "beste_uke_topp3": _f(o["beste_uke_blant_3_beste_andel_aar"])}
        e["vann"] = {
            "stasjon": o["q_stasjon"], "kilde": o["q_kilde"],
            "spenn_m3s": o["beste_q_m3s"], "spenn_m3s_forhold": _f(o["beste_q_m3s_forhold"]), "spenn_m3s_status": o["beste_q_m3s_status"],
            "spenn_pst": o["beste_q_prosent"], "spenn_pst_forhold": _f(o["beste_q_prosent_forhold"]), "spenn_pst_status": o["beste_q_prosent_status"],
            "lav_pst": _f(o["lavgrense_prosent"]), "flom_pst": _f(o["flomgrense_prosent"]),
            "lav_m3s": _f(o["lavgrense_m3s"]), "flom_m3s": _f(o["flomgrense_m3s"]),
            "stigende_forhold": _f(o["kraftig_stigende_forhold"]), "synkende_forhold": _f(o["synkende_forhold"])}
        e["temp"] = {"stasjon": o["wt_stasjon"], "kilde": o["wt_kilde"], "spenn": o["beste_wt"],
                     "forhold": _f(o["beste_wt_forhold"]), "status": o["beste_wt_status"], "varm": _f(o["varm_grense_wt"])}
        e["barometer"] = {"status": o["barometer_status"],
                          "groenn": _f(o["tre_nivaa_groenn_forhold"]), "gul": _f(o["tre_nivaa_gul_forhold"]), "roed": _f(o["tre_nivaa_roed_forhold"]),
                          "andel_groenn": _f(o["tre_nivaa_groenn_andel_dager"]), "andel_gul": _f(o["tre_nivaa_gul_andel_dager"]),
                          "andel_roed": _f(o["tre_nivaa_roed_andel_dager"])}
        e["region"] = o["region_E"]
        e["rang"] = int(o["rang"])
    # Fangst per sesong (2026-10-17, Stian): SSBs offisielle elvefangst (tabell 08991, avlivet + gjenutsatt), hentet
    # i laksedata/analyse/M_aarsprognose. Per vassdragsnr og år (summert når SSB deler et vassdrag i flere elver):
    # [år, laks, snittvekt kg, smålaks < 3 kg, mellomlaks 3–7 kg, storlaks >= 7 kg, gjenutsatt]. Siste 15 sesonger.
    ssb_sti = os.path.join(an, "M_aarsprognose", "M_elvaar_ssb.csv")
    ssb_n = 0
    if os.path.exists(ssb_sti):
        sum_ = collections.defaultdict(lambda: [0, 0.0, 0, 0, 0, 0])
        for r in les(ssb_sti):
            if r["vassdragsnr"] not in elver or int(r["aar"]) < 2011:
                continue
            s = sum_[(r["vassdragsnr"], int(r["aar"]))]
            s[0] += int(r["laks"] or 0)
            s[1] += sum(float(r[k] or 0) for k in ("smaa_kg", "mellom_kg", "stor_kg"))
            s[2] += int(r["smaa"] or 0); s[3] += int(r["mellom"] or 0); s[4] += int(r["stor"] or 0)
            s[5] += int(r["laks_gjenutsatt"] or 0)
        per_elv = collections.defaultdict(list)
        for (vnr, aar), s in sorted(sum_.items()):
            n_klasse = s[2] + s[3] + s[4]
            per_elv[vnr].append([aar, s[0], round(s[1] / n_klasse, 1) if n_klasse else None, s[2], s[3], s[4], s[5]])
        for vnr, rader in per_elv.items():
            if any(r[1] for r in rader):
                elver[vnr]["ssb"] = rader; ssb_n += 1
    meta = {"bygget": datetime.datetime.now().isoformat(timespec="seconds"), "elver": len(elver),
            "analysert": len(oversikt), "ssb_fangst": ssb_n,
            "kilde": "Lakseregisteret (Miljødirektoratet) + HatchWatch-analyse H, bare aggregerte tall"}
    with open(os.path.join(OUT, "elver.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "elver": elver}, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"elver: {len(elver)} elver, {len(oversikt)} med fangstkurve, {os.path.getsize(os.path.join(OUT, 'elver.json')) // 1024} kB")


# ── Laks ─────────────────────────────────────────────────────────────────
def hent_laks():
    feats, off = [], 0
    while True:
        js = hent(LAKS_URL, {"where": "1=1", "outFields": "elvenavn,vassdragsNR,nasjonaltLaksevassdrag,lakseregURL",
                             "outSR": 4326, "maxAllowableOffset": 0.00005, "geometryPrecision": 5,
                             "resultOffset": off, "resultRecordCount": 1000, "orderByFields": "OBJECTID", "f": "geojson"})
        b = js.get("features", [])
        feats += b
        if len(b) < 1000:
            break
        off += 1000
    print(f"laks: {len(feats)} strekninger")
    return feats


# ── Kartfliser ───────────────────────────────────────────────────────────
def bygg_fliser(laks):
    import mercantile
    import mapbox_vector_tile
    import shapely
    from shapely.geometry import shape, box
    from shapely.strtree import STRtree
    from pmtiles.writer import Writer
    from pmtiles.tile import zxy_to_tileid, TileType, Compression

    import numpy as np
    R = 6378137.0

    def til_merc(geom):
        # lon/lat → Web Mercator (meter), vektorisert over alle koordinater
        def f(c):
            lat = np.clip(c[:, 1], -85.0511, 85.0511)
            return np.column_stack([R * np.radians(c[:, 0]), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))])
        return shapely.transform(geom, f)

    vann_js = json.load(open(VANN_SRC, encoding="utf-8"))
    vann = []
    for f in vann_js["features"]:
        p = f["properties"]
        g = til_merc(shape(f["geometry"]))
        if not g.is_valid:
            g = g.buffer(0)
        ha = round((p.get("areal_km2") or 0) * 100, 1)
        vann.append((g, {"vatnlnr": int(p["vatnlnr"]), "navn": p.get("navn") or "", "moh": p.get("hoyde"),
                         "ha": ha, "kommune": p.get("kommune") or ""}))
    lakslinjer = []
    for f in laks:
        if not f.get("geometry"):
            continue
        p = f["properties"]
        lakslinjer.append((til_merc(shape(f["geometry"])), {
            "elv": p.get("elvenavn") or "", "vassdrag": p.get("vassdragsNR") or "",
            "nasjonalt": 1 if p.get("nasjonaltLaksevassdrag") == "Ja" else 0, "url": p.get("lakseregURL") or ""}))
    print(f"vann lest: {len(vann)}")
    # Punktlag «vannpunkt» (2026-10-14): ett punkt inne i hvert vann (representative_point av den
    # uforenklede formen). Turkartet viser vannene som prikker i stedet for vår egen vannflate, så
    # Kartverkets strandlinje får stå alene. Fra z8.
    PUNKT_MINZ = 8
    punkter = [(g.representative_point(), {"vatnlnr": p["vatnlnr"], "ha": p["ha"]}) for g, p in vann]
    tre_p = STRtree([g for g, _ in punkter])

    # Hvilke vann som vises på lave zoomnivåer (resten dukker opp når du zoomer inn)
    def min_ha(z):
        return {3: 3000, 4: 1500, 5: 600, 6: 200, 7: 60, 8: 20}.get(z, 0)

    # z3 (2026-10-14): hele Norge får plass på mobil først ved zoom ~3,5, og
    # MapLibre henter ikke fliser under kildens laveste nivå. Laks vises fra z3.
    MINZ, MAXZ = 3, 12
    bounds_ll = (4.0, 57.8, 31.5, 71.3)
    tiles_out = {}
    t0 = time.time()
    for z in range(MINZ, MAXZ + 1):
        tol = (2 * math.pi * R / (256 * 2 ** z)) * 0.6       # ca. 0,6 piksel
        mh = min_ha(z)
        vz = [(g.simplify(tol, preserve_topology=True), p) for g, p in vann if p["ha"] >= mh]
        vz = [(g, p) for g, p in vz if not g.is_empty]
        lz = [(g.simplify(tol, preserve_topology=False), p) for g, p in lakslinjer]
        tre_v = STRtree([g for g, _ in vz]) if vz else None
        tre_l = STRtree([g for g, _ in lz]) if lz else None
        n = 0
        for t in mercantile.tiles(*bounds_ll, zooms=[z]):
            b = mercantile.xy_bounds(t)
            pad = (b.right - b.left) * 8 / 256.0
            tb = box(b.left - pad, b.bottom - pad, b.right + pad, b.top + pad)
            lag = []
            if tre_v is not None:
                idx = tre_v.query(tb, predicate="intersects")
                feats = []
                for i in idx:
                    g, p = vz[i]
                    c = g.intersection(tb)
                    if c.is_empty or c.geom_type not in ("Polygon", "MultiPolygon"):
                        if c.geom_type == "GeometryCollection":
                            polys = [x for x in c.geoms if x.geom_type in ("Polygon", "MultiPolygon")]
                            if not polys:
                                continue
                            c = shapely.union_all(polys)
                        else:
                            continue
                    feats.append({"geometry": c, "properties": p, "id": p["vatnlnr"]})
                if feats:
                    lag.append({"name": "vann", "features": feats})
            if tre_l is not None:
                idx = tre_l.query(tb, predicate="intersects")
                feats = []
                for i in idx:
                    g, p = lz[i]
                    c = g.intersection(tb)
                    if c.is_empty:
                        continue
                    feats.append({"geometry": c, "properties": p})
                if feats:
                    lag.append({"name": "laks", "features": feats})
            if z >= PUNKT_MINZ:
                # bare punkter inne i selve flisa (ikke kantbufferen), så hvert vann får én prikk
                tb0 = box(b.left, b.bottom, b.right, b.top)
                idx = tre_p.query(tb0, predicate="intersects")
                feats = [{"geometry": punkter[i][0], "properties": punkter[i][1], "id": punkter[i][1]["vatnlnr"]} for i in idx]
                if feats:
                    lag.append({"name": "vannpunkt", "features": feats})
            if not lag:
                continue
            data = mapbox_vector_tile.encode(lag, default_options={
                "quantize_bounds": (b.left, b.bottom, b.right, b.top), "extents": 4096, "y_coord_down": False})
            tiles_out[zxy_to_tileid(z, t.x, t.y)] = gzip.compress(data, 9)
            n += 1
        print(f"  z{z}: {n} fliser, {len(vz)} vann  ({time.time() - t0:.0f} s)")

    path = os.path.join(OUT, "hatchwatch.pmtiles")
    with open(path, "wb") as fh:
        w = Writer(fh)
        for tid in sorted(tiles_out):
            w.write_tile(tid, tiles_out[tid])
        w.finalize({
            "tile_type": TileType.MVT, "tile_compression": Compression.GZIP,
            "min_zoom": MINZ, "max_zoom": MAXZ,
            "min_lon_e7": int(bounds_ll[0] * 1e7), "min_lat_e7": int(bounds_ll[1] * 1e7),
            "max_lon_e7": int(bounds_ll[2] * 1e7), "max_lat_e7": int(bounds_ll[3] * 1e7),
            "center_zoom": 5, "center_lon_e7": int(15 * 1e7), "center_lat_e7": int(65 * 1e7),
        }, {
            "name": "HatchWatch vann og laks",
            "attribution": "NVE Innsjødatabase · Miljødirektoratet Lakseregister",
            "vector_layers": [
                {"id": "vann", "fields": {"vatnlnr": "Number", "navn": "String", "moh": "Number", "ha": "Number", "kommune": "String"}, "minzoom": MINZ, "maxzoom": MAXZ},
                {"id": "laks", "fields": {"elv": "String", "vassdrag": "String", "nasjonalt": "Number", "url": "String"}, "minzoom": MINZ, "maxzoom": MAXZ},
                {"id": "vannpunkt", "fields": {"vatnlnr": "Number", "ha": "Number"}, "minzoom": PUNKT_MINZ, "maxzoom": MAXZ},
            ],
        })
    mb = os.path.getsize(path) / 1e6
    print(f"hatchwatch.pmtiles: {len(tiles_out)} fliser, {mb:.1f} MB  ({time.time() - t0:.0f} s)")


# ── Vannsidene (vann.html) ───────────────────────────────────────────────
# 2026-10-14: én liten fil per gruppe av vann, så siden for ett vann laster ~50 kB i stedet for
# alle isgangårene (~2,3 MB). Gruppe = vatnlnr % VANN_GRUPPER (samme regel i vann.html og index.html).
# Bygges av isgangfilene + arter.json i data/kart, så kjør den etter isgang/arter.
VANN_GRUPPER = 64

# Vulgata bekreftet av andre enn Artsdatabanken (2026-10-14): OFAs 16 beste vulgata-vann i Nordmarka
# (samme liste som ofaLakes i dashboard.html). 11 finnes i NVE-lista (>= 10 ha); Gåslungen, Lille
# Åklungen, Blankvann og Auretjern Nord/Sør er under 10 ha og er ikke med på kartet.
BEKREFTET = {vid: {"vulgata": "ofa"} for vid in (5170, 5208, 5140, 5145, 5101, 5094, 4977, 2497, 306, 299, 307)}


def bygg_vann():
    from shapely.geometry import shape
    vann_js = json.load(open(VANN_SRC, encoding="utf-8"))
    isg = {}
    for fn in os.listdir(OUT):
        if fn.startswith("isgang_") and fn[7:11].isdigit():
            isg[int(fn[7:11])] = json.load(open(os.path.join(OUT, fn), encoding="utf-8"))
    arter_p = os.path.join(OUT, "arter.json")
    arter = json.load(open(arter_p, encoding="utf-8")) if os.path.exists(arter_p) else {}
    grupper = [dict() for _ in range(VANN_GRUPPER)]
    for f in vann_js["features"]:
        p = f["properties"]
        vid = int(p["vatnlnr"])
        pt = shape(f["geometry"]).representative_point()
        rec = {"navn": p.get("navn") or "", "moh": p.get("hoyde"), "ha": round((p.get("areal_km2") or 0) * 100, 1),
               "kommune": p.get("kommune") or "", "lat": round(pt.y, 5), "lon": round(pt.x, 5)}
        g = {str(a): d[str(vid)] for a, d in sorted(isg.items()) if str(vid) in d}
        if g:
            rec["isg"] = g
        if str(vid) in arter:
            rec["arter"] = arter[str(vid)]
        if vid in BEKREFTET:
            rec["bekreftet"] = BEKREFTET[vid]
        grupper[vid % VANN_GRUPPER][str(vid)] = rec
    mappe = os.path.join(OUT, "vann")
    os.makedirs(mappe, exist_ok=True)
    tot = 0
    for i, g in enumerate(grupper):
        path = os.path.join(mappe, f"{i}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False, separators=(",", ":"))
        tot += os.path.getsize(path)
    print(f"vann: {len(vann_js['features'])} vann i {VANN_GRUPPER} filer, snitt {tot // VANN_GRUPPER // 1024} kB per fil")


def bygg_sverige(fliser=True):
    """Svenske vann (2026-10-17, Stian: «publiser Sverige allerede nå»). Leser sverige/data (s1–s4) og skriver:
    data/kart/se/vann/<hylak_id % 64>.json  {id: {navn, moh, ha, dyp, lat, lon, arter, fisk}}
        arter = [[latin, gruppe d/v/m/s/a, funn, siste_år, sikker, norsk]] (samme form som norske arter)
        fisk  = [[latin, norsk, funn, siste_år, sikker, 0]] (samme form som data/kart/fisk; norske navn fra de norske filene)
        dyp   = HydroLAKES' beregnede middeldyp (modell, ikke loddet)
    data/kart/sverige.pmtiles  lag vann_se (omriss, id/navn/ha/moh) og vannpunkt_se (ett punkt per vann, z8+).
    Ingen isgang ennå (venter på Earth Engine-kvoten)."""
    import mapbox_vector_tile, mercantile, shapely, shapely.errors, numpy as np
    from shapely.geometry import shape, box
    from shapely.strtree import STRtree
    from pmtiles.writer import Writer
    from pmtiles.tile import zxy_to_tileid, TileType, Compression
    sv = os.path.join(ROOT, "sverige", "data")
    gj = json.load(open(os.path.join(sv, "sjoar_se.geojson"), encoding="utf-8"))
    attr = {int(r["hylak_id"]): r for r in csv.DictReader(open(os.path.join(sv, "sjoar_se.csv"), encoding="utf-8-sig"), delimiter=";")}
    # Norske fiskenavn fra de norske filene (samme arter går igjen)
    norsk = {}
    fdir = os.path.join(OUT, "fisk")
    for fn in (os.listdir(fdir) if os.path.isdir(fdir) else []):
        for liste in json.load(open(os.path.join(fdir, fn), encoding="utf-8")).values():
            for f in liste:
                if f[1]:
                    norsk.setdefault(f[0], f[1])
    # Norske insektnavn fra de norske vannfilene (arter[5], der de finnes)
    vdir = os.path.join(OUT, "vann")
    for fn in (os.listdir(vdir) if os.path.isdir(vdir) else []):
        for v in json.load(open(os.path.join(vdir, fn), encoding="utf-8")).values():
            for a in v.get("arter") or []:
                if len(a) > 5 and a[5]:
                    norsk.setdefault(a[0], a[5])
    ORDEN_KODE = {"Ephemeroptera": "d", "Trichoptera": "v", "Amphipoda": "m", "Notostraca": "s"}
    arter, fisk = collections.defaultdict(list), collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(sv, "arter_per_vann_se.csv"), encoding="utf-8-sig"), delimiter=";"):
        hid, siste = int(r["hylak_id"]), int(r["siste_aar"]) if r["siste_aar"] else None
        if r["gruppe"] == "fisk":
            fisk[hid].append([r["art"], norsk.get(r["art"], ""), int(r["funn"]), siste, int(r["sikker"]), 0])
        else:
            arter[hid].append([r["art"], ORDEN_KODE.get(r["orden"], "a"), int(r["funn"]), siste, int(r["sikker"]), norsk.get(r["art"], "")])
    # Berggrunn (s5_berggrunn.py): SGU-bergart med NGU-kalkklasse 1–5 (0 = ukjent), norsk bergartsnavn
    berg = {}
    bfil = os.path.join(sv, "berggrunn_per_vann_se.csv")
    if os.path.exists(bfil):
        for r in csv.DictReader(open(bfil, encoding="utf-8-sig"), delimiter=";"):
            berg[int(r["hylak_id"])] = [int(r["klasse"]), r["bergart_no"]]
    # Dybdekart hos SMHI (s6_dybdekart.py): SJOID, vi lenker til SMHIs nedlasting
    smhi = {}
    dfil = os.path.join(sv, "smhi_dybdekart_se.csv")
    if os.path.exists(dfil):
        for r in csv.DictReader(open(dfil, encoding="utf-8-sig"), delimiter=";"):
            smhi[int(r["hylak_id"])] = r["sjoid"]
    # Målt isgang fra SMHI (s7_isgang_smhi.py): {"st": målepunkt, "aar": {år: dag i året}}. Flere målepunkter i samme
    # vann: det med flest år fra 1991 (deretter flest år totalt).
    is_smhi = {}
    ifil = os.path.join(sv, "isgang_smhi_se.csv")
    if os.path.exists(ifil):
        per = collections.defaultdict(lambda: collections.defaultdict(dict))
        navn_st = {}
        for r in csv.DictReader(open(ifil, encoding="utf-8-sig"), delimiter=";"):
            per[int(r["hylak_id"])][r["stasjon_id"]][int(r["aar"])] = int(r["dag"])
            navn_st[r["stasjon_id"]] = r["stasjon"]
        for hid, st in per.items():
            sid = max(st, key=lambda s: (sum(1 for y in st[s] if y >= 1991), len(st[s])))
            is_smhi[hid] = {"st": navn_st[sid].title(), "aar": {str(y): d for y, d in sorted(st[sid].items())}}
    grupper = [dict() for _ in range(VANN_GRUPPER)]
    for hid, a in attr.items():
        rec = {"navn": a["navn"] or "", "moh": round(float(a["hoyde_m"])) if a["hoyde_m"] else None, "ha": float(a["areal_ha"]),
               "dyp": round(float(a["middeldyp_m"]), 1) if a["middeldyp_m"] else None, "lat": float(a["lat"]), "lon": float(a["lon"])}
        if hid in berg:
            rec["berg"] = berg[hid]
        if hid in smhi:
            rec["smhi"] = smhi[hid]
        if hid in is_smhi:
            rec["is_smhi"] = is_smhi[hid]
            # SMHIs navn har riktige svenske bokstaver («Tornetrask» → «Torneträsk»), og gir navn til navnløse vann
            # når målepunktet bare heter som sjøen (ett ord; «Allgunnen Lagan» = sjø + elv brukes ikke)
            import unicodedata
            fold = lambda s: "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
            st = is_smhi[hid]["st"]
            if (rec["navn"] and fold(rec["navn"]) == fold(st)) or (not rec["navn"] and " " not in st):
                rec["navn"] = st
        if arter.get(hid):
            rec["arter"] = sorted(arter[hid], key=lambda x: -x[2])
        if fisk.get(hid):
            rec["fisk"] = sorted(fisk[hid], key=lambda x: -x[2])
        grupper[hid % VANN_GRUPPER][str(hid)] = rec
    mappe = os.path.join(OUT, "se", "vann")
    os.makedirs(mappe, exist_ok=True)
    for i, g in enumerate(grupper):
        with open(os.path.join(mappe, f"{i}.json"), "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"sverige: {len(attr)} vann i {VANN_GRUPPER} filer, {sum(1 for h in attr if arter.get(h))} med insekter, {sum(1 for h in attr if fisk.get(h))} med fisk")
    # Søk (2026-10-17): navngitte svenske vann [navn, id, lat·1e4, lon·1e4, ha], størst først
    navn = sorted(([r["navn"], int(hid), round(r["lat"] * 1e4), round(r["lon"] * 1e4), round(r["ha"])]
                   for g in grupper for hid, r in g.items() if r["navn"]), key=lambda x: -x[4])
    with open(os.path.join(OUT, "se", "navn.json"), "w", encoding="utf-8") as fh:
        json.dump(navn, fh, ensure_ascii=False, separators=(",", ":"))
    # Dagboka (2026-10-17): nærmeste svenske vann, samme flate form som vannpunkt.json [id, lat·1e4, lon·1e4, ...]
    flat = []
    for hid, a in attr.items():
        flat += [hid, round(float(a["lat"]) * 1e4), round(float(a["lon"]) * 1e4)]
    with open(os.path.join(OUT, "se", "vannpunkt.json"), "w", encoding="utf-8") as fh:
        json.dump(flat, fh, separators=(",", ":"))
    print(f"  se/navn.json: {len(navn)} navn; se/vannpunkt.json: {len(flat) // 3} vann")
    if not fliser:
        return

    # Kartfliser (samme oppskrift som bygg_fliser, egen fil så den norske ikke må bygges på nytt)
    R = 6378137.0
    def til_merc(geom):
        def f(c):
            lat = np.clip(c[:, 1], -85.0511, 85.0511)
            return np.column_stack([R * np.radians(c[:, 0]), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))])
        return shapely.transform(geom, f)
    vann = []
    for f in gj["features"]:
        hid = f["properties"]["hylak_id"]; a = attr.get(hid)
        if not a:
            continue
        g = til_merc(shape(f["geometry"]))
        if not g.is_valid:
            g = g.buffer(0)
        vann.append((g, {"id": hid, "navn": a["navn"] or "", "ha": float(a["areal_ha"]), "moh": round(float(a["hoyde_m"])) if a["hoyde_m"] else None}))
    PUNKT_MINZ, MINZ, MAXZ = 8, 3, 12
    punkter = [(g.representative_point(), {"id": p["id"], "ha": p["ha"]}) for g, p in vann]
    tre_p = STRtree([g for g, _ in punkter])
    def min_ha(z):
        return {3: 3000, 4: 1500, 5: 600, 6: 200, 7: 60, 8: 20}.get(z, 0)
    bounds_ll = (10.5, 55.0, 24.5, 69.2)
    # Skog og bre på oversiktsnivå (tools/kart/se_skog.py, OSM via OpenFreeMap z9): lag skog_se, k 1 = skog, 2 = bre
    SKOG_MAXZ, skog = 9, []
    sfil = os.path.join(sv, "skog_se.wkb.gz")
    if os.path.exists(sfil):
        import pickle
        for k, w in pickle.load(gzip.open(sfil, "rb")):
            g = shapely.from_wkb(w)
            if not g.is_valid:
                g = g.buffer(0)
            skog += [(k, p) for p in (g.geoms if hasattr(g, "geoms") else [g]) if not p.is_empty]
        print(f"  skog_se: {len(skog)} flater")
    tiles_out, t0 = {}, time.time()
    for z in range(MINZ, MAXZ + 1):
        tol = (2 * math.pi * R / (256 * 2 ** z)) * 0.6
        vz = [(g.simplify(tol, preserve_topology=True), p) for g, p in vann if p["ha"] >= min_ha(z)]
        vz = [(g, p) for g, p in vz if not g.is_empty]
        tre_v = STRtree([g for g, _ in vz]) if vz else None
        sz = []
        if skog and z <= SKOG_MAXZ:
            min_a = (tol * 3) ** 2
            sz = [(k, g.simplify(tol, preserve_topology=True)) for k, g in skog if g.area >= min_a]
            sz = [(k, g if g.is_valid else g.buffer(0)) for k, g in sz if not g.is_empty]
            sz = [(k, g) for k, g in sz if not g.is_empty]
        tre_s = STRtree([g for _, g in sz]) if sz else None
        n = 0
        for t in mercantile.tiles(*bounds_ll, zooms=[z]):
            b = mercantile.xy_bounds(t)
            pad = (b.right - b.left) * 8 / 256.0
            tb = box(b.left - pad, b.bottom - pad, b.right + pad, b.top + pad)
            lag = []
            if tre_v is not None:
                feats = []
                for i in tre_v.query(tb, predicate="intersects"):
                    g, p = vz[i]
                    c = g.intersection(tb)
                    if c.geom_type == "GeometryCollection":
                        polys = [x for x in c.geoms if x.geom_type in ("Polygon", "MultiPolygon")]
                        if not polys:
                            continue
                        c = shapely.union_all(polys)
                    if c.is_empty or c.geom_type not in ("Polygon", "MultiPolygon"):
                        continue
                    feats.append({"geometry": c, "properties": {k: v for k, v in p.items() if v is not None}, "id": p["id"]})
                if feats:
                    lag.append({"name": "vann_se", "features": feats})
            if tre_s is not None:
                per_k = collections.defaultdict(list)
                for i in tre_s.query(tb, predicate="intersects"):
                    k, g = sz[i]
                    try:
                        c = g.intersection(tb)
                    except shapely.errors.GEOSException:
                        continue
                    if not c.is_empty:
                        per_k[k].append(c)
                feats = []
                for k, deler in sorted(per_k.items()):
                    try:
                        u = shapely.union_all(deler)
                    except shapely.errors.GEOSException:
                        u = shapely.union_all([d.buffer(0) for d in deler])
                    if u.geom_type == "GeometryCollection":
                        u = shapely.union_all([x for x in u.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
                    if not u.is_empty and u.geom_type in ("Polygon", "MultiPolygon"):
                        feats.append({"geometry": u, "properties": {"k": k}})
                if feats:
                    lag.insert(0, {"name": "skog_se", "features": feats})
            if z >= PUNKT_MINZ:
                tb0 = box(b.left, b.bottom, b.right, b.top)
                feats = [{"geometry": punkter[i][0], "properties": punkter[i][1], "id": punkter[i][1]["id"]} for i in tre_p.query(tb0, predicate="intersects")]
                if feats:
                    lag.append({"name": "vannpunkt_se", "features": feats})
            if not lag:
                continue
            data = mapbox_vector_tile.encode(lag, default_options={"quantize_bounds": (b.left, b.bottom, b.right, b.top), "extents": 4096, "y_coord_down": False})
            tiles_out[zxy_to_tileid(z, t.x, t.y)] = gzip.compress(data, 9)
            n += 1
        print(f"  z{z}: {n} fliser, {len(vz)} vann  ({time.time() - t0:.0f} s)")
    path = os.path.join(OUT, "sverige.pmtiles")
    with open(path, "wb") as fh:
        w = Writer(fh)
        for tid in sorted(tiles_out):
            w.write_tile(tid, tiles_out[tid])
        w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP, "min_zoom": MINZ, "max_zoom": MAXZ,
                    "min_lon_e7": int(bounds_ll[0] * 1e7), "min_lat_e7": int(bounds_ll[1] * 1e7),
                    "max_lon_e7": int(bounds_ll[2] * 1e7), "max_lat_e7": int(bounds_ll[3] * 1e7),
                    "center_zoom": 5, "center_lon_e7": int(16 * 1e7), "center_lat_e7": int(62 * 1e7)},
                   {"name": "HatchWatch Sverige", "attribution": "HydroLAKES (CC BY 4.0) · OpenStreetMap",
                    "vector_layers": [{"id": "vann_se", "fields": {"id": "Number", "navn": "String", "ha": "Number", "moh": "Number"}, "minzoom": MINZ, "maxzoom": MAXZ},
                                      {"id": "vannpunkt_se", "fields": {"id": "Number", "ha": "Number"}, "minzoom": PUNKT_MINZ, "maxzoom": MAXZ},
                                      {"id": "skog_se", "fields": {"k": "Number"}, "minzoom": MINZ, "maxzoom": SKOG_MAXZ}]})
    print(f"sverige.pmtiles: {len(tiles_out)} fliser, {os.path.getsize(path) / 1e6:.1f} MB ({time.time() - t0:.0f} s)")


def bygg_sverige_kalk():
    """Kalk i berggrunnen, Sverige (2026-10-17): data/kart/sverige_kalk.pmtiles, lag kalk_se med egenskap k = NGU-klasse
    1–5. Fra sverige/data/kalk_se.wkb.gz (s5_berggrunn.py: SGU-bergart → NGU 2020-003 tabell 6). Egen fil, så den bare
    lastes når kalklaget er slått på. Flater med samme klasse slås sammen per flis, så kartet ikke får sømmer."""
    import mapbox_vector_tile, mercantile, shapely, pickle, numpy as np
    from shapely.geometry import box
    from shapely.strtree import STRtree
    from pmtiles.writer import Writer
    from pmtiles.tile import zxy_to_tileid, TileType, Compression
    R = 6378137.0
    def til_merc(c):
        lat = np.clip(c[:, 1], -85.0511, 85.0511)
        return np.column_stack([R * np.radians(c[:, 0]), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))])
    t0 = time.time()
    rader = pickle.load(gzip.open(os.path.join(ROOT, "sverige", "data", "kalk_se.wkb.gz"), "rb"))
    flater = [(k, shapely.transform(shapely.from_wkb(w), til_merc)) for k, w in rader]
    print(f"kalk: {len(flater)} flater ({time.time() - t0:.0f} s)")
    MINZ, MAXZ = 5, 11
    bounds_ll = (10.5, 55.0, 24.5, 69.2)
    tiles_out = {}
    for z in range(MINZ, MAXZ + 1):
        px = 2 * math.pi * R / (256 * 2 ** z)
        tol, min_areal = px * 0.8, (px * 2.5) ** 2
        fz = [(k, g.simplify(tol, preserve_topology=True)) for k, g in flater if g.area >= min_areal]
        fz = [(k, g) for k, g in fz if not g.is_empty]
        tre = STRtree([g for _, g in fz])
        n = 0
        for t in mercantile.tiles(*bounds_ll, zooms=[z]):
            b = mercantile.xy_bounds(t)
            pad = (b.right - b.left) * 4 / 256.0
            tb = box(b.left - pad, b.bottom - pad, b.right + pad, b.top + pad)
            per_k = collections.defaultdict(list)
            for i in tre.query(tb, predicate="intersects"):
                k, g = fz[i]
                c = g.intersection(tb)
                if not c.is_empty:
                    per_k[k].append(c)
            feats = []
            for k, deler in sorted(per_k.items()):
                u = shapely.union_all(deler)
                if u.geom_type == "GeometryCollection":
                    u = shapely.union_all([x for x in u.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
                if u.is_empty or u.geom_type not in ("Polygon", "MultiPolygon"):
                    continue
                feats.append({"geometry": u, "properties": {"k": k}})
            if not feats:
                continue
            data = mapbox_vector_tile.encode([{"name": "kalk_se", "features": feats}], default_options={"quantize_bounds": (b.left, b.bottom, b.right, b.top), "extents": 4096, "y_coord_down": False})
            tiles_out[zxy_to_tileid(z, t.x, t.y)] = gzip.compress(data, 9)
            n += 1
        print(f"  z{z}: {n} fliser, {len(fz)} flater ({time.time() - t0:.0f} s)")
    path = os.path.join(OUT, "sverige_kalk.pmtiles")
    with open(path, "wb") as fh:
        w = Writer(fh)
        for tid in sorted(tiles_out):
            w.write_tile(tid, tiles_out[tid])
        w.finalize({"tile_type": TileType.MVT, "tile_compression": Compression.GZIP, "min_zoom": MINZ, "max_zoom": MAXZ,
                    "min_lon_e7": int(bounds_ll[0] * 1e7), "min_lat_e7": int(bounds_ll[1] * 1e7),
                    "max_lon_e7": int(bounds_ll[2] * 1e7), "max_lat_e7": int(bounds_ll[3] * 1e7),
                    "center_zoom": 5, "center_lon_e7": int(16 * 1e7), "center_lat_e7": int(62 * 1e7)},
                   {"name": "HatchWatch kalk Sverige", "attribution": "SGU (CC0), klasser etter NGU",
                    "vector_layers": [{"id": "kalk_se", "fields": {"k": "Number"}, "minzoom": MINZ, "maxzoom": MAXZ}]})
    print(f"sverige_kalk.pmtiles: {len(tiles_out)} fliser, {os.path.getsize(path) / 1e6:.1f} MB ({time.time() - t0:.0f} s)")


def bygg_punkt():
    """Fangstdagboka (2026-10-16): nærmeste vann fra GPS. Flat liste [vatnlnr, lat·1e4, lon·1e4, ...] fra vann/*.json."""
    flat = []
    for i in range(VANN_GRUPPER):
        for vid, rec in json.load(open(os.path.join(OUT, "vann", f"{i}.json"), encoding="utf-8")).items():
            if rec.get("lat") is not None:
                flat += [int(vid), round(rec["lat"] * 1e4), round(rec["lon"] * 1e4)]
    path = os.path.join(OUT, "vannpunkt.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(flat, fh, separators=(",", ":"))
    print(f"vannpunkt: {len(flat) // 3} vann, {os.path.getsize(path) // 1024} kB")


def oppdater_vann_isgang():
    """Bytter bare isgangen («isg») i de ferdige vannfilene. Trenger verken NVE-geojson eller shapely,
    så GitHub-jobben kan kjøre den. Navn, arter og «bekreftet» beholdes som de er."""
    isg = {}
    for fn in os.listdir(OUT):
        if fn.startswith("isgang_") and fn[7:11].isdigit():
            isg[int(fn[7:11])] = json.load(open(os.path.join(OUT, fn), encoding="utf-8"))
    mappe, endret = os.path.join(OUT, "vann"), 0
    for i in range(VANN_GRUPPER):
        path = os.path.join(mappe, f"{i}.json")
        g = json.load(open(path, encoding="utf-8"))
        for vid, rec in g.items():
            ny = {str(a): d[vid] for a, d in sorted(isg.items()) if vid in d}
            if ny != rec.get("isg", {}):
                endret += 1
                if ny:
                    rec["isg"] = ny
                else:
                    rec.pop("isg", None)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"vann: isgang oppdatert, {endret} vann endret")


# ── Dybdekart (2026-10-14) ───────────────────────────────────────────────
# NVE Innsjødatabase2 lag 4 «Dybdekart» (686 vann). Bare tabellen; selve kotene vises rett fra NVEs
# WMS (lag DybdeKurve/DybdePunkt) på kartet. PDF-ene ligger på https://gis3.nve.no/dybdekart/<pdf>.
# dybde.json = {vatnlnr: [maksdyp_m, middeldyp_m|null, oppmålt_år|null, pdf|null, ekvidistanse_m|null, digitale_koter 0/1]}
# Digitale koter (lag 3 «Innsjo_ved_dybdemaling», ca. 528 vann) vises i kartet; resten har bare PDF.
DYBDE_URL = "https://kart.nve.no/enterprise/rest/services/Innsjodatabase2/MapServer/{}/query"


def bygg_dybde():
    q = {"where": "1=1", "returnGeometry": "false", "f": "json", "resultRecordCount": 5000}
    j = hent(DYBDE_URL.format(4), dict(q, outFields="vatnlnr,maksdyp_m,middeldyp_m,oppmaltaar,pdf1,ekvidistanse_m"))
    digital = {f["attributes"].get("vatnlnr") for f in hent(DYBDE_URL.format(3), dict(q, outFields="vatnlnr")).get("features", [])}
    pos = lambda x: x if isinstance(x, (int, float)) and x > 0 else None
    ut = {}
    for f in j.get("features", []):
        a = f["attributes"]
        if not a.get("vatnlnr"):
            continue
        ut[str(a["vatnlnr"])] = [pos(a.get("maksdyp_m")), pos(a.get("middeldyp_m")), pos(a.get("oppmaltaar")),
                                 (a.get("pdf1") or "").strip() or None, pos(a.get("ekvidistanse_m")),
                                 1 if a["vatnlnr"] in digital else 0]
    if len(ut) < 500:
        raise SystemExit(f"dybde: bare {len(ut)} vann fra NVE — avbryter (forventet ca. 686)")
    with open(os.path.join(OUT, "dybde.json"), "w", encoding="utf-8") as fh:
        json.dump(ut, fh, separators=(",", ":"))
    print(f"dybde: {len(ut)} vann med dybdekart, {os.path.getsize(os.path.join(OUT, 'dybde.json')) // 1024} kB")


# ── Fisk per vann (2026-10-15, Stian: «alle registrerte fiskearter, siste funndato») ──
# Kilde: tools/research_analyser/I_arter_per_vann/fisk_per_vann.csv (i3_fisk.py: GBIF-nedlasting, samme
# koblingsregler som insektene). Egne filer data/kart/fisk/<id % 64>.json — IKKE i vann/*.json, som
# isgang-jobben eier, så de kommer med i en vanlig opplasting.
# {vatnlnr: [[latinsk navn, norsk navn, funn, siste år, sikker 0/1, innført 0/1], ...]}  sortert etter funn
FISK_SRC = os.path.join(ROOT, "tools", "research_analyser", "I_arter_per_vann", "fisk_per_vann.csv")


def bygg_fisk():
    if not os.path.exists(FISK_SRC):
        raise SystemExit("fisk: fant ikke %s — kjør i3_fisk.py først" % FISK_SRC)
    per = collections.defaultdict(list)
    with open(FISK_SRC, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            per[int(r["vatnLnr"])].append([r["art"], (r.get("norsk_navn") or "").strip(), int(r["n_funn"] or 0),
                                           int(r["siste_aar"]) if r.get("siste_aar") else None,
                                           1 if int(r.get("n_sikre") or 0) > 0 else 0, 1 if int(r.get("n_innfort") or 0) > 0 else 0])
    grupper = [dict() for _ in range(VANN_GRUPPER)]
    for vid, liste in per.items():
        liste.sort(key=lambda x: -x[2])
        grupper[vid % VANN_GRUPPER][str(vid)] = liste
    mappe = os.path.join(OUT, "fisk")
    os.makedirs(mappe, exist_ok=True)
    for i, g in enumerate(grupper):
        with open(os.path.join(mappe, f"{i}.json"), "w", encoding="utf-8") as fh:
            json.dump(g, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"fisk: {len(per)} vann med fiskefunn, {sum(len(x) for x in per.values())} vann/art-par")


# ── OFA-utsettinger (2026-10-15, Stian) ──────────────────────────────────
# Kilde: DATA i ofa-settefisk.html (Oslomarkas Fiskeadministrasjon, fisk satt ut 2021–2025; art oppgis ikke).
# OFA har navn + område, ikke NVE-nummer. Kobling: navnevarianter (Store Åklungen ↔ Åklungen Store,
# -vann/-vannet osv.) mot våre vann i Oslomarka-boksen. Navn som finnes flere steder avgjøres av avstand til
# områdets sentrum (median av entydige treff). Alle treff må ligge innen 12 km fra områdesentrum, og peker
# flere OFA-rader mot samme vann, beholdes bare eksakt navnetreff. Feil kobling er verre enn ingen.
# ofa.json = {vatnlnr: {"n": OFA-navn, "o": område, "s": {"2021": satt, ...}, "t": total}}
def bygg_ofa():
    import re, statistics
    html = open(os.path.join(ROOT, "ofa-settefisk.html"), encoding="utf-8").read()
    rec = json.loads(re.search(r"const DATA = (\{.*?\});\s*$", html, re.M).group(1))["records"]
    vann = {}
    for i in range(VANN_GRUPPER):
        for k, v in json.load(open(os.path.join(OUT, "vann", f"{i}.json"), encoding="utf-8")).items():
            if 59.55 < v["lat"] < 60.45 and 9.9 < v["lon"] < 11.45:
                vann[int(k)] = v
    kval = {"store", "lille", "søndre", "nordre", "vestre", "østre", "øvre", "nedre", "midtre", "indre", "ytre"}

    def grunn(s):
        s = re.sub(r"\(.*?\)", "", s.lower().replace("*", ""))
        s = re.sub(r"\b(v\.|ved)\b.*$", "", s)
        return re.sub(r"\s+", " ", s).strip()

    def varianter(s):
        s = grunn(s); ut = {s}; o = s.split(" ")
        if len(o) == 2 and (o[0] in kval or o[1] in kval):
            ut.add(o[1] + " " + o[0])
        for x in list(ut):
            for a, b in (("vannet", "vann"), ("vann", "vannet"), ("tjernet", "tjern"), ("tjern", "tjernet"), ("sjøen", "sjø")):
                if x.endswith(a):
                    ut.add(x[: -len(a)] + b)
        return ut

    per = collections.defaultdict(set)
    for k, v in vann.items():
        for n in varianter(v.get("navn") or ""):
            per[n].add(k)
    kand = lambda r: sorted(set().union(*[per.get(n, set()) for n in varianter(r["vann"])]))
    pos = collections.defaultdict(list)
    for r in rec:
        c = kand(r)
        if len(c) == 1:
            pos[r["omrade"]].append((vann[c[0]]["lat"], vann[c[0]]["lon"]))
    senter = {o: (statistics.median(p[0] for p in ps), statistics.median(p[1] for p in ps)) for o, ps in pos.items() if len(ps) >= 2}
    km = lambda a, b: math.hypot((a[0] - b[0]) * 111.2, (a[1] - b[1]) * 111.2 * math.cos(math.radians(a[0])))
    koblet = collections.defaultdict(list)
    for r in rec:
        c, sc = kand(r), senter.get(r["omrade"])
        if not c or not sc:
            continue
        c = sorted(c, key=lambda k: km((vann[k]["lat"], vann[k]["lon"]), sc))
        if len(c) > 1 and km((vann[c[1]]["lat"], vann[c[1]]["lon"]), sc) < 1.8 * km((vann[c[0]]["lat"], vann[c[0]]["lon"]), sc):
            continue   # ikke tydelig hvilket vann
        if km((vann[c[0]]["lat"], vann[c[0]]["lon"]), sc) > 12:
            continue
        koblet[c[0]].append(r)
    ut = {}
    for k, rs in koblet.items():
        if len(rs) > 1:
            eksakt = [r for r in rs if grunn(r["vann"]) == grunn(vann[k]["navn"] or "")]
            if len(eksakt) != 1:
                continue
            rs = eksakt
        r = rs[0]
        ut[str(k)] = {"n": r["vann"].replace("*", "").strip(), "o": r["omrade"], "t": r.get("total") or 0,
                      "s": {str(y): r.get(f"satt_{y}") or 0 for y in range(2021, 2026)}}
    with open(os.path.join(OUT, "ofa.json"), "w", encoding="utf-8") as fh:
        json.dump(ut, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"ofa: {len(ut)} vann koblet av {len(rec)} OFA-rader (resten er små vann under 10 ha, elver eller usikre navn)")
    for k, x in sorted(ut.items(), key=lambda kv: kv[1]["o"]):
        print(f"   {x['o']:22} {x['n']:28} -> {vann[int(k)]['navn']} ({k})")


if __name__ == "__main__":
    hva = sys.argv[1] if len(sys.argv) > 1 else "alt"
    if hva in ("alt", "ofa"):
        bygg_ofa()
    if hva in ("alt", "fisk") and (hva == "fisk" or os.path.exists(FISK_SRC)):
        bygg_fisk()
    if hva in ("alt", "dybde"):
        bygg_dybde()
    if hva in ("alt", "isgang"):
        bygg_isgang()
    if hva == "isgang-lokal":          # GitHub-jobben isgang-gee: les fylkesfilene på disk, bytt bare isgangen
        bygg_isgang(lokal=True)
        oppdater_vann_isgang()
    if hva in ("alt", "arter"):
        bygg_arter()
    if hva in ("alt", "isgang", "arter", "vann"):
        bygg_vann()
    if hva in ("alt", "vann", "punkt"):
        bygg_punkt()
    if hva == "sverige":               # svenske vann (sverige/data fra sverige/skript/s1–s6)
        bygg_sverige()
    if hva == "sverige-vann":          # bare vannfilene, søk og punkter (sekunder; ingen kartfliser)
        bygg_sverige(fliser=False)
    if hva in ("sverige", "sverige-kalk"):   # kalk i berggrunnen, Sverige (s5_berggrunn.py)
        bygg_sverige_kalk()
    if hva in ("finland", "finland-vann"):   # finske vann (finland/data fra finland/skript/f1–f5), egen fil bygg_finland.py
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import bygg_finland
        bygg_finland.bygg(fliser=hva == "finland")
    if hva in ("alt", "elver"):
        bygg_elver()
    if hva in ("alt", "fliser"):
        bygg_fliser(hent_laks())
