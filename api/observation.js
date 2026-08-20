// Vercel serverless function — innebygd observasjonsskjema (2026-08-20).
// Erstatter Tally-formen VLvGQE. Lagrer observasjoner i Upstash Redis og
// push-varsler admin-abonnenter (Stian) ved hver ny innsending.
//
// Endpoints:
//   POST /api/observation                          — body: observasjon → lagres + push
//   POST /api/observation?action=admin-subscribe   — body: { key, subscription }
//   POST /api/observation?action=admin-unsubscribe — body: { key, endpoint }
//   GET  /api/observation?key=...                  — alle observasjoner (JSON)
//   GET  /api/observation?key=...&format=csv       — CSV (semikolon, Excel-vennlig)
//
// Datamodell (Redis):
//   obs:all       — LIST, LPUSH av JSON-records (nyeste først)
//   obsadmin:subs — SET av JSON.stringify(subscription) for admin-push
//
// Admin-nøkkel: env OBS_ADMIN_KEY, fallback = beta-passordet fra login.js.

import { redis } from '../lib/redis.js';
import { sendPush } from '../lib/push.js';

const ADMIN_KEY = process.env.OBS_ADMIN_KEY || 'marginata!!!';

const TYPES = ['klekking', 'spinnerfall'];
const INSECTS = ['Marginata', 'Vespertina', 'Vulgata', 'Grandis'];
const OBSERVED = ['Første klekking sett', 'Pågående klekkebølge', 'Slutt på klekking', 'Sporadisk'];
const AMOUNTS = ['Få enkelt-stykker', 'Tydelig klekking', 'Eksplosjon (massiv klekking)'];

function clip(v, max) {
    if (v == null) return '';
    return String(v).trim().slice(0, max);
}

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (req.method === 'OPTIONS') {
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        return res.status(204).end();
    }
    try {
        if (req.method === 'GET') return await handleList(req, res);
        if (req.method === 'POST') {
            const action = (req.query.action || '').toString();
            if (action === 'admin-subscribe') return await handleAdminSubscribe(req, res);
            if (action === 'admin-unsubscribe') return await handleAdminUnsubscribe(req, res);
            return await handleSubmit(req, res);
        }
        return res.status(405).json({ error: 'Method not allowed' });
    } catch (err) {
        console.error('observation handler error:', err);
        return res.status(500).json({ error: err.message || 'Observasjons-handler feilet' });
    }
}

// ── Innsending ───────────────────────────────────────────────────────────
async function handleSubmit(req, res) {
    const b = req.body || {};

    // Honeypot: skjult felt i skjemaet — mennesker lar det stå tomt.
    if (b.website) return res.status(200).json({ ok: true });

    const type = clip(b.type, 20).toLowerCase();
    const date = clip(b.date, 10);
    const insect = clip(b.insect, 30);
    const area = clip(b.area, 60);
    const name = clip(b.name, 80);
    const email = clip(b.email, 120);

    if (!TYPES.includes(type)) return res.status(400).json({ error: 'Ugyldig type' });
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return res.status(400).json({ error: 'Ugyldig dato' });
    if (!INSECTS.includes(insect)) return res.status(400).json({ error: 'Ugyldig insekt' });
    if (!area) return res.status(400).json({ error: 'Mangler lokasjonsområde' });
    if (!name) return res.status(400).json({ error: 'Mangler navn' });
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return res.status(400).json({ error: 'Ugyldig e-post' });

    const record = {
        ts: new Date().toISOString(),
        type, date, insect, area,
        lake: clip(b.lake, 80),
        altitude: b.altitude != null && b.altitude !== '' ? parseInt(b.altitude, 10) || null : null,
        observed: OBSERVED.includes(b.observed) ? b.observed : '',
        amount: AMOUNTS.includes(b.amount) ? b.amount : '',
        comment: clip(b.comment, 2000),
        name, email,
    };

    const r = redis();
    await r.lpush('obs:all', JSON.stringify(record));

    // Push til admin-abonnenter — best effort, feiler aldri innsendingen.
    try {
        const subs = await r.smembers('obsadmin:subs');
        const typeLabel = type === 'klekking' ? 'Klekking' : 'Spinnerfall';
        const payload = {
            title: `🪰 Ny observasjon — ${area}`,
            body: `${typeLabel} · ${insect} · ${date} — fra ${name}`,
            url: '/observasjon.html?admin=1',
            tag: 'obs-admin',
        };
        for (const s of subs) {
            const sub = typeof s === 'string' ? JSON.parse(s) : s;
            const result = await sendPush(sub, payload);
            if (result.expired) await r.srem('obsadmin:subs', typeof s === 'string' ? s : JSON.stringify(s));
        }
    } catch (e) {
        console.error('admin push feilet (ignorert):', e.message);
    }

    return res.status(200).json({ ok: true });
}

// ── Admin: liste / CSV ───────────────────────────────────────────────────
async function handleList(req, res) {
    if ((req.query.key || '') !== ADMIN_KEY) {
        return res.status(401).json({ error: 'Feil nøkkel' });
    }
    const r = redis();
    const raw = await r.lrange('obs:all', 0, -1);
    const obs = raw.map(x => {
        try { return typeof x === 'string' ? JSON.parse(x) : x; } catch (e) { return null; }
    }).filter(Boolean);

    if ((req.query.format || '') === 'csv') {
        const cols = ['ts', 'type', 'date', 'insect', 'area', 'lake', 'altitude',
                      'observed', 'amount', 'name', 'email', 'comment'];
        const esc = v => `"${String(v == null ? '' : v).replace(/"/g, '""').replace(/\r?\n/g, ' ')}"`;
        const lines = [cols.join(';')];
        for (const o of obs) lines.push(cols.map(c => esc(o[c])).join(';'));
        const csv = '﻿' + lines.join('\r\n');   // BOM → norsk Excel leser æøå riktig
        res.setHeader('Content-Type', 'text/csv; charset=utf-8');
        res.setHeader('Content-Disposition', 'attachment; filename="hatchwatch-observasjoner.csv"');
        return res.status(200).send(csv);
    }
    return res.status(200).json({ count: obs.length, observations: obs });
}

// ── Admin: push-abonnement ───────────────────────────────────────────────
async function handleAdminSubscribe(req, res) {
    const { key, subscription } = req.body || {};
    if (key !== ADMIN_KEY) return res.status(401).json({ error: 'Feil nøkkel' });
    if (!subscription || !subscription.endpoint || !subscription.keys) {
        return res.status(400).json({ error: 'Ugyldig subscription' });
    }
    await redis().sadd('obsadmin:subs', JSON.stringify(subscription));
    return res.status(200).json({ ok: true });
}

async function handleAdminUnsubscribe(req, res) {
    const { key, endpoint } = req.body || {};
    if (key !== ADMIN_KEY) return res.status(401).json({ error: 'Feil nøkkel' });
    const r = redis();
    const subs = await r.smembers('obsadmin:subs');
    for (const s of subs) {
        const sub = typeof s === 'string' ? JSON.parse(s) : s;
        if (sub.endpoint === endpoint) {
            await r.srem('obsadmin:subs', typeof s === 'string' ? s : JSON.stringify(s));
        }
    }
    return res.status(200).json({ ok: true });
}
