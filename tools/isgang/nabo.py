"""
Nabo-regel: tette skyhull med pass fra et vann som historisk går likt.

Lagt inn 6. okt 2026 etter Stians forslag. Utforskningen i Nordmarka viste
at beste «nabo» (fritt valgt i området, ikke nødvendigvis nærmest) har en
spredning i isgangsforskjellen på rundt 1,4 dager, og at lånte pass gjør
intervallene litt smalere (median 13 → 11 d) uten flere bommer.

Sikringer (så et ærlig «vet ikke» ikke blir et falskt «vet»):
  - minst MIN_FELLES_AAR felles år med fasit, og årets egen dato holdes
    utenfor når forskyvningen regnes ut
  - spredningen i forskjellen må være høyst MAKS_SPREDNING dager
  - vannene må ligge innenfor MAKS_AVSTAND_KM av hverandre
  - resultatet merkes «indirekte» når et av intervallets endepunkter
    kommer fra et lånt pass

Brukes av 08_forslag.py. Lånte pass merkes med kilde=navn på vannet.
"""
import math
import statistics
from datetime import date, timedelta

MIN_FELLES_AAR = 5
MAKS_SPREDNING = 2.0
MAKS_AVSTAND_KM = 50.0


def _d(s):
    return date.fromisoformat(s)


def tyngdepunkt(geom):
    ringer = [geom["coordinates"][0]] if geom["type"] == "Polygon" else [p[0] for p in geom["coordinates"]]
    pts = [pt for r in ringer for pt in r]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def velg_nabo(vann, aar, fasit, posisjon):
    """Returnerer (nabo, forskyvning_dager, spredning) eller None.
    fasit: {vann: {år(str): 'YYYY-MM-DD'}}, posisjon: {vann: (x, y) i meter}."""
    best = None
    for b in fasit:
        if b == vann or b not in posisjon or vann not in posisjon:
            continue
        dx, dy = posisjon[b][0] - posisjon[vann][0], posisjon[b][1] - posisjon[vann][1]
        if math.hypot(dx, dy) / 1000.0 > MAKS_AVSTAND_KM:
            continue
        felles = [y for y in fasit[vann] if y in fasit[b] and int(y) != aar]
        if len(felles) < MIN_FELLES_AAR:
            continue
        diff = [(_d(fasit[vann][y]) - _d(fasit[b][y])).days for y in felles]
        spred = statistics.pstdev(diff)
        if spred > MAKS_SPREDNING:
            continue
        if best is None or spred < best[2]:
            best = (b, round(statistics.median(diff)), spred)
    return best


def laan_pass(egne, nabo_pass, forskyvning, nabo_navn):
    """Slår sammen egne klare pass [(dato, isandel)] med naboens, forskjøvet.
    Returnerer liste av (dato, isandel, kilde) sortert på dato."""
    ut = [(d, f, "egen") for d, f in egne]
    for d, f in nabo_pass:
        ut.append(((_d(d) + timedelta(days=forskyvning)).isoformat(), f, nabo_navn))
    ut.sort()
    return ut


def finn_isgang_med_kilde(klare3, terskel):
    """Som 03_valider.finn_isgang, men holder rede på om endepunktene er lånt."""
    klare = [(d, f) for d, f, _ in klare3]
    kilde = {d: k for d, _, k in klare3}
    if not klare:
        return {"status": "ingen klare pass", "lo": None, "hi": None, "indirekte": False}
    for k in range(len(klare)):
        dato, f = klare[k]
        if f >= terskel:
            continue
        if k + 1 >= len(klare):
            return {"status": "ubekreftet (siste pass i vinduet)", "lo": None, "hi": dato, "indirekte": kilde[dato] != "egen"}
        if klare[k + 1][1] >= terskel:
            continue
        tidligere = [j for j in range(k) if klare[j][1] >= terskel]
        if not tidligere:
            return {"status": "åpent ved første klare pass", "lo": None, "hi": dato, "indirekte": kilde[dato] != "egen"}
        lo = klare[tidligere[-1]][0]
        return {"status": "ok", "lo": lo, "hi": dato,
                "indirekte": kilde[lo] != "egen" or kilde[dato] != "egen",
                "laant_fra": sorted({kilde[lo], kilde[dato]} - {"egen"})}
    return {"status": "is i hele vinduet", "lo": klare[-1][0], "hi": None, "indirekte": False}
