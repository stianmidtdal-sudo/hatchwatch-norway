// Vercel Cron — kjøres daglig kl. 06:00 UTC (08:00 norsk tid).
// Looper gjennom alle aktive subscriptions, sjekker trigger-betingelser
// mot stored predictions, sender push for de som matcher.
//
// Konfigureres i vercel.json via crons-array. Vercel kaller dette
// endpointet uten body. Returnerer JSON-rapport med antall sendt + feil.
//
// Trigger-logikk (alle bruker stored predictions fra /api/store-prediction):
//
//   klekkeChange   — predDoy har endret seg ≥ 2 d siden forrige lagring.
//                    Krever forrige record i pred:{loc}:{species}:prev.
//   klekkeImminent — predDate er innen 2 dager fra nå.
//                    Debounce: maks 1 push per (sub, trigger, loc) per dag.
//   spinnerfall    — i kveld er forholdene gode for vulgata-spinnerfall.
//                    Krever live MET-data (kalles via /api/spinnerfall).
//                    Aktiv kun i vulgata-sesongen (~mai-juli).
//   stokkmaur      — værforholdene treffer stokkmaur-svermings-kriteriene
//                    i dag eller neste 2 dager.
//                    (Foreløpig stub — bygges ut når Stokkmaur-værmelder er live.)
//   seasonstart    — predDate er innen 7-10 dager (sesongen åpner snart).
//
// Debounce: notif:{hash}:{trigger}:{loc} settes med TTL 22 t etter send.
// Hvis nøkkelen finnes, hopper vi over (unngår dupliserte pushes).
//
// Vercel Cron har ingen body. Manuell GET for testing krever samme header som Vercel sender
// (Authorization: Bearer <CRON_SECRET>) når CRON_SECRET er satt.
// Hvis en push-server returnerer 404/410, fjernes subscription automatisk
// (bruker har avinstallert appen eller skrudd av varsler).
//
// Innført 2026-05-19.

import { redis, k, hashEndpoint } from '../lib/redis.js';
import { sendPush, buildPayload, buildVannPayload, pushDato } from '../lib/push.js';
import { hentVann, regnVann, finnes, doyOf, spinnerfallSjanse, SPINNER_HOY } from '../lib/vannmodell.js';
import { internNokkel } from '../lib/fartsgrense.js';
import crypto from 'crypto';

// 2026-10-17: bare Vercel Cron får starte runden. Når CRON_SECRET er satt i Vercel, sender Vercel
// «Authorization: Bearer <CRON_SECRET>» med de planlagte kallene; alle andre får 401. Mangler
// variabelen, slippes kallet gjennom som før (så ingenting stopper før den er lagt inn).
function fraVercelCron(req) {
    const hemmelig = (process.env.CRON_SECRET || '').trim();
    if (!hemmelig) return true;
    const a = crypto.createHash('sha256').update(String(req.headers.authorization || '')).digest();
    const b = crypto.createHash('sha256').update('Bearer ' + hemmelig).digest();
    return crypto.timingSafeEqual(a, b);
}

// Maks antall subs vi prosesserer i én kjøring — beskytt mot timeout.
const MAX_SUBS_PER_RUN = 200;
// Vannvarsler (2026-10-14): nøkkel «vann:<NVE-id>» i sub.locations, triggere under. Modellen regnes
// én gang per vann per kjøring (lib/vannmodell.js, speiler vann.html). Hvert varsel sendes én gang
// per sesong per vann. Maks antall vann vi regner per kjøring (open-meteo + tidsgrense).
// spinnerfall (2026-10-14): kan komme hver kveld i vulgata-sesongen, så den har dagsnøkkel i stedet for sesongnøkkel.
const VANN_TRIGGERS = ['isgang', 'marginata', 'vulgata', 'spinnerfall'];
const MAX_VANN_PER_RUN = 80;

