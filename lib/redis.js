// Delt Upstash Redis-klient for push-subscription-håndtering.
// Brukes av alle push-* endpoints i HatchWatch. Innført 2026-05-19.
//
// Datamodell:
//   sub:{hash}        — JSON-objekt med subscription + preferanser
//   subs:all          — Redis Set med alle hash-er (for iterasjon i cron)
//   pred:{loc}:{spec} — JSON-objekt med siste predikerte klekkedato per lokasjon/art
//                       (postes av frontend, leses av cron for change-detection)
//   notif:{hash}:{trig}:{loc} — siste push sendt-timestamp + verdi (debounce)
//   predhist:{loc}:{spec}:{year} — Redis hash, felt = ISO-dato (YYYY-MM-DD),
//                       verdi = JSON { predDoy, predDate, info, ts }.
//                       Lagrer én snapshot per dag (første skriving vinner).
//                       Brukes av konvergensgrafen for å vise ekte historikk i
//                       stedet for replay-from-current-data. Innført 2026-05-25.
//
// hash = SHA-256 av subscription.endpoint, første 16 hex-tegn — kort men unik nok.

import { Redis } from '@upstash/redis';
import crypto from 'crypto';

let _client = null;
export function redis() {
    if (_client) return _client;
    const url = process.env.UPSTASH_REDIS_REST_URL;
    const token = process.env.UPSTASH_REDIS_REST_TOKEN;
    if (!url || !token) {
        throw new Error('Upstash env vars mangler: UPSTASH_REDIS_REST_URL og UPSTASH_REDIS_REST_TOKEN');
    }
    _client = new Redis({ url, token });
    return _client;
}

// Kort, deterministisk hash for endpoint (16 hex-tegn = 64 bits, mer enn nok)
export function hashEndpoint(endpoint) {
    return crypto.createHash('sha256').update(endpoint).digest('hex').slice(0, 16);
}

// Nøkkelhjelpere
export const k = {
    sub:    (hash)                     => `sub:${hash}`,
    subsAll:                              `subs:all`,
    pred:   (loc, species)             => `pred:${loc}:${species}`,
    notif:  (hash, trigger, loc)       => `notif:${hash}:${trigger}:${loc}`,
    predHist: (loc, species, year)     => `predhist:${loc}:${species}:${year}`,
};
