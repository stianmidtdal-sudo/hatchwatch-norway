// Prediksjoner i Upstash Redis — lese OG lagre.
//
// Tre moduser:
//
//   GET /api/predictions
//     → returnerer alle lokasjoners siste vulgata-prediksjon (legacy mode).
//       Brukes av forsiden for å avgjøre om vulgata-onset er nådd.
//       Innført 2026-05-20.
//
//   GET /api/predictions?mode=history&loc=ostmarka&species=vulgata&year=2026
//     → returnerer daglig historikk for én lokasjon/art/år.
//       Brukes av konvergensgrafen for å vise ekte historikk.
//       Innført 2026-05-25.
//
//   POST /api/predictions?mode=store   (også: POST /api/store-prediction via rewrite)
//     → mottar dagens prediksjon fra frontend og lagrer den.
//       Tidligere eget endpoint api/store-prediction.js — slått sammen hit
//       2026-10-01 for å frigjøre en Vercel-function (Hobby-grense 12).
//       Body: { loc, species, predDate, predDoy, info }
//       Lagrer pred:{loc}:{species} = { predDate, predDoy, info, ts },
//       beholder forrige som :prev (cron sammenligner), og skriver én daglig
//       snapshot til predhist:{loc}:{spec}:{year} (første skriving per dag vinner).
//
// Hvis en lokasjon mangler stored prediction, returneres ingen entry — forsiden
// skal da være konservativ og IKKE vise badge.
//
// Cache (GET): 5 min på Vercel edge (prediksjoner endrer seg sjelden).

import { redis, k } from '../lib/redis.js';

const LOCATIONS = [
    'kautokeino', 'alta', 'porsanger', 'ifjordfjellet', 'dividalen',
    'bardu', 'narvik', 'mo_i_rana', 'borgefjell', 'roros', 'lierne',
    'trondheim', 'rena', 'oslo', 'nordmarka_dyn', 'finnemarka',
    'ostmarka', 'vestfjella', 'hardangervidda', 'bergen',
];

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (req.method === 'OPTIONS') {
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        return res.status(204).end();
    }

    const mode = (req.query.mode || '').toString();

    try {
        if (req.method === 'POST') {
            if (mode === 'store') return await handleStore(req, res);
            return res.status(400).json({ error: 'POST krever mode=store' });
        }
        if (req.method !== 'GET') {
            return res.status(405).json({ error: 'Method not allowed' });
        }
        if (mode === 'history') return await handleHistory(req, res);
        return await handleLatest(req, res);
    } catch (err) {
        console.error('predictions error:', err);
        return res.status(500).json({ error: err.message });
    }
}

async function handleLatest(req, res) {
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=60');
    const r = redis();
    const result = {};
    const fetches = LOCATIONS.map(async (loc) => {
        const pred = await r.get(k.pred(loc, 'vulgata'));
        if (pred && pred.predDate) {
            result[loc] = {
                predDate: pred.predDate,
                predDoy: pred.predDoy ?? null,
                ts: pred.ts ?? null,
            };
        }
    });
    await Promise.all(fetches);
    return res.status(200).json(result);
}

async function handleHistory(req, res) {
    const loc = (req.query.loc || '').toString();
    const species = (req.query.species || 'vulgata').toString();
    const year = parseInt(req.query.year, 10) || new Date().getUTCFullYear();
    if (!loc) return res.status(400).json({ error: 'Mangler loc' });

    // Kortere cache: historikken får et nytt punkt hver dag, så vi vil ikke at
    // gårsdagens svar skal cache-treffe i mer enn ~5 min.
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=60');

    const r = redis();
    const histKey = k.predHist(loc, species, year);
    const raw = await r.hgetall(histKey);
    if (!raw) return res.status(200).json({ loc, species, year, history: {} });

    // Upstash returnerer hash som object; parse JSON-verdier
    const history = {};
    for (const [date, val] of Object.entries(raw)) {
        try {
            history[date] = typeof val === 'string' ? JSON.parse(val) : val;
        } catch {
            // Hopp over korrupte entries
        }
    }
    return res.status(200).json({ loc, species, year, history });
}

async function handleStore(req, res) {
    const { loc, species, predDate, predDoy, info } = req.body || {};
    if (!loc || !species) {
        return res.status(400).json({ error: 'Mangler loc eller species' });
    }

    const r = redis();
    const key = k.pred(loc, species);
    const now = new Date();
    const todayIso = now.toISOString().slice(0, 10);
    const year = now.getUTCFullYear();
    const newRecord = {
        predDate: predDate || null,
        predDoy: predDoy != null ? predDoy : null,
        info: info || null,
        ts: now.toISOString(),
    };

    // Daglig historikk-snapshot: lagre kun hvis dagens dato ikke allerede finnes.
    // Dette gir oss "hva sa vi første gang den dagen" — robust mot at samme bruker
    // refresher dashboard flere ganger og rare side-effekter underveis.
    if (newRecord.predDoy != null) {
        const histKey = k.predHist(loc, species, year);
        const existingDay = await r.hget(histKey, todayIso);
        if (!existingDay) {
            await r.hset(histKey, { [todayIso]: JSON.stringify(newRecord) });
            // TTL ~400 dager — én sesongs historikk + buffer.
            await r.expire(histKey, 400 * 24 * 3600);
        }
    }

    // Hent forrige (for cron-sammenligning) — vi roterer kun hvis ny er forskjellig
    // fra forrige.
    const existing = await r.get(key);
    if (existing && existing.predDoy === newRecord.predDoy && existing.predDate === newRecord.predDate) {
        // Ingen endring — bare oppdater timestamp uten å rotere prev
        existing.ts = newRecord.ts;
        await r.set(key, existing);
        return res.status(200).json({ ok: true, changed: false });
    }
    // Endring eller første gang — lagre gammel som "prev" og ny som primær
    if (existing) {
        await r.set(key + ':prev', existing);
    }
    await r.set(key, newRecord);
    return res.status(200).json({ ok: true, changed: true });
}
