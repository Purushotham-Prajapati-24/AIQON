import { AnimatePresence, motion } from "motion/react";
import { AlertOctagon, ArrowUpRight, CalendarClock, Link2Off, TrendingUp, VolumeX } from "lucide-react";
import { useMemo, useState } from "react";
import { SectionHead, Skeleton, Ticker } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { ago } from "../lib/format";
import { useStore } from "../lib/store";
import type { Alert } from "../lib/types";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Alert rules in plain words. */
function explain(a: Alert): { title: string; detail: string; icon: typeof AlertOctagon } {
  // Only the API's own sentence is parsed; any narrative appended after it is ignored.
  const head = a.message.split(/(?<=\.)\s/)[0];
  const n = head.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? [];
  const pct = a.new_p_late != null ? Math.round(a.new_p_late * 100) : null;
  switch (a.rule) {
    case "TIER_ESCALATION_LATE":
      return { title: "Now late", detail: pct != null ? `${pct}% chance of arriving more than a day late.` : "Expected more than a day late.", icon: AlertOctagon };
    case "TIER_ESCALATION_AT_RISK":
      return { title: "Now at risk", detail: pct != null ? `${pct}% chance of arriving more than a day late.` : "Could slip past the delivery window.", icon: AlertOctagon };
    case "MISSED_CONNECTION_LIKELY":
      return { title: "May miss its connection", detail: `${n[0] ?? "High"}% chance of missing the next vessel at the hub.`, icon: Link2Off };
    case "P_LATE_JUMP":
      return {
        title: "Chance late jumped",
        detail:
          a.previous_p_late != null && a.new_p_late != null
            ? `${Math.round(a.previous_p_late * 100)}% → ${Math.round(a.new_p_late * 100)}%`
            : n.length >= 2
              ? `${n[0]}% → ${n[1]}%`
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
  const alerts = data.data?.alerts.alerts ?? [];
  const view = useMemo(() => alerts.filter((a) => sev === "all" || a.severity === sev), [alerts, sev]);
  const urgent = alerts.filter((a) => a.severity === "critical").length;

  return (
    <section id="alerts" className="shell">
      <SectionHead
        id="alerts"
        index="04"
        kicker="Alerts"
        title={[
          <>
            <span className="text-late">
              <Ticker value={urgent} />
            </span>{" "}
            urgent
          </>,
          <span className="text-fg-3">
            of <Ticker value={alerts.length} /> this week.
          </span>,
        ]}
        aside="Raised the moment a forecast changes, so nobody has to keep checking."
      />

      <div className="flex flex-wrap gap-2 border-t border-line pt-6">
        {(["all", "critical", "warn"] as const).map((k) => (
          <button key={k} className="chip" aria-pressed={sev === k} onClick={() => setSev(k)}>
            {k === "all" ? "All" : SEV[k].label}
            <span className="opacity-60">{k === "all" ? alerts.length : alerts.filter((a) => a.severity === k).length}</span>
          </button>
        ))}
      </div>

      {data.loading && !alerts.length ? (
        <Skeleton className="mt-6 h-96 w-full" />
      ) : !view.length ? (
        <p className="py-16 text-center text-fg-2">All quiet.</p>
      ) : (
        <ol className="mt-6 grid gap-x-10 md:grid-cols-2">
          <AnimatePresence initial={false}>
            {view.slice(0, 12).map((a, k) => {
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
                    onClick={() => select(a.shipment_id, true)}
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
                    </span>
                    <span className="flex items-center gap-2 font-mono text-[0.78rem] text-fg-3">
                      <span className="sr-only">{SEV[a.severity].label},</span>
                      {ago(a.age_h)}
                      <ArrowUpRight size={15} className="transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-late" />
                    </span>
                  </button>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
      {view.length > 12 && <p className="mt-6 text-center font-mono text-xs uppercase tracking-[0.16em] text-fg-3">+ {view.length - 12} more</p>}
    </section>
  );
}
