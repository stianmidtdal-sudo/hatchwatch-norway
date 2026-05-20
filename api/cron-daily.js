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
// Vercel Cron har ingen body — vi støtter også manuell GET for testing.
// Hvis en push-server returnerer 404/410, fjernes subscription automatisk
// (bruker har avinstallert appen eller skrudd av varsler).
//
// Innført 2026-05-19.

import { redis, k, hashEndpoint } from '../lib/redis.js';
import { sendPush, buildPayload } from '../lib/push.js';

// Maks antall subs vi prosesserer i én kjøring — beskytt mot timeout.
const MAX_SUBS_PER_RUN = 200;

export default async function handler(req, res) {
    // Tillat både GET (Vercel Cron / manuell test) og POST
    if (req.method !== 'GET' && req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
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

                    for (const trigger of triggers) {
                        // Debounce-sjekk
                        const debounceKey = k.notif(hash, trigger, locId);
                        const recent = await r.get(debounceKey);
                        if (recent && recent === todayIso) continue;  // Allerede sendt i dag

                        const decision = await evaluateTrigger(trigger, locId);
                        if (!decision.fire) continue;

                        // Send push
                        const subscription = { endpoint: sub.endpoint, keys: sub.keys };
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
            const delta = cur.predDoy - prev.predDoy;
            if (Math.abs(delta) < 2) return { fire: false };  // Krev ≥ 2 dager
            const isEarlier = delta < 0;
            const deltaText = `${Math.abs(delta)} dager ${isEarlier ? 'tidligere' : 'senere'}`;
            const predDate = formatNorwegianDate(cur.predDate);
            return { fire: true, data: { predDate, deltaText, delta } };
        }

        case 'klekkeImminent': {
            const cur = await r.get(k.pred(locId, 'vulgata'));
            if (!cur || !cur.predDoy) return { fire: false };
            const todayDoy = dayOfYear(new Date());
            const daysUntil = cur.predDoy - todayDoy;
            if (daysUntil < 1 || daysUntil > 2) return { fire: false };
            const predDate = formatNorwegianDate(cur.predDate);
            return {
                fire: true,
                data: { predDate, info: `Klekking om ${daysUntil} dag${daysUntil === 1 ? '' : 'er'}.` },
            };
        }

        case 'seasonstart': {
            const cur = await r.get(k.pred(locId, 'vulgata'));
            if (!cur || !cur.predDoy) return { fire: false };
            const todayDoy = dayOfYear(new Date());
            const daysUntil = cur.predDoy - todayDoy;
            if (daysUntil < 7 || daysUntil > 10) return { fire: false };  // Litt før klekking
            const predDate = formatNorwegianDate(cur.predDate);
            return { fire: true, data: { species: 'Vulgata · Grandis', predDate } };
        }

        case 'spinnerfall': {
            // Aktiv kun i vulgata-sesongen (mai-juli)
            const m = new Date().getMonth();  // 4=mai, 5=juni, 6=juli
            if (m < 4 || m > 6) return { fire: false };
            // Sjekk om dagens kvelds-skår er grønn via /api/spinnerfall.
            // Vi trenger lat/lon per lokasjon. Hardkodet liste her.
            const ll = LOC_LATLON[locId];
            if (!ll) return { fire: false };
            try {
                const url = `${getBaseUrl()}/api/spinnerfall?lat=${ll.lat}&lon=${ll.lon}`;
                const resp = await fetch(url);
                if (!resp.ok) return { fire: false };
                const data = await resp.json();
                // Forventet shape: { evenings: [{date, score, ...}, ...] }
                // Skår > 0.7 (justerbar) = grønn nok til å varsle
                const today = (data.evenings || []).find(e => e.date === new Date().toISOString().slice(0, 10));
                if (!today || (today.score ?? 0) < 0.7) return { fire: false };
                return { fire: true, data: { info: `Skår ${Math.round(today.score * 100)}/100.` } };
            } catch (e) {
                return { fire: false };
            }
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

            // Sesongvindu: 20. mai - 15. juli (doy 140-196).
            // Camponotus-sverming i Sør-Norge konsentrerer seg i denne perioden.
            const todayDoy = dayOfYear(new Date());
            if (todayDoy < 140 || todayDoy > 196) return { fire: false };

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

                return {
                    fire: true,
                    data: {
                        info: `Maks ${Math.round(maxTemp)}°C, vind ${avgWind.toFixed(1)} m/s, skyer ${Math.round(avgClouds)} %. Skår ${score}/100.`,
                    },
                };
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

function formatNorwegianDate(isoStr) {
    if (!isoStr) return '—';
    const months = ['jan','feb','mar','apr','mai','jun','jul','aug','sep','okt','nov','des'];
    const d = new Date(isoStr);
    return `${d.getDate()}. ${months[d.getMonth()]}`;
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
    'bergen', 'rena', 'finnemarka', 'hardangervidda', 'rondane',
    'roros', 'trondheim',
]);
