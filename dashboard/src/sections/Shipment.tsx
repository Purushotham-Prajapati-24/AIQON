import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, Copy, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { CascadeChart } from "../components/CascadeChart";
import { Gauge } from "../components/Gauge";
import { ErrorNote, SectionHead, Skeleton, Ticker, TierBadge } from "../components/ui";
import { Waterfall } from "../components/Waterfall";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { TIER, checkpointLabel, day, delay, delayParts, groupName, pct, port, usd } from "../lib/format";
import { useStore } from "../lib/store";
import type { Moment, Recommendation } from "../lib/types";
import { ChartLegend } from "./Hero";

const EASE = [0.16, 1, 0.3, 1] as const;

export function Shipment() {
  const { world, selected, select } = useStore();
  const list = useAsync(() => (world ? api.fleet(0, world.now) : null), [world?.now]);
  const data = useAsync(async () => {
    if (!world) return null;
    const { checkpoints, stops } = await api.stops(selected, world.now);
    const moments = await Promise.all(stops.map((s) => api.moment(selected, s)));
    return { sid: selected, labels: [...checkpoints.map((c) => checkpointLabel(c.label)), "Now"], moments };
  }, [world?.now, selected]);
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => setAt(null), [selected]);

  const d = data.data?.sid === selected ? data.data : undefined;
  const idx = d ? (at ?? d.moments.length - 1) : 0;
  const m = d?.moments[idx];
  const options = useMemo(
    () => [...(list.data?.fleet.active ?? [])].sort((a, b) => b.p_late - a.p_late),
    [list.data],
  );

  return (
    <section id="shipment" className="shell">
      <SectionHead
        id="shipment"
        index="02"
        kicker="Shipment"
        title={[
          <span key={selected}>{selected}</span>,
          <span className="text-fg-3">
            {m ? `${port(m.ops.shipment.origin)} → ${port(m.ops.shipment.dest)}` : "…"}
          </span>,
        ]}
        aside={
          <div>
            <label htmlFor="pick" className="eyebrow block">
              Open shipment
            </label>
            <select
              id="pick"
              value={selected}
              onChange={(e) => select(e.target.value)}
              className="mt-3 w-full appearance-none rounded-[4px] border border-line-2 bg-bg-2 px-4 py-3 font-mono text-[0.95rem] text-fg hover:border-fg-2"
            >
              {!options.some((o) => o.shipment_id === selected) && <option value={selected}>{selected}</option>}
              {options.map((o) => (
                <option key={o.shipment_id} value={o.shipment_id}>
                  {o.shipment_id} · {TIER[o.risk_tier].label} · {pct(Math.min(o.p_late, 0.99))}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {data.error && <ErrorNote error={data.error} />}
      {!d || !m ? (
        <Skeleton className="h-[640px] w-full" />
      ) : (
        <Detail key={selected} m={m} moments={d.moments} labels={d.labels} idx={idx} setAt={setAt} />
      )}
    </section>
  );
}

function Detail({
  m,
  moments,
  labels,
  idx,
  setAt,
}: {
  m: Moment;
  moments: Moment[];
  labels: string[];
  idx: number;
  setAt: (i: number) => void;
}) {
  const v = m.ops;
  const delivered = v.status === "DELIVERED";
  const parts = delayParts(delivered ? (v.actual_total_delay_h ?? v.delay_hours.p50) : v.delay_hours.p50);
  const yMax = Math.max(...moments.map((x) => x.ops.delay_hours.p90));
  const tier = TIER[v.risk_tier];

  return (
    <div className="border-t border-line">
      {/* Time travel */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line py-5">
        <span className="eyebrow">Replay</span>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Milestones">
          {moments.map((x, k) => (
            <button
              key={k}
              role="tab"
              aria-selected={k === idx}
              aria-pressed={k === idx}
              onClick={() => setAt(k)}
              className="chip"
            >
              {labels[k]}
              <span className="opacity-60">{k === moments.length - 1 ? "today" : day(x.ops.as_of)}</span>
            </button>
          ))}
        </div>
        <span className="ml-auto flex items-center gap-3">
          <TierBadge tier={v.risk_tier} />
          {v.flags.missing_events.length > 0 && (
            <span className="font-mono text-[0.72rem] uppercase tracking-[0.14em] text-fg-3">
              {v.flags.missing_events.length} milestone{v.flags.missing_events.length > 1 ? "s" : ""} not reported
            </span>
          )}
        </span>
      </div>

      {/* The four numbers that matter */}
      <div className="grid grid-cols-2 border-b border-line lg:grid-cols-4">
        <Figure label={delivered ? "Final delay" : "Expected delay"}>
          <div className="flex items-baseline gap-2" style={{ color: v.delay_hours.p50 > 24 ? "var(--late)" : undefined }}>
            <span className="num text-[clamp(3.2rem,5vw,4.75rem)]">
              {parts.sign}
              <Ticker value={+parts.v} format={(x) => (parts.u === "days" ? x.toFixed(1) : x.toFixed(0))} duration={0.8} />
            </span>
            <span className="font-display text-xl font-bold uppercase">{parts.u}</span>
          </div>
          {!delivered && (
            <p className="mt-2 font-mono text-[0.82rem] text-fg-3">
              likely {delay(v.delay_hours.p10, { short: true })} to {delay(v.delay_hours.p90, { short: true })}
            </p>
          )}
        </Figure>
        <Figure label="Chance late" className="border-l border-line">
          <div className="relative w-fit">
            <Gauge value={v.p_late} color={tier.color} size={150} />
            <span className="num absolute inset-x-0 bottom-0 text-center text-[2.6rem]">
              <Ticker value={Math.min(99, v.p_late * 100)} format={(x) => `${Math.round(x)}%`} duration={0.8} />
            </span>
          </div>
          <p className="mt-2 font-mono text-[0.82rem] text-fg-3">more than 24 h late</p>
        </Figure>
        <Figure label="Arrives" className="border-line max-lg:border-t lg:border-l">
          <AnimatePresence mode="wait">
            <motion.div
              key={v.eta.p50}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.35, ease: EASE }}
              className="num text-[clamp(3.2rem,5vw,4.75rem)] uppercase"
            >
              {day(v.eta.p50)}
            </motion.div>
          </AnimatePresence>
          <p className="mt-2 font-mono text-[0.82rem] text-fg-3">
            {v.promise ? <>promise to customer: {day(v.promise.promise_date)}</> : <>planned {day(v.planned_delivery)}</>}
          </p>
        </Figure>
        <Figure label="Delay cost" className="border-l border-line max-lg:border-t">
          <div className="num text-[clamp(3.2rem,5vw,4.75rem)]">
            <Ticker value={v.cost_usd.p50 ?? 0} format={(x) => usd(x)} duration={0.8} />
          </div>
          <CostSplit v={v.cost_usd} />
        </Figure>
      </div>

      {/* Journey */}
      <div className="pt-4">
        <ChartLegend />
        <CascadeChart view={v} ghosts={moments.slice(0, idx).map((x) => x.ops)} yMax={yMax} height={400} />
      </div>

      {/* Why + what to do */}
      <div className="mt-14 grid gap-14 lg:grid-cols-12">
        <div className="lg:col-span-6">
          <h3 className="font-display text-[2.4rem] font-extrabold uppercase leading-none">Why</h3>
          <Narrative m={m} />
          <div className="mt-8">
            <Waterfall items={v.waterfall} />
          </div>
        </div>
        <div className="lg:col-span-6">
          <h3 className="font-display text-[2.4rem] font-extrabold uppercase leading-none">What to do</h3>
          <Actions recs={m.advise} pLate={v.p_late} />
        </div>
      </div>
    </div>
  );
}

function Figure({ label, children, className = "" }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`px-0 py-8 lg:px-8 lg:first:pl-0 ${className} max-lg:[&:nth-child(even)]:pl-5`}>
      <p className="eyebrow mb-4">{label}</p>
      {children}
    </div>
  );
}

