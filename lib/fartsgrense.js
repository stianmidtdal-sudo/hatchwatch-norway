// Fartsgrense per IP for serverfunksjonene (2026-10-16, Stian: «begrensninger på serverfunksjonene»).
//
// Telleren ligger i minnet i hver Vercel-instans: ingen Redis-kall, så den koster ingenting og
// gjør ikke svarene tregere. Den stopper én klient som hamrer løs (skraping, løkker, feilskrevne
// skript), ikke et angrep fordelt på mange maskiner. Grensene ligger langt over det en vanlig
// sidevisning bruker (dashboardet gjør 4–6 kall per lokasjon; vann- og elvesiden 1–2).
// Svar som allerede ligger i Vercels hurtigbuffer (s-maxage) teller ikke, de når aldri funksjonen.

import crypto from 'crypto';

const tellere = new Map();

// Egne kall mellom funksjonene (cron-daily henter /api/spinnerfall for hvert vann med varsel) kommer
// fra samme IP og skal ikke stoppes. De merkes med en nøkkel avledet av en hemmelighet begge allerede
// har i miljøet; selve hemmeligheten sendes aldri.
export function internNokkel() {
    const s = process.env.UPSTASH_REDIS_REST_TOKEN || '';
    return s ? crypto.createHash('sha256').update('fartsgrense:' + s).digest('hex').slice(0, 32) : '';
}

export function klientIp(req) {
    const f = req.headers['x-forwarded-for'];
    return String(f ? f.split(',')[0] : (req.headers['x-real-ip'] || (req.socket && req.socket.remoteAddress) || '?')).trim();
}

// Sann = grensen er nådd og 429 er sendt; handleren skal returnere straks.
export function forMange(req, res, navn, maks, vinduSek = 60) {
    const intern = internNokkel();
    if (intern && req.headers['x-hw-intern'] === intern) return false;
    const naa = Date.now(), nokkel = navn + '|' + klientIp(req);
    let t = tellere.get(nokkel);
    if (!t || naa > t.slutt) { t = { n: 0, slutt: naa + vinduSek * 1000 }; tellere.set(nokkel, t); }
    t.n++;
    if (tellere.size > 5000) for (const [k, v] of tellere) if (naa > v.slutt) tellere.delete(k);
    if (t.n <= maks) return false;
    res.setHeader('Retry-After', String(Math.ceil((t.slutt - naa) / 1000)));
    res.setHeader('Cache-Control', 'no-store');   // 429 må aldri havne i hurtigbufferen
    res.status(429).json({ error: 'For mange forespørsler. Prøv igjen om litt.' });
    return true;
}
