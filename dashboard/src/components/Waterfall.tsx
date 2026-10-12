import { motion } from "motion/react";
import { delay } from "../lib/format";
import type { WaterfallItem } from "../lib/types";

const EASE = [0.16, 1, 0.3, 1] as const;

const tidy = (l: string) =>
  l
    .replace(" (milestones missing)", " · not reported")
    .replace("Pre-carriage to origin terminal", "Getting to the port")
    .replace("Transshipment connection", "Hub transfer")
    .replace("Typical remaining delay", "Usual delay ahead")
    .replace("Expected total delay (P50)", "Expected total")
    .replace("Getting to the port → Ocean leg to hub", "To the hub")
    .replace("Ocean leg to hub", "Sea leg to hub")
    .replace("Ocean leg", "Sea leg")
    .replace("Ocean transit", "At sea")
    .replace("Destination port", "Arrival port")
    .replace("Inland & delivery", "Final delivery");

/** Where the delay comes from: each bar starts where the previous one ended; parts add up to the total. */
export function Waterfall({ items }: { items: WaterfallItem[] }) {
  const rows = items.filter((it) => it.kind === "total" || Math.abs(it.hours) >= 0.5);
  let run = 0;
  const bars = rows.map((it) => {
    if (it.kind === "total") return { it, a: 0, b: it.hours };
    const a = run;
    run += it.hours;
    return { it, a, b: run };
  });
  const lo = Math.min(0, ...bars.flatMap((b) => [b.a, b.b]));
  const hi = Math.max(1, ...bars.flatMap((b) => [b.a, b.b]));
  const x = (v: number) => ((v - lo) / (hi - lo)) * 100;

  return (
    <ol className="space-y-1" aria-label="Delay breakdown by stage">
      {bars.map(({ it, a, b }, k) => {
        const total = it.kind === "total";
        const left = x(Math.min(a, b));
        const width = Math.max(0.6, Math.abs(x(b) - x(a)));
        const neg = it.hours < 0;
        const forecast = it.kind === "forecast" || it.kind === "baseline" || it.kind === "guardrail";
        return (
          <li
            key={k}
            className={`grid grid-cols-[minmax(0,14rem)_minmax(0,1fr)_5rem] items-center gap-4 py-2 ${total ? "mt-2 border-t border-line pt-4" : ""}`}
          >
            <span className={`truncate text-[0.95rem] ${total ? "font-semibold text-fg" : "text-fg-2"}`} title={it.label}>
              {tidy(it.label)}
            </span>
            <span className="relative h-7">
              <span className="absolute inset-y-0 w-px bg-line-2" style={{ left: `${x(0)}%` }} />
              <motion.span
                className={`absolute inset-y-1 rounded-[3px] ${forecast && !neg ? "hatch" : ""}`}
                style={{
                  color: "var(--late)",
                  background: total
                    ? "var(--fg)"
                    : neg
                      ? "var(--ok)"
                      : forecast
                        ? undefined
                        : "color-mix(in oklab, var(--late) 80%, transparent)",
                  opacity: forecast && !neg ? 0.85 : 1,
                }}
                initial={{ left: `${x(a)}%`, width: 0 }}
                animate={{ left: `${left}%`, width: `${width}%` }}
                transition={{ duration: 0.9, ease: EASE, delay: k * 0.06 }}
              />
            </span>
            <span className={`text-right font-mono text-[0.9rem] ${neg ? "text-ok" : total ? "text-fg" : "text-fg-2"}`}>
              {delay(it.hours, { short: true })}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
