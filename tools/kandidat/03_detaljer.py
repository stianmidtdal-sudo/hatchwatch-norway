"""Steg 3: residualer per observasjon for de to beste kandidatene (K2 og K1b0),
med terskelen valgt på ALT (ikke kryssvalidert — bare for å se hvor feilene sitter)."""
import importlib.util, io, json, os, sys
from datetime import date

HER = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m2", os.path.join(HER, "02_modeller.py"))
m2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m2)

obs = json.load(io.open(os.path.join(m2.DATA, "obs.json"), encoding="utf-8"))
obs = [o for o in obs if o["aar"] >= 2003]
kand = m2.lag_kandidater(None)
L = ["# Residualer per observasjon (terskel valgt på hele utvalget)\n"]
for art in ("vulgata", "marginata"):
    ob = [o for o in obs if o["art"] == art or (art == "marginata" and o["art"] == "marginata/vespertina")]
    for navn in ("K2 varmesum fra 1. april", "K1b0 varmesum fra 1. jan, base 0"):
        f, grid = kand[navn]
        v = m2.velg_terskel(f, grid, ob)
        G = v[1]
        L.append("## %s — %s, terskel %s\n" % (art, navn, G))
        L.append("| Område | År | Lokalitet | Fase | Obs | Prognose | Feil (d) | moh |")
        L.append("|---|---|---|---|---|---|---|---|")
        per_omr = {}
        for o in sorted(ob, key=lambda o: (o["omr"], o["aar"])):
            p = f(o, G)
            if not p:
                continue
            e = (p - m2.d(o["dato"])).days
            if o["klasse"] == "start":
                per_omr.setdefault(o["omr"], []).append(abs(e))
            merk = "" if o["klasse"] == "start" else (" (grense%s)" % (", BRUDD" if e > 0 else ""))
            L.append("| %s | %d | %s | %s%s | %s | %s | %+d | %s |" % (o["omr"], o["aar"], o["lok"][:40], o["fase"][:22], merk, o["dato"], p.isoformat(), e, o["moh"]))
        L.append("\nMAE per område (start-obs): " + ", ".join("%s %.1f (n=%d)" % (k, sum(v) / len(v), len(v)) for k, v in sorted(per_omr.items())) + "\n")
io.open(os.path.join(HER, "KANDIDATMODELL_residualer.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
print("\n".join(l for l in L if l.startswith("MAE per") or l.startswith("## ")))
