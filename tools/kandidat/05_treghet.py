"""
Kandidatmodell — steg 5: treghets-testen. Kan isen fortelle hvor «tregt» et
vann er, som erstatning for snittdybde (som nesten ikke finnes)?

Idé: et dypt vann mister isen senere enn været alene tilsier. Forsinkelsen
= observert isgang − isgang modellert fra vær (K6, kalibrert i steg 2), i
snitt over årene, er et mål på vannets treghet.

Tester:
  A. Nordmarkas 16 vann (Stians isgang 2017–2026): er forsinkelsen stabil
     per vann (ikke bare støy), og forklarer den noe UTOVER høyden?
  B. De vulgata-observasjonene som navngir et vann: henger klekkefeilen
     fra K2 sammen med vannets is-forsinkelse?
"""
import importlib.util
import io
import json
import os
import statistics
import sys
from datetime import date

HER = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m2", os.path.join(HER, "02_modeller.py"))
m2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m2)

ISG_PAR = {"a": 4.0, "b": 80}      # fra steg 2
OMR = "Nordmarka"


def main():
    vann = {k.split("/", 1)[1]: v for k, v in m2.ISG.items() if k.startswith("nordmarka_dyn/")}
    L = ["# Treghets-testen: is-forsinkelse som erstatning for dybde\n",
         "Isgang modellert fra vær: tine-graddager fra 1. mars ≥ 4·√(frysegraddager) + 80 (steg 2). "
         "Forsinkelse = observert isgang (Stians avlesning) − modellert, per vann og år.\n",
         "## A. Nordmarkas 16 vann\n",
         "| Vann | moh | Snitt forsinkelse (d) | Spredning år til år (d) | n år |",
         "|---|---|---|---|---|"]
    fors = {}
    for navn, v in sorted(vann.items(), key=lambda kv: kv[1]["moh"]):
        f = []
        for y, s in v["aar"].items():
            y = int(y)
            mdl = m2.isgang_modell(OMR, y, v["moh"], ISG_PAR["a"], ISG_PAR["b"])
            if mdl:
                f.append((m2.d(s) - mdl).days)
        if len(f) >= 5:
            fors[navn] = (statistics.mean(f), statistics.pstdev(f), v["moh"])
            L.append("| %s | %d | %+.1f | %.1f | %d |" % (navn, v["moh"], fors[navn][0], fors[navn][1], len(f)))
    # høyde forklarer hvor mye? enkel lineær regresjon forsinkelse ~ moh
    xs = [v[2] for v in fors.values()]
    ys = [v[0] for v in fors.values()]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0
    a = my - b * mx
    rest = {k: v[0] - (a + b * v[2]) for k, v in fors.items()}
    r2 = 1 - sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / sum((y - my) ** 2 for y in ys) if len(ys) > 2 else 0
    L.append("\nForsinkelse mot høyde: %+.2f d per 100 m, R² = %.2f. Spredningen MELLOM vann i snitt-forsinkelse er %.1f d, "
             "spredningen INNEN vann fra år til år er i snitt %.1f d. Rest etter høyde (treghets-indeks):\n"
             % (b * 100, r2, statistics.pstdev(ys), statistics.mean(v[1] for v in fors.values())))
    L.append("| Vann | Rest etter høyde (d) |")
    L.append("|---|---|")
    for k, v in sorted(rest.items(), key=lambda kv: kv[1]):
        L.append("| %s | %+.1f |" % (k, v))

    # B. klekkeobs som navngir vann
    obs = json.load(io.open(os.path.join(m2.DATA, "obs.json"), encoding="utf-8"))
    kand = m2.lag_kandidater(None)
    f2, _ = kand["K2 varmesum fra 1. april"]
    L.append("\n## B. Vulgata-observasjoner på navngitte Nordmarka-vann\n")
    L.append("| År | Lokalitet | Fase | Obs | K2 (450) | Feil | Vannets rest-forsinkelse |")
    L.append("|---|---|---|---|---|---|---|")
    n = 0
    for o in obs:
        if o["omr"] != "Nordmarka" or o["art"] != "vulgata":
            continue
        treff = [k for k in rest if k.split()[0].lower() in o["lok"].lower()]
        if not treff:
            continue
        p = f2(o, 450)
        if not p:
            continue
        e = (p - m2.d(o["dato"])).days
        L.append("| %d | %s | %s | %s | %s | %+d | %s |" % (o["aar"], o["lok"][:40], o["fase"][:18], o["dato"], p.isoformat(), e,
                                                         ", ".join("%s %+.1f" % (k, rest[k]) for k in treff)))
        n += 1
    if n < 4:
        L.append("\nFor få observasjoner (%d) på navngitte vann til å si noe om sammenhengen. "
                 "Testen kan først gjøres når OFA-/brukerobservasjoner per vann foreligger.\n" % n)
    io.open(os.path.join(HER, "KANDIDATMODELL_treghet.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
