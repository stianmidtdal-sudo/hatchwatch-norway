// Vercel Edge Middleware — cookie-basert auth for hatchwatch.no
// Forsiden (index.html, /) er åpen — alle kan se oversikten over lokasjoner.
// Kun dashboard.html og verify-stations.html krever passord.

export const config = {
    matcher: ['/dashboard.html', '/verify-stations.html'],
};

export default function middleware(request) {
    const cookieHeader = request.headers.get('cookie') || '';
    const authenticated = cookieHeader
        .split(';')
        .some(c => c.trim() === 'hw_auth=hw_ok');

    if (authenticated) return; // Alt OK — slipp gjennom

    const url = new URL(request.url);
    const loginUrl = new URL('/login.html', url);
    // Bevar destinasjonen slik at login kan sende brukeren tilbake etter innlogging
    loginUrl.searchParams.set('next', url.pathname + url.search);
    return Response.redirect(loginUrl);
}
