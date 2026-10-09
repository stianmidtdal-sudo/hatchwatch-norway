"""
Kandidatmodell — steg 6: Nordmarka-problemet. Tre tester (Stian: «kjør»).

  1. VÆRKILDE. Dagens ERA5-rute for Nordmarka ligger på 93 moh (Oslo), vannene
     på 300–490. Bytt til (a) ERA5-rute oppe i marka (60,05 N 10,65 Ø, 377 moh)
     og (b) Bjørnholt-stasjonen (SN18500, 380 moh, via hatchwatch.no/api/frost).
     Forsvinner bommene, er problemet værdata, ikke biologi.
  2. ISGANG SOM SPERRE. Start = seneste av (varmesum ≥ 450 fra 1. april) og
     (varmesum etter isgang ≥ Y). Bare år med isgang (2017–).
  3. VANNTEMPERATUR FRA LUFTA. T_vann følger lufta med tidskonstant τ dager
     (fra 1. april, start 1 °C). Start = første dag varmesum ≥ 450 OG T_vann ≥ W.

Alle tester: samme 26 start-observasjoner (+ grenser) som før. Feil per
Nordmarka-år vises, så vi ser om 2017/2019/2022 flytter seg uten at resten
ødelegges.
"""
import importlib.util
import io
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

HER = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m2", os.path.join(HER, "02_modeller.py"))
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)
g1 = m2.g1

HOY = ("Nordmarka_hoy", 60.05, 10.65)
BJ = "Nordmarka_bjornholt"
FROST_STI = os.path.join(g1.DATA, "frost_SN18500.json")


