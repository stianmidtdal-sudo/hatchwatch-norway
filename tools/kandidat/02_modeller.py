"""
Kandidatmodell — steg 2: kandidatene og den ærlige testen.

Alle kandidater er FLYTTBARE: én global parameter (eller to), ingen lokal
kalibrering. Inndata bare fra kilder som finnes overalt (ERA5-vær via
open-meteo, høyde, isgang fra satellitt der den finnes).

Kandidater (klekkestart = første dag kriteriet er oppfylt):
  K0  global median dag-i-året per art (værblind referanse)
  K1b varmesum fra 1. jan, base b (0/4/5), høydekorrigert 0,6 °C/100 m, terskel G
  K2  varmesum fra 1. april, base 0
  K3  snøfri dato (ERA5 snødybde) + varmesum etter snøfri
  K4  isgang (satellitt/observert) + fast antall dager
  K5  isgang + varmesum etter isgang (base 0)
  K6  modellert isgang fra vær (kalibrert mot satellitt-isgang) + varmesum etter
  K7  varmesum vektet med daglengde (fotoperiode), base 0
  K8  varmesum av maks-temperatur, base 5 (grunne vann varmes av dagvarmen)

Test: forhåndsbestemt. Terskelen velges på treningsfoldene, feilen måles på
den utelatte folden. To oppdelinger:
  LOSO  ett OMRÅDE holdes utenfor om gangen (det er «Sverige-testen»)
  LOYO  ett ÅR holdes utenfor (modellen har sett stedet før)
Feilmål: MAE på «start»-observasjoner; andel «senest»-grenser som brytes
(prognose etter en dato da klekkingen alt var i gang) og hvor mye.
Kriterium satt på forhånd: en flyttbar kandidat er interessant hvis LOSO-MAE
slår K0 med minst 2 dager OG LOSO ligger innenfor 2 dager av LOYO.
"""
import importlib.util
import io
import json
import math
import os
import re
import statistics
import sys
from datetime import date, timedelta

HER = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("g1", os.path.join(HER, "01_grunnlag.py"))
g1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g1)
DATA = g1.DATA
LAPSE = 0.006  # °C per m (0,6 °C / 100 m, som i dashboardet)

OMR_TIL_DASH = {"Kautokeino": "kautokeino", "Østmarka": "ostmarka", "Nordmarka": "oslo", "Røros": "roros",
                "Rena": "rena", "Vestfjella": "vestfjella"}


def d(s):
    return date.fromisoformat(s)


def doy(dt):
    return (dt - date(dt.year, 1, 1)).days + 1


def dato_av(aar, n):
    return date(aar, 1, 1) + timedelta(days=int(round(n)) - 1)


# ── Vær per sted ──────────────────────────────────────────────────────────
STEDER = json.load(io.open(os.path.join(DATA, "steder.json"), encoding="utf-8"))
_vaer = {}


def vaer(sted):
    if sted not in _vaer:
        st = STEDER[sted]
        _vaer[sted] = g1.hent_vaer(sted, st["lat"], st["lon"])
    return _vaer[sted]


def serie(sted, aar, moh):
    """Døgnserie for ett år ved vannets høyde: liste av (dato, tm, tx, sn)."""
    v = vaer(sted)
    korr = -LAPSE * (moh - (v["elevation"] or moh))
    ut = []
    dt = date(aar, 1, 1)
    while dt.year == aar:
        r = v["dager"].get(dt.isoformat())
        if r and r["tm"] is not None:
            ut.append((dt, r["tm"] + korr, (r["tx"] or r["tm"]) + korr, r["sn"] or 0.0))
        dt += timedelta(days=1)
    return ut


def daglengde(lat, dt):
    """Timer dagslys (enkel formel), klampet 0–24."""
    n = doy(dt)
    dec = 23.44 * math.sin(math.radians(360 / 365.0 * (n - 81)))
    x = -math.tan(math.radians(lat)) * math.tan(math.radians(dec))
    if x <= -1:
        return 24.0
    if x >= 1:
        return 0.0
    return 24.0 / math.pi * math.acos(x)


