// Vercel serverless function – searches Frost sources by county/name/element

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate');

    const { county, name, elements } = req.query;

    const FROST_ID = process.env.FROST_ID;
    if (!FROST_ID) return res.status(500).json({ error: 'FROST_ID not set' });

    const auth = 'Basic ' + Buffer.from(FROST_ID + ':').toString('base64');

    const params = new URLSearchParams({ fields: 'id,name,masl,geometry,county' });
    if (county)   params.append('county',   county);
    if (name)     params.append('name',     name);
    if (elements) params.append('elements', elements);

    const url = `https://frost.met.no/sources/v0.jsonld?${params}`;

    try {
        const upstream = await fetch(url, { headers: { Authorization: auth } });
        const data = await upstream.json();
        res.status(upstream.status).json(data);
    } catch (err) {
        res.status(502).json({ error: `Frost search error: ${err.message}` });
    }
}
