const CACHE='real-mart-public-v4';
self.addEventListener('install',e=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==location.origin)return;if(u.pathname.startsWith('/otcOmc')||u.pathname.startsWith('/fr%2')||u.pathname.startsWith('/admin')||u.pathname.startsWith('/api'))return;e.respondWith(fetch(e.request).catch(()=>new Response('Shopping site unavailable offline',{status:503})))});
