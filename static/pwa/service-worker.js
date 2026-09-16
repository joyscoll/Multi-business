const CACHE='real-mart-v2';
const CORE=['/','/shop','/supermarket','/static/css/app.css','/static/js/app.js','/static/js/pos.js','/static/pwa/manifest.webmanifest'];
const BLOCKED=['/api','/login','/logout','/otcOmc','/fr%2','/admin'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const u=new URL(e.request.url);
  if(u.origin!==location.origin||BLOCKED.some(x=>u.pathname.startsWith(x)))return;
  e.respondWith(caches.match(e.request).then(cached=>cached||fetch(e.request).then(res=>{if(res.ok&&['style','script','image','font'].includes(e.request.destination)){const clone=res.clone();caches.open(CACHE).then(c=>c.put(e.request,clone));}return res}).catch(()=>cached||new Response('Offline',{status:503}))));
});