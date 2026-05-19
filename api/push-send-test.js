// Vercel serverless function — sender en push-notifikasjon til en gitt subscription.
// Brukes i Etappe 3a (pipeline-test) for å verifisere at Web Push fungerer
// end-to-end. Subscription sendes som request body — ingen server-side lagring
// ennå (det kommer i Etappe 3b med Upstash).
//
// Krever Vercel env-variabler:
//   VAPID_PUBLIC_KEY   — kan også deles via /api/push-config eller hardkodes i frontend
//   VAPID_PRIVATE_KEY  — kun server-side
//   VAPID_SUBJECT      — mailto:... eller https://... (krav fra Web Push)
//
// Innført 2026-05-19.

import webpush from 'web-push';

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');

    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed — use POST' });
    }

    const VAPID_PUBLIC  = process.env.VAPID_PUBLIC_KEY;
    const VAPID_PRIVATE = process.env.VAPID_PRIVATE_KEY;
    const VAPID_SUBJECT = process.env.VAPID_SUBJECT || 'mailto:stian.midtdal@gmail.com';

    if (!VAPID_PUBLIC || !VAPID_PRIVATE) {
        return res.status(500).json({
            error: 'VAPID-nøkler mangler i Vercel env. Legg til VAPID_PUBLIC_KEY og VAPID_PRIVATE_KEY.',
        });
    }

    webpush.setVapidDetails(VAPID_SUBJECT, VAPID_PUBLIC, VAPID_PRIVATE);

    const { subscription, payload } = req.body || {};
    if (!subscription || !subscription.endpoint) {
        return res.status(400).json({ error: 'Mangler subscription i request body' });
    }

    const notif = payload || {
        title: 'HatchWatch — test',
        body: 'Push-pipelinen fungerer 🎣',
        url: '/',
    };

    try {
        const result = await webpush.sendNotification(
            subscription,
            JSON.stringify(notif)
        );
        return res.status(200).json({ ok: true, statusCode: result.statusCode });
    } catch (err) {
        return res.status(500).json({
            error: err.message || 'Push-send feilet',
            statusCode: err.statusCode,
            body: err.body,
        });
    }
}
