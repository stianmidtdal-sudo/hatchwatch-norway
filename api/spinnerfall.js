// Vercel serverless function – proxies requests to MET Norway Locationforecast API.
// Returnerer kveldsvindu-aggregering (kl 19-22 lokal tid Europe/Oslo) for de
// neste 9 dagene: snitt-vindstyrke, snitt-temperatur, snitt-skydekke,
// nedbørssum, snitt-luftfuktighet og trykk-trend. Brukes av spinnerfall-vakt.
//
// MET ber om identifiserbar User-Agent: hatchwatch.no support@hatchwatch.no
// Rate limit: 20 req/sec per User-Agent — vi cacher 1 time, langt under taket.
//
// Tidsvindu: 19, 20, 21, 22 lokal tid (paringsdans + spinnerfall).
//   - Vind:        instant snitt over disse timene
//   - Vindkast:    instant snitt av wind_speed_of_gust — innført 2026-05-28
//                  (svermesøyler ødelegges av kast, ikke bare snittvind)
//   - Temp:        instant snitt
//   - Skydekke:    instant snitt (0-100%)
//   - Nedbør:      sum (mm) over de fire timene
//   - Luftfuktighet: instant snitt (0-100% RH) — innført 2026-05-20
//   - Trykk:       instant snitt kvelden + snitt ettermiddag (13-16) for
//                  trend-beregning (evening - afternoon, hPa).
//                  Stigende/stabilt = god indikator, raskt fall = front på vei.
//
// Dager med ≥3 av 4 målinger gir presis prognose (time-oppløsning, dag 1-2).
// Dager med 1-2 målinger (dag 3+ — MET går over til 6-timers oppløsning) inkluderes
// også, men markeres som indikative i frontend. Bedre enn å skjule dem helt.
//
// Endret 2026-05-28: minste-grense senket fra 3 til 1 målinger. Stian foreslo
// dette etter at Østmarka bare viste 2 dager — vi forkastet 7 brukbare dager
// fordi MET-data har grovere oppløsning lengre ut i prognosen.
//
// Utvidet 2026-08-18: DAGVINDU (10-18 lokal tid) for Forhold-modus.
// Samme MET-payload gir nå to aggregeringer:
//   ?window=evening (default) — uendret kveldsvindu, brukt av spinnerfall-vakta
//   ?window=day               — dagvindu 10-18, brukt av forhold-stripa
//   ?window=both              — { evening: {...}, day: {...} } i ett kall
// Default er bevisst uendret så eksisterende kallere ikke påvirkes.
//
// Dagvinduet returnerer i tillegg tempMax og windMax, fordi forhold-modellen
// bryr seg om dagens topptemperatur (klekkingen trigges av varmeste time,
// ikke snittet) og om verste vindkast i løpet av fiskedagen.

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    // Cache 1 time — MET oppdaterer prognose maks hver time
    res.setHeader('Cache-Control', 's-maxage=3600, stale-while-revalidate=600');

    const { lat, lon } = req.query;
    const window = (req.query.window || 'evening').toLowerCase();
    if (!lat || !lon) {
        return res.status(400).json({ error: 'Missing required query params: lat, lon' });
    }
    if (['evening', 'day', 'both'].indexOf(window) === -1) {
        return res.status(400).json({ error: "window must be one of: evening, day, both" });
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

        // Akkumulator per dato. Vi samler tre tidsvinduer:
        //   morgen  (07-10) — kun trykk, for dagvinduets trend
        //   dag     (10-18) — full aggregering for forhold-stripa
        //   emiddag (13-16) — trykk, brukes av begge trender
        //   kveld   (19-22) — full aggregering for spinnerfall-vakta
        const buckets = {};
        function bucket(dateStr) {
            if (!buckets[dateStr]) {
                buckets[dateStr] = {
                    // Evening 19-22 — hovedaggregering (uendret)
                    windSum: 0, tempSum: 0, cloudSum: 0, precipSum: 0,
                    humidSum: 0, humidN: 0,
                    gustSum: 0, gustN: 0,
                    pressEveSum: 0, pressEveN: 0,
                    n: 0,
                    // Afternoon 13-16 — trykk-trend for begge vinduer
                    pressAftSum: 0, pressAftN: 0,
                    // Morning 07-10 — trykk-trend for dagvinduet
                    pressMornSum: 0, pressMornN: 0,
                    // Day 10-18 — aggregering for forhold-stripa
                    dWindSum: 0, dWindMax: -Infinity,
                    dTempSum: 0, dTempMax: -Infinity,
                    dCloudSum: 0, dPrecipSum: 0,
                    dHumidSum: 0, dHumidN: 0,
                    dGustSum: 0, dGustMax: -Infinity, dGustN: 0,
                    dN: 0,
                };
            }
            return buckets[dateStr];
        }

        for (const ts of series) {
            const { date, hour } = osloHourAndDate(ts.time);
            const inst = ts.data.instant && ts.data.instant.details;
            if (!inst) continue;
            const pressure = inst.air_pressure_at_sea_level;

            // Morgen (07-10): bare trykk, for dagvinduets trend
            if (hour >= 7 && hour <= 10 && pressure != null) {
                const b = bucket(date);
                b.pressMornSum += pressure;
                b.pressMornN += 1;
            }

            // Ettermiddag (13-16): bare trykk, for trend-sammenligning
            if (hour >= 13 && hour <= 16 && pressure != null) {
                const b = bucket(date);
                b.pressAftSum += pressure;
                b.pressAftN += 1;
            }

            const wind = inst.wind_speed;
            const gust = inst.wind_speed_of_gust;   // Valgfri felt fra MET
            const temp = inst.air_temperature;
            const cloud = inst.cloud_area_fraction;
            const humid = inst.relative_humidity;
            // Nedbør: bruk next_1_hours hvis tilgjengelig (kun dag 1-3)
            const next1 = ts.data.next_1_hours && ts.data.next_1_hours.details;
            const precip = next1 ? next1.precipitation_amount : null;

            // Dagvindu (10-18): full aggregering for forhold-stripa
            if (hour >= 10 && hour <= 18 && wind != null && temp != null && cloud != null) {
                const b = bucket(date);
                b.dWindSum += wind;
                if (wind > b.dWindMax) b.dWindMax = wind;
                b.dTempSum += temp;
                if (temp > b.dTempMax) b.dTempMax = temp;
                b.dCloudSum += cloud;
                b.dPrecipSum += (precip != null ? precip : 0);
                if (humid != null) { b.dHumidSum += humid; b.dHumidN += 1; }
                if (gust != null) {
                    b.dGustSum += gust;
                    if (gust > b.dGustMax) b.dGustMax = gust;
                    b.dGustN += 1;
                }
                b.dN += 1;
            }

            // Kveldsvindu (19-22): full aggregering
            if (hour < 19 || hour > 22) continue;

            if (wind == null || temp == null || cloud == null) continue;

            const b = bucket(date);
            b.windSum   += wind;
            b.tempSum   += temp;
            b.cloudSum  += cloud;
            b.precipSum += (precip != null ? precip : 0);
            if (humid != null) {
                b.humidSum += humid;
                b.humidN += 1;
            }
            if (gust != null) {
                b.gustSum += gust;
                b.gustN += 1;
            }
            if (pressure != null) {
                b.pressEveSum += pressure;
                b.pressEveN += 1;
            }
            b.n += 1;
        }

        const r1 = (v) => Math.round(v * 10) / 10;

        // ── Kveldsvindu (uendret output-form) ──────────────────────────────
        const evening = {};
        for (const date in buckets) {
            const b = buckets[date];
            // Krev minst 1 måling. Dag 1-2 har typisk 4 målinger (time-oppløsning),
            // dag 3+ har 0-1 (6-timers oppløsning). Frontend markerer dager med
            // n < 3 som indikative.
            if (b.n < 1) continue;
            const humidAvg = b.humidN > 0 ? b.humidSum / b.humidN : null;
            const gustAvg = b.gustN > 0 ? b.gustSum / b.gustN : null;
            const pressEveAvg = b.pressEveN > 0 ? b.pressEveSum / b.pressEveN : null;
            const pressAftAvg = b.pressAftN > 0 ? b.pressAftSum / b.pressAftN : null;
            // Trykk-trend = (kveld) - (ettermiddag). Stigende/stabilt = god, raskt fall = front.
            // Krever begge for å beregne; ellers null (= ingen modifikator).
            const pressureTrend = (pressEveAvg != null && pressAftAvg != null)
                ? pressEveAvg - pressAftAvg
                : null;
            evening[date] = {
                wind:   r1(b.windSum / b.n),
                gust:   gustAvg != null ? r1(gustAvg) : null,
                temp:   r1(b.tempSum / b.n),
                cloud:  Math.round(b.cloudSum / b.n),
                precip: r1(b.precipSum),
                humid:  humidAvg != null ? Math.round(humidAvg) : null,
                pressure: pressEveAvg != null ? r1(pressEveAvg) : null,
                pressureTrend: pressureTrend != null ? r1(pressureTrend) : null,
                n: b.n,
            };
        }

        // ── Dagvindu 10-18 (nytt — forhold-stripa) ─────────────────────────
        const day = {};
        for (const date in buckets) {
            const b = buckets[date];
            if (b.dN < 1) continue;
            const humidAvg = b.dHumidN > 0 ? b.dHumidSum / b.dHumidN : null;
            const gustAvg  = b.dGustN > 0 ? b.dGustSum / b.dGustN : null;
            const pressMornAvg = b.pressMornN > 0 ? b.pressMornSum / b.pressMornN : null;
            const pressAftAvg  = b.pressAftN > 0 ? b.pressAftSum / b.pressAftN : null;
            // Dagens trykk-trend = ettermiddag - morgen. Stigende = stabilt vær.
            const pressureTrend = (pressAftAvg != null && pressMornAvg != null)
                ? pressAftAvg - pressMornAvg
                : null;
            day[date] = {
                wind:    r1(b.dWindSum / b.dN),
                windMax: b.dWindMax > -Infinity ? r1(b.dWindMax) : null,
                gust:    gustAvg != null ? r1(gustAvg) : null,
                gustMax: b.dGustMax > -Infinity ? r1(b.dGustMax) : null,
                temp:    r1(b.dTempSum / b.dN),
                tempMax: b.dTempMax > -Infinity ? r1(b.dTempMax) : null,
                cloud:   Math.round(b.dCloudSum / b.dN),
                precip:  r1(b.dPrecipSum),
                humid:   humidAvg != null ? Math.round(humidAvg) : null,
                pressureTrend: pressureTrend != null ? r1(pressureTrend) : null,
                n: b.dN,
            };
        }

        if (window === 'day')  return res.json(day);
        if (window === 'both') return res.json({ evening, day });
        res.json(evening);   // default — uendret for eksisterende kallere
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
}