export default async function handler(req, res) {
    // Tillat både GET (Vercel Cron / manuell test) og POST
    if (req.method !== 'GET' && req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }
    if (!fraVercelCron(req)) {
        return res.status(401).json({ error: 'Ikke tillatt' });
    }

    try {
        const r = redis();
        const allHashes = await r.smembers(k.subsAll);
        const subsToProcess = (allHashes || []).slice(0, MAX_SUBS_PER_RUN);

        const todayIso = new Date().toISOString().slice(0, 10);
        const stats = {
            processed: 0,
            sent: 0,
            errors: [],
            expired: 0,
            byTrigger: {},
        };

        const vannCache = new Map();   // NVE-id → { v, m } (eller null) for denne kjøringen
        for (const hash of subsToProcess) {
            try {
                const sub = await r.get(k.sub(hash));
                if (!sub || !sub.locations || !sub.endpoint) {
                    await r.del(k.sub(hash));
                    await r.srem(k.subsAll, hash);
                    continue;
                }
                stats.processed++;

                for (const [locId, triggers] of Object.entries(sub.locations)) {
                    if (!Array.isArray(triggers) || triggers.length === 0) continue;
                    if (locId.startsWith('vann:')) {
                        const ut = await handleVann(r, hash, sub, locId, triggers, stats, vannCache);
                        if (ut === 'expired') break;
                        continue;
                    }

                    for (const trigger of triggers) {
                        // Debounce-sjekk
                        const debounceKey = k.notif(hash, trigger, locId);
                        const recent = await r.get(debounceKey);
                        if (recent && recent === todayIso) continue;  // Allerede sendt i dag

                        const decision = await evaluateTrigger(trigger, locId);
                        if (!decision.fire) continue;

                        // Send push
                        // platform/token brukes av iOS-appen (APNs); web-abonnementer har dem ikke.
                        const subscription = { endpoint: sub.endpoint, keys: sub.keys, platform: sub.platform, token: sub.token };
                        const locArea = LOC_AREAS[locId] || locId;
                        const payload = buildPayload(trigger, locArea, locId, decision.data, sub.lang);
                        const result = await sendPush(subscription, payload);

                        if (result.ok) {
                            stats.sent++;
                            stats.byTrigger[trigger] = (stats.byTrigger[trigger] || 0) + 1;
                            // Debounce: marker som sendt i dag (TTL 22 t)
                            await r.set(debounceKey, todayIso, { ex: 22 * 3600 });
                        } else if (result.expired) {
                            stats.expired++;
                            await r.del(k.sub(hash));
                            await r.srem(k.subsAll, hash);
                            break;  // Hopp til neste sub
                        } else {
                            stats.errors.push({ hash, trigger, locId, status: result.statusCode, err: result.error });
                        }
                    }
                }
            } catch (subErr) {
                stats.errors.push({ hash, err: subErr.message });
            }
        }

        return res.status(200).json({ ok: true, ...stats });
    } catch (err) {
        console.error('cron-daily error:', err);
        return res.status(500).json({ error: err.message });
    }
}

