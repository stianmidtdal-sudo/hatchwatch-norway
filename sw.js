// HatchWatch Service Worker
// Versjon-bumpes ved hver deploy som introduserer ny app-shell.
// Cache-strategi:
//   - HTML/JS/CSS/ikoner: cache-first med network-update i bakgrunnen (stale-while-revalidate)
//   - API-kall (Frost/NVE/MET): network-first med fallback til cache (siste kjente data offline)
//   - Eksterne biblioteker (cdn.jsdelivr, cdnjs, chart.js osv.): cache-first med lang levetid
//
// Innført 2026-05-19.

const CACHE_VERSION = 'hw-v34';  // v34: kartlag-knapp med Turkart (Kartverket topo + Turrutebasen, vann som prikker); avstandsmåling med høydeprofil; dashboardet med graddag-isgang og ny marginata-regel; vannvarsler og Mine vann for alle vann; vann.html (egen side per vann: isgang, klekking fra været ved vannet, «funnet her»-merking); kildesetningen ut av elvekortet; merket øverst til venstre og forklaringen nederst til venstre på forsiden (Stian) (2026-10-14).  // v33: ekte kart på forsiden (MapLibre + PMTiles), Tørrflue | Laksefiske, elv.html, Mine elver; Range-forespørsler slippes forbi (2026-10-14).  // v32: «window» ut av de engelske tekstene (Stian) (2026-10-09).  // v31: generell modell som kandidatrad i kalibreringspanelet (?calib=1) (2026-10-09).  // v30: engelsk på forside, varsler, om + felles språkvalg hw-lang.js (2026-10-08).  // v29: satellitt-isgang 2026 for ti lokasjoner (2026-10-06).  // v24: personvern.html + lenke fra om.html (2026-10-01).  // v19: historikk opp, emojier ut.  // v18: varsler i iPhone-appen (APNs via Capacitor) i dashboard + varsler (2026-10-01)
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const API_CACHE = `${CACHE_VERSION}-api`;
const VENDOR_CACHE = `${CACHE_VERSION}-vendor`;

const SHELL_URLS = [
    '/',
    '/index.html',
    '/dashboard.html',
    '/elv.html',
    '/vann.html',
    '/artikler.html',
    '/om.html',
    '/personvern.html',
    '/varsler.html',
    '/observasjon.html',
    '/manifest.json',
    '/hw.css',
    '/hw-shell.js',
    '/hw-lang.js',
    '/logos/fly-mask.png',
    '/logos/icon-192.png',
    '/logos/icon-512.png',
    '/logos/apple-touch-icon-180.png',
    '/logos/favicon-64.png',
    '/logos/favicon-32.png',
    '/logos/logo-inverted-192.png',
    '/logos/logo-inverted-256.png',
    '/logos/logo-inverted-512.png',
    '/logos/logo-inverted-180.png',
    '/logos/logo-inverted-144.png',
    '/logos/logo-inverted-64.png',
    '/logos/logo-inverted-32.png',
    '/logos/logo-inverted-16.png',
    '/favicon.ico',
];

// API-mønstre som bør network-first cache-fallback
const API_HOST_PATTERNS = [
    /^https:\/\/frost\.met\.no\//,
    /^https:\/\/api\.met\.no\//,
    /^https:\/\/hydapi\.nve\.no\//,
    /\/api\//,  // egne Vercel functions
];

// Eksterne CDN-libs — cache-first, sjelden endring
const VENDOR_HOST_PATTERNS = [
    /^https:\/\/cdn\.jsdelivr\.net\//,
    /^https:\/\/cdnjs\.cloudflare\.com\//,
    /^https:\/\/unpkg\.com\//,
];

// ─── INSTALL: prefetch app-shell ────────────────────────────────────
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(SHELL_CACHE).then((cache) => {
            // addAll feiler hvis EN ressurs feiler — bruk individuelle puts for robusthet
            return Promise.all(
                SHELL_URLS.map((url) =>
                    fetch(url, { cache: 'no-cache' })
                        .then((r) => { if (r.ok) cache.put(url, r); })
                        .catch(() => { /* ignore — kan prefetches under deploy */ })
                )
            );
        }).then(() => self.skipWaiting())
    );
});

