"""Steg 5b: treghet målt RELATIVT, uten værmodell. Per år: vannets isgang minus
medianen for alle 16 Nordmarka-vann samme år. Været er likt for alle, så det
som står igjen er vannets egen treghet (pluss høyde). Snitt over år = indeks."""
import importlib.util, io, os, statistics, sys
HER = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("m2", os.path.join(HER, "02_modeller.py"))
m2 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m2)

vann = {k.split("/", 1)[1]: v for k, v in m2.ISG.items() if k.startswith("nordmarka_dyn/")}
aar = sorted({int(y) for v in vann.values() for y in v["aar"]})
rel = {k: [] for k in vann}
for y in aar:
    datoer = {k: m2.doy(m2.d(v["aar"].get(y) or v["aar"].get(str(y)))) for k, v in vann.items() if (v["aar"].get(y) or v["aar"].get(str(y)))}
    if len(datoer) < 8:
        continue
    med = statistics.median(datoer.values())
    for k, dd in datoer.items():
        rel[k].append(dd - med)
L = ["# Treghet målt relativt (uten værmodell): isgang minus områdets median samme år\n",
     "| Vann | moh | Snitt relativ isgang (d) | Spredning år til år (d) |", "|---|---|---|---|"]
snitt = {}
for k, v in sorted(vann.items(), key=lambda kv: kv[1]["moh"]):
    if len(rel[k]) >= 5:
        snitt[k] = (statistics.mean(rel[k]), statistics.pstdev(rel[k]), v["moh"])
        L.append("| %s | %d | %+.1f | %.1f |" % (k, v["moh"], snitt[k][0], snitt[k][1]))
xs = [v[2] for v in snitt.values()]; ys = [v[0] for v in snitt.values()]
mx, my = statistics.mean(xs), statistics.mean(ys)
b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
a = my - b * mx
r2 = 1 - sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / sum((y - my) ** 2 for y in ys)
L.append("\nMot høyde: %+.2f d per 100 m, R² = %.2f. Spredning mellom vann %.1f d, innen vann år til år i snitt %.1f d.\n"
         % (b * 100, r2, statistics.pstdev(ys), statistics.mean(v[1] for v in snitt.values())))
L.append("| Vann | Rest etter høyde (d) = treghets-indeks |"); L.append("|---|---|")
for k, v in sorted(snitt.items(), key=lambda kv: kv[1][0] - (a + b * kv[1][2])):
    L.append("| %s | %+.1f |" % (k, v[0] - (a + b * v[2])))
t = "\n".join(L) + "\n"
io.open(os.path.join(HER, "KANDIDATMODELL_treghet.md"), "a", encoding="utf-8").write("\n" + t)
print(t)
