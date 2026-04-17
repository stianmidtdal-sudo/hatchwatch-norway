// Vercel serverless function – proxies requests to MET Norway Frost API
// Keeps the Frost client ID secret (stored as env var FROST_ID)

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    // Cache at Vercel edge for 1 hour — reduces Frost API calls dramatically under load
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    const { elements, start, end, station } = req.query;
    if (!elements || !start || !end) {
        return res.status(400).json({ error: 'Missing required query params: elements, start, end' });
    }

    const FROST_ID      = process.env.FROST_ID;
    const FROST_STATION = station || 'SN93700'; // Default: Kautokeino

    if (!FROST_ID) {
        return res.status(500).json({ error: 'FROST_ID environment variable not set' });
    }

    const auth = 'Basic ' + Buffer.from(FROST_ID + ':').toString('base64');

    const url = 'https://frost.met.no/observations/v0.jsonld'
        + `?sources=${FROST_STATION}`
        + `&elements=${encodeURIComponent(elements)}`
        + `&referencetime=${start}/${end}`
        + `&timeresolutions=P1D`;

    try {
        const upstream = await fetch(url, {
            headers: { Authorization: auth }
        });
        const data = await upstream.json();
        res.status(upstream.status).json(data);
    } catch (err) {
        res.status(502).json({ error: `Upstream Frost API error: ${err.message}` });
    }
}
