// Data access. Talks to the live CASCADE API when it is reachable; otherwise reads the recorded
// snapshot in /public/snapshot (real API responses captured by scripts/snapshot.mjs).
//
// Resilience contract:
// - the source is probed once at start-up (live if /ready answers within 1.5 s);
// - if the live API stops answering mid-session (network error, timeout or 5xx), the app
//   switches to the recorded run for the rest of the session and tells subscribers, so the badge,
//   the footer and every section update instead of failing one request at a time;
// - client errors (4xx) are real errors and are surfaced, never masked by the fallback.
import type {
  Alerts,
  Checkpoint,
  Drift,
  Fleet,
  Insights,
  ModelInfo,
  Moment,
  Preset,
  Recommendation,
  ScenarioImpact,
  ShipmentView,
  WhatIfParams,
  WhatIfResult,
  World,
} from "./types";

export type Mode = "live" | "snapshot";

// Same-origin by default: Vite (dev and preview) and the Docker nginx proxy /api to the CASCADE API,
// so the session cookie is first-party. VITE_API_URL points elsewhere (that origin must then be
// listed in the API's CASCADE_CORS_ORIGINS).
export const API = (import.meta.env.VITE_API_URL as string | undefined) ?? `${import.meta.env.BASE_URL}api`.replace(/\/{2,}/g, "/");
const SNAP = `${import.meta.env.BASE_URL}snapshot`;
/** Static deployments can pin the source: VITE_SOURCE=snapshot never probes a local API. */
const PINNED = import.meta.env.VITE_SOURCE as Mode | undefined;
const LIVE_TIMEOUT_MS = 20_000;

let mode: Promise<Mode> | null = null;
let degradedReason: string | null = null;
const listeners = new Set<(m: Mode) => void>();

/** Subscribe to source changes (e.g. live → recorded when the API goes away). */
export function onModeChange(fn: (m: Mode) => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}
/** Why the app fell back to the recorded run, if it did. */
export const fallbackReason = () => degradedReason;

/**
 * Probe once: live if /ready answers. Nothing listening (network error / 1.5 s timeout) means the
 * recorded run straight away; a server that is up but still warming (503) gets up to ~8 s.
 */
export function detectMode(): Promise<Mode> {
  if (mode) return mode;
  const forced = new URLSearchParams(location.search).get("source") ?? PINNED;
  if (forced === "snapshot" || forced === "live") return (mode = Promise.resolve(forced));
  mode = (async () => {
    const until = Date.now() + 8000;
    for (;;) {
      try {
        const r = await fetch(`${API}/ready`, { signal: AbortSignal.timeout(1500), credentials: "include" });
        if (r.ok) return "live";
        if (r.status !== 503 || Date.now() > until) return "snapshot";
      } catch {
        return "snapshot";
      }
      await new Promise((res) => setTimeout(res, 700));
    }
  })();
  return mode;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    url: string,
  ) {
    super(status >= 500 ? `The model service returned an error (${status}).` : `Request failed (${status}) · ${url}`);
  }
}

const isOutage = (e: unknown) =>
  e instanceof TypeError || // network failure / CORS
  (e instanceof DOMException && (e.name === "TimeoutError" || e.name === "AbortError")) ||
  (e instanceof HttpError && e.status >= 500);

function degrade(reason: string) {
  if (degradedReason) return;
  degradedReason = reason;
  mode = Promise.resolve("snapshot");
  for (const k of [...cache.keys()]) if (k.includes(API)) cache.delete(k);
  listeners.forEach((fn) => fn("snapshot"));
}

const cache = new Map<string, Promise<unknown>>();

function json<T>(url: string, init?: RequestInit): Promise<T> {
  const key = `${init?.method ?? "GET"} ${url} ${init?.body ?? ""}`;
  if (!cache.has(key)) {
    const live = url.startsWith(API);
    const signal = init?.signal ?? (live ? AbortSignal.timeout(LIVE_TIMEOUT_MS) : undefined);
    const p = fetch(url, { credentials: "include", ...init, signal }).then(async (r) => {
      if (r.status === 401) {
        // The session ended (expired, signed out elsewhere, or the API now requires sign-in).
        cache.clear();
        dispatchEvent(new CustomEvent("cascade:signed-out", { detail: "expired" }));
      }
      if (!r.ok) throw new HttpError(r.status, url);
      return r.json();
    });
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return cache.get(key) as Promise<T>;
}

/** Run the live loader; on an outage, switch the session to the recorded run and use it. */
async function pick<T>(liveFn: () => Promise<T>, snapFn: () => Promise<T>): Promise<T> {
  if ((await detectMode()) === "snapshot") return snapFn();
  try {
    return await liveFn();
  } catch (e) {
    if (!isOutage(e)) throw e;
    degrade(e instanceof HttpError ? e.message : "The live model stopped answering.");
    return snapFn();
  }
}

function live<T>(path: string, params: Record<string, string | number | boolean | null | undefined> = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined) q.set(k, String(v));
  return json<T>(`${API}${path}${q.size ? `?${q}` : ""}`);
}
const snap = <T,>(file: string) => json<T>(`${SNAP}/${file}`);

