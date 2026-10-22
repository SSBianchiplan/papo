// Service worker do Papo. Só guarda o casco do app (HTML, JS/CSS com hash, ícones).
// Nunca toca em /api, /auth, /config.json nem em nada de outra origem: dado e login vão sempre à rede.
const VERSION = "papo-v5";
const SHELL = ["/", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/favicon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/auth") || url.pathname === "/config.json") return;

  // Navegação: rede primeiro (inclui o retorno do login com ?code=), casco em cache só sem conexão.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req)
        .then((r) => {
          if (r.ok && !url.search) { const copy = r.clone(); void caches.open(VERSION).then((c) => c.put("/", copy)); }
          return r;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  // Arquivos com hash no nome são imutáveis: cache primeiro.
  if (url.pathname.startsWith("/assets/")) {
    e.respondWith(
      caches.match(req).then((hit) => hit ?? fetch(req).then((r) => {
        if (r.ok) { const copy = r.clone(); void caches.open(VERSION).then((c) => c.put(req, copy)); }
        return r;
      })),
    );
    return;
  }

  // Ícones e manifest: responde do cache e atualiza por trás.
  e.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req).then((r) => {
        if (r.ok) { const copy = r.clone(); void caches.open(VERSION).then((c) => c.put(req, copy)); }
        return r;
      });
      return hit ?? net;
    }),
  );
});