def frost_bjornholt():
    """Døgnmiddel luft Bjørnholt 2009–2026 via hatchwatch.no/api/frost (ett kall per år)."""
    ut = json.load(io.open(FROST_STI, encoding="utf-8")) if os.path.exists(FROST_STI) else {}
    gammel = os.path.join(HER, "..", "isgang", "data", "frost_SN18500.json")
    if os.path.exists(gammel):
        ut.update(json.load(io.open(gammel, encoding="utf-8")))
    for a in range(2009, 2027):
        if any(k.startswith("%d-05" % a) for k in ut):
            continue
        q = urllib.parse.urlencode({"elements": "mean(air_temperature P1D)", "start": "%d-01-01" % a,
                                    "end": "%d-01-01" % (a + 1), "station": "SN18500"})
        req = urllib.request.Request("https://www.hatchwatch.no/api/frost?" + q, headers={"User-Agent": "hatchwatch-tools"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.load(r)
        except Exception as e:
            print("  Frost %d: %s" % (a, e))
            continue
        sums, cnt = {}, {}
        for it in j.get("data", []):
            d = it["referenceTime"][:10]
            v = (it.get("observations") or [{}])[0].get("value")
            if v is None:
                continue
            sums[d] = sums.get(d, 0) + v
            cnt[d] = cnt.get(d, 0) + 1
        for d in sums:
            ut[d] = sums[d] / cnt[d]
        print("  Frost %d: %d dager" % (a, len(sums)), flush=True)
    json.dump(ut, io.open(FROST_STI, "w", encoding="utf-8"))
    return ut


def registrer_kilder():
    # (a) ERA5-rute oppe i marka
    m2.STEDER[HOY[0]] = {"lat": HOY[1], "lon": HOY[2], "moh": 381}
    g1.STEDER[HOY[0]] = (HOY[1], HOY[2], 381)
    v = g1.hent_vaer(HOY[0], HOY[1], HOY[2])
    print("ERA5 oppe i marka: rutehøyde %s m" % v["elevation"])
    # (b) Bjørnholt
    fr = frost_bjornholt()
    m2.STEDER[BJ] = {"lat": 60.05, "lon": 10.69, "moh": 381}
    m2._vaer[BJ] = {"elevation": 380, "dager": {d: {"tm": t, "tx": t, "tn": t, "sn": 0.0, "rr": 0.0} for d, t in fr.items()}}
    print("Bjørnholt: %d dager, fra %s" % (len(fr), min(fr)))


def med_kilde(obs, kilde, fra_aar=2003):
    ut = []
    for o in obs:
        if o["omr"] == "Nordmarka":
            if o["aar"] < fra_aar:
                continue
            o = dict(o, omr=kilde)
        ut.append(o)
    return ut


def k2(o, G=450):
    ser = m2.serie(o["omr"], o["aar"], o["moh"])
    return m2.forste_dag(ser, date(o["aar"], 4, 1), lambda dt, tm, tx: max(0.0, tm), G)


def tabell_nordmarka(obs, f, L, tittel):
    L.append("\n**%s** — Nordmarka start-obs, feil = prognose − obs:\n" % tittel)
    rad = []
    for o in sorted(obs, key=lambda o: o["aar"]):
        if o["omr"].startswith("Nordmarka") and o["klasse"] == "start":
            p = f(o)
            rad.append("%d: %s" % (o["aar"], ("%+d" % (p - m2.d(o["dato"])).days) if p else "–"))
    L.append(", ".join(rad) + "\n")


def mae_alle(obs, f):
    e = [abs((f(o) - m2.d(o["dato"])).days) for o in obs if o["klasse"] == "start" and f(o)]
    return (round(sum(e) / len(e), 1), len(e)) if e else (None, 0)


def main():
    registrer_kilder()
    alle = [o for o in json.load(io.open(os.path.join(m2.DATA, "obs.json"), encoding="utf-8"))
            if o["art"] == "vulgata" and o["aar"] >= 2003]
    L = ["# Nordmarka-problemet: tre tester (%s)\n" % date.today().isoformat(),
         "Samme 26 vulgata-startobservasjoner som i steg 2. K2 = varmesum fra 1. april ≥ 450, høydekorrigert.\n",
         "## 1. Værkilde for Nordmarka\n",
         "| Værkilde for Nordmarka | MAE alle start-obs | n | MAE Nordmarka | n |", "|---|---|---|---|---|"]
    varianter = [("ERA5 ved Oslo, 93 moh (som i steg 2)", "Nordmarka", 2003),
                 ("ERA5 oppe i marka, 377 moh", HOY[0], 2003),
                 ("Bjørnholt-stasjonen, 380 moh (obs fra 2009)", BJ, 2009)]
    for navn, kilde, fra in varianter:
        ob = med_kilde(alle, kilde, fra)
        m_alle, n_alle = mae_alle(ob, k2)
        nm = [o for o in ob if o["omr"].startswith("Nordmarka")]
        m_nm, n_nm = mae_alle(nm, k2)
        L.append("| %s | %s | %d | %s | %d |" % (navn, m_alle, n_alle, m_nm, n_nm))
    for navn, kilde, fra in varianter:
        tabell_nordmarka(med_kilde(alle, kilde, fra), k2, L, navn)

    # Hvilken kilde bruker vi videre? Den med lavest Nordmarka-MAE (obs fra 2009 for rettferdig sammenligning)
    beste = None
    for navn, kilde, fra in varianter:
        m, n = mae_alle([o for o in med_kilde(alle, kilde, 2009) if o["omr"].startswith("Nordmarka")], k2)
        if m is not None and (beste is None or m < beste[0]):
            beste = (m, navn, kilde)
    L.append("\nBeste værkilde for Nordmarka (obs fra 2009, likt utvalg): %s (MAE %s). Brukes i test 2 og 3.\n" % (beste[1], beste[0]))
    kilde = beste[2]
    ob = med_kilde(alle, kilde, 2003)

    # ── 2. Isgang som sperre ──
    L.append("## 2. Isgang som sperre (bare år med isgang, 2017–)\n")
    ob_isg = [o for o in ob if m2.isgang_obs(dict(o, omr="Nordmarka") if o["omr"].startswith("Nordmarka") else o)]

    def isg(o):
        return m2.isgang_obs(dict(o, omr="Nordmarka") if o["omr"].startswith("Nordmarka") else o)

    def sperre(o, Y):
        a = k2(o)
        i = isg(o)
        if not a or not i:
            return a
        ser = m2.serie(o["omr"], o["aar"], o["moh"])
        b = m2.forste_dag(ser, i, lambda dt, tm, tx: max(0.0, tm), Y) if Y > 0 else i
        return max(a, b) if b else a

    L += ["| Y (varmesum etter isgang) | MAE start | n | Nordmarka-feil per år |", "|---|---|---|---|"]
    for Y in (0, 50, 100, 150, 200, 250, 300, 350, 400):
        f = lambda o, Y=Y: sperre(o, Y)
        m, n = mae_alle(ob_isg, f)
        nm = ", ".join("%d: %+d" % (o["aar"], (f(o) - m2.d(o["dato"])).days) for o in sorted(ob_isg, key=lambda o: o["aar"])
                       if o["omr"].startswith("Nordmarka") and o["klasse"] == "start" and f(o))
        L.append("| %s | %s | %d | %s |" % ("0 (tidligst på isgangsdagen)" if Y == 0 else Y, m, n, nm))
    m0, n0 = mae_alle(ob_isg, k2)
    L.append("| uten sperre (K2 alene) | %s | %d | %s |" % (m0, n0, ", ".join(
        "%d: %+d" % (o["aar"], (k2(o) - m2.d(o["dato"])).days) for o in sorted(ob_isg, key=lambda o: o["aar"])
        if o["omr"].startswith("Nordmarka") and o["klasse"] == "start" and k2(o))))

    # ── 3. Vanntemperatur fra lufta ──
    L.append("\n## 3. Vanntemperatur regnet fra lufta (tidskonstant τ) som andre krav\n")

    def tvann_gate(o, tau, W, G=450):
        ser = m2.serie(o["omr"], o["aar"], o["moh"])
        s, tv, start = 0.0, 1.0, date(o["aar"], 4, 1)
        for dt, tm, tx, sn in ser:
            if dt < start:
                continue
            s += max(0.0, tm)
            tv += (tm - tv) / float(tau)
            if s >= G and tv >= W:
                return dt
        return None

    L += ["| τ (dager) | W (°C) | MAE start, alle | n | Nordmarka-feil per år |", "|---|---|---|---|---|"]
    beste3 = None
    for tau in (3, 5, 8, 12, 16, 20, 30):
        for W in (10, 11, 12, 13, 14, 15):
            f = lambda o, tau=tau, W=W: tvann_gate(o, tau, W)
            m, n = mae_alle(ob, f)
            if m is None:
                continue
            if beste3 is None or m < beste3[0]:
                beste3 = (m, tau, W)
    for tau, W in sorted({(beste3[1], beste3[2]), (5, 12), (8, 12), (12, 12), (12, 14), (20, 12), (20, 14)}):
        f = lambda o, tau=tau, W=W: tvann_gate(o, tau, W)
        m, n = mae_alle(ob, f)
        nm = ", ".join("%d: %+d" % (o["aar"], (f(o) - m2.d(o["dato"])).days) for o in sorted(ob, key=lambda o: o["aar"])
                       if o["omr"].startswith("Nordmarka") and o["klasse"] == "start" and f(o))
        L.append("| %s | %s | %s | %d | %s |" % (tau, W, m, n, nm))
    L.append("\nBeste kombinasjon i utvalget: τ=%s, W=%s, MAE %s (K2 alene på samme utvalg: %s). "
             "NB: to frie parametre valgt på 26 obs — in-sample, ikke kryssvalidert.\n"
             % (beste3[1], beste3[2], beste3[0], mae_alle(ob, k2)[0]))
    # kryssvalidering (LOSO) av test 3 med (τ, W) valgt på treningsfoldene
    folds = m2.folds_av(ob, lambda o: o["omr"].replace("_hoy", "").replace("_bjornholt", ""))
    feil = []
    for tren, test in folds:
        b = None
        for tau in (3, 5, 8, 12, 16, 20, 30):
            for W in (10, 11, 12, 13, 14, 15):
                m, n = mae_alle(tren, lambda o, tau=tau, W=W: tvann_gate(o, tau, W))
                if m is not None and (b is None or m < b[0]):
                    b = (m, tau, W)
        for o in test:
            if o["klasse"] != "start":
                continue
            p = tvann_gate(o, b[1], b[2])
            if p:
                feil.append(abs((p - m2.d(o["dato"])).days))
    L.append("LOSO (region holdt utenfor, τ og W valgt på resten): MAE %.1f d, n=%d.\n" % (sum(feil) / len(feil), len(feil)))
    io.open(os.path.join(HER, "KANDIDATMODELL_nordmarka.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
