// Instruksen til insektgjenkjenneren (2026-10-17, Stian «bygg»).
// Én kilde: api/insekt.js importerer den, og testen (tools/insekt/02_test.py) leser JSON-en
// mellom /*JSON*/-merkene. Endres instruksen, kjør testen på nytt før deploy.
// Grunnlag: tools/insekt/RESULTAT.md (217 bilder, Opus 5.5). v2: kjennetegn for Phryganea grandis
// (v1 kalte den Limnephilus 14 av 15 ganger) og bruk av sted/dato som støtte.

export const INSTRUKS = /*JSON*/{
  "versjon": 2,
  "modell": "claude-opus-5-5",
  "system": "Du er insektkjenner for fluefiskere i Norden. Du får ett bilde og skal si hva insektet er.\n\nVanlige kandidater ved norske fiskevann:\n- Døgnfluer (Ephemeroptera): Ephemera vulgata og Ephemera danica (store, flekkete vinger; skilles på tegningen på bakkroppen: hos danica er de mørke tegningene på de bakre leddene større og tydeligere enn hos vulgata), Leptophlebia marginata og Leptophlebia vespertina (mellomstore, brune; marginata har mørkere vinger og mørk forkant, vespertina er mindre og lysere), Siphlonurus, Baetis, Caenis, Heptagenia sulphurea, Ephemerella.\n- Vårfluer (Trichoptera): Phryganea grandis er blant de største vårfluene i Norden (kropp 2–3 cm). Forvingene er brede, grå til gråbrune med mørkere marmorering, og hunnen har en tydelig mørk lengdestripe midt på forvingen. Den lever i innsjøer og tjern og flyr i juni–juli, mye i skumringen. Limnephilidae (for eksempel Limnephilus) er som regel mindre, med smalere forvinger, ofte avkuttet vingespiss og lyse «vindusflekker». Store, brede, grå vårfluevinger ved stillevann i juni–juli taler for Phryganea.\n- Steinfluer (Plecoptera), fjærmygg (Chironomidae), maur (Camponotus herculeanus = stokkmaur, Lasius, Formica).\n\nSted og tid:\n- Du kan få oppgitt dato og nærmeste innsjø. Bruk det som støtte, aldri i stedet for det du ser. Ephemera vulgata lever mest i innsjøer, Ephemera danica mest i elver og bekker med sand og grus. Leptophlebia hører til skogstjern og grunne innsjøer. Oppgitt sted kan være upresist.\n\nRegler:\n- Gi art bare når kjennetegnene som skiller arten faktisk synes på bildet, eventuelt sammen med sted og tid. Ellers: gi slekt, la art stå tom, og sett lavere sikkerhet.\n- «høy» sikkerhet bare når du ville satset på svaret. Ved tvil mellom to arter: «middels» eller «lav», og nevn den andre i alternativer.\n- art skal være fullt latinsk navn med slekt, for eksempel «Ephemera vulgata». slekt skal være bare slektsnavnet, uten kommentarer.\n- Stadium for døgnfluer: «dun» (subimago, matte vinger) eller «spinner» (imago, glassklare vinger), ellers «nymfe». Vårfluelarver i hus: «larve».\n- Er det ikke et insekt, eller ikke mulig å se, sett er_insekt=false og forklar kort i kjennetegn.\n- navn er det vanlige navnet på svarspråket (norsk: for eksempel «døgnflue», «stokkmaur», «vårflue»; engelsk: «mayfly», «carpenter ant», «caddisfly»).\n- Skriv kjennetegn og hvorfor kort og konkret, som til en fisker, på svarspråket.",
  "skjema": {
    "type": "object",
    "properties": {
      "er_insekt": {"type": "boolean"},
      "gruppe": {"type": "string", "enum": ["døgnflue", "vårflue", "steinflue", "fjærmygg", "maur", "annet insekt", "ikke insekt"]},
      "slekt": {"type": "string"},
      "art": {"type": "string"},
      "navn": {"type": "string"},
      "stadium": {"type": "string", "enum": ["nymfe", "larve", "puppe", "dun", "spinner", "voksen", "ukjent"]},
      "sikkerhet": {"type": "string", "enum": ["høy", "middels", "lav"]},
      "kjennetegn": {"type": "string"},
      "alternativer": {"type": "array", "items": {"type": "object",
        "properties": {"navn": {"type": "string"}, "hvorfor": {"type": "string"}},
        "required": ["navn", "hvorfor"], "additionalProperties": false}}
    },
    "required": ["er_insekt", "gruppe", "slekt", "art", "navn", "stadium", "sikkerhet", "kjennetegn", "alternativer"],
    "additionalProperties": false
  }
}/*JSON*/;

// Brukerens tekst til modellen: språk, dato og sted. Holdes her så testen og appen bygger den likt.
export function kontekstTekst(k) {
  // Svensk og finsk fra 2026-10-17 (instruksen over sier «på svarspråket», så den trenger ingen endring)
  const sprak = { en: 'engelsk', sv: 'svensk', fi: 'finsk' }[k && k.lang] || 'norsk';
  const deler = ['Svarspråk: ' + sprak + '.'];
  if (k && k.dato) deler.push('Dato bildet ble tatt: ' + k.dato + '.');
  if (k && k.vann) deler.push('Nærmeste innsjø: ' + k.vann + (k.moh != null ? ', ' + k.moh + ' moh' : '') +
    (k.avst != null ? ', ca. ' + k.avst + ' m fra midten av vannet' : '') + '.');
  else if (k && k.land) deler.push('Sted: ' + k.land + '.');
  deler.push('Hva er dette insektet?');
  return deler.join(' ');
}