// ── Vannvarsler ─────────────────────────────────────────────────────────────
// isgang:    satellitten har sett isgangen i år (sendes én gang)
// marginata: modellens start for marginata er 0–4 dager unna
// vulgata:   modellens start for vulgata er 0–5 dager unna
// Bare i sesongen (mars–august). Ordlyd: «modellen anslår», og «gjelder bare hvis arten finnes»
// når arten ikke er registrert i vannet (samme merking som vannsiden).
async function handleVann(r, hash, sub, locId, triggers, stats, vannCache) {
    const idag = new Date();
    const mnd = idag.getUTCMonth();
    if (mnd < 2 || mnd > 7) return;
    // «vann:<NVE-id>», eller «vann:se<id>» / «vann:fi<id>» for svenske og finske vann (2026-10-17). Der finnes ingen
    // isgang ennå, så bare vulgata og spinnerfall kan utløses.
    const id = locId.slice(5);
    if (!/^(se|fi)?\d+$/.test(id)) return;
    if (!vannCache.has(id)) {
        if (vannCache.size >= MAX_VANN_PER_RUN) return;
        let rec = null;
        try {
            const v = await hentVann(getBaseUrl(), id);
            if (v) rec = { v, m: await regnVann(v, idag) };
        } catch (e) {
            stats.errors.push({ hash, locId, err: 'vannmodell: ' + e.message });
        }
        vannCache.set(id, rec);
    }
    const rec = vannCache.get(id);
    if (!rec) return;
    const { v, m } = rec;
    // Tekstene ligger i lib/push.js (buildVannPayload), på språket som er lagret med abonnementet (no/en/sv/fi).
    const dato = (doy) => pushDato(new Date(Date.UTC(m.S, 0, doy)), sub.lang);
    const iDag = doyOf(idag);
    for (const trigger of triggers) {
        if (!VANN_TRIGGERS.includes(trigger)) continue;
        const sesongKey = k.notif(hash, trigger, locId);
        const sendtFor = await r.get(sesongKey);
        if (trigger === 'spinnerfall' ? sendtFor === osloDato() : sendtFor === `sesong-${m.S}`) continue;
        let payload = null;
        if (trigger === 'spinnerfall') {
            // Bare der modellen har en vulgata-start (ikke store innsjøer), og bare 0–21 dager etter den.
            if (!m.vulgata) continue;
            const dager = iDag - m.vulgata;
            if (dager < 0 || dager > 21) continue;
            if (rec.kveld === undefined) rec.kveld = await hentKveld(v.lat, v.lon);
            const w = rec.kveld && rec.kveld[osloDato()];
            const p = spinnerfallSjanse(w, dager);
            if (p < SPINNER_HOY) continue;
            const her = finnes(v, 'Ephemera vulgata', 'vulgata');
            payload = buildVannPayload('spinnerfall', v.navn, { wind: w.wind, temp: w.temp, p, her }, sub.lang);
        } else if (trigger === 'isgang' && m.isgang && m.isgang.sat) {
            payload = buildVannPayload('isgang', v.navn, { dato: dato(m.isgang.doy), marginata: m.marginata ? dato(m.marginata) : null }, sub.lang);
        } else if ((trigger === 'marginata' || trigger === 'vulgata') && m[trigger]) {
            const dager = m[trigger] - iDag, maks = trigger === 'marginata' ? 4 : 5;
            if (dager >= 0 && dager <= maks) {
                const art = trigger === 'marginata' ? 'Marginata' : 'Vulgata';
                const latin = trigger === 'marginata' ? 'Leptophlebia marginata' : 'Ephemera vulgata';
                const her = finnes(v, latin, trigger);
                payload = buildVannPayload(trigger, v.navn, { art, dato: dato(m[trigger]), dager, her }, sub.lang);
            }
        }
        if (!payload) continue;
        payload.url = `/vann.html?id=${id}`;
        payload.tag = `vann-${trigger}-${id}`;
        const subscription = { endpoint: sub.endpoint, keys: sub.keys, platform: sub.platform, token: sub.token };
        const result = await sendPush(subscription, payload);
        if (result.ok) {
            stats.sent++;
            stats.byTrigger['vann-' + trigger] = (stats.byTrigger['vann-' + trigger] || 0) + 1;
            if (trigger === 'spinnerfall') await r.set(sesongKey, osloDato(), { ex: 22 * 3600 });
            else await r.set(sesongKey, `sesong-${m.S}`, { ex: 200 * 86400 });
        } else if (result.expired) {
            stats.expired++;
            await r.del(k.sub(hash));
            await r.srem(k.subsAll, hash);
            return 'expired';
        } else {
            stats.errors.push({ hash, trigger, locId, status: result.statusCode, err: result.error });
        }
    }
}

