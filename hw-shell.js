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
//  Faner (godkjent 1. okt 2026): Kart · Sesong · Mine vann · Meny.
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
    season: '<svg viewBox="0 0 24 24"><path d="M3 17l5-6 4 4 4-7 5 5"/><path d="M3 21h18"/></svg>',
    heart: '<svg viewBox="0 0 24 24"><path d="M12 20.5s-7.5-4.7-9.3-9A5.2 5.2 0 0 1 12 6.6a5.2 5.2 0 0 1 9.3 4.9c-1.8 4.3-9.3 9-9.3 9z"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></svg>',
    menu: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    bell: '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>',
    book: '<svg viewBox="0 0 24 24"><path d="M4 19V5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z"/><path d="M8 7h7M8 11h7"/></svg>',
    drop: '<svg viewBox="0 0 24 24"><path d="M12 3c3 4.5 6 7.5 6 11a6 6 0 1 1-12 0c0-3.5 3-6.5 6-11z"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
    out: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-9-9"/><path d="M21 3l-9 9M15 3h6v6"/></svg>',
    globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></svg>'
  };

  var path = location.pathname.replace(/\/index\.html$/, '/');
  var pageTab = path === '/' ? (location.hash === '#sesong' ? 'sesong' : 'home') : '';

  // Tekster: språket kommer fra hw-lang.js (window.HW_LANG); dashboardet kan
  // overstyre via cfg.lang. Uten hw-lang.js: norsk.
  var EN = (cfg.lang || window.HW_LANG) === 'en';
  var S = EN ? {
    map: 'Map', season: 'Season', fav: 'My waters', menu: 'Menu', close: 'Close', nav: 'Main navigation',
    obs: 'Report a hatch', obsSub: 'Seen a hatch? It makes the model better.',
    notif: 'Notifications', notifSub: 'Hatch, spinner fall, ants · push',
    articles: 'Articles', articlesSub: 'Mayflies, spinner fall, ants · in Norwegian for now',
    ofa: 'OFA stocking', ofaSub: 'Nordmarka 2021–2025',
    about: 'About HatchWatch', aboutSub: 'The model, data sources, stations',
    feedback: 'Send feedback', feedbackSub: 'Beta · we read everything',
    lang: 'Norsk', langSub: 'Switch to Norwegian',
    empty: '<b>No waters yet.</b><br>Tap the heart on a water in the map or at the top of a forecast, and your waters gather here. Your notifications follow this list.'
  } : {
    map: 'Kart', season: 'Sesong', fav: 'Mine vann', menu: 'Meny', close: 'Lukk', nav: 'Hovednavigasjon',
    obs: 'Meld observasjon', obsSub: 'Så du klekking? Det gjør modellen bedre.',
    notif: 'Varsler', notifSub: 'Klekking, spinnerfall, stokkmaur · push',
    articles: 'Artikler', articlesSub: 'Døgnfluer, spinnerfall, stokkmaur',
    ofa: 'OFA settefisk', ofaSub: 'Utsett i Nordmarka 2021–2025',
    about: 'Om HatchWatch', aboutSub: 'Modellen, datakildene, stasjonene',
    feedback: 'Send tilbakemelding', feedbackSub: 'Beta · vi leser alt',
    lang: 'English', langSub: 'Bytt til engelsk',
    empty: '<b>Ingen vann ennå.</b><br>Trykk hjertet på et vann i kartet eller øverst på prognosen, så samler vannene dine seg her. Varslene dine følger denne lista.'
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

  var html =
    '<nav id="hwBar" aria-label="' + S.nav + '">' +
      '<a class="hwb" data-tab="home" href="/">' + ICON.map + '<span>' + S.map + '</span></a>' +
      '<a class="hwb" data-tab="sesong" href="/#sesong">' + ICON.season + '<span>' + S.season + '</span></a>' +
      '<button class="hwb" data-tab="fav" id="hwbFav" type="button">' + ICON.heart + '<span>' + S.fav + '</span></button>' +
      '<button class="hwb" data-tab="menu" id="hwbMenu" type="button">' + ICON.menu + '<span>' + S.menu + '</span></button>' +
    '</nav>' +
    '<div class="hwpanel" id="hwbFavPanel" role="dialog" aria-label="' + S.fav + '">' +
      '<div class="hwp-title"><span>' + S.fav + '</span><button class="hwp-close" type="button" data-close="hwbFavPanel" aria-label="' + S.close + '">×</button></div>' +
      '<div class="hwp-scroll" id="hwbFavList"></div>' +
    '</div>' +
    '<div class="hwpanel" id="hwbMenuPanel" role="dialog" aria-label="' + S.menu + '">' +
      '<div class="hwp-title"><span>' + S.menu + '</span><button class="hwp-close" type="button" data-close="hwbMenuPanel" aria-label="' + S.close + '">×</button></div>' +
      '<div class="hwp-scroll">' +
        row(cfg.obsHref || '/observasjon.html', ICON.plus, S.obs, S.obsSub) +
        row('/varsler.html', ICON.bell, S.notif, S.notifSub, ' id="hwbNotif"') +
        row('/artikler.html', ICON.book, S.articles, S.articlesSub) +
        row('/ofa-settefisk.html', ICON.drop, S.ofa, S.ofaSub) +
        row('/om.html', ICON.info, S.about, S.aboutSub) +
        row('https://tally.so/r/EkBErN', ICON.out, S.feedback, S.feedbackSub, ' target="_blank" rel="noopener"') +
        extras.map(function (x, i) { return btnRow(i, x.icon || ICON.out, x.title, x.sub); }).join('') +
        '<button class="hwp-row" type="button" id="hwbLang">' + ICON.globe +
          '<span><span class="mt">' + S.lang + '</span><span class="ms">' + S.langSub + '</span></span><span class="chev">›</span></button>' +
        '<div class="hwp-foot">hatchwatch.no · beta · data: MET · NVE · Sentinel</div>' +
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
  function renderFavs() {
    var list = document.getElementById('hwbFavList');
    var f = favs();
    if (!f.length) {
      list.innerHTML = '<div class="hwp-empty">' + S.empty + '</div>';
      return;
    }
    list.innerHTML = f.map(function (id) {
      var sub = typeof cfg.favSub === 'function' ? (cfg.favSub(id) || '') : '';
      return row('/dashboard.html?loc=' + encodeURIComponent(id), ICON.drop, NAMES[id] || id, sub);
    }).join('');
  }

  mount.querySelectorAll('a.hwb').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('data-tab');
      if (typeof cfg.onTab === 'function' && cfg.onTab(id)) { e.preventDefault(); closeAll(); setActive(id); }
    });
  });
  document.getElementById('hwbFav').addEventListener('click', function () { renderFavs(); open('hwbFavPanel', 'fav'); });
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
