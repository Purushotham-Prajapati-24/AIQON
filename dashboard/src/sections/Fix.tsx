import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, CloudLightning, Waves } from "lucide-react";
import { useState } from "react";
import { EASE, ErrorNote, Reveal, SectionHead, Skeleton, Ticker, TierBadge } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { day, delay, pct, port, route, signed, usd } from "../lib/format";
import { useStore } from "../lib/store";
import type { WhatIfParams } from "../lib/types";

const RHO: (number | null)[] = [null, 0.5, 0.6, 0.7, 0.8, 0.9];
const BASE: WhatIfParams = { rho: null, hub: false, customs: false, docs: false };

export function Fix() {
  const { selected } = useStore();
  return (
    <section id="fix" className="shell">
      <SectionHead
        id="fix"
        index="03"
        kicker="Fix"
        title={["Try a fix", <span className="text-fg-3">before you pay for it.</span>]}
        aside="Change one thing. See the new arrival, chance late and cost."
      />
      {/* Keyed by shipment: switching resets the fixes and never shows the last shipment's numbers. */}
      <WhatIf key={selected} />
      <Disruption />
    </section>
  );
}

function WhatIf() {
  const { world, selected, mode } = useStore();
  const [p, setP] = useState<WhatIfParams>(BASE);
  const now = useAsync(() => (world ? api.moment(selected, world.now) : null), [world?.now, selected]);
  const res = useAsync(() => api.whatIf(selected, p), [selected, p.rho, p.hub, p.customs, p.docs]);
  const base = useAsync(() => api.whatIf(selected, BASE), [selected]);

  const v = now.data?.ops;
  const active = v && v.status !== "DELIVERED";
  const r = res.data;
  const b = base.data;
  const changed = p.rho !== null || p.hub || p.customs || p.docs;
  // A fix only helps a stage that has not happened yet.
  const done = (e: string) => !!v?.timeline.find((t) => t.event === e)?.observed;
  const portDone = done("DISCHARGED");
  const hubDone = done("DEPART_TS");
  const customsDone = done("CUSTOMS_CLEARED");

  return (
    <div className="grid gap-12 border-t border-line pt-10 lg:grid-cols-12">
      <div className="lg:col-span-5">
        <p className="eyebrow">Shipment</p>
        <p className="mt-2 font-mono text-[1.1rem]">{selected}</p>
        <p className="mt-1 text-fg-2">{v ? route(v.lane_id) : "…"}</p>

        <fieldset className="mt-10 disabled:opacity-40" disabled={!active || portDone}>
          <legend className="text-[1.1rem] font-medium">
            How busy is {v ? port(v.shipment.dest) : "the arrival port"}?
            {portDone && <span className="ml-2 font-mono text-xs uppercase tracking-[0.14em] text-fg-3">already unloaded</span>}
          </legend>
          <div className="mt-4 flex flex-wrap gap-2">
            {RHO.map((x) => (
              <button key={String(x)} className="chip" aria-pressed={p.rho === x} onClick={() => setP({ ...p, rho: x })}>
                {x === null ? "As forecast" : `${Math.round(x * 100)}% full`}
              </button>
            ))}
          </div>
        </fieldset>

        <div className="mt-10 space-y-1 border-t border-line">
          {v?.shipment.hub && (
            <Toggle on={p.hub} set={(hub) => setP({ ...p, hub })} label={`Priority transfer at ${port(v.shipment.hub)}`} disabled={!active || hubDone} note={hubDone ? "already left" : undefined} />
          )}
          <Toggle on={p.customs} set={(customs) => setP({ ...p, customs })} label="Weekend customs clearance" disabled={!active || customsDone} note={customsDone ? "already cleared" : undefined} />
          <Toggle on={p.docs} set={(docs) => setP({ ...p, docs })} label="Customs papers filed early" disabled={!active || customsDone} note={customsDone ? "already cleared" : undefined} />
        </div>
        {changed && (
          <button onClick={() => setP(BASE)} className="-mx-2 mt-3 px-2 py-3 font-mono text-xs uppercase tracking-[0.16em] text-fg-3 underline-offset-4 hover:text-fg hover:underline">
            Reset
          </button>
        )}
      </div>

      <div className="lg:col-span-7">
        {now.error && <ErrorNote error={now.error} onRetry={now.retry} />}
        {r && b && active && (
          <p className="sr-only" aria-live="polite">
            {changed
              ? `With this fix: ${delay(r.d.p50)} versus plan, ${pct(Math.min(r.pl, 0.99))} chance late, delay cost ${usd(r.cost)}.`
              : `Now: ${delay(b.d.p50)} versus plan.`}
          </p>
        )}
        {!v ? (
          <Skeleton className="h-80 w-full" />
        ) : !active ? (
          <Empty text="This shipment is already delivered. Pick one still on the way." />
        ) : !r || !b ? (
          res.loading || base.loading ? (
            <Skeleton className="h-80 w-full" label="Computing the what-if" />
          ) : res.error || base.error ? (
            <ErrorNote error={(res.error ?? base.error)!} onRetry={() => (res.retry(), base.retry())} />
          ) : (
            <Empty
              text={
                mode === "live"
                  ? "No what-if is available for this combination."
                  : "This combination wasn't recorded. Start the API for live answers to any fix."
              }
            />
          )
        ) : (
          <div>
            <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-4">
              <Side label="Now" delayH={b.d.p50} eta={b.eta} />
              <ArrowRight className="mb-10 text-fg-3" size={28} />
              <Side label={changed ? "With the fix" : "Pick a fix"} delayH={r.d.p50} eta={r.eta} accent={changed} />
            </div>

            <div className="mt-10 grid grid-cols-3 border-y border-line">
              <Delta label="Time saved" value={-r.dd} format={(x) => (Math.abs(x) < 0.5 ? "0 h" : delay(x, { sign: false, short: true }))} good={r.dd < -0.5} />
              <Delta label="Chance late" value={r.pl * 100} format={(x) => `${Math.round(Math.min(99, x))}%`} note={changed ? `was ${pct(Math.min(b.pl, 0.99))}` : undefined} good={r.dpl < -0.01} border />
              <Delta label="Delay cost" value={r.cost} format={(x) => usd(x)} note={changed ? `${r.dc <= 0 ? "saves" : "adds"} ${usd(Math.abs(r.dc))}` : undefined} good={r.dc < -1} border />
            </div>
            <div className="mt-6 flex items-center gap-3">
              <TierBadge tier={r.tier} />
              <span className="text-fg-2" aria-live="polite">
                {changed
                  ? r.dd < -0.5
                    ? `Arrives ${delay(-r.dd, { sign: false })} sooner.`
                    : "No change to the arrival."
                  : "Toggle a fix to compare."}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Side({ label, delayH, eta, accent }: { label: string; delayH: number; eta: string; accent?: boolean }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <div className={`num mt-3 text-[clamp(3rem,calc(5.5*var(--cw)),5.25rem)] ${accent ? "text-fg" : "text-fg-2"}`}>
        <Ticker value={delayH / 24} format={(x) => signed(x, 1)} duration={0.7} />
        <span className="ml-1 text-[0.4em] uppercase">days</span>
      </div>
      <p className="mt-2 font-mono text-[0.85rem] text-fg-3">arrives {day(eta)}</p>
    </div>
  );
}

function Delta({
  label,
  value,
  format,
  note,
  good,
  border,
}: {
  label: string;
  value: number;
  format: (x: number) => string;
  note?: string;
  good?: boolean;
  border?: boolean;
}) {
  return (
    <div className={`py-6 ${border ? "border-l border-line pl-4 md:pl-6" : "pr-4"}`}>
      <p className="eyebrow">{label}</p>
      <div className={`num mt-3 text-[clamp(2rem,calc(3.4*var(--cw)),3rem)] ${good ? "text-ok" : ""}`}>
        <Ticker value={value} format={format} duration={0.7} />
      </div>
      {note && <p className="mt-1 font-mono text-[0.78rem] text-fg-3">{note}</p>}
    </div>
  );
}

function Toggle({ on, set, label, disabled, note }: { on: boolean; set: (v: boolean) => void; label: string; disabled?: boolean; note?: string }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={() => set(!on)}
      className="flex w-full items-center justify-between gap-4 border-b border-line py-4 text-left text-[1.05rem] transition-colors hover:text-fg disabled:opacity-40"
    >
      <span className={on ? "text-fg" : "text-fg-2"}>
        {label}
        {note && <span className="ml-2 font-mono text-xs uppercase tracking-[0.14em] text-fg-3">{note}</span>}
      </span>
      <span className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${on ? "bg-ok" : "bg-bg-3"}`}>
        <motion.span
          className="absolute top-1 size-4 rounded-full bg-fg"
          animate={{ left: on ? 24 : 4 }}
          transition={{ type: "spring", stiffness: 500, damping: 32 }}
        />
      </span>
    </button>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="grid h-full min-h-60 place-items-center border border-dashed border-line-2 p-8 text-center text-fg-2">{text}</div>;
}

function Disruption() {
  const { select } = useStore();
  // Run every preset up front so each button can say how many shipments it hits.
  const all = useAsync(async () => {
    const presets = await api.presets();
    const impacts = await Promise.all(presets.map((p) => api.scenario(p.scenario_id)));
    return presets.flatMap((p, k) => {
      const impact = impacts[k];
      return impact ? [{ p, impact }] : []; // a preset with no recorded impact is simply not offered
    });
  }, []);
  const [id, setId] = useState<string | null>(null);
  const items = all.data ?? [];
  const worst = items.reduce<(typeof items)[number] | null>((a, x) => (!a || x.impact.n_affected > a.impact.n_affected ? x : a), null);
  const pick = id ?? worst?.p.scenario_id ?? null;
  const x = items.find((i) => i.p.scenario_id === pick)?.impact;
  const presets = { data: items.map((i) => i.p), error: all.error };
  const hits = Object.fromEntries(items.map((i) => [i.p.scenario_id, i.impact.n_affected]));

  return (
    <div className="mt-28">
      <div className="grid gap-6 border-b border-line pb-6 md:grid-cols-12">
        <h3 className="font-display text-[2.4rem] font-extrabold uppercase leading-none md:col-span-5">If this happens</h3>
        <p className="text-[1.05rem] text-fg-2 md:col-span-7 md:text-right">Pick an event. See which shipments it hits.</p>
      </div>
      {presets.error && <ErrorNote error={presets.error} onRetry={all.retry} className="mt-6" />}
      <div className="grid gap-10 pt-8 lg:grid-cols-12">
        <ul className="space-y-2 lg:col-span-5">
          {(presets.data ?? []).map((p) => {
            const Icon = p.kind === "weather" ? CloudLightning : Waves;
            const on = p.scenario_id === pick;
            return (
              <li key={p.scenario_id}>
                <button
                  data-spotlight
                  onClick={() => setId(p.scenario_id)}
                  aria-pressed={on}
                  className={`flex w-full items-center gap-4 rounded-[4px] border px-4 py-4 text-left transition-colors ${
                    on ? "border-fg bg-fg text-bg" : "border-line text-fg-2 hover:border-fg-2 hover:text-fg"
                  }`}
                >
                  <Icon size={20} className="shrink-0" />
                  <span className="text-[1.02rem]">{p.label}</span>
                  <span className={`ml-auto shrink-0 font-mono text-[0.75rem] uppercase tracking-[0.12em] ${on ? "text-bg/70" : "text-fg-3"}`}>
                    {hits[p.scenario_id] ?? "–"} hit
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="lg:col-span-7">
          <p className="sr-only" aria-live="polite">
            {x ? `${x.scenario.label}: ${x.n_affected} of ${x.n_shipments} shipments hit, ${x.delta_late_count} more late.` : ""}
          </p>
          {!x ? (
            all.loading ? <Skeleton className="h-72 w-full" label="Running the disruption presets" /> : null
          ) : (
            <AnimatePresence mode="wait">
              <motion.div key={x.scenario.scenario_id} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.45, ease: EASE }}>
                <div className="grid grid-cols-3">
                  <Big v={x.n_affected} l={`of ${x.n_shipments} shipments hit`} />
                  <Big v={x.delta_late_count} l="more will be late" tone={x.delta_late_count > 0 ? "var(--late)" : undefined} prefix={x.delta_late_count > 0 ? "+" : ""} border />
                  <Big v={x.delta_cost_usd} l="added delay cost" money border />
                </div>
                {x.affected.length ? (
                  <ul className="mt-8 border-t border-line">
                    {x.affected.slice(0, 6).map((a) => (
                      <li key={a.shipment_id}>
                        <button
                          data-spotlight
                          onClick={(ev) => select(a.shipment_id, true, { label: "If this happens", section: "fix", el: ev.currentTarget })}
                          className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-line py-4 text-left transition-colors hover:bg-bg-2 sm:grid-cols-[8rem_minmax(0,1fr)_auto_auto]"
                        >
                          <span className="font-mono">{a.shipment_id}</span>
                          <span className="hidden truncate text-fg-2 sm:block">{route(a.lane_id)}</span>
                          <span className="font-mono text-late">{delay(a.delta_p50_h, { short: true })}</span>
                          <span className="col-span-2 flex items-center gap-2 sm:col-span-1">
                            <TierBadge tier={a.tier_before} size="sm" />
                            <ArrowRight size={12} className="text-fg-3" />
                            <TierBadge tier={a.tier_after} size="sm" />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-8 text-fg-2">No active shipment is on an affected route.</p>
                )}
              </motion.div>
            </AnimatePresence>
          )}
        </div>
      </div>
    </div>
  );
}

function Big({ v, l, tone, prefix = "", money, border }: { v: number; l: string; tone?: string; prefix?: string; money?: boolean; border?: boolean }) {
  return (
    <Reveal className={border ? "border-l border-line pl-4 md:pl-6" : ""} y={10}>
      <div className="num text-[clamp(2.6rem,calc(5*var(--cw)),4.5rem)]" style={tone ? { color: tone } : undefined}>
        <Ticker value={v} format={(x) => (money ? usd(x, true) : `${prefix}${Math.round(x)}`)} duration={0.8} />
      </div>
      <p className="mt-2 text-[0.95rem] text-fg-2">{l}</p>
    </Reveal>
  );
}

