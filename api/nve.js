// Vercel serverless function – proxies requests to NVE HydAPI
// Keeps the NVE API key secret (stored as env var NVE_KEY)

import { forMange } from '../lib/fartsgrense.js';

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    if (forMange(req, res, 'nve', 120)) return;
    // Cache at Vercel edge for 1 hour
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    // 2026-10-14: snødybde fra seNorge (NVE Grid Time Series) for vannsidene. GTS-API-et sender ikke
    // CORS-hoder, så nettleseren kan ikke hente direkte. Lagt her i stedet for en ny function (Vercel Hobby
    // har maks 12). /api/nve?gts=sd&x=<UTM33 øst>&y=<UTM33 nord>&start=YYYY-MM-DD&end=YYYY-MM-DD
    if (req.query.gts) {
        const tema = String(req.query.gts);
        const x = String(req.query.x || ''), y = String(req.query.y || '');
        const s = String(req.query.start || ''), e = String(req.query.end || '');
        if (!['sd', 'swe'].includes(tema) || !/^\d{5,7}$/.test(x) || !/^\d{6,8}$/.test(y)
            || !/^\d{4}-\d{2}-\d{2}$/.test(s) || !/^\d{4}-\d{2}-\d{2}$/.test(e)) {
            return res.status(400).json({ error: 'Ugyldige parametre for gts' });
        }
        res.setHeader('Cache-Control', 's-maxage=21600, stale-while-revalidate=3600');
        try {
            const up = await fetch(`https://gts.nve.no/api/GridTimeSeries/${x}/${y}/${s}/${e}/${tema}.json`);
            if (!up.ok) return res.status(up.status).json({ error: `seNorge svarte ${up.status}` });
            return res.status(200).json(await up.json());
        } catch (err) {
            return res.status(502).json({ error: 'seNorge utilgjengelig' });
        }
    }

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
