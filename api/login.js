// Vercel serverless function — validates password and sets auth cookie

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
            res.writeHead(302, { Location: '/' });
        } else {
            res.writeHead(302, { Location: '/login.html?err=1' });
        }
        res.end();
    });
}
