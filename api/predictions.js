// Returnerer alle lagrede vulgata-prediksjoner fra Upstash Redis.
// Brukes av forsiden for å avgjøre om en lokasjon allerede har vulgata-onset
// (og dermed om spinnerfall-badgen kan vises).
//
// Prediksjoner lagres av dashboard.html via /api/store-prediction når noen
// besøker en lokasjons-dashboard. Hvis en lokasjon mangler stored prediction,
// returneres ingen entry — forsiden skal da være konservativ og IKKE vise badge.
//
// Innført 2026-05-20 etter at "Bra kveld"-badgen viste seg på Vestfjella før
// vulgata-onset (modellen sa ca. 5. juni, dato var 20. mai).
//
// Cache: 5 min på Vercel edge (prediksjoner endrer seg sjelden, og vi kan
// tåle litt forsinkelse på badge-oppdatering).

import { redis, k } from '../lib/redis.js';

const LOCATIONS = [
    'kautokeino', 'alta', 'porsanger', 'ifjordfjellet', 'dividalen',
    'bardu', 'narvik', 'mo_i_rana', 'borgefjell', 'roros', 'lierne',
    'trondheim', 'rena', 'oslo', 'nordmarka_dyn', 'finnemarka',
    'ostmarka', 'vestfjella', 'hardangervidda', 'bergen',
];

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=60');

    if (req.method !== 'GET') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
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
    } catch (err) {
        console.error('predictions error:', err);
        return res.status(500).json({ error: err.message });
    }
}
