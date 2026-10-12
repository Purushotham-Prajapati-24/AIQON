// Data access. Talks to the live CASCADE API when it is reachable; otherwise reads the recorded
// snapshot in /public/snapshot (real API responses captured by scripts/snapshot.mjs).
import type {
  Alerts,
  Checkpoint,
  Fleet,
  Insights,
  ModelInfo,
  Moment,
  Preset,
  ScenarioImpact,
  ShipmentView,
  Recommendation,
  WhatIfParams,
  WhatIfResult,
  World,
} from "./types";

export type Mode = "live" | "snapshot";

const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://127.0.0.1:8000";
const SNAP = `${import.meta.env.BASE_URL}snapshot`;

let mode: Promise<Mode> | null = null;

/** Probe once: live if /ready answers within 1.5 s, else the recorded snapshot. */
export function detectMode(): Promise<Mode> {
  if (mode) return mode;
  const forced = new URLSearchParams(location.search).get("source");
  if (forced === "snapshot" || forced === "live") return (mode = Promise.resolve(forced));
  mode = (async () => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1500);
      const r = await fetch(`${API}/ready`, { signal: ctrl.signal });
      clearTimeout(t);
      return r.ok ? "live" : "snapshot";
    } catch {
      return "snapshot";
    }
  })();
  return mode;
}

const cache = new Map<string, Promise<unknown>>();

function json<T>(url: string, init?: RequestInit): Promise<T> {
  const key = `${init?.method ?? "GET"} ${url} ${init?.body ?? ""}`;
  if (!cache.has(key)) {
    const p = fetch(url, init).then(async (r) => {
      if (!r.ok) throw new Error(`${r.status} ${url}`);
      return r.json();
    });
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return cache.get(key) as Promise<T>;
}

function live<T>(path: string, params: Record<string, string | number | boolean | null | undefined> = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined) q.set(k, String(v));
  return json<T>(`${API}${path}${q.size ? `?${q}` : ""}`);
}
const snap = <T,>(file: string) => json<T>(`${SNAP}/${file}`);

const isoShift = (now: string, days: number) =>
  new Date(new Date(now).getTime() + days * 864e5).toISOString().replace(/\.\d{3}Z$/, "Z");

export const api = {
  async world() {
    return (await detectMode()) === "live" ? live<World>("/v1/world") : snap<World>("world.json");
  },
  async model() {
    return (await detectMode()) === "live" ? live<ModelInfo>("/v1/model") : snap<ModelInfo>("model.json");
  },
  async insights() {
    return (await detectMode()) === "live" ? live<Insights>("/v1/insights") : snap<Insights>("insights.json");
  },

  /** Fleet + alerts, `days` before the world's "now" (0 = now, −21 … 0). */
  async fleet(days: number, now: string): Promise<{ fleet: Fleet; alerts: Alerts }> {
    if ((await detectMode()) === "snapshot") return snap(`fleet/${days}.json`);
    const as_of = days === 0 ? undefined : isoShift(now, days);
    const [fleet, alerts] = await Promise.all([
      live<Fleet>("/v1/fleet", { as_of }),
      live<Alerts>("/v1/alerts", { as_of, window_days: 7 }),
    ]);
    return { fleet, alerts };
  },

  /** The milestones a shipment can be replayed at: every reported milestone, then "now". */
  async stops(sid: string, now: string): Promise<{ checkpoints: Checkpoint[]; stops: string[] }> {
    const checkpoints =
      (await detectMode()) === "live"
        ? await live<Checkpoint[]>(`/v1/shipments/${sid}/checkpoints`)
        : (await snap<{ checkpoints: Checkpoint[] }>(`shipments/${sid}.json`)).checkpoints;
    return { checkpoints, stops: [...checkpoints.map((c) => c.as_of), now] };
  },

  async moment(sid: string, asOf: string): Promise<Moment> {
    if ((await detectMode()) === "snapshot") {
      const f = await snap<{ views: Record<string, Moment> }>(`shipments/${sid}.json`);
      const m = f.views[asOf];
      if (!m) throw new Error(`no recorded view for ${sid} at ${asOf}`);
      return m;
    }
    const [ops, customer, advise] = await Promise.all([
      live<ShipmentView>(`/v1/shipments/${sid}`, { as_of: asOf }),
      live<ShipmentView>(`/v1/shipments/${sid}`, { as_of: asOf, audience: "customer" }),
      live<{ recommendations: Recommendation[] }>(`/v1/shipments/${sid}/advise`, { as_of: asOf }),
    ]);
    return { ops, customer: customer.narrative, advise: advise.recommendations };
  },

  /** Counterfactual at "now". Snapshot mode serves the recorded grid (null = not recorded). */
  async whatIf(sid: string, p: WhatIfParams): Promise<WhatIfResult | null> {
    if ((await detectMode()) === "snapshot") {
      const f = await snap<{ whatif: Record<string, WhatIfResult> }>(`shipments/${sid}.json`);
      return f.whatif[`${p.rho ?? "-"}|${+p.hub}|${+p.customs}|${+p.docs}`] ?? null;
    }
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
    };
  },

  async presets() {
    return (await detectMode()) === "live"
      ? live<Preset[]>("/v1/scenarios/presets")
      : snap<Preset[]>("presets.json");
  },

  async scenario(id: string): Promise<ScenarioImpact> {
    if ((await detectMode()) === "snapshot")
      return (await snap<Record<string, ScenarioImpact>>("scenarios.json"))[id];
    return json<ScenarioImpact>(`${API}/v1/scenarios/impact`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ preset: id }),
    });
  },
};
