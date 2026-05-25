// Returnerer lagrede prediksjoner fra Upstash Redis.
//
// To moduser:
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
// Hvis en lokasjon mangler stored prediction, returneres ingen entry — forsiden
// skal da være konservativ og IKKE vise badge.
//
// Cache: 5 min på Vercel edge (prediksjoner endrer seg sjelden).

import { redis, k } from '../lib/redis.js';

const LOCATIONS = [
    'kautokeino', 'alta', 'porsanger', 'ifjordfjellet', 'dividalen',
    'bardu', 'narvik', 'mo_i_rana', 'borgefjell', 'roros', 'lierne',
    'trondheim', 'rena', 'oslo', 'nordmarka_dyn', 'finnemarka',
    'ostmarka', 'vestfjella', 'hardangervidda', 'bergen',
];

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');

    if (req.method !== 'GET') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const mode = (req.query.mode || '').toString();

    try {
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
