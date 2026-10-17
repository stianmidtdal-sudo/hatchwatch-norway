// ═══════════════════════════════════════════════════════════════════
//  HatchWatch felles språkvalg (innført 2026-10-08; svensk og finsk fra 2026-10-17)
//
//  Lastes SYNKRONT i <head> på alle sider, før sidens eget skript:
//      <script src="/hw-lang.js"></script>
//
//  Språk: 'no' | 'en' | 'sv' | 'fi', lagret i localStorage 'lang' (samme nøkkel
//  som dashboardet har brukt hele tiden). Første besøk følger telefonens språk:
//  norsk/dansk → norsk, svensk → svensk, finsk → finsk, alt annet → engelsk
//  (Stian 17.10: «Mikko i Kautokeino skal få finsk», derfor telefonens språk og
//  ikke landet man står i). Valget i menyen (hw-shell.js) overstyrer. Én gang
//  (lang_v2) får svenske og finske telefoner sitt eget språk, også om de hadde
//  norsk/engelsk fra før — det fikk de automatisk da bare to språk fantes.
//
//  Koden skrives fortsatt med norsk og engelsk side om side: tx('norsk', 'english')
//  → hwT. Svensk og finsk ligger i /i18n/sv.js og /i18n/fi.js (window.HW_I18N) og
//  slås opp på den NORSKE teksten — eksakt, eller som mal der tall, navn og datoer
//  er spleiset inn ({0}, {1} …; tools/i18n/trekk_ut.cjs lager malene). Mangler en
//  tekst, vises norsk for svensk og engelsk for finsk. ?i18n=1 logger det som
//  mangler i konsollen.
//
//  Gir:  window.HW_LANG, window.HW_LOCALE
//        window.hwT(no, en)           tekst etter språk
//        window.hwArt(latin, no, en)  artsnavn (svensk/finsk fra HW_I18N.arter)
//        window.hwDato(d, kort)       «16. april» / «16 Apr» / «16 april» / «16.4.»
//        window.hwMnd()               månedsnavn (kort form) for språket
//        window.hwI18nSide(EN, side)  data-i18n-sidene: engelsk ordbok eller HW_I18N.k
//        window.hwSettSpraak(l)       velg språk og last siden på nytt
//        window.hwToggleLang()        (eldre) bytt mellom norsk og engelsk
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';
  var SPRAK = ['no', 'en', 'sv', 'fi'];
  var nav = ((navigator.languages && navigator.languages[0]) || navigator.language || 'no').toLowerCase();
  var telefon = /^(nb|nn|no|da)/.test(nav) ? 'no' : /^sv/.test(nav) ? 'sv' : /^fi/.test(nav) ? 'fi' : 'en';
  var lang = null, v2 = null;
  try { lang = localStorage.getItem('lang'); v2 = localStorage.getItem('lang_v2'); } catch (e) {}
  if (SPRAK.indexOf(lang) < 0 || (!v2 && (telefon === 'sv' || telefon === 'fi'))) lang = telefon;
  try { localStorage.setItem('lang', lang); localStorage.setItem('lang_v2', '1'); } catch (e) {}
  window.HW_LANG = lang;
  window.HW_LOCALE = { no: 'nb-NO', en: 'en-GB', sv: 'sv-SE', fi: 'fi-FI' }[lang];
  document.documentElement.setAttribute('lang', lang);

  // Svensk og finsk: ordboka lastes synkront her, så den er klar før sidens eget skript kjører.
  // Bytt I18N_V når oversettelsene endres (tvinger ny henting forbi hurtigbufferen).
  var I18N_V = '1';
  if (lang === 'sv' || lang === 'fi') {
    document.write('<script src="/i18n/' + lang + '.js?v=' + I18N_V + '"><\/script>');
    if (/\/artikler(\.html)?$/.test(location.pathname)) document.write('<script src="/i18n/' + lang + '-artikler.js?v=' + I18N_V + '"><\/script>');
  }

  var debug = /[?&]i18n=1/.test(location.search), mangler = {};
  function merk(no) {
    if (!debug || mangler[no]) return;
    mangler[no] = 1;
    try { console.info('[i18n] mangler (' + lang + '):', no); } catch (e) {}
  }
  var maler = null;
  function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function oversett(no) {
    var I = window.HW_I18N;
    if (!I || no == null) return null;
    var s = String(no), x = I.t && I.t[s];
    if (x != null) return x;
    if (!maler) maler = (I.m || []).map(function (p) {
      return { re: new RegExp('^' + p[0].split(/\{\d+\}/).map(escRe).join('([\\s\\S]*?)') + '$'), ut: p[1] };
    });
    for (var i = 0; i < maler.length; i++) {
      var r = maler[i].re.exec(s);
      if (r) return maler[i].ut.replace(/\{(\d+)\}/g, function (_, k) {
        var v = r[+k + 1];
        if (v == null) return '';
        var t = I.t && I.t[v];
        return t != null ? t : v;
      });
    }
    return null;
  }
  window.hwT = function (no, en) {
    if (lang === 'no') return no;
    if (lang === 'en') return en;
    var x = oversett(no);
    if (x != null) return x;
    merk(no);
    return lang === 'fi' && en != null ? en : no;
  };
  window.hwArt = function (latin, no, en) {
    if (lang === 'no') return no;
    if (lang === 'en') return en;
    var I = window.HW_I18N, x = I && I.arter && I.arter[latin];
    return x || (lang === 'fi' ? (en || no) : (no || en));
  };
  var MND = {
    no: ['jan', 'feb', 'mars', 'april', 'mai', 'juni', 'juli', 'aug', 'sep', 'okt', 'nov', 'des'],
    en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    sv: ['jan', 'feb', 'mars', 'april', 'maj', 'juni', 'juli', 'aug', 'sep', 'okt', 'nov', 'dec'],
    fi: ['tammi', 'helmi', 'maalis', 'huhti', 'touko', 'kesä', 'heinä', 'elo', 'syys', 'loka', 'marras', 'joulu']
  };
  window.hwMnd = function () { return MND[lang].slice(); };
  // Dag og måned slik hvert språk skriver det: norsk «16. april», engelsk «16 Apr», svensk «16 april», finsk «16.4.»
  window.hwDato = function (d, kort) {
    var dd = d.getDate(), m = d.getMonth();
    if (lang === 'fi') return dd + '.' + (m + 1) + '.';
    var n = MND[lang][m];
    if (kort) n = n.slice(0, 3);
    return lang === 'no' ? dd + '. ' + n : dd + ' ' + n;
  };
  // Sider med data-i18n / data-i18n-html: engelsk fra sidens egen ordbok, svensk/finsk fra HW_I18N.k['<side>:<nøkkel>'].
  // tittelEN: sidens engelske <title>; svensk/finsk tittel ligger under nøkkelen '<side>:__title'.
  window.hwI18nSide = function (EN, side, tittelEN) {
    if (lang === 'no') return;
    var K = (window.HW_I18N && window.HW_I18N.k) || {};
    var hent = function (key) {
      if (lang === 'en') return EN[key];
      var x = K[side + ':' + key];
      if (x != null) return x;
      merk(side + ':' + key);
      return lang === 'fi' ? EN[key] : null;
    };
    document.querySelectorAll('[data-i18n]').forEach(function (el) { var v = hent(el.getAttribute('data-i18n')); if (v) el.textContent = v; });
    document.querySelectorAll('[data-i18n-html]').forEach(function (el) { var v = hent(el.getAttribute('data-i18n-html')); if (v) el.innerHTML = v; });
    if (tittelEN != null) {
      var t = lang === 'en' ? tittelEN : (K[side + ':__title'] || (lang === 'fi' ? tittelEN : null));
      if (t) document.title = t;
    }
  };
  window.hwSettSpraak = function (l) {
    if (SPRAK.indexOf(l) < 0) return;
    try { localStorage.setItem('lang', l); } catch (e) {}
    location.reload();
  };
  window.hwToggleLang = function () { window.hwSettSpraak(lang === 'no' ? 'en' : 'no'); };

  // Lyst tema (2026-10-15, Stian): velger man Turkart på kartet, får hele appen det lyse fargevalget
  // (token-settet :root[data-theme="light"] i hw.css). Settes her fordi fila lastes synkront i <head>
  // på alle sider, så siden tegnes lys med en gang uten å blinke mørkt først. Kartet bytter med hwSettTema().
  window.hwSettTema = function (lys) {
    var html = document.documentElement;
    if (lys) html.setAttribute('data-theme', 'light'); else html.removeAttribute('data-theme');
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.setAttribute('content', lys ? '#f2f6f5' : '#0b1418');
  };
  // Fra 2026-10-15 (Stian) er den mørke varianten fjernet: hele appen er alltid lys.
  window.hwSettTema(true);
  document.addEventListener('DOMContentLoaded', function () { window.hwSettTema(true); });   // theme-color står ofte etter dette skriptet
})();
