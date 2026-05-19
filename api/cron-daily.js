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

import { redis, k, hashEndpoint } from './_lib/redis.js';
import { sendPush, buildPayload } from './_lib/push.js';

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
            // STUB — implementeres når Stokkmaur-værmelder er bygget.
            // Foreløpig: aldri fyrer i prod, men kan testes via push-test-trigger.
            return { fire: false };
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
// Brukes for å hente MET-data i spinnerfall-evalueringen.
const LOC_LATLON = {
    kautokeino: { lat: 69.01, lon: 23.04 },
    ostmarka:   { lat: 59.70, lon: 11.17 },
    oslo:       { lat: 59.94, lon: 10.72 },
    nordmarka_dyn: { lat: 59.94, lon: 10.72 },
    vestfjella: { lat: 59.30, lon: 11.66 },
    bergen:     { lat: 60.39, lon: 5.32 },
};
