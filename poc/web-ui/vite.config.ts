/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Bundle versionné, servi tel quel par FastAPI sous /static/dist/ : le POC s'installe sans Node.
// Noms de fichiers fixes (pas d'empreinte) pour que le dépôt ne change qu'avec le contenu.
export default defineConfig({
  plugins: [react()],
  base: "/static/dist/",
  build: {
    outDir: "../src/diagagent/web/static/dist",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    rollupOptions: {
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
  server: {
    // npm run dev : l'API et l'ancienne interface viennent du serveur Python (diagagent serve).
    proxy: {
      "/api": "http://127.0.0.1:8080",
      "/login": "http://127.0.0.1:8080",
      "/static/app": "http://127.0.0.1:8080",
    },
  },
  test: { environment: "jsdom" },
});