function CostSplit({ v }: { v: Moment["ops"]["cost_usd"] }) {
  const parts = [
    { k: "Missed slot", v: v.p50_missed_appointment ?? 0 },
    { k: "Stock waiting", v: v.p50_inventory_carry ?? 0 },
    { k: "Port storage", v: (v.p50_demurrage ?? 0) + (v.p50_detention ?? 0) },
  ].filter((p) => p.v > 0);
  const total = parts.reduce((a, p) => a + p.v, 0) || 1;
  const shade = ["var(--fg)", "var(--fg-2)", "var(--fg-3)"];
  if (!parts.length) return <p className="mt-2 font-mono text-[0.82rem] text-fg-3">no extra cost expected</p>;
  return (
    <div className="mt-3">
      <div className="flex h-1.5 w-full gap-[2px] overflow-hidden rounded-full">
        {parts.map((p, k) => (
          <motion.span key={p.k} className="h-full" style={{ background: shade[k] }} initial={{ width: 0 }} animate={{ width: `${(p.v / total) * 100}%` }} transition={{ duration: 0.9, ease: EASE }} />
        ))}
      </div>
      <ul className="mt-2 space-y-0.5 font-mono text-[0.75rem] text-fg-3">
        {parts.map((p, k) => (
          <li key={p.k} className="flex items-center gap-2">
            <span className="size-1.5 rounded-full" style={{ background: shade[k] }} />
            {p.k} <span className="ml-auto text-fg-2">{usd(p.v)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Narrative({ m }: { m: Moment }) {
  const [who, setWho] = useState<"ops" | "customer">("customer");
  const [copied, setCopied] = useState(false);
  const v = m.ops;
  const main = v.drivers[0];
  const action = v.narrative.match(/Suggested action: ([^.]+\.)/)?.[1];
  const planner = main
    ? `${groupName(main.group)}: ${main.phrase} (${delay(main.contribution_h, { short: true })}).${action ? ` ${action}` : ""}`
    : v.narrative;
  const text = who === "customer" ? m.customer : planner;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked */
    }
  };
  return (
    <div className="mt-6">
      <div className="flex items-center gap-2" role="group" aria-label="Explain for">
        <button className="chip" aria-pressed={who === "customer"} onClick={() => setWho("customer")}>
          For the customer
        </button>
        <button className="chip" aria-pressed={who === "ops"} onClick={() => setWho("ops")}>
          For the planner
        </button>
        <button onClick={copy} className="chip ml-auto" aria-label="Copy explanation">
          {copied ? <Check size={14} /> : <Copy size={14} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <AnimatePresence mode="wait">
        <motion.blockquote
          key={who + v.as_of}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.35, ease: EASE }}
          className="mt-5 text-[1.45rem] leading-snug text-fg"
        >
          “{text}”
        </motion.blockquote>
      </AnimatePresence>
    </div>
  );
}

function Actions({ recs, pLate }: { recs: Recommendation[]; pLate: number }) {
  if (!recs.length)
    return (
      <div className="mt-6 flex items-center gap-3 border-y border-line py-10 text-fg-2">
        <Check size={18} className="text-ok" /> Nothing worth doing right now.
      </div>
    );
  const best = recs.reduce((a, r) => (r.net_value_usd > a.net_value_usd ? r : a), recs[0]);
  return (
    <ol className="mt-6 border-t border-line">
      {recs.map((r, k) => {
        const top = r === best && r.net_value_usd > 0;
        return (
          <motion.li
            key={r.action_id}
            initial={{ opacity: 0, x: 16 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, ease: EASE, delay: k * 0.08 }}
            className={`relative border-b border-line py-6 ${top ? "pl-5" : ""}`}
          >
            {top && <span className="absolute inset-y-6 left-0 w-[3px] rounded-full bg-ok" aria-hidden />}
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                {top && (
                  <p className="mb-2 flex items-center gap-1.5 font-mono text-[0.72rem] uppercase tracking-[0.16em] text-ok">
                    <Sparkles size={13} /> Best move
                  </p>
                )}
                <p className="text-[1.15rem] font-medium">{r.label}</p>
                <p className="mt-1 text-[0.95rem] text-fg-3">{r.feasible_reason}</p>
              </div>
              <div className="text-right">
                <p className="num text-[2.2rem] text-ok">−{delay(r.hours_saved, { sign: false, short: true })}</p>
                <p className={`font-mono text-[0.8rem] ${r.net_value_usd >= 0 ? "text-fg-2" : "text-fg-3"}`}>
                  {r.net_value_usd >= 0 ? "saves" : "costs"} {usd(Math.abs(r.net_value_usd))} net
                </p>
              </div>
            </div>
            <div className="mt-4 flex items-center gap-3 font-mono text-[0.85rem]">
              <span className="text-fg-3">Chance late</span>
              <span>{pct(Math.min(pLate, 0.99))}</span>
              <ArrowRight size={14} className="text-fg-3" />
              <span className="text-ok">{pct(r.p_late_after)}</span>
              <span className="ml-auto text-fg-3">
                costs {usd(r.action_cost_usd)} · avoids {usd(r.usd_saved)}
              </span>
            </div>
          </motion.li>
        );
      })}
    </ol>
  );
}

