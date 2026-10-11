"""
Engangs-såing av GEE-lageret til GitHub (G5, 11. okt 2026).

GitHub-jobben .github/workflows/isgang_gee.yml trenger det PC-en alt har hentet for å fortsette
der den slapp (ellers hentes alt på nytt og kvoten brukes to ganger):
  norge/isgang_<nr>_<navn>.json + .csv   de fulle fylkesfilene (med passlista «p»)
  data/serier_fylke_NN.csv               rådata per pass
  data/fremdrift_fylke_NN.json           hvilke enheter (rute × år × måneds-bit) som er hentet
  vann/fylke_NN.json                     vannlistene — MÅ følge med: rute-id-ene i framdrifta
                                         bygger på rekkefølgen i denne lista
  kjorelogg_g2.json                      kjøreloggen
Disse er for store for et offentlig git-repo, så de pakkes i gee-lager.zip og legges som
release-asset på taggen «gee-lager-seed» i repoet. Jobben henter zipen første gang den kjører
(etterpå bruker den sin egen artifact fra forrige kjøring, og release-en kan slettes).

norge_plan.json pakkes IKKE — den ligger i git og deployes med deploy_now.py (første gang).

Rekkefølgen filene leses i er med vilje: framdriftsfila FØR rådatafila per fylke. Går den lokale
prosessen samtidig, kan rådata da i verste fall ha én enhet mer enn framdrifta (den hentes én gang
til og dobbeltrader gjør ingen skade i finn_isgang) — aldri omvendt (enhet merket hentet uten rader).

Kjør (fra denne mappa):   python g5_lager_til_github.py            pakk og last opp
                          python g5_lager_til_github.py --bare-zip  bare pakk (last opp selv under Releases)
Token: «GitHub token.txt» i prosjektmappa (samme som deploy_now.py). Ingen hemmeligheter i fila.
"""
import io
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import zipfile

HER = os.path.dirname(os.path.abspath(__file__))
ROT = os.path.abspath(os.path.join(HER, "..", "..", ".."))
REPO = "stianmidtdal-sudo/hatchwatch-norway"
TAG = "gee-lager-seed"
ASSET = "gee-lager.zip"
ZIP = os.path.join(HER, ASSET)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                   # noqa: BLE001
    pass


def filer():
    """[(sti relativt til G_gee)] i trygg leserekkefølge."""
    ut = []
    norge = os.path.join(HER, "norge")
    if os.path.isdir(norge):
        for fn in sorted(os.listdir(norge)):
            if fn.endswith((".json", ".csv")) and not fn.endswith(".tmp"):
                ut.append("norge/" + fn)
    plan = os.path.join(HER, "norge_plan.json")
    fylker = []
    if os.path.exists(plan):
        fylker = [f["nr"] for f in json.load(io.open(plan, encoding="utf-8")).get("fylker", [])]
    for nr in fylker:
        for rel in ("vann/fylke_%s.json" % nr, "data/fremdrift_fylke_%s.json" % nr, "data/serier_fylke_%s.csv" % nr):
            if os.path.exists(os.path.join(HER, rel)):
                ut.append(rel)
    if os.path.exists(os.path.join(HER, "kjorelogg_g2.json")):
        ut.append("kjorelogg_g2.json")
    return ut


def pakk():
    liste = filer()
    if not any(r.startswith("norge") for r in liste):
        raise SystemExit("Fant ingen fylkesfiler i norge/ — ingenting å så.")
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in liste:
            sti = os.path.join(HER, *rel.split("/"))
            z.write(sti, rel)
            print("  %-40s %8.1f MB" % (rel, os.path.getsize(sti) / 1e6))
    print("%s: %d filer, %.1f MB pakket." % (ASSET, len(liste), os.path.getsize(ZIP) / 1e6))


def gh(token, method, url, data=None, rå=None, ctype="application/json"):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "token %s" % token)
    req.add_header("Accept", "application/vnd.github+json")
    if data is not None:
        req.data = json.dumps(data).encode()
        req.add_header("Content-Type", "application/json")
    if rå is not None:
        req.data = rå
        req.add_header("Content-Type", ctype)
    ctx = ssl.create_default_context()
    for forsok in (0, 1):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=900) as r:
                tekst = r.read()
                return (json.loads(tekst) if tekst else {}), r.status
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read()), e.code
            except Exception:                       # noqa: BLE001
                return {"message": str(e)}, e.code
        except ssl.SSLError:
            if forsok:
                raise
            # som deploy_now.py: PC-en har hatt trøbbel med sertifikatkjeden — prøv én gang uten verifisering
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE


def last_opp():
    sti = os.path.join(ROT, "GitHub token.txt")
    if not os.path.exists(sti):
        raise SystemExit("Fant ikke «GitHub token.txt» i %s. Kjør med --bare-zip og last opp %s selv under Releases → %s." % (ROT, ASSET, TAG))
    token = io.open(sti, encoding="utf-8").read().strip()
    api = "https://api.github.com/repos/%s" % REPO
    rel, st = gh(token, "GET", api + "/releases/tags/" + TAG)
    if st == 404:
        rel, st = gh(token, "POST", api + "/releases", {
            "tag_name": TAG, "name": "GEE-lager (engangs-såing til isgang-gee-jobben)", "prerelease": True,
            "body": "Fulle fylkesfiler, rådata og vannlister fra PC-en, så GitHub-jobben isgang-gee kan fortsette "
                    "der PC-en slapp. Lagd av tools/research_analyser/G_gee/g5_lager_til_github.py. "
                    "Kan slettes når jobben har kjørt én gang og laget sin egen artifact «gee-lager»."})
        if st not in (200, 201):
            raise SystemExit("Kunne ikke lage release: %s %s" % (st, rel.get("message")))
        print("Laget release «%s»." % TAG)
    elif st != 200:
        raise SystemExit("Kunne ikke lese release: %s %s" % (st, rel.get("message")))
    for a in rel.get("assets", []):
        if a["name"] == ASSET:
            _, st = gh(token, "DELETE", api + "/releases/assets/%d" % a["id"])
            print("Slettet gammel %s (%s)." % (ASSET, st))
    print("Laster opp %s (%.1f MB) ..." % (ASSET, os.path.getsize(ZIP) / 1e6))
    url = "https://uploads.github.com/repos/%s/releases/%d/assets?name=%s" % (REPO, rel["id"], ASSET)
    svar, st = gh(token, "POST", url, rå=io.open(ZIP, "rb").read(), ctype="application/zip")
    if st not in (200, 201):
        raise SystemExit("Opplasting feilet: %s %s" % (st, svar.get("message")))
    print("Ferdig: %s" % svar.get("browser_download_url"))
    print("Jobben henter den fra https://github.com/%s/releases/download/%s/%s" % (REPO, TAG, ASSET))


if __name__ == "__main__":
    pakk()
    if "--bare-zip" not in sys.argv:
        last_opp()
