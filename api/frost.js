// Vercel serverless function – proxies requests to MET Norway Frost API
// Keeps the Frost client ID secret (stored as env var FROST_ID)
//
// To moduser:
//   GET /api/frost?elements=...&start=...&end=...[&station=SNxxxx]
//     → daglige observasjoner (standard).
//   GET /api/frost?mode=sources&station=SNxxxx
//     → stasjonsmetadata. Tidligere eget endpoint /api/frost-sources —
//       slått sammen hit 2026-10-01 for å frigjøre en Vercel-function.
//       /api/frost-sources fungerer fortsatt via rewrite i vercel.json.

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');

    const FROST_ID = process.env.FROST_ID;
    if (!FROST_ID) {
        return res.status(500).json({ error: 'FROST_ID environment variable not set' });
    }
    const auth = 'Basic ' + Buffer.from(FROST_ID + ':').toString('base64');

    const mode = (req.query.mode || '').toString();
    if (mode === 'sources') return handleSources(req, res, auth);
    return handleObservations(req, res, auth);
}

async function handleObservations(req, res, auth) {
    // Cache at Vercel edge for 1 hour — reduces Frost API calls dramatically under load
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    const { elements, start, end, station } = req.query;
    if (!elements || !start || !end) {
        return res.status(400).json({ error: 'Missing required query params: elements, start, end' });
    }
    const FROST_STATION = station || 'SN93700'; // Default: Kautokeino

    const url = 'https://frost.met.no/observations/v0.jsonld'
        + `?sources=${FROST_STATION}`
        + `&elements=${encodeURIComponent(elements)}`
        + `&referencetime=${start}/${end}`
        + `&timeresolutions=P1D`;

    try {
        const upstream = await fetch(url, { headers: { Authorization: auth } });
        const data = await upstream.json();
        res.status(upstream.status).json(data);
    } catch (err) {
        res.status(502).json({ error: `Upstream Frost API error: ${err.message}` });
    }
}

async function handleSources(req, res, auth) {
    // Cache at edge for 24 hours — station metadata rarely changes
    res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate');

    const { station } = req.query;
    if (!station) return res.status(400).json({ error: 'Missing station param' });

    const url = `https://frost.met.no/sources/v0.jsonld?ids=${station}`;
    try {
        const upstream = await fetch(url, { headers: { Authorization: auth } });
        const data = await upstream.json();
        res.status(upstream.status).json(data);
    } catch (err) {
        res.status(502).json({ error: `Frost sources error: ${err.message}` });
    }
}
