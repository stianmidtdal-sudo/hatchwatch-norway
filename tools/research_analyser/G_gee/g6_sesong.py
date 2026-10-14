"""
G6 — vårmodus: isgang for INNEVÆRENDE år mens sesongen pågår (innført 14. okt 2026, Stian «fiks
satellittjobben for 2027»).

Hvorfor: Norge-kjøringen (g2 --norge) henter et fast sett år (2017–2026) og skriver aldri over et
vann-år som alt ligger inne. Inneværende år ville da blitt hentet én gang, kanskje før isen gikk,
og aldri igjen. Vannsidene, kartet og varselet «isen har gått» trenger årets dato så snart
satellitten ser den.

Samme metode som g2 (klassifisering, klare(), finn_isgang — alt importert uendret). To deler:
  1. HELE måneder (1. feb → første dag i inneværende måned) hentes én gang for ALLE vann i fylket
     (kjøringsnavn sesong_<år>_fylke_<nr>, --fortsett-maskineriet i g2). Vannlista er den samme
     hver gang, så rutene og framdriften er stabile; ferdige måneder hentes aldri på nytt.
  2. RESTEN av inneværende måned (1. → i dag) hentes på nytt hver kjøring, men bare for vann som
     ikke har fått en sikker isgang for året ennå (kjøringsnavn sesong_<år>_fylke_<nr>_rest,
     overskrives hver gang).
Resultatet slås inn i fylkesfilene for året. En isgang som er funnet («ok») skrives aldri over av
et svakere resultat. Ferdige statuser: ok, ingen_is_sett (åpent ved første klare pass),
for_faa_piksler. Etter vinduets slutt (16. juli) hentes bare den siste hele biten.

Kjører bare mellom 15. mars og 25. juli, og høyst hvert --hver-dager døgn (siste kjøring står i
norge_plan.json → «sesong»). Bruker kvoteboka og tidsvakten i g2 (samme månedsbudsjett).

  python g6_sesong.py [--aar 2027] [--hver-dager 2] [--parallell 4] [--budsjett-timer 950]
                      [--maks-minutter 150] [--tving] [--fylke 03]
Skriver minuttene brukt til $GITHUB_ENV som SESONG_MIN (så backfill-steget kan korte ned).
Returkoder: 0 ferdig/ingenting å gjøre, 3 kvotevakten, 4 tidsvakten (som g2).
"""
import argparse
import datetime as dt
import os
import sys
import time

HER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HER)
import g2_gee_norge as g2          # noqa: E402
g1 = g2.g1

SESONG_FRA = (3, 15)
SESONG_TIL = (7, 25)
FERDIGE = {"ok", "ingen_is_sett", "for_faa_piksler"}


# g1._maanedsbiter gir ingen bit når start og slutt er i samme måned (resten av inneværende måned).
# Vi trenger akkurat det, så biten lages direkte i det tilfellet. Gjelder bare denne prosessen.
_orig_biter = g1._maanedsbiter


def _biter(vindu):
    if vindu[0][:2] == vindu[1][:2]:
        return [tuple(vindu)] if vindu[0] < vindu[1] else []
    return _orig_biter(vindu)


g1._maanedsbiter = _biter


def mmdd(d):
    return "%02d-%02d" % (d.month, d.day)


def i_sesong(i_dag):
    return (i_dag.month, i_dag.day) >= SESONG_FRA and (i_dag.month, i_dag.day) <= SESONG_TIL


def vinduer(i_dag):
    """(hele månedsvindu, restvindu) for inneværende år, innenfor g2.VINDU (02-01 → 07-16, slutt eksklusiv)."""
    start, slutt = g2.VINDU
    i_dag_s = mmdd(i_dag)
    if i_dag_s >= slutt:
        # Etter vinduets slutt: «hele» slutter på 1. juli og juli-biten (07-01 → 07-16) tas som rest.
        # (g1._maanedsbiter ville ellers slått sammen juni og juli til én bit med juni-nøkkelen, som alt
        # er ferdig — og 1.–15. juli ville aldri blitt hentet.)
        forste = slutt[:2] + "-01"
        return (start, forste), (forste, slutt)
    forste = "%02d-01" % i_dag.month
    hele = (start, forste) if forste > start else None
    rest = (forste, i_dag_s) if i_dag_s > forste else None
    return hele, rest


