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

const ID_RE = /^[A-Z0-9]{10}$/;
function safeId(v) {
    const s = String(v || '').trim();
    return ID_RE.test(s) ? s : `[feil format, ${s.length} tegn]`;
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
    // Apple-ID-er er alltid 10 tegn (A–Z, 0–9). Stopp her hvis noe annet er
    // limt inn — og vis aldri selve verdien.
    if (!ID_RE.test(keyId)) {
        throw new Error(`APNS_KEY_ID har feil format (${keyId.length} tegn, skal være 10). Lim inn Key ID-en fra Apple, ikke innholdet i .p8-fila.`);
    }
    if (!ID_RE.test(teamId)) {
        throw new Error(`APNS_TEAM_ID har feil format (${teamId.length} tegn, skal være 10).`);
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
                // Feilsøking: vis hvilken Key ID / Team ID serveren bruker — men KUN
                // når verdien har riktig ID-format (10 tegn A–Z/0–9). Alt annet
                // maskeres, i tilfelle noe hemmelig er limt inn i feil felt.
                reason += ` (Key ID ${safeId(process.env.APNS_KEY_ID)}, Team ID ${safeId(process.env.APNS_TEAM_ID)})`;
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

// ── Varseltekster på fire språk (2026-10-17) ────────────────────────────────
// Språket lagres med abonnementet (api/push.js) og er det appen viste da varslene ble lagret:
// 'no' | 'en' | 'sv' | 'fi'. Alt annet blir norsk. Ordvalg som i appens svenske/finske ordbøker (i18n/).
export function pushSpraak(lang) {
    return ['en', 'sv', 'fi'].includes(lang) ? lang : 'no';
}
const MND = {
    no: ['jan', 'feb', 'mars', 'april', 'mai', 'juni', 'juli', 'aug', 'sep', 'okt', 'nov', 'des'],
    en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    sv: ['jan', 'feb', 'mars', 'april', 'maj', 'juni', 'juli', 'aug', 'sep', 'okt', 'nov', 'dec'],
};
// Dato som appen skriver den (hwDato i hw-lang.js): «13. juni», «13 Jun», «13 juni», «13.6.».
// d = Date (UTC-dato) eller 'YYYY-MM-DD'.
export function pushDato(d, lang) {
    if (!d) return '—';
    if (!(d instanceof Date)) d = new Date(String(d).slice(0, 10) + 'T00:00:00Z');
    if (isNaN(d)) return '—';
    const l = pushSpraak(lang), dag = d.getUTCDate(), m = d.getUTCMonth();
    if (l === 'fi') return `${dag}.${m + 1}.`;
    return l === 'no' ? `${dag}. ${MND.no[m]}` : `${dag} ${MND[l][m]}`;
}
// Desimalkomma på norsk, svensk og finsk.
function tall(x, l, desimaler) {
    if (x == null || isNaN(x)) return '—';
    const s = desimaler == null ? String(x) : Number(x).toFixed(desimaler);
    return l === 'en' ? s : s.replace('.', ',');
}
// Finsk dato slutter på punktum: «… 13.6.» + «.» skal ikke bli «13.6..».
function ryddFi(s, l) {
    return l === 'fi' ? s.replace(/(\d\.)\./g, '$1') : s;
}

// Bygger payload per trigger-type. Returnerer { title, body, url, tag }
// data (rå verdier fra cron-daily.js / api/push.js test-trigger):
//   klekkeChange { predIso, delta } · klekkeImminent { predIso, daysUntil } · seasonstart { predIso, species }
//   spinnerfall { wind, temp, p } · stokkmaur { maxTemp, wind, clouds, score }
export function buildPayload(triggerType, locArea, locId, data, lang) {
    const l = pushSpraak(lang), T = (o) => o[l], d = data || {};
    const baseUrl = `/dashboard.html?loc=${encodeURIComponent(locId)}`;
    const dato = pushDato(d.predIso, l);
    const ut = (tittel, body) => ({ title: `${locArea} — ${tittel}`, body: ryddFi(body, l), url: baseUrl, tag: `${triggerType}-${locId}` });

    switch (triggerType) {
        case 'klekkeChange': {
            const n = Math.abs(d.delta || 0), tidl = (d.delta || 0) < 0;
            return ut(T({ no: 'Klekkedato endret', en: 'Hatch date changed', sv: 'Kläckningsdatumet har ändrats', fi: 'Kuoriutumispäivä on muuttunut' }), T({
                no: `Prediksjonen har flyttet seg ${n} dager ${tidl ? 'tidligere' : 'senere'}. Nytt estimat: ${dato}.`,
                en: `Prediction has shifted ${n} days ${tidl ? 'earlier' : 'later'}. New estimate: ${dato}.`,
                sv: `Prognosen har flyttats ${n} dagar ${tidl ? 'tidigare' : 'senare'}. Ny uppskattning: ${dato}.`,
                fi: `Ennuste siirtyi ${n} päivää ${tidl ? 'aikaisemmaksi' : 'myöhemmäksi'}. Uusi arvio: ${dato}.`,
            }));
        }
        case 'klekkeImminent': {
            const n = d.daysUntil;
            const om = n == null ? '' : ' ' + T({
                no: `Klekking om ${n} dag${n === 1 ? '' : 'er'}.`,
                en: `Hatching in ${n} day${n === 1 ? '' : 's'}.`,
                sv: `Kläckning om ${n} dag${n === 1 ? '' : 'ar'}.`,
                fi: `Kuoriutuminen ${n} päivän päästä.`,
            });
            return ut(T({ no: 'Klekking starter snart', en: 'Hatch starting soon', sv: 'Kläckningen börjar snart', fi: 'Kuoriutuminen alkaa pian' }), T({
                no: `Estimert klekkestart ${dato}.`,
                en: `Estimated hatch start ${dato}.`,
                sv: `Uppskattad kläckningsstart ${dato}.`,
                fi: `Arvioitu kuoriutumisen alku ${dato}.`,
            }) + om);
        }
        case 'spinnerfall': {
            const v = tall(d.wind, l), t = Math.round(d.temp), p = Math.round((d.p || 0) * 100);
            const info = d.wind == null ? '' : ' ' + T({
                no: `Kveld 19–22: ${v} m/s, ${t} °C. Sjanse ${p} %.`,
                en: `Evening 19–22: ${v} m/s, ${t} °C. Chance ${p} %.`,
                sv: `Kväll 19–22: ${v} m/s, ${t} °C. Chans ${p} %.`,
                fi: `Ilta klo 19–22: ${v} m/s, ${t} °C. Mahdollisuus ${p} %.`,
            });
            return ut(T({ no: 'Spinnerfall i kveld', en: 'Spinner fall tonight', sv: 'Spinnerfall i kväll', fi: 'Spinnerfall tänä iltana' }), T({
                no: 'Forholdene for vulgataspinnerfall ser gode ut i kveld (19–22).',
                en: 'Conditions look good for vulgata spinner fall tonight (19–22).',
                sv: 'Förhållandena för spinnerfall av vulgata ser bra ut i kväll (19–22).',
                fi: 'Olosuhteet näyttävät hyviltä vulgatan spinnerfallille tänä iltana (klo 19–22).',
            }) + info);
        }
        case 'stokkmaur': {
            const t = Math.round(d.maxTemp), v = tall(d.wind, l, 1), c = Math.round(d.clouds), s = d.score;
            const info = d.maxTemp == null ? '' : ' ' + T({
                no: `Maks ${t}°C, vind ${v} m/s, skyer ${c} %. Skår ${s}/100.`,
                en: `Max ${t}°C, wind ${v} m/s, clouds ${c} %. Score ${s}/100.`,
                sv: `Max ${t} °C, vind ${v} m/s, moln ${c} %. Poäng ${s}/100.`,
                fi: `Enintään ${t} °C, tuuli ${v} m/s, pilvisyys ${c} %. Pisteet ${s}/100.`,
            });
            return ut(T({ no: 'Stokkmaur-sverming ventet', en: 'Carpenter ant swarm expected', sv: 'Hästmyror väntas svärma', fi: 'Hevosmuurahaisten parveilua odotettavissa' }), T({
                no: 'Værforholdene treffer stokkmaur-svermings-kriteriene.',
                en: 'Weather conditions match carpenter ant swarming criteria.',
                sv: 'Vädret stämmer med kriterierna för att hästmyrorna ska svärma.',
                fi: 'Sää täyttää hevosmuurahaisten parveilun ehdot.',
            }) + info);
        }
        case 'seasonstart': {
            const sp = d.species || 'Vulgata';
            return ut(T({ no: 'Sesongstart', en: 'Season start', sv: 'Säsongsstart', fi: 'Kauden alku' }), T({
                no: `${sp}-sesongen begynner snart. Estimert: ${dato}.`,
                en: `${sp} season is starting soon. Estimated: ${dato}.`,
                sv: `Säsongen för ${sp} börjar snart. Uppskattat: ${dato}.`,
                fi: `${sp} -kausi alkaa pian. Arvio: ${dato}.`,
            }));
        }
        default:
            return {
                title: 'HatchWatch',
                body: T({ no: 'Du har et nytt varsel.', en: 'You have a new notification.', sv: 'Du har en ny notis.', fi: 'Sinulla on uusi ilmoitus.' }),
                url: '/',
                tag: 'hatchwatch',
            };
    }
}

// Vannvarsler (cron-daily.js handleVann). Samme ordlyd som vannsiden: «modellen anslår», og
// «gjelder bare hvis arten finnes» når arten ikke er registrert i vannet.
//   spinnerfall { wind, temp, p, her } · isgang { dato, marginata } · marginata/vulgata { art, dato, dager, her }
// (datoene ferdig skrevet med pushDato). Returnerer { title, body }.
export function buildVannPayload(trigger, navn, data, lang) {
    const l = pushSpraak(lang), T = (o) => o[l], d = data || {};
    const N = navn || T({ no: 'Vannet ditt', en: 'Your lake', sv: 'Din sjö', fi: 'Järvesi' });
    const her = d.her == null ? '' : ' ' + T(d.her
        ? { no: 'Arten er funnet her.', en: 'The species has been found here.', sv: 'Arten har påträffats här.', fi: 'Lajia on havaittu täällä.' }
        : { no: 'Gjelder bare hvis arten finnes i vannet.', en: 'Only applies if the species lives in the lake.', sv: 'Gäller bara om arten finns i sjön.', fi: 'Pätee vain, jos lajia on järvessä.' });
    let title, body;
    if (trigger === 'spinnerfall') {
        const v = tall(d.wind, l), t = Math.round(d.temp), p = Math.round((d.p || 0) * 100);
        title = `${N}: ` + T({ no: 'spinnerfall i kveld?', en: 'spinner fall tonight?', sv: 'spinnerfall i kväll?', fi: 'spinnerfall tänä iltana?' });
        body = T({
            no: `Rolig og mild kveld (19–22: ${v} m/s, ${t} °C), og modellen anslår at vulgata er i sesong. Sjanse ${p} %.`,
            en: `Calm, mild evening (19–22: ${v} m/s, ${t} °C), and the model puts vulgata in season. Chance ${p} %.`,
            sv: `Lugn och mild kväll (19–22: ${v} m/s, ${t} °C), och modellen uppskattar att vulgata är i säsong. Chans ${p} %.`,
            fi: `Tyyni ja leuto ilta (klo 19–22: ${v} m/s, ${t} °C), ja malli arvioi, että vulgata-kausi on käynnissä. Mahdollisuus ${p} %.`,
        }) + her;
    } else if (trigger === 'isgang') {
        title = `${N}: ` + T({ no: 'isen har gått', en: 'the ice is out', sv: 'isen har gått upp', fi: 'jäät ovat lähteneet' });
        body = T({
            no: `Satellitten så isgangen ${d.dato}.`,
            en: `The satellite saw ice-out on ${d.dato}.`,
            sv: `Satelliten såg islossningen ${d.dato}.`,
            fi: `Satelliitti näki jäidenlähdön ${d.dato}.`,
        }) + (d.marginata ? ' ' + T({
            no: `Modellen anslår marginata fra rundt ${d.marginata}.`,
            en: `The model estimates marginata from around ${d.marginata}.`,
            sv: `Modellen uppskattar marginata från runt ${d.marginata}.`,
            fi: `Malli arvioi marginatan alkavan noin ${d.marginata}.`,
        }) : '');
    } else {   // marginata, vulgata
        const n = d.dager;
        const naar = n === 0 ? T({ no: 'i dag', en: 'today', sv: 'i dag', fi: 'tänään' }) : T({
            no: `om ${n} dag${n === 1 ? '' : 'er'}`,
            en: `in ${n} day${n === 1 ? '' : 's'}`,
            sv: `om ${n} dag${n === 1 ? '' : 'ar'}`,
            fi: `${n} päivän päästä`,
        });
        title = `${N}: ${d.art} ` + T({ no: 'nærmer seg', en: 'soon', sv: 'närmar sig', fi: 'lähestyy' });
        body = T({
            no: `Modellen anslår start rundt ${d.dato} (${naar}).`,
            en: `The model estimates the start around ${d.dato} (${naar}).`,
            sv: `Modellen uppskattar att kläckningen börjar runt ${d.dato} (${naar}).`,
            fi: `Malli arvioi kuoriutumisen alkavan noin ${d.dato} (${naar}).`,
        }) + her;
    }
    return { title, body: ryddFi(body, l) };
}

export const TRIGGER_TYPES = [
    'klekkeChange',
    'klekkeImminent',
    'spinnerfall',
    'stokkmaur',
    'seasonstart',
];
