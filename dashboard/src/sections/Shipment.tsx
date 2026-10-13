import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, Copy, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CascadeChart } from "../components/CascadeChart";
import { Gauge } from "../components/Gauge";
import { ChartLegend, EASE, ErrorNote, SectionHead, Skeleton, Ticker, TierBadge } from "../components/ui";
import { Waterfall } from "../components/Waterfall";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { TIER, ago, checkpointLabel, day, delay, delayParts, groupName, pct, port, usd } from "../lib/format";
import { useStore } from "../lib/store";
import type { Moment, Recommendation } from "../lib/types";

export function Shipment() {
  const { world, selected, select, origin, goBack } = useStore();
  const list = useAsync(() => (world ? api.fleet(0, world.now) : null), [world?.now]);
  const data = useAsync(async () => {
    if (!world) return null;
    const { checkpoints, moments } = await api.replay(selected, world.now);
    return { sid: selected, labels: [...checkpoints.map((c) => checkpointLabel(c.label)), "Now"], moments };
  }, [world?.now, selected]);
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => setAt(null), [selected]);

  // While the next shipment loads, keep showing the previous one (dimmed) instead of a skeleton,
  // so picking from the list never makes the page jump.
  const d = data.data;
  // If the new one fails to load, show the error alone: not the old shipment, dimmed and busy forever.
  const failed = !!data.error && (!d || d.sid !== selected);
  const stale = !!d && d.sid !== selected && !failed;
  const idx = d ? Math.min(stale ? d.moments.length - 1 : (at ?? d.moments.length - 1), d.moments.length - 1) : 0;
  const m = d?.moments[idx];
  const shownId = failed ? selected : (d?.sid ?? selected);
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
          <span key={shownId}>{shownId}</span>,
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
              className="select mt-3 w-full appearance-none rounded-[4px] border border-line-2 bg-bg-2 px-4 py-3 font-mono text-[0.95rem] text-fg hover:border-fg-2"
            >
              {!options.some((o) => o.shipment_id === selected) && <option value={selected}>{selected}</option>}
              {options.map((o) => (
                <option key={o.shipment_id} value={o.shipment_id}>
                  {o.shipment_id} · {pct(Math.min(o.p_late, 0.99))} late
                </option>
              ))}
            </select>
          </div>
        }
      />

      {origin && (
        <button
          onClick={goBack}
          className="-mt-4 mb-6 inline-flex items-center gap-2 rounded-[4px] border border-line-2 px-3.5 py-2.5 font-mono text-[0.78rem] uppercase tracking-[0.14em] text-fg-2 transition-colors hover:border-fg hover:text-fg"
        >
          <ArrowLeft size={14} aria-hidden />
          Back to {origin.label}
        </button>
      )}
      {data.error && <ErrorNote error={data.error} onRetry={data.retry} className="mb-6" />}
      {!d || !m || failed ? (
        data.error ? null : <Skeleton className="h-[640px] w-full" label="Loading shipment" />
      ) : (
        <div aria-busy={stale} className={`transition-opacity duration-300 ${stale ? "pointer-events-none opacity-45" : ""}`}>
          <Detail key={d.sid} m={m} moments={d.moments} labels={d.labels} idx={idx} setAt={setAt} />
        </div>
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
  const chips = useRef<(HTMLButtonElement | null)[]>([]);
  const dq = v.data_quality;

  return (
    <div className="border-t border-line">
      {/* Time travel */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line py-5">
        <span className="eyebrow">Replay</span>
        <div
          className="flex flex-wrap gap-2"
          role="radiogroup"
          aria-label="Replay the shipment at a milestone"
          onKeyDown={(e) => {
            const to = { ArrowRight: idx + 1, ArrowDown: idx + 1, ArrowLeft: idx - 1, ArrowUp: idx - 1, Home: 0, End: moments.length - 1 }[e.key];
            if (to === undefined) return;
            e.preventDefault();
            const k = Math.max(0, Math.min(moments.length - 1, to));
            setAt(k);
            chips.current[k]?.focus();
          }}
        >
          {moments.map((x, k) => (
            <button
              key={k}
              ref={(el) => {
                chips.current[k] = el;
              }}
              role="radio"
              aria-checked={k === idx}
              tabIndex={k === idx ? 0 : -1}
              onClick={() => setAt(k)}
              className="chip"
            >
              {labels[k]}
              <span className="chip-count">{k === moments.length - 1 ? "today" : day(x.ops.as_of)}</span>
            </button>
          ))}
        </div>
        <span className="ml-auto flex flex-wrap items-center gap-3">
          <TierBadge tier={v.risk_tier} />
          {v.flags.missing_events.length > 0 && (
            <span className="font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3">
              {v.flags.missing_events.length} milestone{v.flags.missing_events.length > 1 ? "s" : ""} not reported
            </span>
          )}
          {dq?.last_milestone_age_h != null && !delivered && (
            <span className="font-mono text-[0.72rem] uppercase tracking-[0.14em] text-fg-3">
              last update {ago(dq.last_milestone_age_h)}
            </span>
          )}
        </span>
      </div>

      {/* The four numbers that matter */}
      <div className="grid grid-cols-2 border-b border-line lg:grid-cols-4">
        <Figure label={delivered ? "Final delay" : "Expected delay"}>
          <div className="flex items-baseline gap-2" style={{ color: v.delay_hours.p50 > 24 ? "var(--late)" : undefined }}>
            <span className="num text-[clamp(3.2rem,calc(5*var(--cw)),4.75rem)]">
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
              className="num text-[clamp(3.2rem,calc(5*var(--cw)),4.75rem)] uppercase"
            >
              {day(v.eta.p50)}
            </motion.div>
          </AnimatePresence>
          <p className="mt-2 font-mono text-[0.82rem] text-fg-3">
            {v.promise ? (
              <span title={v.delay_hours.p80 != null ? "The promise uses the calibrated P80: about 4 in 5 shipments arrive by it." : undefined}>
                promise to customer: {day(v.promise.promise_date)}
                {v.delay_hours.p80 != null && <span className="text-fg-3"> · P80</span>}
              </span>
            ) : (
              <>planned {day(v.planned_delivery)}</>
            )}
          </p>
        </Figure>
        <Figure label="Delay cost" className="border-l border-line max-lg:border-t">
          <div className="num text-[clamp(3.2rem,calc(5*var(--cw)),4.75rem)]">
            <Ticker value={v.cost_usd.p50 ?? 0} format={(x) => usd(x)} duration={0.8} />
          </div>
          <CostSplit v={v.cost_usd} />
        </Figure>
      </div>

      {/* Commitments: what was promised, what the carrier says now, what CASCADE expects */}
      {v.schedule && !delivered && <PlanStrip v={v} />}

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
            {v.explanation && (
              <p className="mt-3 text-[0.85rem] text-fg-3">
                Solid = observed so far · hatched = projected. {v.explanation.note}
              </p>
            )}
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

// 2 columns on phones, 4 from md: left rules and top rules per position (static class names).
const CELL = ["", "border-l pl-5", "max-md:border-t md:border-l md:pl-5", "border-l pl-5 max-md:border-t"];

function PlanStrip({ v }: { v: Moment["ops"] }) {
  const s = v.schedule!;
  const items = [
    { k: "Original commitment", d: s.original_planned_delivery, note: "lateness is measured against this" },
    {
      k: s.revisions_known ? `Carrier's current plan · ${s.revisions_known} revision${s.revisions_known > 1 ? "s" : ""}` : "Carrier's plan",
      d: s.current_plan_delivery,
      note: s.revisions_known ? `${delay(s.carrier_plan_delay_h, { short: true })} vs commitment` : "unchanged",
    },
    { k: "CASCADE expects (P50)", d: v.eta.p50, note: `${delay(s.delay_vs_current_plan_h, { short: true })} vs carrier's plan` },
    ...(v.promise ? [{ k: "Promise to customer", d: v.promise.promise_date, note: "calibrated P80" }] : []),
  ];
  return (
    <dl className="grid grid-cols-2 border-b border-line md:grid-cols-4" aria-label="Delivery dates compared">
      {items.map((it, k) => (
        <div key={it.k} className={`border-line py-5 ${CELL[k]}`}>
          <dt className="eyebrow">{it.k}</dt>
          <dd className="mt-2 font-display text-[1.7rem] font-bold uppercase leading-none">{day(it.d)}</dd>
          <dd className="mt-1 font-mono text-[0.78rem] text-fg-3">{it.note}</dd>
        </div>
      ))}
    </dl>
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
  const { role } = useStore();
  const [who, setWho] = useState<"ops" | "customer">(role?.audience ?? "customer");
  const [copied, setCopied] = useState<"ok" | "failed" | null>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(copyTimer.current), []);
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
      setCopied("ok");
    } catch {
      setCopied("failed");
    }
    clearTimeout(copyTimer.current); // a second copy restarts the timer instead of being cut short
    copyTimer.current = setTimeout(() => setCopied(null), 2400);
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
        <button onClick={copy} className="chip ml-auto">
          {copied === "ok" ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />}
          {copied === "ok" ? "Copied" : "Copy"}
          <span className="sr-only"> explanation</span>
        </button>
      </div>
      <p className="mt-2 min-h-5 text-right font-mono text-[0.78rem] text-fg-3" aria-live="polite">
        {copied === "failed" ? "Couldn't reach the clipboard. Select the text below to copy it." : copied === "ok" ? <span className="sr-only">Explanation copied</span> : null}
      </p>
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
                  <p className="mb-2 flex items-center gap-1.5 font-mono text-[0.75rem] uppercase tracking-[0.16em] text-ok">
                    <Sparkles size={13} /> Best move
                  </p>
                )}
                <p className="text-[1.15rem] font-medium">{r.label}</p>
                <p className="mt-1 text-[0.95rem] text-fg-3">{r.feasible_reason}</p>
              </div>
              <div className="text-right">
                {r.hours_saved >= 0.5 ? (
                  <p className="num text-[2.2rem] text-ok" aria-label={`Arrives ${delay(r.hours_saved, { sign: false })} sooner`}>
                    −{delay(r.hours_saved, { sign: false, short: true })}
                  </p>
                ) : (
                  <p className="num text-[2.2rem] text-fg-3" aria-label={r.hours_saved <= -0.5 ? `Adds ${delay(-r.hours_saved, { sign: false })}` : "No time saved"}>
                    {r.hours_saved <= -0.5 ? `+${delay(-r.hours_saved, { sign: false, short: true })}` : "0 h"}
                  </p>
                )}
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