# ── Isgang-kilder ─────────────────────────────────────────────────────────
ISG = json.load(io.open(os.path.join(DATA, "isgang.json"), encoding="utf-8"))


def isgang_obs(o):
    """Observert/satellitt-isgang for observasjonens område og år (2017+)."""
    if o["omr"] == "Nordmarka":
        for k, v in ISG.items():
            if k.startswith("nordmarka_dyn/") and k.split("/", 1)[1].split()[0].lower() in o["lok"].lower():
                if o["aar"] in v["aar"] or str(o["aar"]) in v["aar"]:
                    return d(v["aar"].get(o["aar"]) or v["aar"][str(o["aar"])])
    lid = OMR_TIL_DASH.get(o["omr"])
    if lid and lid in ISG:
        a = ISG[lid]["aar"]
        s = a.get(o["aar"]) or a.get(str(o["aar"]))
        return d(s) if s else None
    return None


# ── Akkumulatorer ─────────────────────────────────────────────────────────
def forste_dag(ser, start_dt, vekt_fn, terskel):
    s = 0.0
    for dt, tm, tx, sn in ser:
        if dt < start_dt:
            continue
        s += vekt_fn(dt, tm, tx)
        if s >= terskel:
            return dt
    return None


def snofri(ser):
    """Dagen etter siste dag med > 2 cm snø i jan–juli; 1. mars hvis aldri snø."""
    siste = None
    for dt, tm, tx, sn in ser:
        if dt.month <= 7 and sn > 0.02:
            siste = dt
    return (siste + timedelta(days=1)) if siste else date(ser[0][0].year, 3, 1)


# ── Modellert isgang fra vær (K6), kalibrert mot isgang-seriene i dashboardet ──
def fdd_tdd(ser_forrige_host, ser):
    """Fryse-graddager nov–mars (forrige høst + i år) og funksjon for tine-graddager fra 1. mars."""
    fdd = 0.0
    for dt, tm, tx, sn in ser_forrige_host:
        if dt.month >= 11 and tm < 0:
            fdd += -tm
    for dt, tm, tx, sn in ser:
        if dt.month <= 3 and tm < 0:
            fdd += -tm
    return fdd


def isgang_modell(sted, aar, moh, a, b):
    """Isgang = første dag der tine-graddager (tm>0, fra 1. mars) >= a * sqrt(FDD) + b."""
    ser = serie(sted, aar, moh)
    forrige = serie(sted, aar - 1, moh)
    if not ser or not forrige:
        return None
    fdd = fdd_tdd(forrige, ser)
    mal = a * math.sqrt(max(fdd, 1.0)) + b
    s = 0.0
    for dt, tm, tx, sn in ser:
        if dt < date(aar, 3, 1):
            continue
        if tm > 0:
            s += tm
        if s >= mal:
            return dt
    return None


def kalibrer_isgang():
    """Kalibrerer (a, b) mot dashboardets isgang-serier for stedene vi har vær for.
    Returnerer (a, b, MAE, n). Leave-one-site-out-MAE rapporteres også."""
    punkter = []  # (sted, aar, moh, isgang_dato)
    dash_til_sted = {v: k for k, v in OMR_TIL_DASH.items()}
    for lid, v in ISG.items():
        if "/" in lid:
            continue
        sted = dash_til_sted.get(lid)
        if not sted:
            continue
        moh = STEDER[sted]["moh"]
        for y, s in v["aar"].items():
            punkter.append((sted, int(y), moh, d(s)))
    if not punkter:
        return None
    steder = sorted({p[0] for p in punkter})

    def passform(a, b, ps):
        feil = []
        for sted, y, moh, obs in ps:
            m = isgang_modell(sted, y, moh, a, b)
            if m:
                feil.append((m - obs).days)
        return feil

    def velg(ps):
        best = None
        for a in [x * 2.0 for x in range(2, 26)]:        # 4..50
            for b in [0, 20, 40, 60, 80, 100]:
                f = passform(a, b, ps)
                if not f:
                    continue
                mae = sum(abs(x) for x in f) / len(f)
                if best is None or mae < best[0]:
                    best = (mae, a, b)
        return best

    alle = velg(punkter)
    loso = []
    for s in steder:
        tren = [p for p in punkter if p[0] != s]
        test = [p for p in punkter if p[0] == s]
        v = velg(tren)
        if v:
            loso += [abs(x) for x in passform(v[1], v[2], test)]
    return {"a": alle[1], "b": alle[2], "mae_insample": round(alle[0], 1), "n": len(punkter),
            "mae_loso": round(sum(loso) / len(loso), 1) if loso else None, "steder": steder}


