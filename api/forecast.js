// Vercel serverless function – proxies requests to MET Norway Locationforecast API.
// Returnerer 9-dagers daglig snitt-temperatur for et koordinatpunkt.
// Brukes av langtidsvarsel-funksjonalitet for å erstatte klimasnitt med faktisk
// prognose for de neste 7-9 dager (mer presis konvergensgraf).
//
// MET ber om identifiserbar User-Agent: hatchwatch.no support@hatchwatch.no
// Rate limit: 20 req/sec per User-Agent — vi cacher 1 time, langt under taket.
//
// Aggregering (oppdatert 2026-05-02): Tidsvektet snitt for å håndtere
// MET sin variable intervall-struktur:
//   - Dag 1-3: time-for-time data (24 målinger * 1 time = 24t)
//   - Dag 4-9: 6-timers data (4 målinger * 6 timer = 24t)
//   - Dag 10+: 12-timers data, sjelden brukt
// Hver måling vektes med intervallet til neste måling. Daglig snitt =
// sum(temp * timer) / sum(timer). Krever ≥12 timers dekning per dag.

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

        const series = data.properties.timeseries;
        const dailyTempSum = {};   // sum(temp * hours)
        const dailyHours   = {};   // sum(hours)

        for (let i = 0; i < series.length; i++) {
            const ts = series[i];
            const temp = ts.data.instant.details.air_temperature;
            if (temp == null) continue;

            const time = new Date(ts.time);
            // Beregn intervall til neste måling (i timer)
            let intervalHours;
            if (i + 1 < series.length) {
                const nextTime = new Date(series[i + 1].time);
                intervalHours = (nextTime - time) / (1000 * 60 * 60);
                // Cap på 6 timer for å unngå at en stor lakune i data
                // gir én måling for stor vekt
                intervalHours = Math.min(intervalHours, 6);
            } else {
                // Siste måling — anta 1 time (typisk for time-for-time data)
                intervalHours = 1;
            }

            // Tilordne til dag (UTC-dato fra timestamp)
            const dateStr = ts.time.substring(0, 10);
            dailyTempSum[dateStr] = (dailyTempSum[dateStr] || 0) + temp * intervalHours;
            dailyHours[dateStr]   = (dailyHours[dateStr] || 0) + intervalHours;
        }

        const result = {};
        for (const dateStr in dailyTempSum) {
            // Krev minst 12 timer dekning per dag for stabilt snitt
            if (dailyHours[dateStr] >= 12) {
                result[dateStr] = Math.round(dailyTempSum[dateStr] / dailyHours[dateStr] * 10) / 10;
            }
        }

        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
}