def slaa_inn_sesong(nr, res, aar, valg):
    """Slår årets resultat inn i fylkesfila uten å skrive over en funnet isgang med et svakere svar."""
    store = g2.les_fylkesfil(nr) or g2.nytt_fylkeslager(nr, valg, g2.VINDU)
    store["kilde"] = g2.STORE_KILDE
    y = str(aar)
    nye = endret = beholdt = 0
    for lnr, v in res.items():
        p = v["aar"].get(y)
        if not p:
            continue
        gammel = store["vann"].get(lnr)
        if gammel is None:
            gammel = {k: v[k] for k in v if k != "aar"}
            gammel["aar"] = {}
            store["vann"][lnr] = gammel
        g = gammel["aar"].get(y)
        if g and g.get("status") == "ok" and p.get("status") != "ok":
            beholdt += 1
            continue
        if g is None:
            nye += 1
        elif g != p:
            endret += 1
        gammel["aar"][y] = p
    store["kjoringer"].append({"navn": "sesong_%d_fylke_%s" % (aar, nr), "naar": dt.datetime.now().isoformat(timespec="seconds"),
                               "aar": [aar, aar], "nye": nye, "endret": endret, "beholdt_ok": beholdt})
    g2.skriv_fylkesfil(nr, store)
    g2.oppdater_index(nr, store["vann"])
    return nye, endret, beholdt