// Lokasjon-IDer → visningsnavn for notifications. Holdes synkronisert med
// LOCATIONS i dashboard.html (ikke automatisk — manuell oppdatering ved nye lokasjoner).
const LOC_AREAS = {
    kautokeino: 'Kautokeino',
    ostmarka: 'Østmarka',
    oslo: 'Nordmarka',
    nordmarka_dyn: 'Nordmarka',
    vestfjella: 'Vestfjella',
    fjella: 'Fjella',
    bergen: 'Bergen',
    bardufoss: 'Bardufoss',
    rena: 'Rena',
    dividalen: 'Dividalen',
    trondheim: 'Trondheim',
    finnemarka: 'Finnemarka',
    hardangervidda: 'Hardangervidda',
    ifjordfjellet: 'Ifjordfjellet',
    rondane: 'Rondane',
    roros: 'Røros',
    porsanger: 'Porsanger',
    alta: 'Alta',
    narvik: 'Narvik',
    lierne: 'Lierne',
    borgefjell: 'Børgefjell',
    moirana: 'Mo i Rana',
};

// Trigger-evaluering — returnerer { fire: bool, data: {...} }
async function evaluateTrigger(trigger, locId) {
    const r = redis();

    switch (trigger) {
        case 'klekkeChange': {
            const cur = await r.get(k.pred(locId, 'vulgata'));
            const prev = await r.get(k.pred(locId, 'vulgata') + ':prev');
            if (!cur || !prev || cur.predDoy == null || prev.predDoy == null) {
                return { fire: false };
            }
            // Bug-fix 2026-05-29: når klekkingen har startet (predDoy <= today),
            // gir et "prediksjonen har flyttet seg X dager"-varsel ingen mening.
            // Det skjer typisk når modellen begynner å rapportere faktisk krysnings-
            // dato i fortid i stedet for en fremtidig prediksjon. Varselet skal kun
            // utløses så lenge klekkingen fortsatt ligger fremover i tid.
            const todayDoy = dayOfYear(new Date());
            if (cur.predDoy <= todayDoy) return { fire: false };
            const delta = cur.predDoy - prev.predDoy;
            if (Math.abs(delta) < 2) return { fire: false };  // Krev ≥ 2 dager
            // Rå verdier; teksten skrives på abonnentens språk i buildPayload (lib/push.js).
            return { fire: true, data: { predIso: cur.predDate, delta } };
        }

        case 'klekkeImminent': {
            const cur = await r.get(k.pred(locId, 'vulgata'));
            if (!cur || !cur.predDoy) return { fire: false };
            const todayDoy = dayOfYear(new Date());
            const daysUntil = cur.predDoy - todayDoy;
            if (daysUntil < 1 || daysUntil > 2) return { fire: false };
            return { fire: true, data: { predIso: cur.predDate, daysUntil } };
        }

        case 'seasonstart': {
            const cur = await r.get(k.pred(locId, 'vulgata'));
            if (!cur || !cur.predDoy) return { fire: false };
            const todayDoy = dayOfYear(new Date());
            const daysUntil = cur.predDoy - todayDoy;
            if (daysUntil < 7 || daysUntil > 10) return { fire: false };  // Litt før klekking
            return { fire: true, data: { species: 'Vulgata · Grandis', predIso: cur.predDate } };
        }

        case 'spinnerfall': {
            // Rettet 2026-10-14: koden ventet { evenings: [{date, score}] }, men /api/spinnerfall gir
            // { 'YYYY-MM-DD': {wind, temp, ...} } uten skår, så varselet kunne aldri gå. Nå regnes samme
            // sannsynlighet som dashboardets spinnerfall-kort (lib/vannmodell.js) mot lagret vulgata-prognose.
            const ll = LOC_LATLON[locId];
            if (!ll) return { fire: false };
            const cur = await r.get(k.pred(locId, 'vulgata'));
            if (!cur || !cur.predDoy) return { fire: false };
            if (cur.predDate && String(cur.predDate).slice(0, 4) !== osloDato().slice(0, 4)) return { fire: false };   // fjorårets prognose
            const dager = dayOfYear(new Date()) - cur.predDoy;
            if (dager < 0 || dager > 21) return { fire: false };
            const kveld = await hentKveld(ll.lat, ll.lon);
            const w = kveld && kveld[osloDato()];
            const p = spinnerfallSjanse(w, dager);
            if (p < SPINNER_HOY) return { fire: false };
            return { fire: true, data: { wind: w.wind, temp: w.temp, p } };
        }

        case 'stokkmaur': {
            // Geografisk gate: Camponotus svermer ikke pålitelig i Nord-Norge.
            // C. herculeanus finnes så langt nord som Bodø-området, men svermer
            // ujevnt der. Cutoff = lat 65°N (Sør- og Midt-Norge inkluderes,
            // Nordland/Troms/Finnmark ekskluderes). Lierne (64.4) inkluderes
            // ikke per STOKKMAUR_LOCATIONS-allowlist heller.
            if (!STOKKMAUR_LOCATIONS.has(locId)) return { fire: false };
            const ll = LOC_LATLON[locId];
            if (!ll) return { fire: false };

            // Sesongvindu: 20. mai - 30. juni (doy 140-181).
            // Camponotus-sverming i Sør-Norge konsentrerer seg fra siste halvdel
            // av mai gjennom juni, med topp rundt midtsommer. Juli-sverming er
            // unntaket, ikke regelen.
            // Endret 2026-08-18 (Stian): var doy 196 (15. juli) — for sent, ga
            // varsler i en periode der stokkmaur i praksis ikke svermer.
            const todayDoy = dayOfYear(new Date());
            if (todayDoy < 140 || todayDoy > 181) return { fire: false };

            try {
                const url = `https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=${ll.lat}&lon=${ll.lon}`;
                const resp = await fetch(url, {
                    headers: { 'User-Agent': 'hatchwatch.no support@hatchwatch.no' },
                });
                if (!resp.ok) return { fire: false };
                const data = await resp.json();
                const series = data.properties?.timeseries || [];

                // Sjekk dagens ettermiddag (12-18) — peak svermingstid for stokkmaur
                const todayIso = new Date().toISOString().slice(0, 10);
                const afternoon = series.filter(ts => {
                    const t = new Date(ts.time);
                    return t.toISOString().slice(0, 10) === todayIso
                        && t.getUTCHours() >= 10 && t.getUTCHours() <= 16;  // UTC 10-16 ≈ norsk 12-18
                });
                if (afternoon.length === 0) return { fire: false };

                let maxTemp = -Infinity, sumWind = 0, sumClouds = 0, sumRain = 0, n = 0;
                for (const ts of afternoon) {
                    const det = ts.data?.instant?.details || {};
                    if (det.air_temperature != null) maxTemp = Math.max(maxTemp, det.air_temperature);
                    if (det.wind_speed != null) { sumWind += det.wind_speed; }
                    if (det.cloud_area_fraction != null) { sumClouds += det.cloud_area_fraction; }
                    const rain1h = ts.data?.next_1_hours?.details?.precipitation_amount;
                    if (rain1h != null) sumRain += rain1h;
                    n++;
                }
                if (n === 0) return { fire: false };
                const avgWind = sumWind / n;
                const avgClouds = sumClouds / n;

                // Kriterier (alle må oppfylles):
                //   maxTemp ≥ 18°C, vind ≤ 5 m/s, skyer ≤ 70%, nedbør ≤ 1 mm
                if (maxTemp < 18) return { fire: false };
                if (avgWind > 5) return { fire: false };
                if (avgClouds > 70) return { fire: false };
                if (sumRain > 1) return { fire: false };

                // Skår 0-100 — hvor "ideelt" det er
                const score = Math.max(0, Math.min(100, Math.round(
                    Math.min(30, ((maxTemp - 18) / 7) * 30)
                    + Math.max(0, ((5 - avgWind) / 5) * 25)
                    + Math.max(0, ((70 - avgClouds) / 70) * 25)
                    + (sumRain < 0.2 ? 20 : 10)
                )));

                // Krev høy sannsynlighet før vi fyrer av push. Tidligere fyrte vi når
                // bare de harde kriteriene var oppfylt (≥18°C, ≤5 m/s osv.), som ga
                // notifications ved skår 20-40 — marginalt vær og lav nytteverdi.
                // 80 ≈ "varmt + lite vind + lite skyer + tørt" — verdt å bli varslet om.
                if (score < 80) return { fire: false };

                return { fire: true, data: { maxTemp, wind: avgWind, clouds: avgClouds, score } };
            } catch (e) {
                console.error('stokkmaur eval error:', e);
                return { fire: false };
            }
        }

        default:
            return { fire: false };
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function dayOfYear(date) {
    const start = Date.UTC(date.getUTCFullYear(), 0, 1);
    return Math.floor((Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()) - start) / 86400000) + 1;
}

// Dagens dato i Oslo (YYYY-MM-DD) — nøklene fra /api/spinnerfall er Oslo-datoer.
function osloDato() {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Oslo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

// Kveldsvær (19–22) per dato fra /api/spinnerfall, eller null.
async function hentKveld(lat, lon) {
    try {
        const resp = await fetch(`${getBaseUrl()}/api/spinnerfall?lat=${lat}&lon=${lon}`, { headers: { 'x-hw-intern': internNokkel() } });   // forbi fartsgrensen
        return resp.ok ? await resp.json() : null;
    } catch (e) {
        return null;
    }
}

function getBaseUrl() {
    // Vercel setter VERCEL_URL automatisk for prod og preview
    if (process.env.VERCEL_URL) return `https://${process.env.VERCEL_URL}`;
    if (process.env.HATCHWATCH_BASE_URL) return process.env.HATCHWATCH_BASE_URL;
    return 'https://www.hatchwatch.no';
}

// Lat/lon per lokasjon — synkronisert med LOCATIONS i dashboard.html.
// Brukes for å hente MET-data i spinnerfall- og stokkmaur-evalueringen.
const LOC_LATLON = {
    kautokeino: { lat: 69.01, lon: 23.04 },
    ostmarka:   { lat: 59.70, lon: 11.17 },
    oslo:       { lat: 59.94, lon: 10.72 },
    nordmarka_dyn: { lat: 59.94, lon: 10.72 },
    vestfjella: { lat: 59.30, lon: 11.66 },
    fjella:     { lat: 59.36, lon: 11.62 },
    bergen:     { lat: 60.39, lon: 5.32 },
    rena:       { lat: 61.15, lon: 11.37 },
    trondheim:  { lat: 63.43, lon: 10.39 },
    finnemarka: { lat: 59.85, lon: 10.10 },
    hardangervidda: { lat: 60.10, lon: 7.30 },
    rondane:    { lat: 61.97, lon: 9.84 },
    roros:      { lat: 62.57, lon: 11.39 },
    lierne:     { lat: 64.41, lon: 13.61 },
    bardufoss:  { lat: 69.07, lon: 18.54 },
    dividalen:  { lat: 68.78, lon: 19.71 },
    ifjordfjellet: { lat: 70.60, lon: 27.10 },
    porsanger:  { lat: 70.10, lon: 25.00 },
    alta:       { lat: 69.97, lon: 23.27 },
    narvik:     { lat: 68.44, lon: 17.43 },
    moirana:    { lat: 66.31, lon: 14.14 },
    borgefjell: { lat: 65.40, lon: 13.80 },
};

// Lokasjoner der Camponotus-stokkmaur er aktuelt. Allowlist heller enn
// breddegrad-cutoff — gir eksplisitt kontroll og er lett å justere.
// Utbredelse: C. herculeanus (Sør- og Midt-Norge) og C. ligniperdus (Sør).
// Ekskluderer Nord-Norge (Nordland/Troms/Finnmark) og høyfjellslokasjoner
// der svermer er ujevn og uforutsigbar.
const STOKKMAUR_LOCATIONS = new Set([
    'oslo', 'nordmarka_dyn', 'ostmarka', 'vestfjella', 'fjella',
    'bergen', 'rena', 'finnemarka', 'rondane', 'roros', 'trondheim',
    // Ekskludert: hardangervidda (høyfjellstundra — ingen stokkmaur).
]);