const isoShift = (now: string, days: number) =>
  new Date(new Date(now).getTime() + days * 864e5).toISOString().replace(/\.\d{3}Z$/, "Z");

async function snapMoment(sid: string, asOf: string): Promise<Moment> {
  const f = await snap<{ views: Record<string, Moment> }>(`shipments/${sid}.json`);
  const m = f.views[asOf];
  if (!m) throw new Error(`No recorded view for ${sid} at this moment.`);
  return m;
}

export const api = {
  world: () => pick(() => live<World>("/v1/world"), () => snap<World>("world.json")),
  model: () => pick(() => live<ModelInfo>("/v1/model"), () => snap<ModelInfo>("model.json")),
  insights: () => pick(() => live<Insights>("/v1/insights"), () => snap<Insights>("insights.json")),
  /** Live inputs vs the training distribution (PSI). Null when the recording predates it. */
  drift: () =>
    pick<Drift | null>(
      () => live<Drift>("/v1/monitoring/drift"),
      async () => {
        try {
          return await snap<Drift>("drift.json");
        } catch {
          return null;
        }
      },
    ),

  /** Fleet + alerts, `days` before the world's "now" (0 = now, −21 … 0). */
  fleet(days: number, now: string): Promise<{ fleet: Fleet; alerts: Alerts }> {
    const as_of = days === 0 ? undefined : isoShift(now, days);
    return pick(
      async () => {
        const [fleet, alerts] = await Promise.all([
          live<Fleet>("/v1/fleet", { as_of }),
          live<Alerts>("/v1/alerts", { as_of, window_days: 7 }),
        ]);
        return { fleet, alerts };
      },
      () => snap(`fleet/${days}.json`),
    );
  },

  /** The milestones a shipment can be replayed at: every reported milestone, then "now". */
  async stops(sid: string, now: string): Promise<{ checkpoints: Checkpoint[]; stops: string[] }> {
    const checkpoints = await pick(
      () => live<Checkpoint[]>(`/v1/shipments/${sid}/checkpoints`),
      async () => (await snap<{ checkpoints: Checkpoint[] }>(`shipments/${sid}.json`)).checkpoints,
    );
    return { checkpoints, stops: [...checkpoints.map((c) => c.as_of), now] };
  },

  /** A full replay (every milestone + now). Shared by the hero and the shipment section. */
  async replay(sid: string, now: string) {
    const { checkpoints, stops } = await api.stops(sid, now);
    const moments = await Promise.all(stops.map((s) => api.moment(sid, s)));
    return { checkpoints, stops, moments };
  },

  moment(sid: string, asOf: string): Promise<Moment> {
    return pick(
      async () => {
        const [ops, customer, advise] = await Promise.all([
          live<ShipmentView>(`/v1/shipments/${sid}`, { as_of: asOf }),
          live<ShipmentView>(`/v1/shipments/${sid}`, { as_of: asOf, audience: "customer" }),
          live<{ recommendations: Recommendation[] }>(`/v1/shipments/${sid}/advise`, { as_of: asOf }),
        ]);
        return { ops, customer: customer.narrative, advise: advise.recommendations };
      },
      () => snapMoment(sid, asOf),
    );
  },

  /** Counterfactual at "now". Snapshot mode serves the recorded grid (null = not recorded). */
  whatIf(sid: string, p: WhatIfParams): Promise<WhatIfResult | null> {
    return pick(
      async () => {
        const r = await live<{
          scenario: ShipmentView;
          delta_p50_h: number;
          delta_p_late: number;
          delta_cost_usd: number;
        }>(`/v1/shipments/${sid}/whatif`, {
          dest_rho: p.rho,
          hub_priority: p.hub,
          customs_weekend: p.customs ? true : null,
          docs_complete: p.docs ? true : null,
        });
        return {
          d: r.scenario.delay_hours,
          pl: r.scenario.p_late,
          tier: r.scenario.risk_tier,
          cost: r.scenario.cost_usd.p50 ?? 0,
          eta: r.scenario.eta.p50,
          dd: r.delta_p50_h,
          dpl: r.delta_p_late,
          dc: r.delta_cost_usd,
        } satisfies WhatIfResult;
      },
      async () => {
        const f = await snap<{ whatif: Record<string, WhatIfResult> }>(`shipments/${sid}.json`);
        return f.whatif[`${p.rho ?? "-"}|${+p.hub}|${+p.customs}|${+p.docs}`] ?? null;
      },
    );
  },

  presets: () => pick(() => live<Preset[]>("/v1/scenarios/presets"), () => snap<Preset[]>("presets.json")),

  /** Impact of one disruption preset on the active fleet (null if not recorded). */
  scenario(id: string): Promise<ScenarioImpact | null> {
    return pick(
      () =>
        json<ScenarioImpact>(`${API}/v1/scenarios/impact`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ preset: id }),
        }),
      async () => (await snap<Record<string, ScenarioImpact>>("scenarios.json"))[id] ?? null,
    );
  },
};
