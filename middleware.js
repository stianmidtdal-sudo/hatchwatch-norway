// Vercel Edge Middleware — cookie-based auth for hatchwatch.no
// Password-only login via /login.html + /api/login

export const config = {
    matcher: ['/((?!api/|login\\.html|_next/).*)'],
};

export default function middleware(request) {
    const cookie = request.cookies.get('hw_auth');
    if (cookie?.value === 'hw_ok') return; // authenticated

    const url = new URL(request.url);
    return Response.redirect(new URL('/login.html', url));
}