# ── Kandidatmodellene som prognosefunksjoner ──────────────────────────────
def lag_kandidater(isg_par):
    lat_av = {k: v["lat"] for k, v in STEDER.items()}

    def k1(b):
        def f(o, G):
            ser = serie(o["omr"], o["aar"], o["moh"])
            return forste_dag(ser, date(o["aar"], 1, 1), lambda dt, tm, tx: max(0.0, tm - b), G)
        return f

    def k2(o, G):
        ser = serie(o["omr"], o["aar"], o["moh"])
        return forste_dag(ser, date(o["aar"], 4, 1), lambda dt, tm, tx: max(0.0, tm), G)

    def k3(o, G):
        ser = serie(o["omr"], o["aar"], o["moh"])
        return forste_dag(ser, snofri(ser), lambda dt, tm, tx: max(0.0, tm), G)

    def k4(o, D):
        i = isgang_obs(o)
        return (i + timedelta(days=int(D))) if i else None

    def k5(o, G):
        i = isgang_obs(o)
        if not i:
            return None
        ser = serie(o["omr"], o["aar"], o["moh"])
        return forste_dag(ser, i, lambda dt, tm, tx: max(0.0, tm), G)

    def k6(o, G):
        if not isg_par:
            return None
        i = isgang_modell(o["omr"], o["aar"], o["moh"], isg_par["a"], isg_par["b"])
        if not i:
            return None
        ser = serie(o["omr"], o["aar"], o["moh"])
        return forste_dag(ser, i, lambda dt, tm, tx: max(0.0, tm), G)

    def k7(o, G):
        ser = serie(o["omr"], o["aar"], o["moh"])
        lat = lat_av[o["omr"]]
        return forste_dag(ser, date(o["aar"], 1, 1), lambda dt, tm, tx: max(0.0, tm) * daglengde(lat, dt) / 12.0, G)

    def k8(o, G):
        ser = serie(o["omr"], o["aar"], o["moh"])
        return forste_dag(ser, date(o["aar"], 1, 1), lambda dt, tm, tx: max(0.0, tx - 5), G)

    gdd_grid = list(range(200, 1300, 10))
    return {
        "K1b0 varmesum fra 1. jan, base 0": (k1(0), gdd_grid),
        "K1b4 varmesum fra 1. jan, base 4": (k1(4), list(range(50, 700, 5))),
        "K1b5 varmesum fra 1. jan, base 5": (k1(5), list(range(50, 700, 5))),
        "K2 varmesum fra 1. april": (k2, gdd_grid),
        "K3 snøfri + varmesum": (k3, gdd_grid),
        "K4 isgang + faste dager": (k4, list(range(0, 80))),
        "K5 isgang + varmesum": (k5, list(range(50, 900, 10))),
        "K6 modellert isgang + varmesum": (k6, list(range(50, 900, 10))),
        "K7 varmesum x daglengde": (k7, list(range(200, 1600, 10))),
        "K8 maks-temp base 5": (k8, list(range(100, 1200, 10))),
    }


# ── Tap og kryssvalidering ────────────────────────────────────────────────
def tap(pred, o):
    """Start-obs: |feil|. Senest-obs: bare straff når prognosen er senere enn grensen."""
    if pred is None:
        return None
    e = (pred - d(o["dato"])).days
    if o["klasse"] == "start":
        return abs(e)
    return max(0, e)


