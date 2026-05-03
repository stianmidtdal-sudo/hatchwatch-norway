// Vercel serverless function – proxies requests to MET Norway Locationforecast API.
// Returnerer 9-dagers daglig snitt-temperatur for et koordinatpunkt.
// Brukes av langtidsvarsel-funksjonalitet for å erstatte klimasnitt med faktisk
// prognose for de neste 7-9 dager (mer presis konvergensgraf).
//
// MET ber om identifiserbar User-Agent: hatchwatch.no support@hatchwatch.no
// Rate limit: 20 req/sec per User-Agent — vi cacher 1 time, langt under taket.

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    // Cache 1 time — MET oppdaterer prognose maks hver time
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    const { lat, lon } = req.query;
    if (!lat || !lon) {
        return res.status(400).json({ error: 'Missing required query params: lat, lon' });
    }

    const url = `https://api.met.no/weatherapi/locationforecast/2.0/complete?lat=${lat}&lon=${lon}`;

    try {
        const upstream = await fetch(url, {
            headers: {
                'User-Agent': 'hatchwatch.no support@hatchwatch.no'
            }
        });
        if (!upstream.ok) {
            const txt = await upstream.text();
            return res.status(upstream.status).json({ error: `MET API: ${upstream.status}`, detail: txt.slice(0, 200) });
        }
        const data = await upstream.json();

        // Aggregér time-for-time til daglig snitt
        const dailySum = {};
        const dailyCount = {};
        for (const ts of data.properties.timeseries) {
            const dateStr = ts.time.substring(0, 10); // 'YYYY-MM-DD'
            const temp = ts.data.instant.details.air_temperature;
            if (temp == null) continue;
            dailySum[dateStr] = (dailySum[dateStr] || 0) + temp;
            dailyCount[dateStr] = (dailyCount[dateStr] || 0) + 1;
        }

        const result = {};
        for (const dateStr in dailySum) {
            // Krev minst 12 timer per dag for å stole på snittet
            if (dailyCount[dateStr] >= 12) {
                result[dateStr] = Math.round(dailySum[dateStr] / dailyCount[dateStr] * 10) / 10;
            }
        }

        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
}
