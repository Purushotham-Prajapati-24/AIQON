import { AnimatePresence, motion } from "motion/react";
import { AlertOctagon, ArrowUpRight, CalendarClock, ChevronDown, Link2Off, TrendingUp, VolumeX } from "lucide-react";
import { useMemo, useState } from "react";
import { EASE, ErrorNote, SectionHead, Skeleton, Ticker } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { ago } from "../lib/format";
import { useStore } from "../lib/store";
import type { Alert } from "../lib/types";

/** A model probability as a whole percent, never shown as certain (0% or 100%). */
const pctOf = (p: number) => Math.min(99, Math.max(1, Math.round(p * 100)));

/** Alert rules in plain words. */
function explain(a: Alert): { title: string; detail: string; icon: typeof AlertOctagon } {
  // Only the API's own sentence is parsed; any narrative appended after it is ignored.
  const head = a.message.split(/(?<=\.)\s/)[0];
  const n = head.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
  const pl = a.new_p_late != null ? pctOf(a.new_p_late) : null;
  switch (a.rule) {
    case "TIER_ESCALATION_LATE":
      return { title: "Now late", detail: pl != null ? `${pl}% chance of arriving more than a day late.` : "Expected more than a day late.", icon: AlertOctagon };
    case "TIER_ESCALATION_AT_RISK":
      return { title: "Now at risk", detail: pl != null ? `${pl}% chance of arriving more than a day late.` : "Could slip past the delivery window.", icon: AlertOctagon };
    case "MISSED_CONNECTION_LIKELY":
      return { title: "May miss its connection", detail: n.length ? `${pctOf(n[0] / 100)}% chance of missing the next vessel at the hub.` : "High chance of missing the next vessel at the hub.", icon: Link2Off };
    case "P_LATE_JUMP":
      return {
        title: "Chance late jumped",
        detail:
          a.previous_p_late != null && a.new_p_late != null
            ? `${pctOf(a.previous_p_late)}% → ${pctOf(a.new_p_late)}%`
            : n.length >= 2
              ? `${pctOf(n[0] / 100)}% → ${pctOf(n[1] / 100)}%`
              : head,
        icon: TrendingUp,
      };
    case "PROMISE_MOVED": {
      const d = n[0] ?? 0;
      return { title: "Customer date moved", detail: `${Math.abs(d)} day${Math.abs(d) === 1 ? "" : "s"} ${d > 0 ? "later" : "earlier"}.`, icon: CalendarClock };
    }
    case "SILENT_SHIPMENT":
      return {
        title: "Gone quiet",
        detail: n.length >= 2 ? `No update for ${Math.round(n[0] / 24)} days (usually ${Math.max(1, Math.round(n[1] / 24))}).` : head,
        icon: VolumeX,
      };
    default:
      return { title: a.rule.replace(/_/g, " ").toLowerCase(), detail: a.message, icon: AlertOctagon };
  }
}

const SEV = {
  critical: { label: "Urgent", color: "var(--late)" },
  warn: { label: "Watch", color: "var(--risk)" },
  info: { label: "FYI", color: "var(--fg-3)" },
} as const;

