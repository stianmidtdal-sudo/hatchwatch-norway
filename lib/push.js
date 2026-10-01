// Delt push-helper: konfigurerer web-push og lager notification-payloads
// for hver trigger-type. Brukes av api/push.js og cron-daily.
// Innført 2026-05-19.
//
// 2026-10-01: to leveringsveier.
//   web  — Web Push (VAPID) til nettleser/PWA. Uendret.
//   ios  — APNs (Apples eget varselsystem) til iPhone-appen (Capacitor).
//          Inne i appen finnes ikke Web Push, så appen registrerer et
//          enhetstoken som lagres med platform:'ios'. sendPush() velger vei
//          ut fra subscription.platform.
//   Env for APNs (Vercel): APNS_KEY_ID, APNS_TEAM_ID, APNS_KEY (innholdet i
//   .p8-fila), valgfritt APNS_BUNDLE_ID (default no.hatchwatch.app) og
//   APNS_ENV=sandbox for utviklingsbygg (TestFlight/App Store = production).

import webpush from 'web-push';
import http2 from 'http2';
import crypto from 'crypto';

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
    if (subscription && subscription.platform === 'ios' && subscription.token) {
        return sendApns(subscription.token, payload);
    }
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

// ── APNs ──────────────────────────────────────────────────────────────────
// Apple krever et signert JWT (ES256) per forespørsel. Tokenet er gyldig i
// 60 min og bør ikke fornyes oftere enn hvert 20. min — vi cacher i 50.
// Tåler alle måter .p8-innholdet kan ha blitt limt inn i Vercel på: med ekte
// linjeskift, med bokstavelig "\n", som én lang linje uten linjeskift, med
// Windows-linjeskift, eller base64-kodet i sin helhet. Bygger PEM på nytt
// med 64 tegn per linje, som Node/OpenSSL krever.
export function normalizePem(raw) {
    let s = String(raw || '').trim().replace(/\\n/g, '\n').replace(/\r/g, '');
    // Fjern ev. omsluttende anførselstegn fra limingen
    s = s.replace(/^["']+|["']+$/g, '').trim();
    if (!/PRIVATE KEY/.test(s)) {
        // Hele fila base64-kodet?
        const decoded = Buffer.from(s.replace(/\s+/g, ''), 'base64').toString('utf8');
        if (/PRIVATE KEY/.test(decoded)) s = decoded;
    }
    const m = s.match(/-----BEGIN ([A-Z ]*PRIVATE KEY)-----([\s\S]*?)-----END \1-----/);
    let label = 'PRIVATE KEY';
    let body;
    if (m) {
        label = m[1];
        body = m[2].replace(/\s+/g, '');
    } else {
        // Bare den midterste base64-delen limt inn (uten BEGIN/END-linjer)?
        body = s.replace(/-----[^-]*-----/g, '').replace(/\s+/g, '');
        const der = Buffer.from(body, 'base64');
        // PKCS#8 (Apples .p8) starter alltid med en DER SEQUENCE (0x30)
        if (!/^[A-Za-z0-9+/=]+$/.test(body) || der.length < 50 || der[0] !== 0x30) {
            throw new Error(describeKeyShape(s));
        }
    }
    return `-----BEGIN ${label}-----\n${body.match(/.{1,64}/g).join('\n')}\n-----END ${label}-----\n`;
}

// Diagnose uten å lekke nøkkelen: lengde, om BEGIN/END finnes, hvilke tegn.
function describeKeyShape(s) {
    const hasBegin = /BEGIN/.test(s);
    const hasEnd = /END/.test(s);
    const lines = s.split('\n').length;
    const first = s.slice(0, 12).replace(/[A-Za-z0-9+/=]/g, 'x');
    return `APNS_KEY ser ikke ut som en .p8-nøkkel: ${s.length} tegn, ${lines} linje(r), `
        + `BEGIN=${hasBegin}, END=${hasEnd}, starter med "${first}". `
        + 'Lim inn hele innholdet i AuthKey_*.p8 (inkl. BEGIN/END-linjene) på nytt i Vercel.';
}

let _apnsJwt = null;
let _apnsJwtAt = 0;
function apnsJwt() {
    // trim: et mellomrom eller linjeskift som fulgte med i limingen gir
    // InvalidProviderToken hos Apple.
    const keyId = (process.env.APNS_KEY_ID || '').trim();
    const teamId = (process.env.APNS_TEAM_ID || '').trim();
    let key = process.env.APNS_KEY;
    if (!keyId || !teamId || !key) {
        throw new Error('APNs-nøkler mangler i Vercel env (APNS_KEY_ID, APNS_TEAM_ID, APNS_KEY)');
    }
    key = normalizePem(key);
    const now = Math.floor(Date.now() / 1000);
    if (_apnsJwt && now - _apnsJwtAt < 50 * 60) return _apnsJwt;
    const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
    const header = b64({ alg: 'ES256', kid: keyId });
    const claims = b64({ iss: teamId, iat: now });
    const sig = crypto
        .sign('sha256', Buffer.from(`${header}.${claims}`), { key, dsaEncoding: 'ieee-p1363' })
        .toString('base64url');
    _apnsJwt = `${header}.${claims}.${sig}`;
    _apnsJwtAt = now;
    return _apnsJwt;
}

// Sender ett varsel til ett iOS-enhetstoken. Samme returform som web-push-
// grenen: { ok, statusCode, error?, expired? }. expired=true betyr at tokenet
// er dødt (appen avinstallert e.l.) og abonnementet kan slettes.
export function sendApns(token, payload) {
    const host = process.env.APNS_ENV === 'sandbox'
        ? 'https://api.sandbox.push.apple.com'
        : 'https://api.push.apple.com';
    const topic = process.env.APNS_BUNDLE_ID || 'no.hatchwatch.app';
    const tag = (payload.tag || 'hatchwatch').slice(0, 64);
    const body = JSON.stringify({
        aps: {
            alert: { title: payload.title, body: payload.body },
            sound: 'default',
            'thread-id': tag,
        },
        url: payload.url || '/',
        tag,
    });

    let jwt;
    try { jwt = apnsJwt(); } catch (err) { return Promise.resolve({ ok: false, error: err.message }); }

    return new Promise((resolve) => {
        const client = http2.connect(host);
        let settled = false;
        const done = (r) => { if (!settled) { settled = true; client.close(); resolve(r); } };
        client.on('error', (err) => done({ ok: false, error: `APNs connect: ${err.message}` }));

        const req = client.request({
            ':method': 'POST',
            ':path': `/3/device/${token}`,
            'authorization': `bearer ${jwt}`,
            'apns-topic': topic,
            'apns-push-type': 'alert',
            'apns-priority': '10',
            'apns-expiration': String(Math.floor(Date.now() / 1000) + 86400),
            'apns-collapse-id': tag,
            'content-type': 'application/json',
        });
        let status = 0;
        let data = '';
        req.on('response', (h) => { status = h[':status']; });
        req.setEncoding('utf8');
        req.on('data', (c) => { data += c; });
        req.on('end', () => {
            if (status === 200) return done({ ok: true, statusCode: 200 });
            let reason = '';
            try { reason = JSON.parse(data).reason || ''; } catch { /* ikke JSON */ }
            if (reason === 'ExpiredProviderToken' || reason === 'InvalidProviderToken') {
                _apnsJwt = null;
                // Key ID og Team ID er identifikatorer, ikke hemmeligheter — trygt å vise
                // for feilsøking (hvilken nøkkel serveren faktisk bruker).
                const kid = (process.env.APNS_KEY_ID || '').trim();
                const tid = (process.env.APNS_TEAM_ID || '').trim();
                reason += ` (serveren bruker Key ID ${kid}, Team ID ${tid})`;
            }
            const expired = status === 410
                || reason === 'BadDeviceToken'
                || reason === 'Unregistered'
                || reason === 'DeviceTokenNotForTopic';
            done({ ok: false, statusCode: status, error: reason || data || `APNs ${status}`, expired });
        });
        req.on('error', (err) => done({ ok: false, error: `APNs request: ${err.message}` }));
        req.end(body);
    });
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
