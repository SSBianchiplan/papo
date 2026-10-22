import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } },
  },
  preview: {
    proxy: { "/api": { target: "http://127.0.0.1:8000", ws: true } },
  },
  // assetsInlineLimit 0: fontes pequenas virariam data: URI, que a CSP (font-src 'self') bloqueia
  build: { sourcemap: false, chunkSizeWarningLimit: 700, assetsInlineLimit: 0 },
});
