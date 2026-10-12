import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// /api is proxied to the CASCADE API so the dashboard and API share an origin (first-party
// session cookie, no CORS). Point CASCADE_API_TARGET elsewhere if the API runs on another port.
const target = process.env.CASCADE_API_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, "") },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
});
