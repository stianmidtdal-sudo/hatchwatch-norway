// Vercel Edge Middleware — passordbeskyttelse DEAKTIVERT 2026-04-24 for offentlig lansering.
//
// Hele siden (forside + dashboard) er åpen for alle uten innlogging.
// Middleware er konfigurert på dashboard.html, men funksjonen gjør ingenting (no-op).
// Dette er nødvendig fordi helt manglende matcher forvirret Vercel build.
//
// For å REAKTIVERE passord, erstatt funksjonskroppen med:
//
//   const cookieHeader = request.headers.get('cookie') || '';
//   const authenticated = cookieHeader.split(';').some(c => c.trim() === 'hw_auth=hw_ok');
//   if (authenticated) return;
//   const url = new URL(request.url);
//   const loginUrl = new URL('/login.html', url);
//   loginUrl.searchParams.set('next', url.pathname + url.search);
//   return Response.redirect(loginUrl);

export const config = {
    matcher: ['/dashboard.html', '/verify-stations.html'],
};

export default function middleware(request) {
    // No-op pass-through — ingen auth-sjekk, alt slippes gjennom fritt.
    return;
}
