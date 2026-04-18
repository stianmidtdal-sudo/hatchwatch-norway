// Vercel Edge Middleware — cookie-based auth for hatchwatch.no

export const config = {
    matcher: ['/((?!api/|login.html|_next/).*)'],
};

export default function middleware(request) {
    const cookieHeader = request.headers.get('cookie') || '';
    const authenticated = cookieHeader
        .split(';')
        .some(c => c.trim() === 'hw_auth=hw_ok');

    if (authenticated) return; // pass through

    const url = new URL(request.url);
    return Response.redirect(new URL('/login.html', url));
}
