# tools/isgang — trinn 0 i vinterplanen 2026/27

Spørsmålet: kan Copernicus sitt ferdige is/vann-produkt gi isgangsdato per
vann som stemmer med de 160 datoene Stian har lest av for hånd?

Verktøyet rører ikke nettsiden. Ingenting her deployes.

## Viktig avvik fra planen

Planen pekte på RLIE/ARLIE (HR-S&I). Det prosjektet ble avsluttet i 2025, og
katalogen ble stengt 30. juni 2025. Etterfølgeren heter **HR-WSI**, og
produktet heter **Water and Ice Cover (WIC)**:

| Planen sa | Gjelder nå | Merknad |
|---|---|---|
| RLIE S2 | WIC S2, 20 m, daglig | optisk, skyer gir hull |
| RLIE S1 / S1+S2 | WIC S1+S2, 20 m, daglig | radar + optisk, ser gjennom skyer |
| ARLIE (ferdig per innsjø) | AWIC | ikke brukt her: vi sender egne polygoner |
| dekning «34–66°N» | 27–72°N | Kautokeino er innenfor |
| `hrsi-rlie-s2` | `byoc-4c770f75-…` i CDSE | se `02_hent_wic.py` |

Arkivet går fra 2016 til i dag, og hentes med Sentinel Hub Statistical API
i Copernicus Data Space Ecosystem (CDSE). Gratiskvote: 10 000 PU per måned.

## Slik kjøres det

1. `python 01_bygg_grunnlag.py` — fasit fra dashboard.html + polygoner fra NVE.
   Krever ingen konto. Allerede kjørt 5. okt 2026.
2. `python 02_hent_wic.py --prov` — ett vann, ett år. Viser at kontoen virker
   og hva en full kjøring vil koste.
3. `python 02_hent_wic.py --kilde begge` — alle 16 vann, 2017–2026.
4. `python 03_valider.py` — skriver `rapport.md` og `isgang_satellitt.json`.

## Konto (gjøres av Stian, én gang)

1. Registrer bruker på dataspace.copernicus.eu og bekreft e-posten.
2. Logg inn på shapps.dataspace.copernicus.eu/dashboard → User settings →
   OAuth clients → Create. Navn: `HatchWatch isgang`.
3. Kopier **Client ID** og **Client secret**. Hemmeligheten vises bare én gang.
4. Kopier `.env.example` til `.env` i denne mappa og lim inn de to verdiene.

`.env` skal aldri deles, limes inn i en chat eller legges ut.

## Regler satt før dataene ble hentet

Står i sin helhet øverst i `03_valider.py`. Kort:

- Isgang = første klare pass med under 20 % is, bekreftet av neste klare pass,
  etter at det er sett is samme vår. Rapporteres som intervall.
- **Bestått** når minst 70 % av vann-årene har fasiten innenfor intervallet
  eller høyst 3 dager utenfor, skjevheten er høyst 2 dager, og median
  intervallbredde er høyst 7 dager.
- Er intervallene bredere enn 7 dager, er testen **uavklart**, ikke bestått.
- Tersklene 0,50 og 0,10 vises for følsomhet. Ingen terskel velges i etterkant.

## Det testen ikke kan si

- Fasiten er Stians avlesning av de samme Sentinel-bildene. Testen måler om
  algoritmen er enig med øyet, ikke en uavhengig sannhet.
- Tre vannpar har identiske datoer alle år (Øyungen = Gåslungen, Måsjøen
  Sør = Nord, Auretjern Nord = Sør). Det er 13 ulike serier, ikke 16.
- WIC klassifiserer bare piksler innenfor Copernicus sin egen vannmaske. Små
  tjern kan mangle. Kolonnen «Piksler» i rapporten viser hvor mange piksler
  hvert vann faktisk fikk.

## Oversikt over skriptene (per 6. okt 2026)

| Skript | Gjør |
|---|---|
| 01_bygg_grunnlag.py | fasit fra dashboard.html + NVE-polygoner (Nordmarka) |
| 02_hent_wic.py / 03_valider.py | trinn 0: ferdig Copernicus-produkt (feilet) |
| 04_hent_s2.py / 05_valider_s2.py | trinn 1: egen klassifisering fra rå Sentinel-2 |
| 06_dagens_modell.py | dagens hybrid-ismodell mot samme fasit |
| 07_andre_steder.py | låst metode, uavhengig test på 14 vann ellers i landet |
| 08_forslag.py + nabo.py | forslagstabell for alle vann, med nabo-regel |
| 09_hent_s1.py / 10_valider_s1.py | radar-eksperiment (Sentinel-1 som bekreftelse) |
| 11_referansenett.py | landsdekning steg 1: alle vann ≥ 10 ha rundt lokasjonene |
| kjor_sesong.py | trinn A: ukentlig avlesning av årets isgang for de 31 vannene |
| sky_hent.py + sky/ | skyjobben: hele områder, kjøres av GitHub hver natt (se under) |
| test_tiaar*.py | eksperiment 7. okt: ti år i én forespørsel (10× raskere i kø, 1,6× kvote) |

## Skyjobben (fra 7. okt 2026)

`.github/workflows/isgang.yml` kjører `sky_hent.py` hos GitHub hver natt
kl. 21 UTC. Den tar områdene i `sky/plan.json` i rekkefølge, henter hvert
vann-år som mangler (én forespørsel per vann og år), regner intervallet med
den låste metoden og lagrer bare resultatet i `sky/isgang_<område>.json`
pluss en lesbar `sky/status_<område>.md`. Rådata kastes. Jobben stopper selv
etter 5,25 timer eller ved 20 000 PU i måneden (av 30 000), og fortsetter
neste natt. Nye områder: legg en boks i `sky/omraader.json` og id-en i
`sky/plan.json`. Vann på 10–3 000 ha med midtpunkt i boksen tas med.

Fra 8. okt lagres også «p» per vann-år: en kompakt liste over alle pass
(MMDD:n/mørk/lys_is/lys_annet/sky, ca. 1 KB). Med den kan klar-pass-regelen
og isandel-terskelen regnes om i ettertid uten å hente fra satellitten; bare
lyshets-/ndsi-terskelen (tv, tn) er låst i tallene. Vann-år uten «p» (natt 1)
hentes automatisk på nytt.

Resultatfilene eies av jobben og ligger kun i repoet på GitHub.
`deploy_now.py` laster dem aldri opp. Nøklene ligger som GitHub-hemmeligheter
(CDSE_CLIENT_ID, CDSE_CLIENT_SECRET), aldri i filer.

Hvorfor ikke ti år i én forespørsel: det er ti ganger raskere i køen, men
koster 1,6 ganger mer kvote fordi høst og vinter følger med. Kvoten er
flaskehalsen i skyen, så jobben henter per år.

Copernicus behandler forespørsler i kø: 5–25 per minutt uansett hvor mange
jobber som kjører. Store hentinger tar timer og bør gå i bakgrunnen.
Innloggingen varer én time; 02_hent_wic.send() logger inn på nytt selv.

## Funn underveis som Stian bør se på

- Lille Åklungen: koden sier 293 moh, NVE sier 259 moh.
- Søndre Heggelivatnet: koden sier 488 moh, NVE sier 500 moh.
- NVE har dybdekart for 4 av de 16: Øyungen, Gåslungen, Storflåtan, Katnosa.
  Relevant for vanntemp-modellen i trinn 0b, som trenger dybde.
