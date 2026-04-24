// Vercel Edge Middleware — passordbeskyttelse DEAKTIVERT 2026-04-24 for offentlig lansering.
//
// Hele siden (forside + dashboard) er nå åpen for alle uten innlogging.
// Bakgrunn: Stunt/markedsføring for å fange interesse i klekkesesongen. Betalingsmur planlagt 2027.
//
// For å REAKTIVERE passord:
//   matcher: ['/dashboard.html', '/verify-stations.html'],
// og fjern early return i middleware-funksjonen.

export const config = {
    matcher: [],  // Tom matcher = middleware kjører aldri
};

export default function middleware(request) {
    return; // Pass through — auth er deaktivert
}