// ─── ACTIVATE: rydd opp gamle cache-versjoner ───────────────────────
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((k) => !k.startsWith(CACHE_VERSION))
                    .map((k) => caches.delete(k))
            )
        ).then(() => self.clients.claim())
    );
});

// ─── FETCH: dispatch til riktig strategi ────────────────────────────
self.addEventListener('fetch', (event) => {
    const req = event.request;
    // Bare håndtere GET; alt annet (POST til Tally osv) går rett til nett
    if (req.method !== 'GET') return;
    const url = req.url;

    // Kartfliser (PMTiles) hentes med Range-forespørsler og svarer 206. Cache API
    // tar ikke delsvar, så de må gå rett til nett (ellers knekker kartet). 2026-10-14.
    if (req.headers.has('range') || /\.pmtiles(\?|$)/.test(url)) return;

    // API → network-first
    if (API_HOST_PATTERNS.some((re) => re.test(url))) {
        event.respondWith(networkFirst(req, API_CACHE));
        return;
    }

    // Vendor libs → cache-first
    if (VENDOR_HOST_PATTERNS.some((re) => re.test(url))) {
        event.respondWith(cacheFirst(req, VENDOR_CACHE));
        return;
    }

    // App-shell (samme origin) → stale-while-revalidate
    if (new URL(url).origin === self.location.origin) {
        event.respondWith(staleWhileRevalidate(req, SHELL_CACHE));
        return;
    }
    // Andre cross-origin → bare fetch
});

// ─── STRATEGIER ─────────────────────────────────────────────────────

async function networkFirst(req, cacheName) {
    const cache = await caches.open(cacheName);
    try {
        const fresh = await fetch(req);
        if (fresh.ok) cache.put(req, fresh.clone());
        return fresh;
    } catch (err) {
        const cached = await cache.match(req);
        if (cached) return cached;
        // Ingen cache, ingen nett — la nettleseren håndtere feilen
        throw err;
    }
}

async function cacheFirst(req, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(req);
    if (cached) return cached;
    const fresh = await fetch(req);
    if (fresh.ok) cache.put(req, fresh.clone());
    return fresh;
}

async function staleWhileRevalidate(req, cacheName) {
    const cache = await caches.open(cacheName);
    const cached = await cache.match(req);
    const fetchPromise = fetch(req).then((fresh) => {
        if (fresh.ok) cache.put(req, fresh.clone());
        return fresh;
    }).catch(() => cached);  // ved offline: returner cache hvis vi har
    return cached || fetchPromise;
}

// ─── PUSH-VARSLER ───────────────────────────────────────────────────
// "Ordentlig varsel": vi setter eksplisitt vibrate-mønster, silent:false,
// renotify:true (samme tag re-alerter brukeren ved oppdatering), og lar
// requireInteraction være true på desktop slik at notification ikke
// forsvinner etter 5s. På iOS overstyrer systemet noe av dette, men
// kombinasjonen 'urgency: high'-header (server-side) + disse options
// gir maks sjanse for et hørbart varsel.
self.addEventListener('push', (event) => {
    if (!event.data) return;
    let data = {};
    try { data = event.data.json(); } catch (e) { data = { title: 'HatchWatch', body: event.data.text() }; }
    const title = data.title || 'HatchWatch';
    const options = {
        body: data.body || '',
        icon: '/logos/icon-192.png',
        badge: '/logos/favicon-64.png',
        data: data.url ? { url: data.url } : undefined,
        tag: data.tag || 'hatchwatch',
        // Hørbart + vibrerende varsel
        renotify: true,
        silent: false,
        vibrate: [200, 100, 200, 100, 300],
        requireInteraction: true,
        timestamp: Date.now(),
    };
    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const url = event.notification.data?.url || '/';
    event.waitUntil(
        self.clients.matchAll({ type: 'window' }).then((clients) => {
            for (const c of clients) {
                if (c.url.includes(url) && 'focus' in c) return c.focus();
            }
            return self.clients.openWindow(url);
        })
    );
});
