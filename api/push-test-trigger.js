// Vercel serverless function — sender en TEST-push for en spesifikk trigger-type.
// Brukes fra varsler-modalen i appen så brukeren kan se hvordan hver notification
// faktisk ser ut på telefonen. Bruker stub-data ("eksempel"-prediksjoner).
//
// Body: {
//   subscription: { endpoint, keys: {p256dh, auth} },
//   triggerType: 'klekkeChange' | 'klekkeImminent' | 'spinnerfall' | 'stokkmaur' | 'seasonstart',
//   locArea: 'Østmarka', locId: 'ostmarka',
//   lang: 'no' | 'en'
// }
//
// Innført 2026-05-19.

import { sendPush, buildPayload, TRIGGER_TYPES } from './_lib/push.js';

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

    const { subscription, triggerType, locArea, locId, lang } = req.body || {};
    if (!subscription || !subscription.endpoint) {
        return res.status(400).json({ error: 'Mangler subscription' });
    }
    if (!triggerType || !TRIGGER_TYPES.includes(triggerType)) {
        return res.status(400).json({
            error: 'Ugyldig triggerType — bruk en av: ' + TRIGGER_TYPES.join(', '),
        });
    }

    // Stub-data per trigger-type for å gjøre push-en realistisk
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
        locArea || (isNo ? 'Østmarka' : 'Østmarka'),
        locId || 'ostmarka',
        stubData[triggerType],
        lang
    );
    // Marker som test slik at brukeren ser det
    payload.body = (isNo ? '[TEST] ' : '[TEST] ') + payload.body;

    const result = await sendPush(subscription, payload);
    if (result.ok) return res.status(200).json({ ok: true, statusCode: result.statusCode });
    return res.status(500).json({ ok: false, ...result });
}
