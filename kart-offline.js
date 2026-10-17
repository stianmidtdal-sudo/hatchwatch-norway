// ═══════════════════════════════════════════════════════════════════
//  Kart uten nett (2026-10-16, Stian «kjør»)
//
//  Alle kartkilder på forsiden går gjennom to egne protokoller:
//    hwoff://<vert>/<sti>   → https://<vert>/<sti>   (OpenFreeMap, Kartverket, Turrutebasen, skrifter)
//    hwpm://<url>.pmtiles   → pmtiles://<url>         (våre egne vanndata)
//  Begge slår først opp i IndexedDB (databasen «hw-kart»). Finnes flisen der, brukes den, også uten nett;
//  ellers hentes den fra nettet som før. Bare «Last ned området» skriver til databasen.
//
//  Hva som lastes ned (vilkårene, sjekket 2026-10-16):
//    - OpenFreeMap (OpenStreetMap, ODbL): vektorfliser z5–14, med stier, bekker, myr og navn.
//    - Kartverkets topografiske kart (CC BY 4.0) BARE oversiktsnivåene. Kartverkets vilkår: nivå 12–20 i cache-
//      og WMS-tjenestene er Geovekst-data, og kopiering krever egen tillatelse. Lagring for bruk uten nett er
//      kopiering, så de detaljerte nivåene tas ikke med før vi eventuelt har tillatelse. Fra 17.10.2026 hentes
//      kartet som WMS uten grenselag (HW_KV_TOPO under): 512-px-fliser z4–10 = samme detaljnivå som cache-nivå 5–11.
//    - Turrutebasen (Kartverket, CC BY 4.0): merkede ruter z10–15.
//    - Våre egne vanndata (hatchwatch.pmtiles) z5–12.
//  Uten nett viser forsiden derfor Kartverket på oversiktsnivå og OpenStreetMap-detaljer innover (kart-
//  stilen bytter selv, se hwOff.utenNett i index.html).
//
//  Lagring: { k: nøkkel (https-URL, bbox avrundet), d: ArrayBuffer eller JSON-tekst, t: 'bin'|'json',
//  o: [områdeId, ...] } i «fliser»; områdene i «omrader». En flis som deles av to områder slettes først
//  når begge er slettet.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';
  // Kartverkets topografiske kart uten grenselinjer (2026-10-17, Stian «kjør»): samme kart som cache-flisene, men
  // fra WMS-tjenesten der lagene kan velges. Alle lag i «topo» unntatt kommune-/fylkes-/riksgrenser og sjøgrenser
  // (kd_administrative_grenser, adm_grenser), skytefelt/statsallmenning (kd_andre_grenser) og verneområdegrenser
  // (kd_verneomradegrense). PNG8 er halvparten så stor som PNG og ser lik ut. 512 px = færre forespørsler og færre
  // flisskjøter for navn. Én definisjon for forsiden og nedlastingen (nøkkelen må bli lik). Utenfor Norge er
  // bildet gjennomsiktig. Riksgrensen tegner forsiden selv (tu-grense).
  var KV_LAG = ['kd_hoydelag', 'kd_arealdekkeflate', 'fkb_arealdekke', 'fkb_vann', 'kd_hoydekurver', 'fkb_hoydekurver', 'fjellskygge',
    'kd_vannflate', 'kd_elver', 'Dybdelag', 'Dybdekontur', 'Torrfall', 'MudretOmrade_Grense', 'MudretOmrade', 'grunne', 'flytedokk_grense',
    'flytedokk', 'Torrdokk_Grense', 'Torrdokk', 'mudret_dybdetall', 'skjaer_punkt', 'Dybdepunkt', 'Konstruertkystkontur', 'Vannkontur',
    'kd_vannkontur', 'vannkontur', 'kd_veger', 'privatveg', 'kommunalveg', 'fylkesveg', 'riksveg', 'europaveg', 'bilferjestrekning',
    'passasjerferje', 'fkb_bygningsmessigeanlegg', 'fkb_samferdsel', 'kd_jernbane', 'kd_ferger', 'kd_anleggslinjer', 'fkb_bygning',
    'fkb_ledning', 'kd_bygninger', 'kd_spesiell_detalj', 'kd_hoydepunkt', 'kd_jernbanestasjon', 'kd_anleggspunkt', 'kd_bygningspunkt',
    'kd_turisthytte', 'kd_arealdekkepunkt', 'kd_tettsted', 'kd_stedsnavn', 'fkb_presentasjonsdata', 'vegnavn_fylk_nr', 'vegnavn_eur_riks_nr',
    'vegnavn', 'presentasjonsdata'];
  window.HW_KV_TOPO = {
    tileSize: 512,
    url: 'https://wms.geonorge.no/skwms1/wms.topo?service=WMS&version=1.3.0&request=GetMap&layers=' + KV_LAG.join(',') +
      '&styles=&format=image/png8&transparent=true&crs=EPSG:3857&width=512&height=512&bbox={bbox-epsg-3857}'
  };
  if (!window.maplibregl) return;

  var DB_NAVN = 'hw-kart', DB_VER = 1;
  var dbP = null;
  function db() {
    if (dbP) return dbP;
    dbP = new Promise(function (ok, feil) {
      if (!window.indexedDB) return feil(new Error('ingen IndexedDB'));
      var r = indexedDB.open(DB_NAVN, DB_VER);
      r.onupgradeneeded = function () {
        var d = r.result;
        if (!d.objectStoreNames.contains('fliser')) d.createObjectStore('fliser', { keyPath: 'k' });
        if (!d.objectStoreNames.contains('omrader')) d.createObjectStore('omrader', { keyPath: 'id' });
      };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { feil(r.error); };
    });
    dbP.catch(function () { dbP = null; });
    return dbP;
  }
  function req(r) { return new Promise(function (ok, feil) { r.onsuccess = function () { ok(r.result); }; r.onerror = function () { feil(r.error); }; }); }
  function hentFlis(k) {
    return db().then(function (d) { return req(d.transaction('fliser').objectStore('fliser').get(k)); }).catch(function () { return null; });
  }

  // WMS-adresser har bbox med lange desimaltall; MapLibre og nedlastingen regner dem litt ulikt. Nøkkelen
  // avrunder derfor bbox til hele meter, så samme flis alltid får samme nøkkel.
  // Skriftnavn kan komme med mellomrom eller %20; nøkkelen bruker alltid mellomrom. OpenFreeMap har versjonsnummer
  // i flisadressen (planet/20261011_080001_pt/...), som byttes når de oppdaterer; nøkkelen dropper det, så områder
  // lastet ned på ulike datoer passer sammen.
  function nokkel(url) {
    return url.replace(/%20/g, ' ').replace(/(tiles\.openfreemap\.org\/planet\/)[^/]+\//, '$1_/').replace(/([?&]bbox=)([^&]+)/i, function (_, p, b) {
      return p + b.split(',').map(function (x) { return Math.round(parseFloat(x)); }).join(',');
    });
  }

  // Områdelista holdes også i minnet, så kartet slipper databaseoppslag når ingenting er lastet ned
  var omrader = [];
  function lesOmrader() {
    return db().then(function (d) { return req(d.transaction('omrader').objectStore('omrader').getAll()); })
      .then(function (a) { omrader = (a || []).sort(function (x, y) { return y.dato - x.dato; }); return omrader; })
      .catch(function () { omrader = []; return omrader; });
  }
  var klar = lesOmrader();

  function tekst(d) { return typeof d === 'string' ? d : new TextDecoder().decode(d); }
  function omskrivTileJson(j, fra, til) {
    if (j && Array.isArray(j.tiles)) j.tiles = j.tiles.map(function (u) { return u.indexOf(fra) === 0 ? til + u.slice(fra.length) : u; });
    return j;
  }

  // ── hwoff:// ──
  maplibregl.addProtocol('hwoff', function (params, ac) {
    var ekte = 'https://' + params.url.slice('hwoff://'.length);
    var json = params.type === 'json';
    return klar.then(function () { return omrader.length ? hentFlis(nokkel(ekte)) : null; }).then(function (l) {
      if (l) return { data: json ? omskrivTileJson(JSON.parse(tekst(l.d)), 'https://', 'hwoff://') : l.d };
      return fetch(ekte, { signal: ac && ac.signal }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + ekte);
        return json ? r.json().then(function (j) { return { data: omskrivTileJson(j, 'https://', 'hwoff://') }; })
                    : r.arrayBuffer().then(function (b) { return { data: b }; });
      });
    });
  });

  // ── hwpm:// (våre egne pmtiles) ──
  var pm = window.pmtiles ? new pmtiles.Protocol() : null;
  maplibregl.addProtocol('hwpm', function (params, ac) {
    var json = params.type === 'json';
    return klar.then(function () { return omrader.length ? hentFlis(params.url) : null; }).then(function (l) {
      if (l) return { data: json ? JSON.parse(tekst(l.d)) : l.d };
      if (!pm) throw new Error('pmtiles mangler');
      return pm.tile(Object.assign({}, params, { url: 'pmtiles://' + params.url.slice('hwpm://'.length) }), ac).then(function (res) {
        if (json) omskrivTileJson(res.data, 'pmtiles://', 'hwpm://');
        return res;
      });
    });
  });

  // ── Flisregning ──
  function lon2x(lon, z) { return Math.floor((lon + 180) / 360 * Math.pow(2, z)); }
  function lat2y(lat, z) { var r = lat * Math.PI / 180; return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, z)); }
  function fliser(b, z) {   // b = [vest, sør, øst, nord]
    var x0 = lon2x(b[0], z), x1 = lon2x(b[2], z), y0 = lat2y(b[3], z), y1 = lat2y(b[1], z), ut = [];
    for (var x = x0; x <= x1; x++) for (var y = y0; y <= y1; y++) ut.push([z, x, y]);
    return ut;
  }
  function bboxMerc(z, x, y) {
    var R = 6378137 * Math.PI, s = 2 * R / Math.pow(2, z);
    return [x * s - R, R - (y + 1) * s, (x + 1) * s - R, R - y * s];
  }

  var KILDER = {
    omt: 'https://tiles.openfreemap.org/planet',
    glyfer: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    topo: window.HW_KV_TOPO.url,
    tur: 'https://wms.geonorge.no/skwms1/wms.friluftsruter2?service=WMS&version=1.3.0&request=GetMap&layers=Fotrute,Ruteinfopunkt&styles=&format=image/png&transparent=true&crs=EPSG:3857&width=256&height=256&bbox={bbox-epsg-3857}'
  };
  var SKRIFTER = ['Noto Sans Regular', 'Noto Sans Bold', 'Noto Sans Italic'];
  var TEGNSETT = ['0-255', '256-511', '8192-8447'];   // latin med æøå, utvidet latin (samisk), tegnsetting
  // Rasterflisene (256 px) hentes på kartzoom + 1, så turrutene trenger flis-z15 for å synes helt inn til kartzoom 14.
  // Kartverket (512 px, WMS) hentes på kartzoom: z4–10 dekker kartzoom under 10,5 = samme detaljnivå som cache-nivå 5–11.
  var NIVAA = { omt: [5, 14], topo: [4, 10], tur: [10, 15], hw: [5, 12] };
  var SNITT_KB = { omt: 45, topo: 160, tur: 3, hw: 10 };   // grovt anslag for størrelsen (målt rundt Sognsvann; topo: PNG8 512 px)
  var MAKS_FLISER = 6000;

  function plan(b) {
    var n = { omt: 0, topo: 0, tur: 0, hw: 0 };
    Object.keys(NIVAA).forEach(function (s) { for (var z = NIVAA[s][0]; z <= NIVAA[s][1]; z++) n[s] += fliser(b, z).length; });
    var tot = n.omt + n.topo + n.tur + n.hw;
    var mb = Math.round((n.omt * SNITT_KB.omt + n.topo * SNITT_KB.topo + n.tur * SNITT_KB.tur + n.hw * SNITT_KB.hw) / 1024);
    return { antall: tot, mb: Math.max(1, mb), forStort: tot > MAKS_FLISER };
  }

  // ── Nedlasting ──
  var jobb = null;   // { avbrutt, id }
  function lastNed(b, navn, pmUrl, fremdrift) {
    if (jobb) return Promise.reject(new Error('Det lastes allerede ned et område.'));
    var p = plan(b);
    if (p.forStort) return Promise.reject(new Error('for stort'));
    var id = 'o' + Date.now().toString(36), mine = { avbrutt: false, id: id };
    jobb = mine;
    var oppgaver = [], ferdig = 0, bytes = 0, feilet = 0;

    // Én oppgave = én nøkkel. Finnes nøkkelen fra før (et annet område), legges bare område-id-en til.
    function legg(k, hent, t) { oppgaver.push({ k: k, hent: hent, t: t }); }
    function hentBin(url) { return function () { return fetch(url).then(function (r) { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); }); }; }

    return db().then(function (d) {
      // OpenFreeMap: TileJSON først (adressen til flisene har versjonsnummer)
      return fetch(KILDER.omt).then(function (r) { return r.json(); }).then(function (tj) {
        var mal = tj.tiles[0];
        legg(KILDER.omt, function () { return Promise.resolve(JSON.stringify(tj)); }, 'json');
        for (var z = NIVAA.omt[0]; z <= NIVAA.omt[1]; z++) fliser(b, z).forEach(function (f) {
          var u = mal.replace('{z}', f[0]).replace('{x}', f[1]).replace('{y}', f[2]);
          legg(nokkel(u), hentBin(u), 'bin');
        });
        SKRIFTER.forEach(function (s) { TEGNSETT.forEach(function (r) {
          var u = KILDER.glyfer.replace('{fontstack}', s).replace('{range}', r);
          legg(nokkel(u), hentBin(u), 'bin');
        }); });
        for (z = NIVAA.topo[0]; z <= NIVAA.topo[1]; z++) fliser(b, z).forEach(function (f) {
          var u = nokkel(KILDER.topo.replace('{bbox-epsg-3857}', bboxMerc(f[0], f[1], f[2]).join(',')));
          legg(u, hentBin(u), 'bin');
        });
        for (z = NIVAA.tur[0]; z <= NIVAA.tur[1]; z++) fliser(b, z).forEach(function (f) {
          var u = nokkel(KILDER.tur.replace('{bbox-epsg-3857}', bboxMerc(f[0], f[1], f[2]).join(',')));
          legg(u, hentBin(u), 'bin');
        });
        if (pm && pmUrl) {
          var pmKey = 'hwpm://' + pmUrl, pmEkte = 'pmtiles://' + pmUrl;
          legg(pmKey, function () { return pm.tile({ url: pmEkte, type: 'json' }, new AbortController()).then(function (res) { return JSON.stringify(omskrivTileJson(res.data, 'pmtiles://', 'hwpm://')); }); }, 'json');
          for (z = NIVAA.hw[0]; z <= NIVAA.hw[1]; z++) fliser(b, z).forEach(function (f) {
            var sti = '/' + f[0] + '/' + f[1] + '/' + f[2];
            legg(pmKey + sti, function () {
              return pm.tile({ url: pmEkte + sti, type: 'arrayBuffer' }, new AbortController()).then(function (res) {
                var x = res.data; return x instanceof ArrayBuffer ? x : (x && x.buffer ? x.buffer.slice(x.byteOffset, x.byteOffset + x.byteLength) : new ArrayBuffer(0));
              });
            }, 'bin');
          });
        }
        var omr = { id: id, navn: navn, bbox: b, dato: Date.now(), antall: oppgaver.length, bytes: 0, ferdig: false };
        return req(d.transaction('omrader', 'readwrite').objectStore('omrader').put(omr)).then(function () {
          return kjor(d, omr);
        });
      });
    }).catch(function (e) {
      // Feil før eller under nedlastingen: frigjør jobben og rydd bort det halve området
      if (jobb === mine) jobb = null;
      return slett(id).catch(function () {}).then(function () { throw e; });
    });

    function kjor(d, omr) {
      var i = 0;
      function neste() {
        if (mine.avbrutt || i >= oppgaver.length) return Promise.resolve();
        var o = oppgaver[i++];
        return req(d.transaction('fliser').objectStore('fliser').get(o.k)).then(function (fra) {
          // TileJSON hentes alltid på nytt (nyeste versjon), men beholder områdene som allerede bruker den
          if (fra && o.t === 'json') return o.hent().then(function (data) {
            if (fra.o.indexOf(id) < 0) fra.o.push(id);
            fra.d = data; bytes += data.length || 0;
            return req(d.transaction('fliser', 'readwrite').objectStore('fliser').put(fra));
          }, function () { feilet++; });
          if (fra) {
            if (fra.o.indexOf(id) < 0) fra.o.push(id);
            bytes += fra.d.byteLength || fra.d.length || 0;
            return req(d.transaction('fliser', 'readwrite').objectStore('fliser').put(fra));
          }
          return o.hent().then(function (data) {
            bytes += data.byteLength || data.length || 0;
            return req(d.transaction('fliser', 'readwrite').objectStore('fliser').put({ k: o.k, d: data, t: o.t, o: [id] }));
          }, function () { feilet++; });
        }).then(function () {
          ferdig++;
          if (fremdrift) fremdrift(ferdig / oppgaver.length, ferdig, oppgaver.length);
          return neste();
        });
      }
      var traader = []; for (var t = 0; t < 6; t++) traader.push(neste());
      return Promise.all(traader).then(function () {
        jobb = null;
        if (mine.avbrutt) return slett(id).then(function () { throw new Error('avbrutt'); });
        omr.ferdig = true; omr.bytes = bytes; omr.feilet = feilet;
        return req(d.transaction('omrader', 'readwrite').objectStore('omrader').put(omr)).then(function () {
          if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(function () {});
          return lesOmrader();
        }).then(function () { return omr; });
      });
    }
  }

  function avbryt() { if (jobb) jobb.avbrutt = true; }

  function slett(id) {
    return db().then(function (d) {
      return new Promise(function (ok, feil) {
        var tx = d.transaction(['fliser', 'omrader'], 'readwrite'), st = tx.objectStore('fliser');
        st.openCursor().onsuccess = function (e) {
          var c = e.target.result; if (!c) return;
          var v = c.value, i = v.o.indexOf(id);
          if (i >= 0) { v.o.splice(i, 1); if (v.o.length) c.update(v); else c.delete(); }
          c.continue();
        };
        tx.objectStore('omrader').delete(id);
        tx.oncomplete = function () { ok(); }; tx.onerror = function () { feil(tx.error); };
      });
    }).then(lesOmrader);
  }

  // Er punktet (eller utsnittet) inne i et nedlastet område?
  function dekker(lon, lat) {
    return omrader.some(function (o) { return o.ferdig && lon >= o.bbox[0] && lon <= o.bbox[2] && lat >= o.bbox[1] && lat <= o.bbox[3]; });
  }

  window.hwOff = {
    klar: klar, plan: plan, lastNed: lastNed, avbryt: avbryt, slett: slett, dekker: dekker,
    omrader: function () { return omrader; }, laster: function () { return !!jobb; }
  };
})();
