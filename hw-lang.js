// ═══════════════════════════════════════════════════════════════════
//  HatchWatch felles språkvalg (innført 2026-10-08)
//
//  Lastes SYNKRONT i <head> på alle sider, før sidens eget skript:
//      <script src="/hw-lang.js"></script>
//
//  Valget lagres i localStorage 'lang' ('no' | 'en'), samme nøkkel som
//  dashboardet har brukt hele tiden, så et valg gjort ett sted gjelder
//  overalt. Første besøk uten lagret valg: norsk for telefoner på norsk,
//  svensk eller dansk, engelsk for alle andre (finnene var grunnen).
//  Knappen i menyen overstyrer alltid.
//
//  Gir:  window.HW_LANG        'no' | 'en'
//        window.hwT(no, en)    velg tekst etter språk
//        window.hwToggleLang() bytt språk og last siden på nytt
// ═══════════════════════════════════════════════════════════════════
(function () {
  'use strict';
  var lang = null;
  try { lang = localStorage.getItem('lang'); } catch (e) {}
  if (lang !== 'no' && lang !== 'en') {
    var nav = ((navigator.languages && navigator.languages[0]) || navigator.language || 'no').toLowerCase();
    lang = /^(nb|nn|no|sv|da)/.test(nav) ? 'no' : 'en';
    try { localStorage.setItem('lang', lang); } catch (e) {}
  }
  window.HW_LANG = lang;
  document.documentElement.setAttribute('lang', lang);
  window.hwT = function (no, en) { return lang === 'en' ? en : no; };
  window.hwToggleLang = function () {
    try { localStorage.setItem('lang', lang === 'no' ? 'en' : 'no'); } catch (e) {}
    location.reload();
  };
})();