export function Alerts() {
  const { world, days, select } = useStore();
  const data = useAsync(() => (world ? api.fleet(days, world.now) : null), [world?.now, days]);
  const [sev, setSev] = useState<"all" | "critical" | "warn">("all");
  const [all, setAll] = useState(false);
  const ready = !!data.data;
  const alerts = data.data?.alerts.alerts ?? [];
  const view = useMemo(() => alerts.filter((a) => sev === "all" || a.severity === sev), [alerts, sev]);
  const urgent = alerts.filter((a) => a.severity === "critical").length;

  return (
    <section id="alerts" className="shell">
      <SectionHead
        id="alerts"
        index="04"
        kicker="Alerts"
        title={
          ready
            ? [
                <>
                  <span className="text-late">
                    <Ticker value={urgent} />
                  </span>{" "}
                  urgent
                </>,
                <span className="text-fg-3">
                  of <Ticker value={alerts.length} /> this week.
                </span>,
              ]
            : ["Alerts,", <span className="text-fg-3">loading…</span>]
        }
        aside="Raised the moment a forecast changes, so nobody has to keep checking."
      />

      <div className="flex flex-wrap gap-2 border-t border-line pt-6">
        {(["all", "critical", "warn"] as const).map((k) => (
          <button key={k} className="chip" aria-pressed={sev === k} onClick={() => setSev(k)}>
            {k === "all" ? "All" : SEV[k].label}
            <span className="chip-count">{k === "all" ? alerts.length : alerts.filter((a) => a.severity === k).length}</span>
          </button>
        ))}
      </div>

      {data.error && !ready ? (
        <ErrorNote error={data.error} onRetry={data.retry} className="mt-6" />
      ) : !ready ? (
        <Skeleton className="mt-6 h-96 w-full" label="Loading alerts" />
      ) : !view.length ? (
        <p className="py-16 text-center text-fg-2">All quiet{sev === "all" ? "" : ` at this level. ${alerts.length} alert${alerts.length === 1 ? "" : "s"} in total`}.</p>
      ) : (
        <ol className="mt-6 grid gap-x-10 md:grid-cols-2">
          <AnimatePresence initial={false}>
            {(all ? view : view.slice(0, 12)).map((a, k) => {
              const e = explain(a);
              const Icon = e.icon;
              return (
                <motion.li
                  key={a.alert_id}
                  layout
                  initial={{ opacity: 0, y: 14 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.5, ease: EASE, delay: (k % 6) * 0.04 }}
                >
                  <button
                    data-spotlight
                    onClick={(ev) => select(a.shipment_id, true, { label: "Alerts", section: "alerts", el: ev.currentTarget })}
                    className="group grid w-full grid-cols-[2.25rem_minmax(0,1fr)_auto] items-start gap-4 border-b border-line py-5 text-left transition-colors hover:bg-bg-2"
                  >
                    <span className="mt-0.5 grid size-9 place-items-center rounded-full" style={{ color: SEV[a.severity].color, background: `color-mix(in oklab, ${SEV[a.severity].color} 14%, transparent)` }}>
                      <Icon size={17} aria-hidden />
                    </span>
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-baseline gap-x-3">
                        <span className="text-[1.1rem] font-medium">{e.title}</span>
                        <span className="font-mono text-[0.85rem] text-fg-3">{a.shipment_id}</span>
                      </span>
                      <span className="mt-1 block text-fg-2">{e.detail}</span>
                      {a.recommended_next_step && (
                        <span className="mt-1.5 block text-[0.9rem] text-fg-3">
                          <span className="font-mono text-[0.72rem] uppercase tracking-[0.14em]">Next · </span>
                          {a.recommended_next_step}
                        </span>
                      )}
                    </span>
                    <span className="flex flex-col items-end gap-1.5 font-mono text-[0.78rem] text-fg-3">
                      <span className="uppercase tracking-[0.14em]" style={{ color: a.severity === "info" ? undefined : `var(--${a.severity === "critical" ? "late" : "risk"}-ink)` }}>
                        {SEV[a.severity].label}
                      </span>
                      <span className="flex items-center gap-2">
                      {ago(a.age_h)}
                      <ArrowUpRight size={15} aria-hidden className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-late" />
                      </span>
                    </span>
                  </button>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
      {view.length > 12 && (
        <button
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mx-auto mt-5 flex items-center gap-2 px-4 py-3.5 font-mono text-xs uppercase tracking-[0.18em] text-fg-2 hover:text-fg"
        >
          {all ? "Show the latest 12" : `Show all ${view.length}`}
          <ChevronDown size={14} aria-hidden className={`transition-transform ${all ? "rotate-180" : ""}`} />
        </button>
      )}
    </section>
  );
}
