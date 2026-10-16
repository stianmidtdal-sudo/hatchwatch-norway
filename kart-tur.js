// ═══════════════════════════════════════════════════════════════════
//  På tur (2026-10-16, Stian «kjør 1–5» etter sammenligning med Norgeskart friluftsliv)
//
//  1. Egne punkter (localStorage hw_punkter) med kategori, og dagbokloggene (hw_dagbok) som prikker i kartet.
//  2. Trykk og hold (høyreklikk på PC): koordinater (desimalgrader + UTM), høyde, nærmeste stedsnavn,
//     Del posisjon, Kjør hit, Lagre punkt. Delt posisjon åpnes med /?punkt=<lat>,<lon>; lagret punkt /?pkt=<id>.
//  3. GPX ut (tur, spor, alle punkter) og inn (spor/rute blir tur i linjalen, veipunkter blir punkter).
//  4. Registrer turen mens du går (GPS-spor, hw_spor_aktiv under opptak). Nettsiden kan bare registrere
//     mens skjermen er på; vi ber om at skjermen holdes våken (Wake Lock) så lenge opptaket går.
//  Lastes etter forsidens hovedskript og bruker globalene der (map, tx, EN, sheet, setSel, showSheet,
//  closeSheet, maalStart, maalPunkter, turNavn, kodPolylinje, hentHoyder, haversine, ymdLokal, TODAY).
//  Forsidens onMapClick spør window.hwPunktKlikk(e) først.
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';
  if (!window.map || !window.maplibregl) return;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function les(k) { try { var v = JSON.parse(localStorage.getItem(k) || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; } }
  function skriv(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { alert(tx('Fikk ikke lagret på telefonen.', 'Could not save on this phone.')); return false; } }
  function des(x, n) { return EN ? x.toFixed(n) : x.toFixed(n).replace('.', ','); }
  function erIos() { return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1); }

  // UTM (WGS84) med vanlig sonebredde 6°, og Norges unntak: 32V utvidet vestover, og Svalbard 31X/33X/35X/37X
  function utm(lat, lon) {
    var sone = Math.floor((lon + 180) / 6) + 1;
    if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) sone = 32;
    if (lat >= 72 && lat < 84) { if (lon >= 0 && lon < 9) sone = 31; else if (lon >= 9 && lon < 21) sone = 33; else if (lon >= 21 && lon < 33) sone = 35; else if (lon >= 33 && lon < 42) sone = 37; }
    var band = 'CDEFGHJKLMNPQRSTUVWXX'.charAt(Math.max(0, Math.min(20, Math.floor((lat + 80) / 8))));
    var a = 6378137, f = 1 / 298.257223563, k0 = 0.9996, lon0 = ((sone - 1) * 6 - 180 + 3) * Math.PI / 180;
    var e2 = f * (2 - f), ep2 = e2 / (1 - e2), r = Math.PI / 180, phi = lat * r, lam = lon * r;
    var N = a / Math.sqrt(1 - e2 * Math.sin(phi) * Math.sin(phi)), T = Math.tan(phi) * Math.tan(phi), C = ep2 * Math.cos(phi) * Math.cos(phi), A = Math.cos(phi) * (lam - lon0);
    var M = a * ((1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 * e2 * e2 / 256) * phi - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 * e2 * e2 / 1024) * Math.sin(2 * phi)
      + (15 * e2 * e2 / 256 + 45 * e2 * e2 * e2 / 1024) * Math.sin(4 * phi) - (35 * e2 * e2 * e2 / 3072) * Math.sin(6 * phi));
    var x = k0 * N * (A + (1 - T + C) * A * A * A / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * Math.pow(A, 5) / 120) + 500000;
    var y = k0 * (M + N * Math.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * Math.pow(A, 4) / 24 + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * Math.pow(A, 6) / 720));
    return { sone: sone + band, ost: Math.round(x), nord: Math.round(y) };
  }
  function utmTekst(lat, lon) { var u = utm(lat, lon); return 'UTM ' + u.sone + ' ' + u.ost + tx(' Ø ', ' E ') + u.nord + ' N'; }
  function kjorHit(lat, lon) {
    return erIos() ? 'https://maps.apple.com/?daddr=' + lat.toFixed(6) + ',' + lon.toFixed(6) : 'https://www.google.com/maps/dir/?api=1&destination=' + lat.toFixed(6) + ',' + lon.toFixed(6);
  }
  function del(tittel, tekst, url, statusEl) {
    if (navigator.share) { navigator.share({ title: tittel, text: tekst, url: url }).catch(function () {}); return; }
    var alt = tekst + (url ? '\n' + url : '');
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(alt).then(function () { if (statusEl) statusEl.textContent = tx('Kopiert. Lim det inn i en melding.', 'Copied. Paste it into a message.'); });
    else if (statusEl) statusEl.textContent = alt;
  }
  // Fil ut: delingsarket på telefon (Lagre i Filer, e-post …), vanlig nedlasting på PC
  function lagFil(navn, innhold, type) {
    var blob = new Blob([innhold], { type: type });
    try {
      var fil = new File([blob], navn, { type: type });
      if ('ontouchstart' in window && navigator.canShare && navigator.canShare({ files: [fil] })) { navigator.share({ files: [fil], title: navn }).catch(function () {}); return; }
    } catch (e) {}
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = navn;
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  function filnavn(s) { return (s || 'hatchwatch').toLowerCase().replace(/[æ]/g, 'ae').replace(/[ø]/g, 'o').replace(/[å]/g, 'a').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'hatchwatch'; }
  function stedsnavn(lat, lon) {
    return fetch('https://ws.geonorge.no/stedsnavn/v1/punkt?nord=' + lat.toFixed(5) + '&ost=' + lon.toFixed(5) + '&koordsys=4258&radius=2000&treffPerSide=10&utkoordsys=4258')
      .then(function (r) { return r.json(); }).then(function (j) {
        var n = (j.navn || []).slice().sort(function (a, b) { return (a.meterFraPunkt || 0) - (b.meterFraPunkt || 0); })[0];
        if (!n || !n.stedsnavn || !n.stedsnavn[0]) return null;
        return { navn: n.stedsnavn[0].skrivemåte, type: n.navneobjekttype, m: Math.round(n.meterFraPunkt || 0) };
      }).catch(function () { return null; });
  }

  // ═══ 1. EGNE PUNKTER OG DAGBOKA I KARTET ═══
  var KAT = {
    fisk: { no: 'Fiskeplass', en: 'Fishing spot', c: '#c98a12' },
    park: { no: 'Parkering', en: 'Parking', c: '#2563a8' },
    vad: { no: 'Vadested', en: 'Ford', c: '#1a8cc0' },
    telt: { no: 'Teltplass', en: 'Campsite', c: '#2f9d63' },
    annet: { no: 'Punkt', en: 'Point', c: '#6b5b95' }
  };
  function katNavn(k) { var x = KAT[k] || KAT.annet; return EN ? x.en : x.no; }
  function punkter() { return les('hw_punkter'); }
  function dagbokLogger() {
    return les('hw_dagbok').map(function (e) {
      var p = e.pos || (e.vann && e.vann.lat != null ? { lat: e.vann.lat, lon: e.vann.lon } : null);
      return p ? { id: e.id, lat: p.lat, lon: p.lon, t: e.t, sted: e.sted || (e.vann && e.vann.navn) || '', fangst: (e.fangst || []).length } : null;
    }).filter(Boolean);
  }
  function datoKort(iso) { var d = new Date(iso); return d.getDate() + '.' + (d.getMonth() + 1) + '.' + String(d.getFullYear()).slice(2); }
  function geo() {
    var f = punkter().map(function (p) {
      return { type: 'Feature', properties: { k: 'p', id: p.id, navn: p.navn || '', farge: (KAT[p.kat] || KAT.annet).c }, geometry: { type: 'Point', coordinates: [p.lon, p.lat] } };
    }).concat(dagbokLogger().map(function (d) {
      return { type: 'Feature', properties: { k: 'd', id: d.id, navn: datoKort(d.t) }, geometry: { type: 'Point', coordinates: [d.lon, d.lat] } };
    }));
    return { type: 'FeatureCollection', features: f };
  }
  function oppdaterKart() { var s = map.getSource('pkt'); if (s) s.setData(geo()); }
  window.hwPunkterEndret = oppdaterKart;
  window.addEventListener('storage', function (e) { if (e.key === 'hw_punkter' || e.key === 'hw_dagbok') oppdaterKart(); });
  window.addEventListener('pageshow', oppdaterKart);   // tilbake fra dagboka: nye logger vises

  function leggTilLag() {
    var under = map.getLayer('loc-cluster') ? 'loc-cluster' : undefined;
    map.addSource('pkt', { type: 'geojson', data: geo() });
    map.addSource('pkt-valgt', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addSource('spor', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'spor-kant', type: 'line', source: 'spor', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#ffffff', 'line-width': 6 } }, under);
    map.addLayer({ id: 'spor-linje', type: 'line', source: 'spor', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#e5484d', 'line-width': 3.5 } }, under);
    map.addLayer({ id: 'dag-sirkel', type: 'circle', source: 'pkt', filter: ['==', ['get', 'k'], 'd'], minzoom: 8,
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 3.5, 14, 6.5], 'circle-color': '#8e44ad', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5 } }, under);
    map.addLayer({ id: 'pkt-sirkel', type: 'circle', source: 'pkt', filter: ['==', ['get', 'k'], 'p'],
      paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 6, 4.5, 14, 8], 'circle-color': ['get', 'farge'], 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } }, under);
    map.addLayer({ id: 'pkt-navn', type: 'symbol', source: 'pkt', minzoom: 12,
      layout: { 'text-field': ['get', 'navn'], 'text-font': ['Noto Sans Bold'], 'text-size': 11, 'text-offset': [0, 1.2], 'text-anchor': 'top', 'text-optional': true },
      paint: { 'text-color': '#11201f', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 } }, under);
    map.addLayer({ id: 'pkt-valgt', type: 'circle', source: 'pkt-valgt',
      paint: { 'circle-radius': 7, 'circle-color': '#e5484d', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2.5 } });
  }
  function merk(lat, lon) {
    var s = map.getSource('pkt-valgt'); if (!s) return;
    s.setData({ type: 'FeatureCollection', features: lat == null ? [] : [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [lon, lat] } }] });
  }

  // ═══ 2. PUNKTKORTET (trykk og hold, lagret punkt, dagboklogg) ═══
  var aktiv = null;   // { type: 'ny'|'lagret'|'dagbok', lat, lon, id }
  function knapp(id, tekst, klasse) { return '<button type="button" class="hw-btn ' + (klasse || 'ghost') + '" data-pk="' + id + '">' + tekst + '</button>'; }
  function visPunkt(o) {
    aktiv = o;
    setSel({ kind: 'punkt' });
    var p = o.type === 'lagret' ? punkter().filter(function (x) { return x.id === o.id; })[0] : null;
    var d = o.type === 'dagbok' ? dagbokLogger().filter(function (x) { return x.id === o.id; })[0] : null;
    if (o.type === 'lagret' && !p) return;
    document.getElementById('shName').textContent = p ? (p.navn || katNavn(p.kat)) : d ? (d.sted || tx('Dagbok', 'Logbook')) : tx('Punkt i kartet', 'Point on the map');
    document.getElementById('shSub').textContent = des(o.lat, 5) + ', ' + des(o.lon, 5);
    var chip = p ? '<span class="hw-chip"><i style="background:' + (KAT[p.kat] || KAT.annet).c + '"></i>' + katNavn(p.kat) + '</span>'
      : d ? '<span class="hw-chip"><i style="background:#8e44ad"></i>' + tx('Dagbok', 'Logbook') + ' · ' + datoKort(d.t) + '</span>' : '';
    document.getElementById('shEye').innerHTML = chip;
    document.getElementById('shBig').innerHTML = '<span id="pkHoyde" style="margin:0">… ' + tx('moh', 'm a.s.l.') + '</span>';
    document.getElementById('shLine').innerHTML = '<span id="pkSted"></span><br><span class="hw-eyebrow">' + utmTekst(o.lat, o.lon) + '</span>';
    var h = '';
    if (p) {
      h += '<div class="pk-kat">' + Object.keys(KAT).map(function (k) { return '<button type="button" data-kat="' + k + '"' + (k === (p.kat || 'annet') ? ' class="on"' : '') + '><i style="background:' + KAT[k].c + '"></i>' + katNavn(k) + '</button>'; }).join('') + '</div>';
      if (p.notat) h += '<div class="line" style="margin-top:8px">' + esc(p.notat) + '</div>';
    }
    if (d) h += '<div class="line" style="margin-top:6px">' + (d.fangst ? tx(d.fangst + ' fangst' + (d.fangst === 1 ? '' : 'er') + ' logget.', d.fangst + ' catch' + (d.fangst === 1 ? '' : 'es') + ' logged.') : tx('Ingen fangst logget.', 'No catch logged.')) + '</div>';
    h += '<div class="pk-knapper">' +
      (o.type === 'ny' ? knapp('lagre', tx('Lagre punkt', 'Save point'), 'primary') : '') +
      knapp('del', tx('Del posisjon', 'Share position')) +
      '<a class="hw-btn ghost" href="' + kjorHit(o.lat, o.lon) + '" target="_blank" rel="noopener">' + tx('Kjør hit', 'Directions') + '</a>' +
      (p ? knapp('navn', tx('Endre navn', 'Rename')) + knapp('notat', tx('Notat', 'Note')) + knapp('gpx', 'GPX') + knapp('slett', tx('Slett', 'Delete'), 'ghost pk-slett') : '') +
      '</div><div class="pk-status" id="pkStatus"></div>';
    shExtra.innerHTML = h;
    shFav.style.display = 'none';
    if (d) { shOpen.style.display = ''; shOpen.textContent = tx('Åpne i dagboka', 'Open in the logbook'); shOpen.setAttribute('href', '/dagbok.html#' + encodeURIComponent(d.id)); }
    else shOpen.style.display = 'none';
    merk(o.type === 'ny' ? o.lat : null, o.lon);
    showSheet();
    // Høyde (Kartverket, open-meteo først) og nærmeste stedsnavn
    var mine = o;
    hentHoyder([[o.lon, o.lat]], function (r) {
      var el = document.getElementById('pkHoyde'); if (!el || aktiv !== mine) return;
      el.textContent = Math.round(r.z[0]) + ' ' + tx('moh', 'm a.s.l.');
    }).catch(function () { var el = document.getElementById('pkHoyde'); if (el && aktiv === mine) el.textContent = tx('Ukjent høyde', 'Unknown height'); });
    stedsnavn(o.lat, o.lon).then(function (s) {
      var el = document.getElementById('pkSted'); if (!el || aktiv !== mine || !s) return;
      el.textContent = (s.m < 60 ? '' : tx('Nær ', 'Near ')) + s.navn + (s.type ? ' (' + s.type.toLowerCase() + ')' : '');
    });
  }
  // Rydd markøren når kortet lukkes
  new MutationObserver(function () { if (!sheet.classList.contains('open') && aktiv) { aktiv = null; merk(null); } }).observe(sheet, { attributes: true, attributeFilter: ['class'] });

  shExtra.addEventListener('click', function (e) {
    if (!aktiv) return;
    var o = aktiv, st = document.getElementById('pkStatus');
    var kat = e.target.closest('[data-kat]');
    if (kat && o.type === 'lagret') {
      skriv('hw_punkter', punkter().map(function (p) { if (p.id === o.id) p.kat = kat.getAttribute('data-kat'); return p; }));
      oppdaterKart(); return visPunkt(o);
    }
    var b = e.target.closest('[data-pk]'); if (!b) return;
    var hva = b.getAttribute('data-pk');
    if (hva === 'lagre') {
      var forslag = (document.getElementById('pkSted') || {}).textContent || '';
      forslag = forslag.replace(/^(Nær |Near )/, '').replace(/ \(.*\)$/, '') || tx('Punkt', 'Point');
      var navn = window.prompt(tx('Navn på punktet', 'Name of the point'), forslag);
      if (navn == null) return;
      var nytt = { id: 'p' + Date.now().toString(36), navn: navn.trim().slice(0, 60) || forslag, lat: +o.lat.toFixed(6), lon: +o.lon.toFixed(6), kat: 'fisk', dato: ymdLokal(new Date()) };
      var alle = punkter(); alle.unshift(nytt);
      if (!skriv('hw_punkter', alle.slice(0, 500))) return;
      oppdaterKart();
      visPunkt({ type: 'lagret', id: nytt.id, lat: nytt.lat, lon: nytt.lon });
      var s2 = document.getElementById('pkStatus'); if (s2) s2.textContent = tx('Lagret under Favoritter → Punkter. Velg type over.', 'Saved under Favourites → Points. Choose a type above.');
    } else if (hva === 'del') {
      var url = location.origin + '/?punkt=' + o.lat.toFixed(5) + ',' + o.lon.toFixed(5);
      var navn2 = document.getElementById('shName').textContent;
      del(navn2, navn2 + ': ' + o.lat.toFixed(5) + ', ' + o.lon.toFixed(5) + ' (' + utmTekst(o.lat, o.lon) + ')', url, st);
    } else if (hva === 'navn' || hva === 'notat') {
      var p = punkter().filter(function (x) { return x.id === o.id; })[0]; if (!p) return;
      var ny = window.prompt(hva === 'navn' ? tx('Navn på punktet', 'Name of the point') : tx('Notat', 'Note'), (hva === 'navn' ? p.navn : p.notat) || '');
      if (ny == null) return;
      skriv('hw_punkter', punkter().map(function (x) { if (x.id === o.id) { if (hva === 'navn') x.navn = ny.trim().slice(0, 60) || x.navn; else x.notat = ny.trim().slice(0, 500); } return x; }));
      oppdaterKart(); visPunkt(o);
    } else if (hva === 'gpx') {
      lagFil('hatchwatch-punkter.gpx', punkterGpx(punkter()), 'application/gpx+xml');
    } else if (hva === 'slett') {
      if (!confirm(tx('Slette punktet?', 'Delete the point?'))) return;
      skriv('hw_punkter', punkter().filter(function (x) { return x.id !== o.id; }));
      oppdaterKart(); closeSheet();
    }
  });

  // Klikk i kartet: egne punkter og dagboklogger før vann og steder (kalles fra onMapClick)
  var undertrykkTil = 0;
  window.hwPunktKlikk = function (e) {
    if (Date.now() < undertrykkTil) return true;            // klikket som fulgte et trykk-og-hold
    if (!map.getLayer('pkt-sirkel')) return false;
    var pad = 10, box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
    var f = map.queryRenderedFeatures(box, { layers: ['pkt-sirkel', 'dag-sirkel'] })[0];
    if (!f) { if (aktiv) { aktiv = null; merk(null); } return false; }
    var c = f.geometry.coordinates;
    visPunkt({ type: f.properties.k === 'p' ? 'lagret' : 'dagbok', id: f.properties.id, lat: c[1], lon: c[0] });
    return true;
  };

  // Trykk og hold (mobil) og høyreklikk (PC)
  function holdt(lngLat) {
    if (window.maaling) return;
    undertrykkTil = Date.now() + 700;
    if (navigator.vibrate) try { navigator.vibrate(15); } catch (e) {}
    visPunkt({ type: 'ny', lat: lngLat.lat, lon: lngLat.lng });
  }
  map.on('contextmenu', function (e) { e.preventDefault && e.preventDefault(); holdt(e.lngLat); });
  (function () {
    var t = null, x0 = 0, y0 = 0, c = map.getCanvasContainer();
    c.addEventListener('touchstart', function (e) {
      clearTimeout(t); if (e.touches.length !== 1) return;
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
      t = setTimeout(function () {
        var r = map.getCanvas().getBoundingClientRect();
        holdt(map.unproject([x0 - r.left, y0 - r.top]));
      }, 550);
    }, { passive: true });
    c.addEventListener('touchmove', function (e) { if (e.touches.length !== 1 || Math.abs(e.touches[0].clientX - x0) > 10 || Math.abs(e.touches[0].clientY - y0) > 10) clearTimeout(t); }, { passive: true });
    ['touchend', 'touchcancel'].forEach(function (ev) { c.addEventListener(ev, function () { clearTimeout(t); }, { passive: true }); });
  })();

  // ═══ 3. GPX ═══
  function gpxHode() { return '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="HatchWatch (hatchwatch.no)" xmlns="http://www.topografix.com/GPX/1/1">\n'; }
  function punkterGpx(liste) {
    return gpxHode() + liste.map(function (p) {
      return '  <wpt lat="' + p.lat + '" lon="' + p.lon + '"><name>' + esc(p.navn || katNavn(p.kat)) + '</name>' + (p.notat ? '<desc>' + esc(p.notat) + '</desc>' : '') + '<type>' + esc(katNavn(p.kat)) + '</type></wpt>\n';
    }).join('') + '</gpx>\n';
  }
  function sporGpx(navn, pkt) {   // pkt: [[lon, lat, tid(ms)?, høyde?], ...]
    return gpxHode() + '  <trk><name>' + esc(navn) + '</name><trkseg>\n' + pkt.map(function (p) {
      return '    <trkpt lat="' + p[1].toFixed(6) + '" lon="' + p[0].toFixed(6) + '">' + (p[3] != null ? '<ele>' + Math.round(p[3]) + '</ele>' : '') + (p[2] ? '<time>' + new Date(p[2]).toISOString() + '</time>' : '') + '</trkpt>\n';
    }).join('') + '  </trkseg></trk>\n</gpx>\n';
  }
  function lesGpx(tekst) {
    var d = new DOMParser().parseFromString(tekst, 'application/xml');
    if (d.getElementsByTagName('parsererror').length) throw new Error('ugyldig');
    var navnEl = d.querySelector('trk > name, rte > name, metadata > name');
    var tak = function (sel) { return Array.prototype.map.call(d.querySelectorAll(sel), function (n) { return [parseFloat(n.getAttribute('lon')), parseFloat(n.getAttribute('lat'))]; }).filter(function (p) { return isFinite(p[0]) && isFinite(p[1]); }); };
    var spor = tak('trkpt'); if (spor.length < 2) spor = tak('rtept');
    var wpt = Array.prototype.map.call(d.querySelectorAll('wpt'), function (n) {
      var nm = n.querySelector('name'), ds = n.querySelector('desc');
      return { lat: parseFloat(n.getAttribute('lat')), lon: parseFloat(n.getAttribute('lon')), navn: nm ? nm.textContent.trim() : '', notat: ds ? ds.textContent.trim() : '' };
    }).filter(function (p) { return isFinite(p.lat) && isFinite(p.lon); });
    return { navn: navnEl ? navnEl.textContent.trim() : '', spor: spor, punkter: wpt };
  }
  // Forenkling (Douglas–Peucker i meter, økende toleranse til streken har maks punkter) — lange spor blir korte
  // nok for linjalen og lenka. Selve GPX-sporet fra opptak lagres i full oppløsning for eksport.
  function forenkle(pkt, maks) {
    if (pkt.length <= maks) return pkt.slice();
    var lat0 = pkt[0][1] * Math.PI / 180, kx = 111320 * Math.cos(lat0), ky = 110540;
    function avst(p, a, b) {
      var x = (p[0] - a[0]) * kx, y = (p[1] - a[1]) * ky, dx = (b[0] - a[0]) * kx, dy = (b[1] - a[1]) * ky, l = dx * dx + dy * dy;
      var t = l ? Math.max(0, Math.min(1, (x * dx + y * dy) / l)) : 0; return Math.hypot(x - t * dx, y - t * dy);
    }
    function dp(tol) {
      var behold = new Uint8Array(pkt.length); behold[0] = behold[pkt.length - 1] = 1;
      var stakk = [[0, pkt.length - 1]];
      while (stakk.length) {
        var s = stakk.pop(), maxD = 0, idx = -1;
        for (var i = s[0] + 1; i < s[1]; i++) { var dd = avst(pkt[i], pkt[s[0]], pkt[s[1]]); if (dd > maxD) { maxD = dd; idx = i; } }
        if (maxD > tol) { behold[idx] = 1; stakk.push([s[0], idx], [idx, s[1]]); }
      }
      return pkt.filter(function (_, i) { return behold[i]; });
    }
    var tol = 3, ut = dp(tol);
    while (ut.length > maks && tol < 500) { tol *= 1.6; ut = dp(tol); }
    return ut;
  }
  function importer(fil) {
    var r = new FileReader();
    r.onload = function () {
      var g;
      try { g = lesGpx(String(r.result)); } catch (e) { alert(tx('Fila kunne ikke leses som GPX.', 'The file could not be read as GPX.')); return; }
      var n = 0;
      if (g.punkter.length) {
        var alle = punkter();
        g.punkter.forEach(function (p, i) { alle.unshift({ id: 'p' + Date.now().toString(36) + i, navn: (p.navn || tx('Punkt', 'Point')).slice(0, 60), notat: p.notat.slice(0, 500), lat: +p.lat.toFixed(6), lon: +p.lon.toFixed(6), kat: 'annet', dato: ymdLokal(new Date()) }); n++; });
        skriv('hw_punkter', alle.slice(0, 500)); oppdaterKart();
      }
      if (g.spor.length >= 2) {
        var navn = (g.navn || fil.name.replace(/\.gpx$/i, '')).slice(0, 60);
        maalStart(forenkle(g.spor, 400), navn);
        rammeInn(g.spor);
        var st = document.getElementById('maalStatus');
        if (st) st.textContent = tx('Importert: ' + navn + (n ? ' og ' + n + ' punkter' : '') + '. Trykk Lagre for å beholde turen.', 'Imported: ' + navn + (n ? ' and ' + n + ' points' : '') + '. Tap Save to keep the trip.');
      } else if (n) {
        var pk = g.punkter; rammeInn(pk.map(function (p) { return [p.lon, p.lat]; }));
        alert(tx(n + ' punkter er lagt til under Favoritter → Punkter.', n + ' points were added under Favourites → Points.'));
      } else alert(tx('Fant ingen spor, ruter eller punkter i fila.', 'Found no tracks, routes or points in the file.'));
    };
    r.readAsText(fil);
  }
  function rammeInn(pkt) {
    if (!pkt.length) return;
    var lo = [Infinity, Infinity], hi = [-Infinity, -Infinity];
    pkt.forEach(function (p) { lo = [Math.min(lo[0], p[0]), Math.min(lo[1], p[1])]; hi = [Math.max(hi[0], p[0]), Math.max(hi[1], p[1])]; });
    if (lo[0] === hi[0] && lo[1] === hi[1]) map.easeTo({ center: lo, zoom: 14 });
    else map.fitBounds([lo, hi], { padding: { top: 140, bottom: 260, left: 30, right: 30 }, maxZoom: 15 });
  }
  var filInn = document.getElementById('gpxInn');
  if (filInn) filInn.addEventListener('change', function () { if (this.files && this.files[0]) importer(this.files[0]); this.value = ''; });
  var gpxUtKnapp = document.getElementById('maalGpx');
  if (gpxUtKnapp) gpxUtKnapp.addEventListener('click', function () {
    if (!window.maalPunkter || maalPunkter.length < 2) return;
    var navn = turNavn || tx('Tur', 'Trip');
    // Er dette et registrert spor med full oppløsning lagret, brukes det (med tid og høyde)
    var t = getTurer().filter(function (x) { return x.tur === kodPolylinje(maalPunkter) && x.spor; })[0], full = null;
    if (t) try { full = JSON.parse(localStorage.getItem('hw_spor_' + t.id) || 'null'); } catch (e) {}
    lagFil(filnavn(navn) + '.gpx', sporGpx(navn, full && full.length >= 2 ? full : maalPunkter), 'application/gpx+xml');
  });
  var gpxInnKnapp = document.getElementById('maalImporter');
  if (gpxInnKnapp && filInn) gpxInnKnapp.addEventListener('click', function () { filInn.click(); });

  // ═══ 4. REGISTRER TUREN (GPS-SPOR) ═══
  var spor = null;   // { start, pkt: [[lon, lat, tid, høyde]], watch, laas }
  var sporKnapp = document.getElementById('sporBtn'), pille = document.getElementById('sporPille');
  function sporLengde(p) { var s = 0; for (var i = 1; i < p.length; i++) s += haversine(p[i - 1][1], p[i - 1][0], p[i][1], p[i][0]) * 1000; return s; }
  function varighet(ms) { var m = Math.round(ms / 60000), t = Math.floor(m / 60); return t ? t + ':' + String(m % 60).padStart(2, '0') : m + ' min'; }
  function sporTegn() {
    var s = map.getSource('spor');
    if (s) s.setData(spor && spor.pkt.length >= 2 ? { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: spor.pkt.map(function (p) { return [p[0], p[1]]; }) } } : { type: 'FeatureCollection', features: [] });
    if (!pille) return;
    if (!spor) { pille.classList.remove('vis'); return; }
    pille.innerHTML = '<span class="rec"></span>' + tx('Registrerer', 'Recording') + ' · ' + maalFmt(sporLengde(spor.pkt)) + ' · ' + varighet(Date.now() - spor.start) +
      (spor.pkt.length ? '' : ' · ' + tx('venter på GPS', 'waiting for GPS')) + ' <button type="button" id="sporStopp">' + tx('Stopp', 'Stop') + '</button>';
    pille.classList.add('vis');
  }
  function lagreAktivt() { try { localStorage.setItem('hw_spor_aktiv', JSON.stringify({ start: spor.start, pkt: spor.pkt })); } catch (e) {} }
  function vaakeLaas() {
    if (!spor || !navigator.wakeLock) return;
    navigator.wakeLock.request('screen').then(function (l) { if (spor) spor.laas = l; else l.release(); }).catch(function () {});
  }
  document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible' && spor && !spor.laas) vaakeLaas(); });
  function sporStart(fortsett) {
    if (!navigator.geolocation) { alert(tx('Telefonen gir ikke posisjon.', 'The phone gives no position.')); return; }
    spor = fortsett || { start: Date.now(), pkt: [] };
    spor.watch = navigator.geolocation.watchPosition(function (pos) {
      if (!spor) return;
      var c = pos.coords; if (c.accuracy > 40) return;                      // for unøyaktig (inne, tett skog uten fiks)
      var p = [+c.longitude.toFixed(6), +c.latitude.toFixed(6), pos.timestamp || Date.now(), c.altitude != null ? Math.round(c.altitude) : null];
      var siste = spor.pkt[spor.pkt.length - 1];
      if (siste && haversine(siste[1], siste[0], p[1], p[0]) * 1000 < 8) return;   // står stille: ikke fyll opp sporet
      spor.pkt.push(p); lagreAktivt(); sporTegn();
    }, function (err) {
      if (err.code === 1) { alert(tx('Du har ikke gitt tilgang til posisjon.', 'You have not allowed location access.')); sporAvbryt(); }
    }, { enableHighAccuracy: true, maximumAge: 0, timeout: 30000 });
    if (sporKnapp) sporKnapp.classList.add('on');
    vaakeLaas(); lagreAktivt(); sporTegn();
    spor.tikk = setInterval(sporTegn, 30000);
    if (!fortsett) {
      var info = document.getElementById('maalStatus');
      try { if (!localStorage.getItem('hw_spor_info')) { localStorage.setItem('hw_spor_info', '1'); alert(tx('Turen registreres mens HatchWatch er åpen og skjermen er på. Skjermen holdes våken så lenge opptaket går. Trykk Stopp når du er ferdig, så lagres turen under Favoritter → Turer.', 'The trip is recorded while HatchWatch is open and the screen is on. The screen is kept awake while recording. Tap Stop when you are done, and the trip is saved under Favourites → Trips.')); } } catch (e) {}
    }
  }
  function sporAvbryt() {
    if (!spor) return;
    navigator.geolocation.clearWatch(spor.watch); clearInterval(spor.tikk);
    if (spor.laas) try { spor.laas.release(); } catch (e) {}
    spor = null;
    try { localStorage.removeItem('hw_spor_aktiv'); } catch (e) {}
    if (sporKnapp) sporKnapp.classList.remove('on');
    sporTegn();
  }
  function sporStopp() {
    if (!spor) return;
    if (!confirm(tx('Stoppe registreringen og lagre turen?', 'Stop recording and save the trip?'))) return;
    var pkt = spor.pkt.slice(), start = spor.start;
    sporAvbryt();
    if (pkt.length < 2) { alert(tx('Sporet ble for kort til å lagres.', 'The track was too short to save.')); return; }
    sporLagre(pkt, start);
  }
  function sporLagre(pkt, start) {
    var navn = tx('Spor ', 'Track ') + new Date(start).getDate() + '.' + (new Date(start).getMonth() + 1) + ' · ' + maalFmt(sporLengde(pkt));
    var kort = forenkle(pkt.map(function (p) { return [p[0], p[1]]; }), 400);
    var id = Date.now().toString(36);
    var turer = getTurer(); turer.unshift({ id: id, navn: navn, tur: kodPolylinje(kort), m: Math.round(sporLengde(pkt)), dato: ymdLokal(new Date(start)), spor: true, min: Math.round((pkt[pkt.length - 1][2] - start) / 60000) });
    try {
      localStorage.setItem('hw_turer', JSON.stringify(turer.slice(0, 50)));
      localStorage.setItem('hw_spor_' + id, JSON.stringify(pkt));
      // Behold fulle spor bare for turer som fortsatt finnes
      var ider = turer.slice(0, 50).map(function (t) { return t.id; });
      Object.keys(localStorage).forEach(function (k) { if (k.indexOf('hw_spor_') === 0 && k !== 'hw_spor_aktiv' && k !== 'hw_spor_info' && ider.indexOf(k.slice(8)) < 0) localStorage.removeItem(k); });
    } catch (e) { alert(tx('Fikk ikke lagret turen på telefonen.', 'Could not save the trip on this phone.')); }
    maalStart(kort, navn);
    var st = document.getElementById('maalStatus');
    if (st) st.textContent = tx('Lagret under Favoritter → Turer. GPX-knappen gir hele sporet med tid og høyde.', 'Saved under Favourites → Trips. The GPX button gives the full track with time and height.');
  }
  if (sporKnapp) sporKnapp.addEventListener('click', function (e) { e.stopPropagation(); if (spor) sporStopp(); else sporStart(); });
  if (pille) pille.addEventListener('click', function (e) { if (e.target.id === 'sporStopp') sporStopp(); });

  // ═══ OPPSTART ═══
  function init() {
    leggTilLag();
    // Påbegynt opptak (siden ble lastet på nytt, eller appen ble lukket): fortsett?
    try {
      var a = JSON.parse(localStorage.getItem('hw_spor_aktiv') || 'null');
      if (a && a.start) {
        if (Date.now() - a.start < 24 * 3600e3 && confirm(tx('Du har en tur som ble registrert. Fortsette registreringen?', 'You have a trip being recorded. Continue recording?'))) sporStart({ start: a.start, pkt: a.pkt || [] });
        else {
          // Ikke fortsett: lagre det som ble registrert (hvis noe), så ingenting går tapt
          try { localStorage.removeItem('hw_spor_aktiv'); } catch (e) {}
          if ((a.pkt || []).length >= 2) sporLagre(a.pkt, a.start);
        }
      }
    } catch (e) {}
    // Lenker: /?punkt=<lat>,<lon> (delt posisjon) og /?pkt=<id> (lagret punkt fra Favoritter)
    var q = new URLSearchParams(location.search), pp = q.get('punkt'), pid = q.get('pkt');
    if (pp) {
      var ll = pp.split(',').map(Number);
      if (ll.length === 2 && isFinite(ll[0]) && isFinite(ll[1]) && Math.abs(ll[0]) <= 90) { map.jumpTo({ center: [ll[1], ll[0]], zoom: 14 }); visPunkt({ type: 'ny', lat: ll[0], lon: ll[1] }); }
    } else if (pid) {
      var p = punkter().filter(function (x) { return x.id === pid; })[0];
      if (p) { map.jumpTo({ center: [p.lon, p.lat], zoom: 14 }); visPunkt({ type: 'lagret', id: p.id, lat: p.lat, lon: p.lon }); }
    }
  }
  if (map.loaded() && map.getLayer('loc-cluster')) init(); else map.once('load', function () { setTimeout(init, 0); });
})();
