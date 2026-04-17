// Vercel serverless function – proxies Frost sources endpoint (station info)

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    // Cache at edge for 24 hours — station metadata rarely changes
    res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate');

    const { station } = req.query;
    if (!station) return res.status(400).json({ error: 'Missing station param' });

    const FROST_ID = process.env.FROST_ID;
    if (!FROST_ID) return res.status(500).json({ error: 'FROST_ID not set' });

    const auth = 'Basic ' + Buffer.from(FROST_ID + ':').toString('base64');
    const url  = `https://frost.met.no/sources/v0.jsonld?ids=${station}`;

    try {
        const upstream = await fetch(url, { headers: { Authorization: auth } });
        const data = await upstream.json();
        res.status(upstream.status).json(data);
    } catch (err) {
        res.status(502).json({ error: `Frost sources error: ${err.message}` });
    }
}
