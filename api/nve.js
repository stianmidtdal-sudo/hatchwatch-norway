// Vercel serverless function – proxies requests to NVE HydAPI
// Keeps the NVE API key secret (stored as env var NVE_KEY)

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    // Cache at Vercel edge for 1 hour
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    const { parameter, start, end, station } = req.query;
    if (!parameter || !start || !end) {
        return res.status(400).json({ error: 'Missing required query params: parameter, start, end' });
    }

    const NVE_KEY     = process.env.NVE_KEY;
    const NVE_STATION = station || '212.26.0'; // Default: Suohpatjohka (Kautokeino)

    if (!NVE_KEY) {
        return res.status(500).json({ error: 'NVE_KEY environment variable not set' });
    }

    const url = 'https://hydapi.nve.no/api/v1/Observations'
        + `?StationId=${NVE_STATION}`
        + `&Parameter=${parameter}`
        + `&ResolutionTime=1440`
        + `&ReferenceTime=${start}T00:00:00Z/${end}T23:59:59Z`;

    try {
        const upstream = await fetch(url, {
            headers: {
                'X-API-Key': NVE_KEY,
                'Accept':    'application/json',
            }
        });
        const data = await upstream.json();
        res.status(upstream.status).json(data);
    } catch (err) {
        res.status(502).json({ error: `Upstream NVE HydAPI error: ${err.message}` });
    }
}
