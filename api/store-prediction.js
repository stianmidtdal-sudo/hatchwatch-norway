// Vercel serverless function — mottar dagens prediksjon fra frontend og lagrer
// i Upstash Redis. Cron-jobben sammenligner gårsdagens vs dagens for å oppdage
// endringer (≥ 2 dager) og sender push.
//
// Body: {
//   loc: 'ostmarka',
//   species: 'vulgata',         // 'vulgata' | 'marginata' | 'vespertina' | 'mygg' | 'all'
//   predDate: '2026-05-25',     // ISO-dato eller null hvis ikke prediksjon
//   predDoy: 145,               // valgfri, lettere å sammenligne
//   info: 'GDD 400 + WT 13°C'   // valgfri, kontekst
// }
//
// Lagrer som: pred:{loc}:{species} = { predDate, predDoy, info, ts }
// Beholder forrige verdi som pred:{loc}:{species}:prev for sammenligning i cron.
//
// Innført 2026-05-19.
//
// 2026-05-25: skriver i tillegg én daglig snapshot til predhist:{loc}:{spec}:{year}
// (Redis hash, felt = ISO-dato). Første skriving per dag vinner — etterfølgende
// requests samme dag rører ikke historikken. Brukes av konvergensgrafen for å
// vise ekte historikk i stedet for replay-from-current-data.

import { redis, k } from '../lib/redis.js';

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (req.method === 'OPTIONS') {
        res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        return res.status(204).end();
    }
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const { loc, species, predDate, predDoy, info } = req.body || {};
    if (!loc || !species) {
        return res.status(400).json({ error: 'Mangler loc eller species' });
    }

    try {
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
        // fra forrige eller hvis det er > 6 timer siden siste lagring.
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
    } catch (err) {
        console.error('store-prediction error:', err);
        return res.status(500).json({ error: err.message });
    }
}
