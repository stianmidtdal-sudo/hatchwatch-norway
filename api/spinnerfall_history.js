// Vercel serverless function – proxies requests to MET Norway Frost API for
// hourly observations. Returnerer kveldsvindu-aggregering (kl 19-22 lokal tid
// Europe/Oslo) for siste N dager. Brukes til å beregne backlog FØR dag 1 i
// forecast-vinduet, så spinnerfall-modellen vet om det har vært en dårlig
// vær-periode bak oss.
//
// Holder Frost client ID hemmelig (env var FROST_ID).
//
// Param:
//   station — Frost stasjons-ID (SN17640, SN18500, ...)
//   days    — antall dager bakover (default 7)
//
// Returnerer samme format som /api/spinnerfall:
//   { 'YYYY-MM-DD': { wind, temp, cloud, precip, n }, ... }
//
// Begrensning: ikke alle stasjoner har alle elementer. Manglende vind eller
// temp = dagen droppes. Manglende cloud/precip = bruker 0 som default
// (ingen straffeffekt — gir nøytral vurdering).

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    const { station, days } = req.query;
    if (!station) {
        return res.status(400).json({ error: 'Missing required query param: station' });
    }
    const FROST_ID = process.env.FROST_ID;
    if (!FROST_ID) {
        return res.status(500).json({ error: 'FROST_ID environment variable not set' });
    }

    const lookbackDays = Math.min(14, Math.max(1, parseInt(days || '7', 10)));
    const auth = 'Basic ' + Buffer.from(FROST_ID + ':').toString('base64');

    // Tidsrom: i dag - lookbackDays til i dag (UTC referencetime)
    const now = new Date();
    const start = new Date(now);
    start.setUTCDate(start.getUTCDate() - lookbackDays);
    const startStr = start.toISOString().slice(0, 19) + 'Z';
    const endStr   = now.toISOString().slice(0, 19) + 'Z';

    // Hent fire elementer på time-oppløsning
    const elements = [
        'wind_speed',
        'air_temperature',
        'cloud_area_fraction',
        'sum(precipitation_amount PT1H)'
    ].join(',');

    const url = 'https://frost.met.no/observations/v0.jsonld'
        + `?sources=${station}`
        + `&elements=${encodeURIComponent(elements)}`
        + `&referencetime=${startStr}/${endStr}`
        + `&timeresolutions=PT1H`;

    try {
        const upstream = await fetch(url, { headers: { Authorization: auth } });
        if (!upstream.ok) {
            const txt = await upstream.text().catch(() => '');
            return res.status(upstream.status).json({ error: `Frost API ${upstream.status}`, detail: txt.slice(0, 200) });
        }
        const data = await upstream.json();

        // Hjelper: lokal time + dato i Europe/Oslo
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

        // Akkumulator: per dato, per element
        // { date: { wind: [v,v,...], temp: [...], cloud: [...], precip: [...] } }
        const buckets = {};
        function bucket(date) {
            if (!buckets[date]) {
                buckets[date] = { wind: [], temp: [], cloud: [], precip: [] };
            }
            return buckets[date];
        }

        for (const item of (data.data || [])) {
            const { date, hour } = osloHourAndDate(item.referenceTime);
            if (hour < 19 || hour > 22) continue;
            const obs = item.observations || [];
            for (const o of obs) {
                if (o.value == null) continue;
                const el = o.elementId;
                const b = bucket(date);
                if (el === 'wind_speed')                              b.wind.push(o.value);
                else if (el === 'air_temperature')                    b.temp.push(o.value);
                else if (el === 'cloud_area_fraction')                b.cloud.push(o.value);
                else if (el === 'sum(precipitation_amount PT1H)')     b.precip.push(o.value);
            }
        }

        function avg(arr) {
            if (!arr.length) return null;
            return arr.reduce((a, b) => a + b, 0) / arr.length;
        }
        function sum(arr) {
            return arr.reduce((a, b) => a + b, 0);
        }

        const result = {};
        for (const date in buckets) {
            const b = buckets[date];
            // Krev minst vind og temp — andre kan være null/tomme
            if (b.wind.length === 0 || b.temp.length === 0) continue;
            // Krev minst 3 målinger på vind for stabilt snitt
            if (b.wind.length < 3) continue;

            result[date] = {
                wind:   Math.round(avg(b.wind) * 10) / 10,
                temp:   Math.round(avg(b.temp) * 10) / 10,
                cloud:  b.cloud.length ? Math.round(avg(b.cloud)) : 50,        // default neutral
                precip: b.precip.length ? Math.round(sum(b.precip) * 10) / 10 : 0,
                n: b.wind.length
            };
        }

        res.json(result);
    } catch (err) {
        res.status(502).json({ error: `Upstream Frost API error: ${err.message}` });
    }
}
