// ═══════════════════════════════════════════════════════════════════
//  HatchWatch delt skall — bunnbar + paneler (innført 2026-10-01)
//
//  Erstatter den byte-identiske bar-blokken som lå kopiert i om, varsler,
//  artikler, observasjon og ofa-settefisk. Sida trenger bare:
//      <link rel="stylesheet" href="/hw.css">   (i <head>)
//      <script src="/hw-shell.js" defer></script>
//  Dashboard har fortsatt egen variant med side-spesifikke kroker; den
//  flyttes hit når Sesongen bygges (steg 4).
//
//  Faner (godkjent 1. okt 2026): Kart · Sesong · Favoritter (het «Mine vann» til 14.10.2026) · Dagbok (16.10.2026) · Meny.
//  Observasjon er en handling: rad i menyen + knapp inne på vannet.
//
//  Kroker (valgfrie) via window.HW_SHELL før skriptet kjører:
//    onTab(id)   → return true for å håndtere fanen selv (kart bruker
//                  dette for «home» og «sesong» så panelet åpnes uten
//                  sideskifte).
//    favSub(id)  → HTML-streng under navnet i Mine vann (status).
//  Sida kan styre baren via window.hwShell.setActive(id) / closeAll().
//
//  Selvstendig: ingen avhengigheter til sidens kode. Favoritter leses
//  fra localStorage-nøkkelen hw_favs (samme som kart og dashboard).
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';
  if (document.getElementById('hwBar')) return;   // sida har egen bar
  var cfg = window.HW_SHELL || {};

  var NAMES = {
    kautokeino: 'Kautokeino', alta: 'Alta', porsanger: 'Porsanger',
    ifjordfjellet: 'Ifjordfjellet', dividalen: 'Dividalen', bardu: 'Bardu',
    narvik: 'Narvik', mo_i_rana: 'Mo i Rana', borgefjell: 'Børgefjell',
    lierne: 'Lierne', trondheim: 'Trondheim', rena: 'Rena',
    finnemarka: 'Finnemarka', hardangervidda: 'Hardangervidda', bergen: 'Bergen',
    roros: 'Røros', oslo: 'Nordmarka', nordmarka_dyn: 'Nordmarka',
    romeriksasen: 'Romeriksåsen', ostmarka: 'Østmarka', vestfjella: 'Vestfjella'
  };

  var ICON = {
    map: '<svg viewBox="0 0 24 24"><path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/></svg>',
    logbook: '<svg viewBox="0 0 24 24"><path d="M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6z"/><path d="M6 3v18M9.5 8h6M9.5 12h6M9.5 16h3.5"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><rect x="6.5" y="2.5" width="11" height="19" rx="2.5"/><path d="M10.5 18.5h3"/></svg>',
    season: '<svg viewBox="0 0 24 24"><path d="M3 17l5-6 4 4 4-7 5 5"/><path d="M3 21h18"/></svg>',
    heart: '<svg viewBox="0 0 24 24"><path d="M12 20.5s-7.5-4.7-9.3-9A5.2 5.2 0 0 1 12 6.6a5.2 5.2 0 0 1 9.3 4.9c-1.8 4.3-9.3 9-9.3 9z"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></svg>',
    camera: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.6"/></svg>',
    menu: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    bell: '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>',
    book: '<svg viewBox="0 0 24 24"><path d="M4 19V5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z"/><path d="M8 7h7M8 11h7"/></svg>',
    drop: '<svg viewBox="0 0 24 24"><path d="M12 3c3 4.5 6 7.5 6 11a6 6 0 1 1-12 0c0-3.5 3-6.5 6-11z"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
    out: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-9-9"/><path d="M21 3l-9 9M15 3h6v6"/></svg>',
    globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>'
  };

  var path = location.pathname.replace(/\/index\.html$/, '/');
  var pageTab = path === '/' ? (location.hash === '#sesong' ? 'sesong' : 'home') : path === '/dagbok.html' ? 'dagbok' : '';

  // Tekster: språket kommer fra hw-lang.js (window.HW_LANG); dashboardet kan
  // overstyre via cfg.lang. Uten hw-lang.js: norsk.
  var EN = (cfg.lang || window.HW_LANG) === 'en';
  var S = EN ? {
    map: 'Map', season: 'Season', fav: 'Favourites', logbook: 'Logbook', menu: 'Menu', close: 'Close', nav: 'Main navigation',
    obs: 'Report a hatch', obsSub: 'Seen a hatch? It makes the model better.',
    insekt: 'What insect is this?', insektSub: 'Take a photo, get an answer',
    notif: 'Notifications', notifSub: 'Hatch, spinner fall, ants · push',
    articles: 'Articles', articlesSub: 'Mayflies, spinner fall, ants',
    ofa: 'OFA stocking', ofaSub: 'Nordmarka 2021–2025',
    about: 'About HatchWatch', aboutSub: 'The model, data sources, stations',
    feedback: 'Send feedback', feedbackSub: 'Beta · we read everything',
    app: 'Get the app', appSub: 'iPhone · App Store',
    lang: 'Norsk', langSub: 'Switch to Norwegian', terms: 'Terms', privacy: 'Privacy',
    empty: '<b>No favourites yet.</b><br>Tap the heart on a water in the map or at the top of a forecast, and your waters gather here. Trips you save with the ruler in the map also end up here. Your notifications follow the waters.'
  } : {
    map: 'Kart', season: 'Sesong', fav: 'Favoritter', logbook: 'Dagbok', menu: 'Meny', close: 'Lukk', nav: 'Hovednavigasjon',
    obs: 'Meld observasjon', obsSub: 'Så du klekking? Det gjør modellen bedre.',
    insekt: 'Hvilket insekt er dette?', insektSub: 'Ta bilde, få svar',
    notif: 'Varsler', notifSub: 'Klekking, spinnerfall, stokkmaur · push',
    articles: 'Artikler', articlesSub: 'Døgnfluer, spinnerfall, stokkmaur',
    ofa: 'OFA settefisk', ofaSub: 'Utsett i Nordmarka 2021–2025',
    about: 'Om HatchWatch', aboutSub: 'Modellen, datakildene, stasjonene',
    feedback: 'Send tilbakemelding', feedbackSub: 'Beta · vi leser alt',
    app: 'Last ned appen', appSub: 'iPhone · App Store',
    lang: 'English', langSub: 'Bytt til engelsk', terms: 'Vilkår', privacy: 'Personvern',
    empty: '<b>Ingen favoritter ennå.</b><br>Trykk hjertet på et vann i kartet eller øverst på prognosen, så samler vannene dine seg her. Turer du lagrer med linjalen i kartet havner også her. Varslene dine følger vannene.'
  };

  function row(href, icon, title, sub, extra) {
    return '<a class="hwp-row" href="' + href + '"' + (extra || '') + '>' + icon +
      '<span><span class="mt">' + title + '</span>' + (sub ? '<span class="ms">' + sub + '</span>' : '') + '</span>' +
      '<span class="chev">›</span></a>';
  }
  function btnRow(id, icon, title, sub) {
    return '<button class="hwp-row" type="button" data-extra="' + id + '">' + icon +
      '<span><span class="mt">' + title + '</span>' + (sub ? '<span class="ms">' + sub + '</span>' : '') + '</span>' +
      '<span class="chev">›</span></button>';
  }
  var extras = Array.isArray(cfg.menuExtra) ? cfg.menuExtra : [];
  // «Last ned appen» (2026-10-15, Stian): skjult inne i iPhone-appen. Telefon → rett til App Store;
  // PC (uten berøring) → Om-siden, der det er en QR-kode å skanne med telefonen.
  var iAppen = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
  var APP_URL = 'https://apps.apple.com/no/app/id6817913220';
  var paPC = !('ontouchstart' in window) && window.innerWidth >= 760;
  var appRad = iAppen ? '' : row(paPC ? '/om.html#app' : APP_URL, ICON.phone, S.app, S.appSub, paPC ? '' : ' target="_blank" rel="noopener"');

  var html =
    '<nav id="hwBar" aria-label="' + S.nav + '">' +
      '<a class="hwb" data-tab="home" href="/">' + ICON.map + '<span>' + S.map + '</span></a>' +
      '<a class="hwb" data-tab="sesong" href="/#sesong">' + ICON.season + '<span>' + S.season + '</span></a>' +
      '<button class="hwb" data-tab="fav" id="hwbFav" type="button">' + ICON.heart + '<span>' + S.fav + '</span></button>' +
      '<a class="hwb" data-tab="dagbok" href="/dagbok.html">' + ICON.logbook + '<span>' + S.logbook + '</span></a>' +
      '<button class="hwb" data-tab="menu" id="hwbMenu" type="button">' + ICON.menu + '<span>' + S.menu + '</span></button>' +
    '</nav>' +
    '<div class="hwpanel" id="hwbFavPanel" role="dialog" aria-label="' + S.fav + '">' +
      '<div class="hwp-title"><span>' + S.fav + '</span><button class="hwp-close" type="button" data-close="hwbFavPanel" aria-label="' + S.close + '">×</button></div>' +
      '<div class="hwp-faner" id="hwbFavFaner" role="tablist"></div>' +
      '<div class="hwp-scroll" id="hwbFavList"></div>' +
    '</div>' +
    '<div class="hwpanel" id="hwbMenuPanel" role="dialog" aria-label="' + S.menu + '">' +
      '<div class="hwp-title"><span>' + S.menu + '</span><button class="hwp-close" type="button" data-close="hwbMenuPanel" aria-label="' + S.close + '">×</button></div>' +
      '<div class="hwp-scroll">' +
        row('/insekt.html', ICON.camera, S.insekt, S.insektSub) +       // insektgjenkjenner (2026-10-17)
        row(cfg.obsHref || '/observasjon.html', ICON.plus, S.obs, S.obsSub) +
        row('/varsler.html', ICON.bell, S.notif, S.notifSub, ' id="hwbNotif"') +
        row('/artikler.html', ICON.book, S.articles, S.articlesSub) +
        row('/ofa-settefisk.html', ICON.drop, S.ofa, S.ofaSub) +
        row('/om.html', ICON.info, S.about, S.aboutSub) +
        appRad +
        row('https://tally.so/r/EkBErN', ICON.out, S.feedback, S.feedbackSub, ' target="_blank" rel="noopener"') +
        extras.map(function (x, i) { return btnRow(i, x.icon || ICON.out, x.title, x.sub); }).join('') +
        '<button class="hwp-row" type="button" id="hwbLang">' + ICON.globe +
          '<span><span class="mt">' + S.lang + '</span><span class="ms">' + S.langSub + '</span></span><span class="chev">›</span></button>' +
        '<div class="hwp-foot">© 2026 Stian Midtdal · <a href="/vilkar.html" style="color:inherit">' + S.terms + '</a> · <a href="/personvern.html" style="color:inherit">' + S.privacy + '</a></div>' +
      '</div>' +
    '</div>';

  var mount = document.createElement('div');
  mount.id = 'hwShell';
  mount.innerHTML = html;
  document.body.appendChild(mount);
  document.body.classList.add('hw-has-bar');

  function favs() {
    try { return JSON.parse(localStorage.getItem('hw_favs') || '[]'); } catch (e) { return []; }
  }
  function setActive(id) {
    mount.querySelectorAll('.hwb').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-tab') === id); });
  }
  function closeAll() {
    mount.querySelectorAll('.hwpanel').forEach(function (p) { p.classList.remove('open'); });
    setActive(pageTab);
  }
  function open(panelId, tab) {
    var p = document.getElementById(panelId);
    var wasOpen = p.classList.contains('open');
    closeAll();
    if (!wasOpen) { p.classList.add('open'); setActive(tab); }
  }
  // Mine elver (2026-10-14): lakseelver lagres som {id, navn} i hw_elv_favs
  // (hjertet på elvesiden og i elvekortet på kartet). Egen seksjon under vannene.
  function elvFavs() {
    try { var v = JSON.parse(localStorage.getItem('hw_elv_favs') || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  var RIVER = '<svg viewBox="0 0 24 24"><path d="M4 4c4 2 2 6 6 8s2 6 6 8"/><path d="M10 4c4 2 2 6 6 8s2 6 6 8"/></svg>';
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // Mine vann (2026-10-14): vilkårlige vann fra vannsiden lagres som {id, navn} i hw_vann_favs
  function vannFavs() {
    try { var v = JSON.parse(localStorage.getItem('hw_vann_favs') || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  // Faner (2026-10-15, Stian): Områder (prognosestedene, hw_favs) · Vann · Elver · Turer. Hver liste vises for
  // seg; valgt fane huskes (hw_fav_fane). Uten husket valg åpnes første fane som har noe i seg.
  var FANER = [
    { id: 'omr', no: 'Områder', en: 'Areas', tom: ['Ingen områder ennå. Trykk hjertet øverst på en prognose, for eksempel Kautokeino, så havner den her.', 'No areas yet. Tap the heart at the top of a forecast, for example Kautokeino, and it ends up here.'] },
    { id: 'vann', no: 'Vann', en: 'Lakes', tom: ['Ingen vann ennå. Trykk hjertet på et vann i kartet eller på vannsiden. Varslene dine følger vannene.', 'No lakes yet. Tap the heart on a lake in the map or on the lake page. Your notifications follow the lakes.'] },
    { id: 'elv', no: 'Elver', en: 'Rivers', tom: ['Ingen elver ennå. Trykk hjertet på en lakseelv i kartet eller på elvesiden.', 'No rivers yet. Tap the heart on a salmon river in the map or on the river page.'] },
    { id: 'tur', no: 'Turer', en: 'Trips', tom: ['Ingen turer ennå. Tegn en tur med linjalen i kartet og trykk Lagre, eller registrer turen mens du går.', 'No trips yet. Draw a trip with the ruler in the map and tap Save, or record the trip as you walk.'] },
    { id: 'pkt', no: 'Punkter', en: 'Points', tom: ['Ingen punkter ennå. Trykk og hold på kartet, og velg Lagre punkt.', 'No points yet. Press and hold on the map, and choose Save point.'] }
  ];
  var favFane = null;
  try { favFane = localStorage.getItem('hw_fav_fane'); } catch (e) {}
  function renderFavs() {
    var list = document.getElementById('hwbFavList'), faner = document.getElementById('hwbFavFaner');
    var f = favs(), e = elvFavs(), vf = vannFavs(), tu = turer(), pk = punkter();
    var antall = { omr: f.length, vann: vf.length, elv: e.length, tur: tu.length, pkt: pk.length };
    if (!FANER.some(function (x) { return x.id === favFane; })) {
      var forste = FANER.filter(function (x) { return antall[x.id] > 0; })[0];
      favFane = forste ? forste.id : 'vann';
    }
    faner.innerHTML = FANER.map(function (x) {
      return '<button type="button" role="tab" data-fane="' + x.id + '" aria-selected="' + (x.id === favFane) + '"' + (x.id === favFane ? ' class="on"' : '') + '>' +
        (EN ? x.en : x.no) + (antall[x.id] ? '<small>' + antall[x.id] + '</small>' : '') + '</button>';
    }).join('');
    var fane = FANER.filter(function (x) { return x.id === favFane; })[0];
    if (!antall[favFane]) {
      list.innerHTML = '<div class="hwp-empty">' + (EN ? fane.tom[1] : fane.tom[0]) + '</div>';
      return;
    }
    var html = '';
    if (favFane === 'omr') html = f.map(function (id) {
      var sub = typeof cfg.favSub === 'function' ? (cfg.favSub(id) || '') : '';
      return row('/dashboard.html?loc=' + encodeURIComponent(id), ICON.drop, NAMES[id] || id, sub);
    }).join('');
    if (favFane === 'vann') html = vf.map(function (x) {
      return row('/vann.html?id=' + encodeURIComponent(x.id), ICON.drop, esc(x.navn || x.id), EN ? 'Ice-out and hatch' : 'Isgang og klekking');
    }).join('');
    if (favFane === 'elv') html = e.map(function (x) {
      return row('/elv.html?id=' + encodeURIComponent(x.id), RIVER, esc(x.navn || x.id), EN ? 'Salmon river' : 'Lakseelv');
    }).join('');
    if (favFane === 'tur') {
      html = tu.map(function (t) {
        var km = t.m >= 1000 ? (t.m / 1000).toFixed(1).replace('.', EN ? '.' : ',') + ' km' : t.m + ' m';
        var href = '/?tur=' + encodeURIComponent(t.tur) + '&navn=' + encodeURIComponent(t.navn || '');
        var dato = /^\d{4}-\d{2}-\d{2}$/.test(t.dato || '') ? (+t.dato.slice(8)) + '.' + (+t.dato.slice(5, 7)) + '.' + t.dato.slice(0, 4) : '';
        return '<div class="hwp-tur">' + row(href, TUR, esc(t.navn || (EN ? 'Trip' : 'Tur')), km + (dato ? ' · ' + dato : '')) +
          '<button type="button" class="hwp-fjern" data-tur="' + esc(t.id) + '" aria-label="' + (EN ? 'Remove trip' : 'Fjern turen') + '">×</button></div>';
      }).join('');
    }
    // Egne punkter (2026-10-16): hw_punkter fra kartet (trykk og hold)
    if (favFane === 'pkt') html = pk.map(function (x) {
      return '<div class="hwp-tur">' + row('/?pkt=' + encodeURIComponent(x.id), PIN, esc(x.navn || (EN ? 'Point' : 'Punkt')), (PKT_KAT[x.kat] ? PKT_KAT[x.kat][EN ? 1 : 0] : '') + (x.dato ? ' · ' + x.dato.split('-').reverse().map(Number).join('.') : '')) +
        '<button type="button" class="hwp-fjern" data-pkt="' + esc(x.id) + '" aria-label="' + (EN ? 'Remove point' : 'Fjern punktet') + '">×</button></div>';
    }).join('');
    list.innerHTML = html;
  }
  var PIN = '<svg viewBox="0 0 24 24"><path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/></svg>';
  var PKT_KAT = { fisk: ['Fiskeplass', 'Fishing spot'], park: ['Parkering', 'Parking'], vad: ['Vadested', 'Ford'], telt: ['Teltplass', 'Campsite'], annet: ['Punkt', 'Point'] };
  function punkter() {
    try { var v = JSON.parse(localStorage.getItem('hw_punkter') || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  // Mine turer (2026-10-14): lagret fra avstandsmålingen på kartet, localStorage hw_turer
  var TUR = '<svg viewBox="0 0 24 24"><circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/><path d="M7 17c4-1 3-6 6-7s3-2 4-3"/></svg>';
  function turer() {
    try { var v = JSON.parse(localStorage.getItem('hw_turer') || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }

  mount.querySelectorAll('a.hwb').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('data-tab');
      if (typeof cfg.onTab === 'function' && cfg.onTab(id)) { e.preventDefault(); closeAll(); setActive(id); }
    });
  });
  document.getElementById('hwbFav').addEventListener('click', function () { renderFavs(); open('hwbFavPanel', 'fav'); });
  document.getElementById('hwbFavFaner').addEventListener('click', function (ev) {
    var b = ev.target.closest('[data-fane]'); if (!b) return;
    favFane = b.getAttribute('data-fane');
    try { localStorage.setItem('hw_fav_fane', favFane); } catch (e) {}
    renderFavs();
    document.getElementById('hwbFavList').scrollTop = 0;
  });
  document.getElementById('hwbFavList').addEventListener('click', function (ev) {
    var b = ev.target.closest('.hwp-fjern'); if (!b) return;
    ev.preventDefault();
    var id = b.getAttribute('data-tur');
    if (b.hasAttribute('data-pkt')) {
      var pid = b.getAttribute('data-pkt');
      try { localStorage.setItem('hw_punkter', JSON.stringify(punkter().filter(function (t) { return t.id !== pid; }))); } catch (e) {}
      if (typeof window.hwPunkterEndret === 'function') window.hwPunkterEndret();
      return renderFavs();
    }
    try { localStorage.setItem('hw_turer', JSON.stringify(turer().filter(function (t) { return t.id !== id; }))); } catch (e) {}
    renderFavs();
  });
  document.getElementById('hwbMenu').addEventListener('click', function () { open('hwbMenuPanel', 'menu'); });
  document.getElementById('hwbNotif').addEventListener('click', function (e) {
    if (typeof cfg.onNotif === 'function' && cfg.onNotif()) { e.preventDefault(); closeAll(); }
  });
  mount.querySelectorAll('[data-extra]').forEach(function (b) {
    b.addEventListener('click', function () { var x = extras[+b.getAttribute('data-extra')]; closeAll(); if (x && typeof x.onClick === 'function') x.onClick(); });
  });
  document.getElementById('hwbLang').addEventListener('click', function () {
    if (typeof window.hwToggleLang === 'function') { window.hwToggleLang(); return; }
    try { localStorage.setItem('lang', EN ? 'no' : 'en'); } catch (e) {}
    location.reload();
  });
  mount.querySelectorAll('.hwp-close').forEach(function (b) { b.addEventListener('click', closeAll); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(); });

  setActive(pageTab);
  window.hwShell = { setActive: setActive, closeAll: closeAll, renderFavs: renderFavs, NAMES: NAMES };
})();
