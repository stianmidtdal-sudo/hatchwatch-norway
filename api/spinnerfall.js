// Vercel serverless function – proxies requests to MET Norway Locationforecast API.
//
// Returnerer aggregert værdata for de neste ~9 dagene i tre former:
//
//   evening — kveldsvindu 19-22 lokal tid. Spinnerfall-vakta.
//   day     — dagvindu 10-18 lokal tid, pluss døgnets min/maks. Forhold-fanen.
//   hourly  — time for time, så langt MET har oppløsning. Forhold-fanen.
//
// MET ber om identifiserbar User-Agent: hatchwatch.no support@hatchwatch.no
// Rate limit: 20 req/sec per User-Agent — vi cacher 1 time, langt under taket.
//
// ── Kall ──────────────────────────────────────────────────────────────────
//   ?window=evening  (default) → kun evening-objektet, flatt. UENDRET fra før,
//                                slik at eksisterende kallere ikke påvirkes.
//   ?window=day                → kun day-objektet
//   ?window=both               → { evening, day, hourly }
//
// ── Historikk ─────────────────────────────────────────────────────────────
// 2026-05-10  Opprettet for spinnerfall-vakta (kveldsvindu 19-22).
// 2026-05-20  Luftfuktighet + trykk-trend lagt til.
// 2026-05-28  Vindkast lagt til. Minstekrav senket fra 3 til 1 måling.
// 2026-08-18  Dagvindu 10-18 lagt til for Forhold-modus.
// 2026-08-18  Timedata, vindretning og MET sine værsymboler lagt til.
//
// ── Hvorfor vindretning ───────────────────────────────────────────────────
// Nordavind og sønnavind på 6 m/s er to helt forskjellige fiskedager i
// Finnmark. Retning aggregeres med SIRKULÆRT snitt (sin/cos), ikke aritmetisk
// — snittet av 350° og 10° er 0°, ikke 180°.
//
// ── Hvorfor MET sine symbolkoder ──────────────────────────────────────────
// Vi kunne utledet ikon fra skydekkeprosent, men MET sin symbol_code tar
// hensyn til nedbørtype, tåke og lysforhold. Å bruke den gir samme ikon som
// yr.no viser, noe brukeren kjenner igjen.

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
            headers: { 'User-Agent': 'hatchwatch.no support@hatchwatch.no' }
        });
        if (!upstream.ok) {
            const txt = await upstream.text();
            return res.status(upstream.status).json({ error: `MET API: ${upstream.status}`, detail: txt.slice(0, 200) });
        }
        const data = await upstream.json();
        const series = data.properties.timeseries;

        // Lokal time og dato (Europe/Oslo) for en ISO-timestamp.
        // Intl håndterer sommertid riktig; manuell offset ville feilet i mars/oktober.
        const osloFmt = new Intl.DateTimeFormat('en-GB', {
            timeZone: 'Europe/Oslo',
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', hour12: false
        });
        function osloHourAndDate(iso) {
            const parts = osloFmt.formatToParts(new Date(iso));
            const map = {};
            for (const p of parts) map[p.type] = p.value;
            return {
                date: `${map.year}-${map.month}-${map.day}`,
                hour: parseInt(map.hour, 10) % 24
            };
        }

        const r1 = (v) => Math.round(v * 10) / 10;

        // Sirkulært snitt for vindretning. Aritmetisk snitt av 350° og 10°
        // ville gitt 180° (stikk motsatt) — sin/cos gir riktig svar, 0°.
        function circMean(sumSin, sumCos, n) {
            if (!n) return null;
            const deg = Math.atan2(sumSin / n, sumCos / n) * 180 / Math.PI;
            return Math.round((deg + 360) % 360);
        }

        // ── Akkumulator per dato ──────────────────────────────────────────
        const buckets = {};
        function bucket(dateStr) {
            if (!buckets[dateStr]) {
                buckets[dateStr] = {
                    // Kveld 19-22
                    e: { windSum: 0, tempSum: 0, cloudSum: 0, precipSum: 0,
                         humidSum: 0, humidN: 0, gustSum: 0, gustN: 0,
                         dirSin: 0, dirCos: 0, dirN: 0,
                         pressSum: 0, pressN: 0, n: 0 },
                    // Dag 10-18
                    d: { windSum: 0, windMax: -Infinity, tempSum: 0, tempMax: -Infinity,
                         cloudSum: 0, precipSum: 0, humidSum: 0, humidN: 0,
                         gustSum: 0, gustMax: -Infinity, gustN: 0,
                         dirSin: 0, dirCos: 0, dirN: 0,
                         symbols: {}, n: 0 },
                    // Hele døgnet — for min/max og total nedbør
                    f: { tempMin: Infinity, tempMax: -Infinity, precipSum: 0, n: 0 },
                    // Trykk i tre vinduer, for de to trendene
                    pMorn: { sum: 0, n: 0 },   // 07-10
                    pAft:  { sum: 0, n: 0 },   // 13-16
                    // Time for time
                    hours: [],
                };
            }
            return buckets[dateStr];
        }

        for (const ts of series) {
            const { date, hour } = osloHourAndDate(ts.time);
            const inst = ts.data.instant && ts.data.instant.details;
            if (!inst) continue;

            const wind    = inst.wind_speed;
            const gust    = inst.wind_speed_of_gust;          // ikke alltid til stede
            const dir     = inst.wind_from_direction;
            const temp    = inst.air_temperature;
            const cloud   = inst.cloud_area_fraction;
            const humid   = inst.relative_humidity;
            const press   = inst.air_pressure_at_sea_level;

            // Nedbør og symbol: next_1_hours finnes kun dag 1-3, deretter
            // next_6_hours. Vi tar det fineste som er tilgjengelig.
            const n1 = ts.data.next_1_hours && ts.data.next_1_hours.details;
            const n6 = ts.data.next_6_hours && ts.data.next_6_hours.details;
            const precip = n1 ? n1.precipitation_amount
                         : (n6 ? n6.precipitation_amount / 6 : null);

            const sym1 = ts.data.next_1_hours && ts.data.next_1_hours.summary;
            const sym6 = ts.data.next_6_hours && ts.data.next_6_hours.summary;
            const symbol = (sym1 && sym1.symbol_code) || (sym6 && sym6.symbol_code) || null;

            const b = bucket(date);

            // Trykk-vinduer
            if (press != null) {
                if (hour >= 7  && hour <= 10) { b.pMorn.sum += press; b.pMorn.n += 1; }
                if (hour >= 13 && hour <= 16) { b.pAft.sum  += press; b.pAft.n  += 1; }
            }

            // Hele døgnet
            if (temp != null) {
                if (temp < b.f.tempMin) b.f.tempMin = temp;
                if (temp > b.f.tempMax) b.f.tempMax = temp;
                b.f.n += 1;
            }
            if (precip != null) b.f.precipSum += precip;

            // Timeoppføring — alt vi vet om denne timen
            if (temp != null && wind != null) {
                b.hours.push({
                    h: hour,
                    temp: r1(temp),
                    wind: r1(wind),
                    gust: gust != null ? r1(gust) : null,
                    dir: dir != null ? Math.round(dir) : null,
                    cloud: cloud != null ? Math.round(cloud) : null,
                    precip: precip != null ? r1(precip) : 0,
                    symbol,
                });
            }

            // Dagvindu 10-18
            if (hour >= 10 && hour <= 18 && wind != null && temp != null && cloud != null) {
                const d = b.d;
                d.windSum += wind;
                if (wind > d.windMax) d.windMax = wind;
                d.tempSum += temp;
                if (temp > d.tempMax) d.tempMax = temp;
                d.cloudSum += cloud;
                d.precipSum += (precip != null ? precip : 0);
                if (humid != null) { d.humidSum += humid; d.humidN += 1; }
                if (gust != null) {
                    d.gustSum += gust;
                    if (gust > d.gustMax) d.gustMax = gust;
                    d.gustN += 1;
                }
                if (dir != null) {
                    const rad = dir * Math.PI / 180;
                    d.dirSin += Math.sin(rad); d.dirCos += Math.cos(rad); d.dirN += 1;
                }
                if (symbol) d.symbols[symbol] = (d.symbols[symbol] || 0) + 1;
                d.n += 1;
            }

            // Kveldsvindu 19-22
            if (hour >= 19 && hour <= 22 && wind != null && temp != null && cloud != null) {
                const e = b.e;
                e.windSum   += wind;
                e.tempSum   += temp;
                e.cloudSum  += cloud;
                e.precipSum += (precip != null ? precip : 0);
                if (humid != null) { e.humidSum += humid; e.humidN += 1; }
                if (gust != null)  { e.gustSum  += gust;  e.gustN  += 1; }
                if (dir != null) {
                    const rad = dir * Math.PI / 180;
                    e.dirSin += Math.sin(rad); e.dirCos += Math.cos(rad); e.dirN += 1;
                }
                if (press != null) { e.pressSum += press; e.pressN += 1; }
                e.n += 1;
            }
        }

        // ── Kveldsvindu (uendret felt-form, + windDir) ─────────────────────
        const evening = {};
        for (const date in buckets) {
            const b = buckets[date], e = b.e;
            // Krev minst 1 måling. Dag 1-2 har typisk 4 (time-oppløsning),
            // dag 3+ har 0-1. Frontend markerer n < 3 som indikative.
            if (e.n < 1) continue;
            const pressEve = e.pressN > 0 ? e.pressSum / e.pressN : null;
            const pressAft = b.pAft.n > 0 ? b.pAft.sum / b.pAft.n : null;
            evening[date] = {
                wind:   r1(e.windSum / e.n),
                gust:   e.gustN > 0 ? r1(e.gustSum / e.gustN) : null,
                temp:   r1(e.tempSum / e.n),
                cloud:  Math.round(e.cloudSum / e.n),
                precip: r1(e.precipSum),
                humid:  e.humidN > 0 ? Math.round(e.humidSum / e.humidN) : null,
                windDir: circMean(e.dirSin, e.dirCos, e.dirN),
                pressure: pressEve != null ? r1(pressEve) : null,
                // Trend = kveld - ettermiddag. Stigende/stabilt = god indikator,
                // raskt fall = front på vei.
                pressureTrend: (pressEve != null && pressAft != null)
                    ? r1(pressEve - pressAft) : null,
                n: e.n,
            };
        }

        // ── Dagvindu ──────────────────────────────────────────────────────
        const day = {};
        for (const date in buckets) {
            const b = buckets[date], d = b.d;
            if (d.n < 1) continue;

            // Dominerende værsymbol i dagvinduet — det mest frekvente.
            let symbol = null, best = 0;
            for (const s in d.symbols) {
                if (d.symbols[s] > best) { best = d.symbols[s]; symbol = s; }
            }

            const pressMorn = b.pMorn.n > 0 ? b.pMorn.sum / b.pMorn.n : null;
            const pressAft  = b.pAft.n  > 0 ? b.pAft.sum  / b.pAft.n  : null;

            day[date] = {
                wind:    r1(d.windSum / d.n),
                windMax: d.windMax > -Infinity ? r1(d.windMax) : null,
                gust:    d.gustN > 0 ? r1(d.gustSum / d.gustN) : null,
                gustMax: d.gustMax > -Infinity ? r1(d.gustMax) : null,
                windDir: circMean(d.dirSin, d.dirCos, d.dirN),
                temp:    r1(d.tempSum / d.n),
                tempMax: d.tempMax > -Infinity ? r1(d.tempMax) : null,
                // Døgnets minimum, ikke dagvinduets — det er "ned mot X" i UI
                tempMin24: b.f.tempMin < Infinity ? r1(b.f.tempMin) : null,
                tempMax24: b.f.tempMax > -Infinity ? r1(b.f.tempMax) : null,
                cloud:   Math.round(d.cloudSum / d.n),
                precip:  r1(d.precipSum),
                precip24: r1(b.f.precipSum),
                humid:   d.humidN > 0 ? Math.round(d.humidSum / d.humidN) : null,
                pressure: pressAft != null ? r1(pressAft) : null,
                // Dagens trend = ettermiddag - morgen
                pressureTrend: (pressAft != null && pressMorn != null)
                    ? r1(pressAft - pressMorn) : null,
                symbol,
                n: d.n,
            };
        }

        // ── Timedata ──────────────────────────────────────────────────────
        // Sortert på klokkeslett. MET gir time-oppløsning ca. 2-3 døgn fram,
        // deretter 6-timers steg — arrayene blir da naturlig korte.
        const hourly = {};
        for (const date in buckets) {
            const hs = buckets[date].hours;
            if (!hs.length) continue;
            hs.sort((a, b) => a.h - b.h);
            hourly[date] = hs;
        }

        if (window === 'day')  return res.json(day);
        if (window === 'both') return res.json({ evening, day, hourly });
        res.json(evening);   // default — uendret for eksisterende kallere
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
}
