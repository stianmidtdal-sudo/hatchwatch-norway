// Klekkemodell for ett vann — serverversjon for varslene (cron-daily.js). Innført 2026-10-14.
//
// SPEILER vann.html (hentVaerNett / serie / naar / isgangPrognose / klekking). Endres modellen der,
// må den endres her også. Grunnlag: tools/research_analyser/J_offset/J_RAPPORT.md.
//   Vulgata:    varmesum fra 1. april (base 0) >= 450
//   Marginata:  start = senest av isgang + 14 og varmesum fra 1. april >= 200 (topp +3, slutt +7)
//   Vespertina: marginata + 7
//   Isgang:     satellittdato for året hvis den finnes, ellers graddager fra 1. mars mot vannets
//               egen terskel (midtverdien av varmesummen ved isgang tidligere år)
// Temperatur: open-meteo (ERA5-arkiv + varsel), skalert til vannets høyde.

const T_VULG = 450, T_MARG = 200, GRUPPER = 64;

function ymd(d) { return d.toISOString().slice(0, 10); }
function doyOf(d) { return Math.floor((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400000) + 1; }
function median(a) { const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }

export async function hentVann(baseUrl, id) {
    const r = await fetch(`${baseUrl}/data/kart/vann/${id % GRUPPER}.json`);
    if (!r.ok) return null;
    const g = await r.json();
    return g[String(id)] || null;
}

async function hentVaer(v, idag) {
    const q = `?latitude=${v.lat}&longitude=${v.lon}${v.moh != null ? `&elevation=${v.moh}` : ''}&daily=temperature_2m_mean&timezone=Europe%2FOslo`;
    const slutt = new Date(idag); slutt.setUTCDate(slutt.getUTCDate() - 5);
    const start = `${idag.getUTCFullYear() - 6}-03-01`;
    const j = async (u) => { const r = await fetch(u); if (!r.ok) throw new Error(`open-meteo ${r.status}`); return r.json(); };
    const [a, f] = await Promise.all([
        j(`https://archive-api.open-meteo.com/v1/archive${q}&start_date=${start}&end_date=${ymd(slutt)}`),
        j(`https://api.open-meteo.com/v1/forecast${q}&past_days=10&forecast_days=16`).catch(() => null),
    ]);
    const w = {}, today = ymd(idag);
    [a, f].forEach((src, i) => {
        if (!src || !src.daily) return;
        src.daily.time.forEach((t, k) => {
            const x = src.daily.temperature_2m_mean[k];
            if (x == null) return;
            if (i === 0 || !w[t]) w[t] = { t: x, m: i === 0 || t < today };
        });
    });
    return w;
}

function serie(w, S) {
    const klima = {};
    for (let y = S - 5; y < S; y++) {
        for (let d = new Date(Date.UTC(y, 2, 1)); d.getUTCMonth() <= 8; d.setUTCDate(d.getUTCDate() + 1)) {
            const x = w[ymd(d)]; if (x) (klima[doyOf(d)] = klima[doyOf(d)] || []).push(x.t);
        }
    }
    const s = [];
    for (let d = new Date(Date.UTC(S, 2, 1)); d.getUTCMonth() <= 8; d.setUTCDate(d.getUTCDate() + 1)) {
        const n = doyOf(d), x = w[ymd(d)], kl = klima[n];
        s.push({ n, t: x ? x.t : kl ? kl.reduce((a, b) => a + b, 0) / kl.length : null, kilde: x ? (x.m ? 'm' : 'v') : 'k' });
    }
    return s;
}

function naar(s, fra, terskel) {
    let sum = 0;
    for (const p of s) {
        if (p.n < fra) continue;
        if (p.t == null) return null;
        sum += Math.max(p.t, 0);
        if (sum >= terskel) return p.n;
    }
    return null;
}

function varmesumTil(s, fra, til) {
    let sum = 0;
    for (const p of s) if (p.n >= fra && p.n <= til) sum += Math.max(p.t || 0, 0);
    return sum;
}

function isgangPrognose(v, w, S) {
    const isg = v.isg || {}, aar = Object.keys(isg).map(Number);
    if (aar.length < 4) return null;
    const klima = median(aar.map(y => isg[y][0]));
    if (klima < 91) return Math.round(klima);
    const terskler = aar.filter(y => y >= S - 6 && y < S).map(y => varmesumTil(serie(w, y), 60, isg[y][0])).filter(x => x > 0);
    if (terskler.length < 2) return Math.round(klima);
    const g = naar(serie(w, S), 60, median(terskler));
    return g || Math.round(klima);
}

// Returnerer { S, isgang: {doy, sat}, marginata: startDoy|null, vulgata: doy|null } for sesongen S (= i år)
export async function regnVann(v, idag = new Date()) {
    const S = idag.getUTCFullYear();
    const isg = v.isg || {};
    const sat = isg[S] ? isg[S][0] : null;
    const ut = { S, isgang: sat ? { doy: sat, sat: true } : null, marginata: null, vulgata: null };
    let w;
    try { w = await hentVaer(v, idag); } catch (e) { ut.feil = e.message; return ut; }
    const s = serie(w, S);
    if (!ut.isgang) { const p = isgangPrognose(v, w, S); if (p) ut.isgang = { doy: p, sat: false }; }
    const gm = naar(s, 91, T_MARG);
    if (ut.isgang && gm) ut.marginata = Math.max(ut.isgang.doy + 14, gm);
    if (!(v.ha > 3000)) ut.vulgata = naar(s, 91, T_VULG);
    return ut;
}

// ── Spinnerfall i kveld (2026-10-14) ────────────────────────────────────────
// SPEILER computeSpinnerfallForecast i dashboard.html (hatchStatusMult × weatherScore), uten
// backlog-løftet (det krever værhistorikk vi ikke har per vann). Endres kurvene der, endre her.
// kveld = ett døgn fra /api/spinnerfall (kveld 19–22): {wind, gust, temp, cloud, precip, humid, pressureTrend}
// dagerEtterStart = i dag minus modellens vulgata-start. Gir sannsynlighet 0–1.
function klekkeFaktor(d) {
    if (d < 0) return 0;
    if (d <= 3) return 0.55;
    if (d <= 14) return 1.0;
    if (d <= 21) return 0.6;
    return 0;
}
function vaerSkaar(w) {
    const vind = w.wind <= 1.5 ? 1.0 : w.wind <= 2.5 ? 0.85 : w.wind <= 3.5 ? 0.4 : w.wind <= 5.0 ? 0.15 : 0.03;
    const kast = w.gust == null ? 1.0 : w.gust <= 3 ? 1.0 : w.gust <= 5 ? 0.9 : w.gust <= 7 ? 0.7 : w.gust <= 10 ? 0.4 : 0.15;
    const temp = w.temp >= 18 ? 1.0 : w.temp >= 16 ? 0.85 : w.temp >= 14 ? 0.55 : w.temp >= 12 ? 0.3 : 0.05;
    const sky = w.cloud < 30 ? 1.0 : w.cloud < 70 ? 0.9 : 0.75;
    const regn = w.precip < 0.1 ? 1.0 : w.precip < 0.3 ? 0.85 : w.precip < 0.7 ? 0.55 : 0.2;
    const fukt = w.humid == null ? 1.0 : w.humid >= 75 ? 1.0 : w.humid >= 60 ? 0.95 : 0.85;
    const trykk = w.pressureTrend == null ? 1.0 : w.pressureTrend >= -1 ? 1.0 : w.pressureTrend >= -3 ? 0.9 : 0.7;
    return vind * kast * temp * sky * regn * fukt * trykk;
}
export function spinnerfallSjanse(kveld, dagerEtterStart) {
    if (!kveld || dagerEtterStart == null) return 0;
    return Math.min(1, klekkeFaktor(dagerEtterStart) * vaerSkaar(kveld));
}
// Samme grense som «Høy» i dashboardets spinnerfall-kort.
export const SPINNER_HOY = 0.6;

export function datoTekst(S, doy, en) {
    const d = new Date(Date.UTC(S, 0, doy));
    const no = ['jan', 'feb', 'mars', 'april', 'mai', 'juni', 'juli', 'aug', 'sep', 'okt', 'nov', 'des'];
    const eng = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return en ? `${d.getUTCDate()} ${eng[d.getUTCMonth()]}` : `${d.getUTCDate()}. ${no[d.getUTCMonth()]}`;
}

export function finnes(v, latin, nokkel) {
    return (v.arter || []).some(a => a[0] === latin) || !!(v.bekreftet && v.bekreftet[nokkel]);
}

export { doyOf };
