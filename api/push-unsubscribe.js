// Vercel serverless function — fjerner push-subscription fra Upstash Redis.
// Brukes når bruker skrur av varsler eller endpoint blir ugyldig.
//
// Body: { endpoint }  ELLER  { subscription: { endpoint } }
//
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

    let { endpoint, subscription } = req.body || {};
    if (!endpoint && subscription && subscription.endpoint) {
        endpoint = subscription.endpoint;
    }
    if (!endpoint) {
        return res.status(400).json({ error: 'Mangler endpoint' });
    }

    try {
        const r = redis();
        const hash = hashEndpoint(endpoint);
        await r.del(k.sub(hash));
        await r.srem(k.subsAll, hash);
        return res.status(200).json({ ok: true });
    } catch (err) {
        console.error('push-unsubscribe error:', err);
        return res.status(500).json({ error: err.message || 'Sletting feilet' });
    }
}