def velg_terskel(f, grid, obs):
    best = None
    for G in grid:
        t = [tap(f(o, G), o) for o in obs]
        t = [x for x in t if x is not None]
        if not t:
            continue
        m = sum(t) / len(t)
        if best is None or m < best[0]:
            best = (m, G)
    return best


def evaluer(f, grid, obs, folds):
    """folds: liste av (trening, test). Returnerer MAE start, n start, brudd-andel, snitt-brudd, n senest, terskler."""
    feil_start, brudd, n_sen, terskler, bias = [], [], 0, [], []
    for tren, test in folds:
        v = velg_terskel(f, grid, tren)
        if not v:
            continue
        G = v[1]
        terskler.append(G)
        for o in test:
            p = f(o, G)
            if p is None:
                continue
            e = (p - d(o["dato"])).days
            if o["klasse"] == "start":
                feil_start.append(abs(e)); bias.append(e)
            else:
                n_sen += 1
                if e > 0:
                    brudd.append(e)
    return {"mae": round(sum(feil_start) / len(feil_start), 1) if feil_start else None,
            "bias": round(sum(bias) / len(bias), 1) if bias else None,
            "n_start": len(feil_start),
            "brudd_pst": round(100.0 * len(brudd) / n_sen) if n_sen else None,
            "brudd_snitt": round(sum(brudd) / len(brudd), 1) if brudd else 0,
            "n_senest": n_sen,
            "terskler": "%s–%s" % (min(terskler), max(terskler)) if terskler else "–"}


def k0_eval(obs, folds):
    feil, bias, brudd, n_sen = [], [], [], 0
    for tren, test in folds:
        starts = [doy(d(o["dato"])) for o in tren if o["klasse"] == "start"]
        if not starts:
            continue
        med = statistics.median(starts)
        for o in test:
            e = int(round(med)) - doy(d(o["dato"]))
            if o["klasse"] == "start":
                feil.append(abs(e)); bias.append(e)
            else:
                n_sen += 1
                if e > 0:
                    brudd.append(e)
    return {"mae": round(sum(feil) / len(feil), 1) if feil else None, "bias": round(sum(bias) / len(bias), 1) if bias else None,
            "n_start": len(feil), "brudd_pst": round(100.0 * len(brudd) / n_sen) if n_sen else None,
            "brudd_snitt": round(sum(brudd) / len(brudd), 1) if brudd else 0, "n_senest": n_sen, "terskler": "median"}


def folds_av(obs, nokkel):
    ut = []
    for k in sorted({nokkel(o) for o in obs}):
        tren = [o for o in obs if nokkel(o) != k]
        test = [o for o in obs if nokkel(o) == k]
        if tren and test:
            ut.append((tren, test))
    return ut


