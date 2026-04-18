// Vercel Edge Middleware — HTTP Basic Auth for hatchwatch.no
// Protects all HTML pages. API routes (/api/*) are excluded via matcher.
// Username: anything  |  Password: marginata

export const config = {
    matcher: ['/((?!api/).*)'],
};

export default function middleware(request) {
    const basicAuth = request.headers.get('authorization');

    if (basicAuth) {
        const authValue = basicAuth.split(' ')[1];
        try {
            const [, pwd] = atob(authValue).split(':');
            if (pwd === 'marginata') return; // pass through
        } catch (e) {}
    }

    return new Response('Authentication required', {
        status: 401,
        headers: { 'WWW-Authenticate': 'Basic realm="Hatch Watch"' },
    });
}
