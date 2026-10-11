# Isgang for hele Norge i GEE (g2) — framdrift per fylke

Oppdatert 2026-10-11T09:59. Vindu 02-01–07-16, 2017–2026, vann >= 10 ha, vann over 3000 ha droppet. Piksel 20 m <= 150 ha, 40 m 150-600 ha, 60 m > 600 ha. Referansenettets vann-år (644 vann, 20 m, vindu 03-01–07-16) beholdes uendret; vann som alt lå inne for alle årene hentes ikke på nytt.

Kvote denne måneden (2026-10): brukt **38.0 EECU-t (estimat)** av budsjett 950 t. Estimat, ikke avlest: 30 EECU-s per vann-år på 20 m (vindu 03-01–07-16), skalert med (20/piksel)^2 og vinduslengde. Stians eget forbruk før 11. okt 2026 (39,23 % = 58,8 t) ligger IKKE her.

| nr | Fylke | Status | Vann NVE | Droppet > maks | Alt i datasettet | I kjøringen | Vann-år komplette / i alt | A | B | C | X | Estimat EECU-t (NVE) | Brukt EECU-t (estimat) | Start | Slutt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 03 | Oslo | ferdig | 31 | 0 | 29 | 2 | 20 / 20 | 2 | 7 | 11 | 0 | 2.7 | 0.1 | 2026-10-11T09:05 | 2026-10-11T09:07 |
| 32 | Akershus | ferdig | 297 | 2 | 69 | 226 | 2260 / 2260 | 949 | 544 | 678 | 89 | 28.0 | 21.3 | 2026-10-11T09:07 | 2026-10-11T09:34 |
| 31 | Østfold | ferdig | 146 | 1 | 37 | 108 | 1080 / 1080 | 270 | 307 | 357 | 146 | 13.1 | 1.2 | 2026-10-11T09:34 | 2026-10-11T09:54 |
| 33 | Buskerud | kjører | 847 | 3 | 37 | 807 |  / 8070 |  |  |  |  | 79.3 |  | 2026-10-11T09:54 |  |
| 39 | Vestfold | venter | 52 | 0 |  |  |  |  |  |  |  | 4.5 |  |  |  |
| 40 | Telemark | venter | 1144 | 8 |  |  |  |  |  |  |  | 106.9 |  |  |  |
| 34 | Innlandet | venter | 1730 | 9 |  |  |  |  |  |  |  | 160.2 |  |  |  |
| 50 | Trøndelag | venter | 2037 | 8 |  |  |  |  |  |  |  | 190.0 |  |  |  |
| 42 | Agder | venter | 1782 | 3 |  |  |  |  |  |  |  | 171.0 |  |  |  |
| 11 | Rogaland | venter | 1026 | 0 |  |  |  |  |  |  |  | 97.7 |  |  |  |
| 46 | Vestland | venter | 2357 | 2 |  |  |  |  |  |  |  | 223.8 |  |  |  |
| 15 | Møre og Romsdal | venter | 744 | 0 |  |  |  |  |  |  |  | 71.5 |  |  |  |
| 18 | Nordland | venter | 1991 | 4 |  |  |  |  |  |  |  | 182.3 |  |  |  |
| 55 | Troms | venter | 1163 | 1 |  |  |  |  |  |  |  | 111.6 |  |  |  |
| 56 | Finnmark | venter | 3760 | 2 |  |  |  |  |  |  |  | 363.9 |  |  |  |
| | **Sum** | | 19107 | 43 | | | | | | | | 1806.4 | 22.5 | | |

Droppede vann (> 3000 ha):

| Fylke | vatnLnr | Navn | ha |
|---|---|---|---|
| Akershus | 113 | Øyeren | 7309 |
| Akershus | 141 | Hurdalssjøen | 3320 |
| Østfold | 291 | Vansjø | 3558 |
| Buskerud | 514 | Sperillen | 3732 |
| Buskerud | 521 | Krøderen | 4391 |
| Buskerud | 522 | Tyrifjorden | 13656 |

Lageret (fra 11. okt 2026): én fil per fylke i `norge/isgang_<fylkesnr>_<navn>.json` og `.csv` (samme skjema som det gamle `isgang_norge.json/.csv`; grensesjøer uten kommnr i `isgang_00_uten_fylke`), pluss den lette samlefila `isgang_norge_index.csv` (vatnLnr, navn, fylke, aar, status, lo, hi, midt, bredde_d, klasse — uten passlista). **Kartet og modellen leser `isgang_norge_index.csv`.** Den oppdateres etter hvert fylke; bygg den på nytt med `python g2_gee_norge.py --samle` (ingen innlogging).

Gjenstår: Buskerud (kjører), Vestfold (venter), Telemark (venter), Innlandet (venter), Trøndelag (venter), Agder (venter), Rogaland (venter), Vestland (venter), Møre og Romsdal (venter), Nordland (venter), Troms (venter), Finnmark (venter) (ca. 1763 EECU-t etter NVE-tellingen).

Gjenoppta (fra tools\research_analyser\G_gee): `python g2_gee_norge.py --norge --fortsett --parallell 4 --budsjett-timer 950`. Kvoteboka nullstilles automatisk når kalendermåneden skifter.