def ventende_vann(nr, vann, aar):
    store = g2.les_fylkesfil(nr)
    ferdige = set()
    if store:
        for lnr, v in store["vann"].items():
            p = v["aar"].get(str(aar))
            if p and p.get("status") in FERDIGE:
                ferdige.add(int(lnr))
    return [v for v in vann if v["vatnlnr"] not in ferdige]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aar", type=int, default=None, help="år (standard: i år)")
    ap.add_argument("--hver-dager", type=float, default=2.0, help="kjør høyst så ofte (døgn)")
    ap.add_argument("--parallell", type=int, default=4)
    ap.add_argument("--budsjett-timer", type=float, default=g2.BUDSJETT_TIMER)
    ap.add_argument("--maks-minutter", type=float, default=150)
    ap.add_argument("--tving", action="store_true", help="kjør selv om det er utenfor sesongen eller nylig kjørt")
    ap.add_argument("--fylke", help="bare dette fylket (test)")
    ap.add_argument("--project")
    a = ap.parse_args()
    t0 = time.time()
    i_dag = dt.date.today()
    aar = a.aar or i_dag.year
    ut = 0
    try:
        if not a.tving and not i_sesong(i_dag):
            g2.logg("Vårmodus: utenfor sesongen (%s) — ingenting å gjøre." % i_dag)
            return 0
        plan = g2.les_plan() or {}
        ses = plan.setdefault("sesong", {})
        siste = ses.get("siste_kjoring")
        if not a.tving and siste and ses.get("aar") == aar:
            alder = (dt.datetime.now() - dt.datetime.fromisoformat(siste)).total_seconds() / 86400
            if alder < a.hver_dager:
                g2.logg("Vårmodus: kjørt for %.1f døgn siden (grense %.1f) — venter." % (alder, a.hver_dager))
                return 0
        if a.maks_minutter and a.maks_minutter > 0:
            g2.FRIST[0] = time.time() + a.maks_minutter * 60
        g2.krev_migrert()
        valg = g1.les_valg()
        budsjett = g2.kvotebok(plan, a.budsjett_timer)
        hele, rest = vinduer(i_dag if aar == i_dag.year else dt.date(aar, 12, 31))
        g2.logg("Vårmodus %d: hele måneder %s, rest %s, kvote brukt %.1f av %.0f t." % (
            aar, hele, rest, budsjett["brukt_sek"] / 3600, budsjett["timer"]))
        ee = g2.ee_init(g1.prosjekt(a.project) or os.environ.get("GEE_PROJECT") or None)
        fylker = [a.fylke] if a.fylke else g2.REKKEFOLGE
        stats = {}
        for nr in fylker:
            if g2.tid_ute():
                g2.logg("TIDSVAKT: stopper før fylke %s." % nr); ut = 4; break
            if budsjett["brukt_sek"] >= budsjett["timer"] * 3600:
                g2.logg("KVOTEVAKT: budsjettet er brukt opp før fylke %s." % nr); ut = 3; break
            vann = [v for v in g2.vann_fylke(nr, g2.MIN_HA) if (v["areal_ha"] or 0) <= g2.MAKS_HA]
            if not vann:
                continue
            navn = "sesong_%d_fylke_%s" % (aar, nr)
            serier = {}
            komplett = None
            if hele:
                # Fortsett-maskineriet krever samme vindu; vinduet vokser med én måned om gangen, og bitene er
                # månedsbiter fra 1. feb, så ferdige biter har samme nøkkel. Oppdater derfor vinduet i framdrifta.
                fr = g2.les_fremdrift(navn)
                if fr.get("vindu") and tuple(fr["vindu"]) != tuple(hele):
                    fr["vindu"] = list(hele)
                    g2.skriv_fremdrift(navn, fr)
                post = g2.hent_alle(ee, navn, vann, [aar], hele, valg, True, max(1, a.parallell), budsjett)
                serier = g2.les_raa(navn)
                komplett = post["komplett"]
                if post["stoppet_budsjett"]:
                    ut = 3
                if post["stoppet_tid"]:
                    ut = 4
            vent = ventende_vann(nr, vann, aar)
            if rest and vent and ut == 0:
                post_r = g2.hent_alle(ee, navn + "_rest", vent, [aar], rest, valg, False, max(1, a.parallell), budsjett)
                for k, rader in g2.les_raa(navn + "_rest").items():
                    serier.setdefault(k, []).extend(rader)
                if post_r["stoppet_budsjett"]:
                    ut = 3
                if post_r["stoppet_tid"]:
                    ut = 4
            # Bare vann der alle HELE måneder er hentet (ellers ville et halvt år gi feil status)
            med = vann if komplett is None else [v for v in vann if (v["vatnlnr"], aar) in komplett]
            res = g2.bygg_resultat(med, serier, [aar], valg)
            nye, endret, beholdt = slaa_inn_sesong(nr, res, aar, valg)
            n_ok = sum(1 for v in res.values() if v["aar"].get(str(aar), {}).get("status") == "ok")
            stats[nr] = {"vann": len(vann), "ventet": len(vent), "ok": n_ok, "nye": nye, "endret": endret, "beholdt_ok": beholdt}
            g2.logg("Fylke %s: %d vann, %d ventet på isgang, %d med isgang nå (%d nye, %d endret, %d funnet isgang beholdt)." % (
                nr, len(vann), len(vent), n_ok, nye, endret, beholdt))
            if ut:
                break
        ses.update({"aar": aar, "siste_kjoring": dt.datetime.now().isoformat(timespec="seconds"), "fylker": stats,
                    "hele": list(hele) if hele else None, "rest": list(rest) if rest else None, "kode": ut})
        g2.skriv_plan(plan)
        return ut
    finally:
        brukt = int((time.time() - t0) / 60)
        env = os.environ.get("GITHUB_ENV")
        if env:
            with open(env, "a", encoding="utf-8") as fh:
                fh.write("SESONG_MIN=%d\n" % brukt)


if __name__ == "__main__":
    sys.exit(main())
