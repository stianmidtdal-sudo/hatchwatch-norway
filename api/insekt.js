// Vercel serverless function — insektgjenkjenner (2026-10-17, Stian «bygg»).
//
//   POST /api/insekt   body: { bilde: <base64 JPEG/PNG/WebP>, type: 'image/jpeg', kontekst: { dato, vann, moh, avst, lang } }
//   → 200 { svar: {...}, versjon }   svar følger skjemaet i lib/insekt_instruks.js
//
// Bildet sendes til Claude (Anthropic) for vurdering og lagres IKKE her: ingen logging av bildet,
// ingen lagring i Redis. Nøkkelen ligger bare i Vercel (ANTHROPIC_API_KEY) og vises aldri i svar.
// Kostnad ~27 øre per bilde (Opus 5.5, målt i tools/insekt/RESULTAT.md), dekket av Max-kreditten.
//
// Vern mot at kreditten tømmes:
//   - per IP: 4 bilder i minuttet og 40 i døgnet (lib/fartsgrense.js, i minnet per instans)
//   - samlet: DAGSTAK bilder per døgn for hele appen (Redis-teller insekt:dag:<dato>)
//   - i Anthropic-konsollen: månedlig utgiftstak, og kreditten stopper av seg selv når den er brukt.

import Anthropic from '@anthropic-ai/sdk';
import { redis } from '../lib/redis.js';
import { forMange } from '../lib/fartsgrense.js';
import { INSTRUKS, kontekstTekst } from '../lib/insekt_instruks.js';

const DAGSTAK = 300;
const TYPER = ['image/jpeg', 'image/png', 'image/webp'];
const MAKS_BASE64 = 3500000;          // ~2,6 MB bilde; nettsiden sender ~0,3 MB (skalert til 1280 px)

function klipp(v, n) { return v == null ? null : String(v).trim().slice(0, n); }

function osloDato() {
    return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Oslo' }).format(new Date());
}

export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 'no-store');
    if (req.method === 'OPTIONS') {
        res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
        return res.status(204).end();
    }
    if (req.method !== 'POST') return res.status(405).json({ error: 'Bruk POST.' });
    if (forMange(req, res, 'insekt', 4, 60)) return;
    if (forMange(req, res, 'insekt-dogn', 40, 86400)) return;

    if (!process.env.ANTHROPIC_API_KEY) {
        return res.status(503).json({ error: 'ikke_satt_opp' });
    }

    const body = req.body || {};
    let bilde = typeof body.bilde === 'string' ? body.bilde : '';
    const m = bilde.match(/^data:(image\/[a-z]+);base64,/);
    let type = typeof body.type === 'string' ? body.type : (m ? m[1] : 'image/jpeg');
    if (m) bilde = bilde.slice(m[0].length);
    if (!bilde || bilde.length > MAKS_BASE64 || !/^[A-Za-z0-9+/=]+$/.test(bilde.slice(0, 200))) {
        return res.status(400).json({ error: 'ugyldig_bilde' });
    }
    if (!TYPER.includes(type)) type = 'image/jpeg';

    const k = body.kontekst || {};
    const kontekst = {
        lang: k.lang === 'en' ? 'en' : 'no',
        dato: klipp(k.dato, 20),
        vann: klipp(k.vann, 80),
        moh: Number.isFinite(+k.moh) && k.moh !== null && k.moh !== '' ? Math.round(+k.moh) : null,
        avst: Number.isFinite(+k.avst) && k.avst !== null && k.avst !== '' ? Math.round(+k.avst) : null,
        land: klipp(k.land, 40),
    };

    // Felles døgntak for hele appen (teller før kallet, så et angrep ikke kan løpe forbi)
    try {
        const r = redis(), nokkel = 'insekt:dag:' + osloDato();
        const n = await r.incr(nokkel);
        if (n === 1) await r.expire(nokkel, 2 * 86400);
        if (n > DAGSTAK) return res.status(429).json({ error: 'dagstak' });
    } catch (e) {
        console.error('insekt: redis-teller feilet', e && e.message);   // tellerfeil skal ikke stoppe gjenkjenningen
    }

    const client = new Anthropic();
    try {
        const svar = await client.beta.messages.create({
            model: INSTRUKS.modell,
            max_tokens: 4000,
            betas: ['server-side-fallback-2026-07-01'],
            fallbacks: 'default',
            output_config: { effort: 'medium', format: { type: 'json_schema', schema: INSTRUKS.skjema } },
            system: INSTRUKS.system,
            messages: [{
                role: 'user',
                content: [
                    { type: 'image', source: { type: 'base64', media_type: type, data: bilde } },
                    { type: 'text', text: kontekstTekst(kontekst) },
                ],
            }],
        });
        if (svar.stop_reason === 'refusal') return res.status(200).json({ svar: null, grunn: 'avslatt', versjon: INSTRUKS.versjon });
        const tekst = (svar.content || []).find((b) => b.type === 'text');
        if (!tekst) return res.status(502).json({ error: 'tomt_svar' });
        return res.status(200).json({ svar: JSON.parse(tekst.text), versjon: INSTRUKS.versjon });
    } catch (err) {
        // Aldri send feilteksten fra Anthropic videre ordrett; bare en kort kode brukeren kan forstå.
        const status = err && err.status;
        const melding = String((err && err.message) || '').toLowerCase();
        console.error('insekt: Anthropic-feil', status || '', err && err.constructor && err.constructor.name);
        if (melding.includes('credit balance')) return res.status(503).json({ error: 'kvote_brukt' });
        if (err instanceof Anthropic.RateLimitError) return res.status(503).json({ error: 'opptatt' });
        if (err instanceof Anthropic.BadRequestError) return res.status(400).json({ error: 'ugyldig_bilde' });
        if (err instanceof Anthropic.APIConnectionError) return res.status(503).json({ error: 'opptatt' });
        return res.status(502).json({ error: 'feil' });
    }
}
