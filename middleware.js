// Vercel Edge Middleware — passordbeskyttelse DEAKTIVERT 2026-04-24 for offentlig lansering.
//
// Hele siden (forside + dashboard) er nå åpen for alle uten innlogging.
// Bakgrunn: Stunt/markedsføring for å fange interesse i klekkesesongen. Betalingsmur planlagt 2027.
//
// For å REAKTIVERE passord, legg tilbake `config` og auth-logikk:
//
//   export const config = {
//       matcher: ['/dashboard.html', '/verify-stations.html'],
//   };
//   export default function middleware(request) {
//       const cookieHeader = request.headers.get('cookie') || '';
//       const authenticated = cookieHeader.split(';').some(c => c.trim() === 'hw_auth=hw_ok');
//       if (authenticated) return;
//       const url = new URL(request.url);
//       const loginUrl = new URL('/login.html', url);
//       loginUrl.searchParams.set('next', url.pathname + url.search);
//       return Response.redirect(loginUrl);
//   }

export default function middleware() {
    // No-op pass-through — ingen autorisasjon aktiv
    return;
}
