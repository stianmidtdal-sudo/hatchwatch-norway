// Vercel serverless function – proxies requests to MET Norway Locationforecast API.
// Returnerer kveldsvindu-aggregering (kl 19-22 lokal tid Europe/Oslo) for de
// neste 9 dagene: snitt-vindstyrke, snitt-temperatur, snitt-skydekke og
// nedbørssum. Brukes av spinnerfall-vakt-funksjonen.
//
// MET ber om identifiserbar User-Agent: hatchwatch.no support@hatchwatch.no
// Rate limit: 20 req/sec per User-Agent — vi cacher 1 time, langt under taket.
//
// Tidsvindu: 19, 20, 21, 22 lokal tid (paringsdans + spinnerfall).
//   - Vind:    instant snitt over disse timene
//   - Temp:    instant snitt
//   - Skydekke: instant snitt (0-100%)
//   - Nedbør:  sum (mm) over de fire timene
//
// Kun dager med ≥3 av 4 målinger inkluderes.

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

        // Hjelper: gir lokal time Europe/Oslo for en ISO-timestamp.
        // Bruker Intl.DateTimeFormat for å håndtere sommertid riktig.
        const osloFmt = new Intl.DateTimeFormat('en-GB', {
            timeZone: 'Europe/Oslo',
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', hour12: false
        });
        function osloHourAndDate(iso) {
            const d = new Date(iso);
            const parts = osloFmt.formatToParts(d);
            const map = {};
            for (const p of parts) map[p.type] = p.value;
            return {
                date: `${map.year}-${map.month}-${map.day}`,
                hour: parseInt(map.hour, 10) % 24
            };
        }

        // Akkumulator per dato
        const buckets = {};
        function bucket(dateStr) {
            if (!buckets[dateStr]) {
                buckets[dateStr] = {
                    windSum: 0, tempSum: 0, cloudSum: 0, precipSum: 0,
                    n: 0
                };
            }
            return buckets[dateStr];
        }

        for (const ts of series) {
            const { date, hour } = osloHourAndDate(ts.time);
            // Kveldsvindu — eksklusivt på 23 (paringsdans 19-21, spinnerfall 21-23)
            if (hour < 19 || hour > 22) continue;

            const inst = ts.data.instant && ts.data.instant.details;
            if (!inst) continue;
            const wind = inst.wind_speed;
            const temp = inst.air_temperature;
            const cloud = inst.cloud_area_fraction;
            // Nedbør: bruk next_1_hours hvis tilgjengelig (kun dag 1-3)
            const next1 = ts.data.next_1_hours && ts.data.next_1_hours.details;
            const precip = next1 ? next1.precipitation_amount : null;

            if (wind == null || temp == null || cloud == null) continue;

            const b = bucket(date);
            b.windSum  += wind;
            b.tempSum  += temp;
            b.cloudSum += cloud;
            b.precipSum += (precip != null ? precip : 0);
            b.n += 1;
        }

        const result = {};
        for (const date in buckets) {
            const b = buckets[date];
            // Krev minst 3 målinger for å aksepetere dagen
            if (b.n < 3) continue;
            result[date] = {
                wind:   Math.round(b.windSum / b.n * 10) / 10,
                temp:   Math.round(b.tempSum / b.n * 10) / 10,
                cloud:  Math.round(b.cloudSum / b.n),
                precip: Math.round(b.precipSum * 10) / 10,
                n: b.n
            };
        }

        res.json(result);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
}
