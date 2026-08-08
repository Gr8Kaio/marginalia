/* Marginalia · service worker
   La app tiene que abrir sin señal: en un aula el wifi no existe.
   App shell cache-first; todo lo demás (Supabase) va directo a la red. */
const CACHE = "marginalia-v1.0.1";
const SHELL = ["./", "./index.html"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const { request } = e;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Nada de Supabase ni de otros orígenes se cachea: los datos tienen que ser frescos.
  if (url.origin !== self.location.origin) return;

  // Navegación: red primero para tomar versiones nuevas, cache si no hay señal.
  if (request.mode === "navigate"){
    e.respondWith(
      fetch(request)
        .then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put("./index.html", copy)); return r; })
        .catch(() => caches.match("./index.html"))
    );
    return;
  }

  e.respondWith(
    caches.match(request).then(hit => hit || fetch(request).then(r => {
      if (r.ok && r.type === "basic"){
        const copy = r.clone();
        caches.open(CACHE).then(c => c.put(request, copy));
      }
      return r;
    }))
  );
});
