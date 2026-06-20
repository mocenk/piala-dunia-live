// Minimal service worker for PWA installability
const CACHE_NAME = 'piala-dunia-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Network-first for HTML, cache fallback
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
  }
  // Don't intercept stream requests (CORS issues)
  if (event.request.url.includes('mflixott.com')) return;
});