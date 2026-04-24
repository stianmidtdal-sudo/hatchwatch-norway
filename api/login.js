// Vercel serverless function — validates password and sets auth cookie.
// Støtter `next=<path>` for å redirecte brukeren tilbake til ønsket destinasjon.

export default function handler(req, res) {
    if (req.method !== 'POST') {
        res.status(405).end();
        return;
    }

    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
        const params = new URLSearchParams(body);
        if (params.get('pw') === 'marginata!!!') {
            res.setHeader('Set-Cookie',
                'hw_auth=hw_ok; Path=/; HttpOnly; Max-Age=604800; SameSite=Strict'
            );
            // Send brukeren tilbake der de kom fra (hvis oppgitt og trygg — må starte med /)
            const next = params.get('next');
            const safeNext = (next && next.startsWith('/') && !next.startsWith('//')) ? next : '/';
            res.writeHead(302, { Location: safeNext });
        } else {
            // Bevar next ved feil slik at redirect-kjeden fungerer når de skriver riktig passord
            const next = params.get('next');
            const errUrl = next
                ? `/login.html?err=1&next=${encodeURIComponent(next)}`
                : '/login.html?err=1';
            res.writeHead(302, { Location: errUrl });
        }
        res.end();
    });
}
