// Delt push-helper: konfigurerer web-push og lager notification-payloads
// for hver trigger-type. Brukes av push-test-trigger og cron-daily.
// Innført 2026-05-19.

import webpush from 'web-push';

let _vapidConfigured = false;
export function configureVapid() {
    if (_vapidConfigured) return;
    const pub = process.env.VAPID_PUBLIC_KEY;
    const priv = process.env.VAPID_PRIVATE_KEY;
    const subject = process.env.VAPID_SUBJECT || 'mailto:stian.midtdal@gmail.com';
    if (!pub || !priv) throw new Error('VAPID-nøkler mangler i Vercel env');
    webpush.setVapidDetails(subject, pub, priv);
    _vapidConfigured = true;
}

// Send en push til en gitt subscription. Returnerer { ok, statusCode }
// eller kaster feil ved server-feil. Tag-bruk gjør at samme tag overskriver
// forrige notification (unngår spam).
//
// urgency: 'high' ber push-tjenesten (APNs/FCM) levere umiddelbart med
// hørbart alert, ikke som silent/lavprioritet. Påkrevd for at iOS skal gi
// et "ordentlig" varsel i stedet for passiv notifikasjon i varsel-senter.
export async function sendPush(subscription, payload) {
    configureVapid();
    try {
        const result = await webpush.sendNotification(
            subscription,
            JSON.stringify(payload),
            { TTL: 86400, urgency: 'high' }  // 24t TTL, høy prioritet
        );
        return { ok: true, statusCode: result.statusCode };
    } catch (err) {
        return {
            ok: false,
            statusCode: err.statusCode,
            error: err.message,
            // 404 / 410 = subscription er borte (bruker unsubscribed eller fjernet app)
            expired: err.statusCode === 404 || err.statusCode === 410,
        };
    }
}

// Bygger payload per trigger-type. Returnerer { title, body, url, tag, emoji }
// data ekstrahar: { locArea, locId, predDate, predDelta, sciSpecies, info } etc.
export function buildPayload(triggerType, locArea, locId, data, lang) {
    const isNo = lang !== 'en';
    const baseUrl = `/dashboard.html?loc=${encodeURIComponent(locId)}`;

    switch (triggerType) {
        case 'klekkeChange':
            return {
                title: `🔄 ${locArea} — Klekkedato endret`,
                body: isNo
                    ? `Prediksjonen har flyttet seg ${data.deltaText || ''}. Ny estimat: ${data.predDate || '—'}.`
                    : `Prediction has shifted ${data.deltaText || ''}. New estimate: ${data.predDate || '—'}.`,
                url: baseUrl,
                tag: `klekkeChange-${locId}`,
            };
        case 'klekkeImminent':
            return {
                title: `🎣 ${locArea} — Klekking starter snart`,
                body: isNo
                    ? `Estimert klekkestart ${data.predDate || 'snart'}. ${data.info || ''}`
                    : `Estimated hatch start ${data.predDate || 'soon'}. ${data.info || ''}`,
                url: baseUrl,
                tag: `klekkeImminent-${locId}`,
            };
        case 'spinnerfall':
            return {
                title: `🌙 ${locArea} — Spinnerfall i kveld`,
                body: isNo
                    ? `Forholdene for vulgataspinnerfall ser gode ut i kveld (19–22). ${data.info || ''}`
                    : `Conditions look good for vulgata spinner fall tonight (19–22). ${data.info || ''}`,
                url: baseUrl,
                tag: `spinnerfall-${locId}`,
            };
        case 'stokkmaur':
            return {
                title: `🐜 ${locArea} — Stokkmaur-vindu åpent`,
                body: isNo
                    ? `Værforholdene treffer stokkmaur-svermings-kriteriene. ${data.info || ''}`
                    : `Weather conditions match carpenter ant swarming criteria. ${data.info || ''}`,
                url: baseUrl,
                tag: `stokkmaur-${locId}`,
            };
        case 'seasonstart':
            return {
                title: `📅 ${locArea} — Sesongstart`,
                body: isNo
                    ? `${data.species || 'Vulgata'}-sesongen begynner snart. Estimert: ${data.predDate || '—'}.`
                    : `${data.species || 'Vulgata'} season is starting soon. Estimated: ${data.predDate || '—'}.`,
                url: baseUrl,
                tag: `seasonstart-${locId}`,
            };
        default:
            return {
                title: 'HatchWatch',
                body: isNo ? 'Du har et nytt varsel.' : 'You have a new notification.',
                url: '/',
                tag: 'hatchwatch',
            };
    }
}

export const TRIGGER_TYPES = [
    'klekkeChange',
    'klekkeImminent',
    'spinnerfall',
    'stokkmaur',
    'seasonstart',
];