def main():
    obs = json.load(io.open(os.path.join(DATA, "obs.json"), encoding="utf-8"))
    # dropp duplikater (samme hendelse to steder) og 1962/1971 (før ERA5-serien vår)
    sett = set()
    rens = []
    for o in obs:
        if o["aar"] < 2003:
            continue
        if o["duplikat"] and o["duplikat"] in sett:
            continue
        sett.add(o["id"])
        rens.append(o)
    obs = rens

    print("Kalibrerer isgang-modellen fra vær mot dashboardets isgang-serier ...", flush=True)
    isg_par = kalibrer_isgang()
    print("  ", isg_par, flush=True)

    kand = lag_kandidater(isg_par)
    L = ["# Kandidatmodell — flyttbar klekkemodell uten lokale observasjoner\n",
         "Kjørt %s. Grunnlag: klekkeobs_master.csv (kun fase «start»/«første» som direkte datoer; «i gang», "
         "«topp», «spinnerfall» som øvre grenser), ERA5-vær via open-meteo (høydekorrigert 0,6 °C/100 m), "
         "isgang fra dashboardets isgangHistory (observert/satellitt, 2017–2026).\n" % date.today().isoformat(),
         "Modellert isgang fra vær (K6): tine-graddager fra 1. mars ≥ a·√(frysegraddager) + b, kalibrert mot %d "
         "isgang-år på %d steder: a=%s, b=%s, MAE %s d (i utvalget), %s d med stedet holdt utenfor.\n"
         % (isg_par["n"], len(isg_par["steder"]), isg_par["a"], isg_par["b"], isg_par["mae_insample"], isg_par["mae_loso"]) if isg_par else "",
         "**Tolkning av kolonnene:** MAE = snittfeil på start-observasjoner (dager). Bias = + betyr for sen prognose. "
         "Brudd = andel «i gang»-datoer der prognosen kom ETTER at klekkingen alt var i gang, og hvor mange dager. "
         "LOSO = området holdt utenfor (flyttbarhet). LOYO = året holdt utenfor (stedet kjent).\n"]
    for art in ("vulgata", "marginata"):
        ob = [o for o in obs if o["art"] == art or (art == "marginata" and o["art"] == "marginata/vespertina")]
        ob_isg = [o for o in ob if isgang_obs(o)]
        L.append("## %s — %d observasjoner (%d start, %d senest), %d med isgang\n"
                 % (art.capitalize(), len(ob), sum(o["klasse"] == "start" for o in ob), sum(o["klasse"] == "senest" for o in ob), len(ob_isg)))
        L.append("Områder: " + ", ".join("%s %d" % (k, sum(o["omr"] == k for o in ob)) for k in sorted({o["omr"] for o in ob})) + "\n")
        L.append("| Kandidat | Utvalg | LOSO MAE | bias | n | brudd | LOYO MAE | bias | n | brudd | terskel (LOSO) |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for navn, (f, grid) in [("K0 global median", (None, None))] + list(kand.items()):
            utvalg = ob_isg if navn.startswith(("K4", "K5")) else ob
            if len([o for o in utvalg if o["klasse"] == "start"]) < 4:
                continue
            fs, fy = folds_av(utvalg, lambda o: o["omr"]), folds_av(utvalg, lambda o: o["aar"])
            if f is None:
                a, b = k0_eval(utvalg, fs), k0_eval(utvalg, fy)
            else:
                a, b = evaluer(f, grid, utvalg, fs), evaluer(f, grid, utvalg, fy)
            L.append("| %s | %s | %s | %s | %d | %s %% / %s d | %s | %s | %d | %s %% / %s d | %s |" % (
                navn, "kun år med isgang" if utvalg is ob_isg else "alle", a["mae"], a["bias"], a["n_start"], a["brudd_pst"], a["brudd_snitt"],
                b["mae"], b["bias"], b["n_start"], b["brudd_pst"], b["brudd_snitt"], a["terskler"]))
            print("  %-36s %-9s LOSO %s (n=%d)  LOYO %s" % (navn, art, a["mae"], a["n_start"], b["mae"]), flush=True)
        # Samme utvalg for alle (bare år med isgang) så K4/K5 kan sammenlignes rettferdig
        if len([o for o in ob_isg if o["klasse"] == "start"]) >= 4:
            L.append("\nSamme utvalg for alle, bare år med isgang (rettferdig sammenligning med K4/K5):\n")
            L.append("| Kandidat | LOSO MAE | bias | n | LOYO MAE | bias |")
            L.append("|---|---|---|---|---|---|")
            fs, fy = folds_av(ob_isg, lambda o: o["omr"]), folds_av(ob_isg, lambda o: o["aar"])
            a, b = k0_eval(ob_isg, fs), k0_eval(ob_isg, fy)
            L.append("| K0 global median | %s | %s | %d | %s | %s |" % (a["mae"], a["bias"], a["n_start"], b["mae"], b["bias"]))
            for navn, (f, grid) in kand.items():
                a, b = evaluer(f, grid, ob_isg, fs), evaluer(f, grid, ob_isg, fy)
                L.append("| %s | %s | %s | %d | %s | %s |" % (navn, a["mae"], a["bias"], a["n_start"], b["mae"], b["bias"]))
        L.append("")
    io.open(os.path.join(HER, "KANDIDATMODELL_resultat.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("Skrevet KANDIDATMODELL_resultat.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
