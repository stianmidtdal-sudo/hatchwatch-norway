// Vercel serverless function — konsolidert push-endpoint.
// Håndterer subscribe, unsubscribe og test-trigger via ?action= query-param.
//
// Vi konsoliderte tre tidligere endpoints (push-subscribe, push-unsubscribe,
// push-test-trigger) til ett her for å holde oss under Vercel Hobby-plan
// sin grense på 12 serverless functions per deploy. Innført 2026-05-20.
//
// Endpoints:
//   POST /api/push?action=subscribe       — body: { subscription, locations, lang }
//   POST /api/push?action=unsubscribe     — body: { endpoint } eller { subscription }
//   POST /api/push?action=test-trigger    — body: { subscription, triggerType, locArea, locId, lang }

import { redis, hashEndpoint, k } from '../lib/redis.js';
import { sendPush, buildPayload, TRIGGER_TYPES } from '../lib/push.js';

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

    const action = (req.query.action || '').toString();

    try {
        if (action === 'subscribe') return await handleSubscribe(req, res);
        if (action === 'unsubscribe') return await handleUnsubscribe(req, res);
        if (action === 'test-trigger') return await handleTestTrigger(req, res);
        return res.status(400).json({ error: 'Ukjent action — bruk subscribe | unsubscribe | test-trigger' });
    } catch (err) {
        console.error('push handler error:', err);
        return res.status(500).json({ error: err.message || 'Push-handler feilet' });
    }
}

async function handleSubscribe(req, res) {
    const { subscription, locations, lang } = req.body || {};
    if (!subscription || !subscription.endpoint || !subscription.keys) {
        return res.status(400).json({ error: 'Ugyldig subscription' });
    }
    if (!locations || typeof locations !== 'object') {
        return res.status(400).json({ error: 'Mangler locations-objekt' });
    }
    const r = redis();
    const hash = hashEndpoint(subscription.endpoint);
    const record = {
        endpoint: subscription.endpoint,
        keys: subscription.keys,
        locations,
        lang: lang || 'no',
        updatedAt: new Date().toISOString(),
    };
    const existing = await r.get(k.sub(hash));
    record.createdAt = (existing && existing.createdAt) ? existing.createdAt : record.updatedAt;
    await r.set(k.sub(hash), record);
    await r.sadd(k.subsAll, hash);
    return res.status(200).json({ ok: true, hash, locations });
}

async function handleUnsubscribe(req, res) {
    let { endpoint, subscription } = req.body || {};
    if (!endpoint && subscription && subscription.endpoint) endpoint = subscription.endpoint;
    if (!endpoint) return res.status(400).json({ error: 'Mangler endpoint' });
    const r = redis();
    const hash = hashEndpoint(endpoint);
    await r.del(k.sub(hash));
    await r.srem(k.subsAll, hash);
    return res.status(200).json({ ok: true });
}

async function handleTestTrigger(req, res) {
    const { subscription, triggerType, locArea, locId, lang } = req.body || {};
    if (!subscription || !subscription.endpoint) {
        return res.status(400).json({ error: 'Mangler subscription' });
    }
    if (!triggerType || !TRIGGER_TYPES.includes(triggerType)) {
        return res.status(400).json({
            error: 'Ugyldig triggerType — bruk en av: ' + TRIGGER_TYPES.join(', '),
        });
    }

    const isNo = lang !== 'en';
    const stubData = {
        klekkeChange: {
            predDate: isNo ? '25. mai' : 'May 25',
            deltaText: isNo ? '3 dager tidligere' : '3 days earlier',
        },
        klekkeImminent: {
            predDate: isNo ? '23. mai' : 'May 23',
            info: isNo ? 'Drivere peker tidlig — Vulgata-vinduet åpner snart.' : 'Drivers point early — Vulgata window opens soon.',
        },
        spinnerfall: {
            info: isNo ? 'Vindstille, klart, 16 °C — perfekt.' : 'Calm winds, clear, 16 °C — perfect.',
        },
        stokkmaur: {
            info: isNo ? 'Varmt og vindstille de neste 3 dagene.' : 'Warm and calm for the next 3 days.',
        },
        seasonstart: {
            species: 'Vulgata · Grandis',
            predDate: isNo ? '25. mai → 8. juni' : 'May 25 → June 8',
        },
    };

    const payload = buildPayload(
        triggerType,
        locArea || 'Østmarka',
        locId || 'ostmarka',
        stubData[triggerType],
        lang
    );
    payload.body = '[TEST] ' + payload.body;

    const result = await sendPush(subscription, payload);
    if (result.ok) return res.status(200).json({ ok: true, statusCode: result.statusCode });
    return res.status(500).json({ ok: false, ...result });
}
