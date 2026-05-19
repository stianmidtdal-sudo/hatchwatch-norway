// Vercel serverless function — registrerer eller oppdaterer push-subscription.
// Lagrer i Upstash Redis. Brukes av Settings-UI i HatchWatch-appen.
//
// Body: {
//   subscription: { endpoint, keys: {p256dh, auth} },
//   locations: { 'ostmarka': ['klekkeChange', 'spinnerfall', ...], ... },
//   lang: 'no' | 'en'
// }
//
// Hvis subscription finnes fra før, oppdaterer preferanser. Hvis ikke, oppretter.
// Innført 2026-05-19.

import { redis, hashEndpoint, k } from './_lib/redis.js';

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (req.method === 'OPTIONS') {
        res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        return res.status(204).end();
    }
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed — use POST' });
    }

    const { subscription, locations, lang } = req.body || {};
    if (!subscription || !subscription.endpoint || !subscription.keys) {
        return res.status(400).json({ error: 'Ugyldig subscription' });
    }
    if (!locations || typeof locations !== 'object') {
        return res.status(400).json({ error: 'Mangler locations-objekt' });
    }

    try {
        const r = redis();
        const hash = hashEndpoint(subscription.endpoint);
        const record = {
            endpoint: subscription.endpoint,
            keys: subscription.keys,
            locations,
            lang: lang || 'no',
            updatedAt: new Date().toISOString(),
        };
        // Bevar createdAt hvis subscription finnes fra før
        const existing = await r.get(k.sub(hash));
        if (existing && existing.createdAt) {
            record.createdAt = existing.createdAt;
        } else {
            record.createdAt = record.updatedAt;
        }
        await r.set(k.sub(hash), record);
        await r.sadd(k.subsAll, hash);

        return res.status(200).json({ ok: true, hash, locations });
    } catch (err) {
        console.error('push-subscribe error:', err);
        return res.status(500).json({ error: err.message || 'Lagring feilet' });
    }
}
