import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * Preload the fonts used above the fold (display headline + body text) so the first paint uses
 * the real typefaces instead of swapping from a fallback. Asset names are hashed at build time,
 * so the links are injected from the final bundle.
 */
function preloadCriticalFonts(): Plugin {
  const critical = [
    /big-shoulders-display-latin-800-normal-[\w-]+\.woff2$/,
    /big-shoulders-display-latin-700-normal-[\w-]+\.woff2$/,
    /ibm-plex-sans-latin-400-normal-[\w-]+\.woff2$/,
  ];
  let base = "/";
  return {
    name: "preload-critical-fonts",
    apply: "build",
    configResolved(c) {
      base = c.base; // honour --base / BASE_URL like the rest of the app
    },
    transformIndexHtml(html, ctx) {
      const files = Object.keys(ctx.bundle ?? {}).filter((f) => critical.some((re) => re.test(f)));
      return {
        html,
        tags: files.map((f) => ({
          tag: "link",
          attrs: { rel: "preload", as: "font", type: "font/woff2", href: `${base}${f}`, crossorigin: "" },
          injectTo: "head-prepend" as const,
        })),
      };
    },
  };
}

/**
 * Social crawlers ignore relative image URLs. When the public address is known
 * (VITE_SITE_URL=https://cascade.example.com), make og:image absolute and add og:url + canonical.
 */
function absoluteSocialUrls(site: string | undefined): Plugin {
  return {
    name: "absolute-social-urls",
    transformIndexHtml(html) {
      if (!site) return html;
      const base = site.replace(/\/+$/, "");
      return {
        html: html.replace('content="/og.png"', `content="${base}/og.png"`),
        tags: [
          { tag: "meta", attrs: { property: "og:url", content: `${base}/` }, injectTo: "head" },
          { tag: "link", attrs: { rel: "canonical", href: `${base}/` }, injectTo: "head" },
        ],
      };
    },
  };
}

// /api is proxied to the CASCADE API so the dashboard and API share an origin (first-party
// session cookie, no CORS). Point CASCADE_API_TARGET elsewhere if the API runs on another port.
const target = process.env.CASCADE_API_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  // xfwd: the API sees the browser's address (X-Forwarded-For), so the sign-in throttle is per client.
  "/api": { target, changeOrigin: true, xfwd: true, rewrite: (p: string) => p.replace(/^\/api/, "") },
};

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  return {
    plugins: [react(), tailwindcss(), preloadCriticalFonts(), absoluteSocialUrls(env.VITE_SITE_URL)],
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
  };
});
