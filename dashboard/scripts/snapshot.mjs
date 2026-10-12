// Records real CASCADE API responses into public/snapshot/ so the dashboard can run without
// the Python service (static hosting, quick reviews). Every number shown in snapshot mode
// came from the model; nothing here is invented.
//
//   cascade serve            # or: python -m uvicorn cascade.serving.app:app --port 8000
//   npm run snapshot         # CASCADE_API_URL=http://127.0.0.1:8000 by default
import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

const API = process.env.CASCADE_API_URL ?? "http://127.0.0.1:8000";
const OUT = join(import.meta.dirname, "..", "public", "snapshot");
const DAYS = 21; // fleet replay window: now − 21 d … now
const RHO = [null, 0.5, 0.6, 0.7, 0.8, 0.9];

async function get(path, params = {}) {
  const q = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => [k, String(v)]),
  );
  const res = await fetch(`${API}${path}${q.size ? `?${q}` : ""}`);
  if (!res.ok) throw new Error(`${path} → ${res.status} ${await res.text()}`);
  return res.json();
}

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

const save = (name, data) => writeFile(join(OUT, name), JSON.stringify(data));
const iso = (d) => d.toISOString().replace(/\.\d{3}Z$/, "Z");

/** Compact what-if result: only what the What-if panel draws. */
const compact = (r) => ({
  d: r.scenario.delay_hours,
  pl: r.scenario.p_late,
  tier: r.scenario.risk_tier,
  cost: r.scenario.cost_usd.p50 ?? 0,
  eta: r.scenario.eta.p50,
  dd: r.delta_p50_h,
  dpl: r.delta_p_late,
  dc: r.delta_cost_usd,
});

async function main() {
  const ready = await get("/ready");
  console.log(`API ${API} ready · model v${ready.model_version}`);
  await rm(OUT, { recursive: true, force: true });
  await mkdir(join(OUT, "fleet"), { recursive: true });
  await mkdir(join(OUT, "shipments"), { recursive: true });

  const world = await get("/v1/world");
  const now = new Date(world.now);
  await save("world.json", world);
  await save("model.json", await get("/v1/model"));
  await save("insights.json", await get("/v1/insights"));
  await save("monitoring.json", await get("/v1/monitoring/accuracy"));
  await save("data-health.json", await get("/v1/data-health"));
  const presets = await get("/v1/scenarios/presets");
  await save("presets.json", presets);

  const impacts = {};
  for (const p of presets) impacts[p.scenario_id] = await post("/v1/scenarios/impact", { preset: p.scenario_id });
  await save("scenarios.json", impacts);

  for (let off = -DAYS; off <= 0; off++) {
    const asOf = off === 0 ? undefined : iso(new Date(now.getTime() + off * 864e5));
    const [fleet, alerts] = await Promise.all([
      get("/v1/fleet", { as_of: asOf }),
      get("/v1/alerts", { as_of: asOf, window_days: 7 }),
    ]);
    await save(`fleet/${off}.json`, { fleet, alerts });
  }
  console.log(`fleet replay: ${DAYS + 1} days`);

  const activeNow = new Set((await get("/v1/fleet")).active.map((r) => r.shipment_id));
  const list = await get("/v1/shipments");
  await save("shipments.json", list);

  for (const { shipment_id: sid } of list) {
    const checkpoints = await get(`/v1/shipments/${sid}/checkpoints`);
    const stops = [...checkpoints.map((c) => c.as_of), world.now];
    const views = {};
    for (const asOf of stops) {
      const [ops, customer, advise] = await Promise.all([
        get(`/v1/shipments/${sid}`, { as_of: asOf }),
        get(`/v1/shipments/${sid}`, { as_of: asOf, audience: "customer" }),
        get(`/v1/shipments/${sid}/advise`, { as_of: asOf }),
      ]);
      views[asOf] = { ops, customer: customer.narrative, advise: advise.recommendations };
    }
    const whatif = {};
    if (activeNow.has(sid)) {
      for (const rho of RHO)
        for (const hub of [false, true])
          for (const cw of [false, true])
            for (const docs of [false, true]) {
              const r = await get(`/v1/shipments/${sid}/whatif`, {
                dest_rho: rho,
                hub_priority: hub,
                customs_weekend: cw ? true : null,
                docs_complete: docs ? true : null,
              });
              whatif[`${rho ?? "-"}|${+hub}|${+cw}|${+docs}`] = compact(r);
            }
    }
    await save(`shipments/${sid}.json`, { checkpoints, views, whatif });
    process.stdout.write(".");
  }
  console.log(`\n${list.length} shipments written to ${OUT}`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
