// Service Worker for Windows Task Manager Remote
// Cache-busting & always fresh network responses
const CACHE_NAME = 'win-taskmgr-v10-nocache';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Always fetch directly from network without caching stale files
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
