// ═══════════════════════════════════════════════════════════════════
//  HatchWatch delt skall — bunnbar + paneler (innført 2026-10-01)
//
//  Erstatter den byte-identiske bar-blokken som lå kopiert i om, varsler,
//  artikler, observasjon og ofa-settefisk. Sida trenger bare:
//      <link rel="stylesheet" href="/hw.css">   (i <head>)
//      <script src="/hw-shell.js" defer></script>
//  Kart (index) og dashboard har fortsatt egne varianter med side-
//  spesifikke kroker; de flyttes hit når de bygges om (steg 3 og 4).
//
//  Faner nå: Kart · Mine vann · Observasjon · Meny.
//  Når sesong-lista finnes (steg 3) byttes Observasjon ut med Sesong,
//  og observasjon blir en handling inne på vannet. Én endring her,
//  alle sider følger med.
//
//  Selvstendig: ingen avhengigheter til sidens kode. Favoritter leses
//  fra localStorage-nøkkelen hw_favs (samme som kart og dashboard).
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';
  if (document.getElementById('hwBar')) return;   // sida har egen bar

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
    heart: '<svg viewBox="0 0 24 24"><path d="M12 20.5s-7.5-4.7-9.3-9A5.2 5.2 0 0 1 12 6.6a5.2 5.2 0 0 1 9.3 4.9c-1.8 4.3-9.3 9-9.3 9z"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></svg>',
    menu: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    bell: '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10 21a2 2 0 0 0 4 0"/></svg>',
    book: '<svg viewBox="0 0 24 24"><path d="M4 19V5a2 2 0 0 1 2-2h13v18H6a2 2 0 0 1-2-2z"/><path d="M8 7h7M8 11h7"/></svg>',
    drop: '<svg viewBox="0 0 24 24"><path d="M12 3c3 4.5 6 7.5 6 11a6 6 0 1 1-12 0c0-3.5 3-6.5 6-11z"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
    out: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-9-9"/><path d="M21 3l-9 9M15 3h6v6"/></svg>'
  };

  var path = location.pathname.replace(/\/index\.html$/, '/');
  var active = path === '/' ? 'home' : /observasjon/.test(path) ? 'obs' : '';

  function row(href, icon, title, sub, extra) {
    return '<a class="hwp-row" href="' + href + '"' + (extra || '') + '>' + icon +
      '<span><span class="mt">' + title + '</span>' + (sub ? '<span class="ms">' + sub + '</span>' : '') + '</span>' +
      '<span class="chev">›</span></a>';
  }

  var html =
    '<nav id="hwBar" aria-label="Hovednavigasjon">' +
      '<a class="hwb' + (active === 'home' ? ' on' : '') + '" href="/">' + ICON.map + '<span>Kart</span></a>' +
      '<button class="hwb" id="hwbFav" type="button">' + ICON.heart + '<span>Mine vann</span></button>' +
      '<a class="hwb' + (active === 'obs' ? ' on' : '') + '" href="/observasjon.html">' + ICON.plus + '<span>Observasjon</span></a>' +
      '<button class="hwb" id="hwbMenu" type="button">' + ICON.menu + '<span>Meny</span></button>' +
    '</nav>' +
    '<div class="hwpanel" id="hwbFavPanel" role="dialog" aria-label="Mine vann">' +
      '<div class="hwp-title"><span>Mine vann</span><button class="hwp-close" type="button" data-close="hwbFavPanel" aria-label="Lukk">×</button></div>' +
      '<div class="hwp-scroll" id="hwbFavList"></div>' +
    '</div>' +
    '<div class="hwpanel" id="hwbMenuPanel" role="dialog" aria-label="Meny">' +
      '<div class="hwp-title"><span>Meny</span><button class="hwp-close" type="button" data-close="hwbMenuPanel" aria-label="Lukk">×</button></div>' +
      '<div class="hwp-scroll">' +
        row('/varsler.html', ICON.bell, 'Varsler', 'Klekking, spinnerfall, stokkmaur · push') +
        row('/artikler.html', ICON.book, 'Artikler', 'Døgnfluer, spinnerfall, stokkmaur') +
        row('/ofa-settefisk.html', ICON.drop, 'OFA settefisk', 'Utsett i Nordmarka 2021–2025') +
        row('/om.html', ICON.info, 'Om HatchWatch', 'Modellen, datakildene, stasjonene') +
        row('https://tally.so/r/EkBErN', ICON.out, 'Send tilbakemelding', 'Beta · vi leser alt', ' target="_blank" rel="noopener"') +
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
  function closeAll() {
    mount.querySelectorAll('.hwpanel').forEach(function (p) { p.classList.remove('open'); });
    mount.querySelectorAll('.hwb').forEach(function (b) {
      var isPage = (b.getAttribute('href') === '/' && active === 'home') || (/observasjon/.test(b.getAttribute('href') || '') && active === 'obs');
      b.classList.toggle('on', isPage);
    });
  }
  function open(panelId, btn) {
    var p = document.getElementById(panelId);
    var wasOpen = p.classList.contains('open');
    closeAll();
    if (!wasOpen) {
      mount.querySelectorAll('.hwb').forEach(function (b) { b.classList.remove('on'); });
      p.classList.add('open'); btn.classList.add('on');
    }
  }
  document.getElementById('hwbFav').addEventListener('click', function () {
    var list = document.getElementById('hwbFavList');
    var f = favs();
    if (!f.length) {
      list.innerHTML = '<div class="hwp-empty"><b>Ingen vann ennå.</b><br>Trykk hjertet på et vann i kartet eller øverst på prognosen, så samler vannene dine seg her. Varslene dine følger denne lista.</div>';
    } else {
      list.innerHTML = f.map(function (id) {
        return row('/dashboard.html?loc=' + encodeURIComponent(id), ICON.drop, NAMES[id] || id, '');
      }).join('');
    }
    open('hwbFavPanel', this);
  });
  document.getElementById('hwbMenu').addEventListener('click', function () { open('hwbMenuPanel', this); });
  mount.querySelectorAll('.hwp-close').forEach(function (b) { b.addEventListener('click', closeAll); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeAll(); });
})();
