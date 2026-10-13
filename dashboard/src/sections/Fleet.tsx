import { AnimatePresence, LayoutGroup, motion } from "motion/react";
import { ArrowUpRight, ChevronDown } from "lucide-react";
import { useMemo, useState } from "react";
import { FleetMap } from "../components/FleetMap";
import { ErrorNote, RangeStrip, Reveal, SectionHead, Skeleton, Ticker, TierBadge } from "../components/ui";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { TIER, dayLong, delay, groupName, pct, route, usd } from "../lib/format";
import { useStore } from "../lib/store";
import type { FleetRow, Tier } from "../lib/types";

const EASE = [0.16, 1, 0.3, 1] as const;
const FILTERS: { id: Tier | "ALL"; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "LATE", label: "Late" },
  { id: "AT_RISK", label: "At risk" },
  { id: "ON_TRACK", label: "On time" },
];
const SORTS = {
  risk: { label: "Chance late", fn: (a: FleetRow, b: FleetRow) => b.p_late - a.p_late || b.delay_hours.p50 - a.delay_hours.p50 },
  delay: { label: "Delay", fn: (a: FleetRow, b: FleetRow) => b.delay_hours.p50 - a.delay_hours.p50 },
  cost: { label: "Cost", fn: (a: FleetRow, b: FleetRow) => (b.cost_usd.p50 ?? 0) - (a.cost_usd.p50 ?? 0) },
};

export function Fleet() {
  const { world, days, setDays, selected, select } = useStore();
  const data = useAsync(() => (world ? api.fleet(days, world.now) : null), [world?.now, days]);
  const rows = data.data?.fleet.active ?? [];
  const asOf = data.data?.fleet.as_of ?? world?.now;

  const counts = useMemo(() => {
    const c = { LATE: 0, AT_RISK: 0, ON_TRACK: 0 } as Record<Tier, number>;
    rows.forEach((r) => c[r.risk_tier]++);
    return c;
  }, [rows]);
  const cost = rows.reduce((a, r) => a + (r.cost_usd.p50 ?? 0), 0);
  const [filter, setFilter] = useState<Tier | "ALL">("ALL");
  const open = (sid: string, label: string, el: Element | null) => select(sid, true, { label, section: "fleet", el });
  /** The tier counts double as shortcuts into the list below. */
  const showTier = (t: Tier) => {
    setFilter((f) => (f === t ? "ALL" : t));
    document.getElementById("fleet-list")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <section id="fleet" className="shell">
      <SectionHead
        id="fleet"
        index="01"
        kicker="Fleet"
        title={[
          <>
            <span className="text-late">
              <Ticker value={counts.LATE} />
            </span>{" "}
            of <Ticker value={rows.length} /> shipments
          </>,
          <span className="text-fg-3">will be late.</span>,
        ]}
        aside={<TimeControl days={days} setDays={setDays} asOf={asOf} />}
      />

      {data.error && <ErrorNote error={data.error} />}

      <div className="grid gap-10 border-t border-line pt-10 lg:grid-cols-12">
        {/* Mix of risk */}
        <Reveal className="lg:col-span-4">
          <ul className="space-y-2">
            {(["LATE", "AT_RISK", "ON_TRACK"] as Tier[]).map((t) => (
              <li key={t}>
                <button
                  onClick={() => showTier(t)}
                  aria-pressed={filter === t}
                  className={`group flex w-full items-end justify-between gap-4 border-b border-line pb-5 pt-3 text-left transition-colors hover:border-fg-2 ${filter === t ? "border-fg-2" : ""}`}
                >
                  <span className="flex flex-col items-start gap-2">
                    <TierBadge tier={t} />
                    <span className="font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3 transition-colors group-hover:text-fg-2">
                      {filter === t ? "Showing in list · clear" : "Show in list ↓"}
                    </span>
                  </span>
                  <span className="num text-[3.6rem]" style={{ color: TIER[t].ink }}>
                    <Ticker value={counts[t]} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-6 flex h-2.5 w-full overflow-hidden rounded-full bg-bg-3" aria-hidden>
            {(["LATE", "AT_RISK", "ON_TRACK"] as Tier[]).map((t) => (
              <motion.div
                key={t}
                className="h-full border-r-2 border-bg last:border-r-0"
                style={{ background: TIER[t].color }}
                initial={{ width: 0 }}
                animate={{ width: rows.length ? `${(counts[t] / rows.length) * 100}%` : 0 }}
                transition={{ duration: 1, ease: EASE }}
              />
            ))}
          </div>
          <div className="mt-10 grid grid-cols-2 gap-6">
            <div>
              <div className="num text-[2.6rem]">
                <Ticker value={cost} format={(v) => usd(v)} />
              </div>
              <p className="mt-1 text-[0.95rem] text-fg-2">expected delay cost</p>
            </div>
            <div>
              <div className="num text-[2.6rem]">
                <Ticker value={data.data?.fleet.delivered.length ?? 0} />
              </div>
              <p className="mt-1 text-[0.95rem] text-fg-2">delivered so far</p>
            </div>
          </div>
        </Reveal>

        {/* Map */}
        <Reveal delay={0.1} className="lg:col-span-8">
          {rows.length ? <FleetMap rows={rows} selected={selected} onSelect={(s, el) => open(s, "Fleet map", el)} /> : <Skeleton className="aspect-[2/1] w-full" />}
          <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3">
            <li className="flex items-center gap-2"><span className="size-2 rounded-full bg-fg-2" /> Port</li>
            <li className="flex items-center gap-2"><span className="size-2 rotate-45 border border-fg-2" /> Hub</li>
            <li>Dot = one shipment · click to open · the list below has every dot</li>
          </ul>
        </Reveal>
      </div>

      <ShipmentList
        rows={rows}
        selected={selected}
        onSelect={(s, el) => open(s, "Worst first list", el)}
        loading={data.loading && !rows.length}
        filter={filter}
        setFilter={setFilter}
      />
    </section>
  );
}

function TimeControl({ days, setDays, asOf }: { days: number; setDays: (d: number) => void; asOf?: string }) {
  return (
    <div>
      <label htmlFor="fleet-clock" className="eyebrow block">
        Fleet on
      </label>
      <div className="mt-2 font-display text-[2.2rem] font-bold uppercase leading-none">
        {asOf ? dayLong(asOf) : "—"}
        {days === 0 && <span className="ml-3 align-middle font-mono text-xs tracking-[0.16em] text-ok">● TODAY</span>}
      </div>
      <input
        id="fleet-clock"
        type="range"
        className="scrub mt-4"
        min={-21}
        max={0}
        step={1}
        value={days}
        onChange={(e) => setDays(+e.target.value)}
        aria-valuetext={days === 0 ? "Today" : `${-days} days ago`}
      />
      <div className="flex justify-between font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3">
        <span>3 weeks ago</span>
        <span>Today</span>
      </div>
    </div>
  );
}

function ShipmentList({
  rows,
  selected,
  onSelect,
  loading,
  filter,
  setFilter,
}: {
  rows: FleetRow[];
  selected: string;
  onSelect: (sid: string, el: Element) => void;
  loading: boolean;
  filter: Tier | "ALL";
  setFilter: (f: Tier | "ALL") => void;
}) {
  const [sort, setSort] = useState<keyof typeof SORTS>("risk");
  const [all, setAll] = useState(false);
  const view = useMemo(
    () => rows.filter((r) => filter === "ALL" || r.risk_tier === filter).sort(SORTS[sort].fn),
    [rows, filter, sort],
  );
  const shown = all ? view : view.slice(0, 10);
  const span = useMemo(() => {
    const lo = Math.min(-24, ...rows.map((r) => r.delay_hours.p10));
    const hi = Math.max(48, ...rows.map((r) => r.delay_hours.p90));
    return [lo, hi] as const;
  }, [rows]);

  return (
    <div className="mt-20 scroll-mt-24 lg:scroll-mt-6" id="fleet-list">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-5">
        <h3 className="font-display text-[2.4rem] font-extrabold uppercase leading-none">Worst first</h3>
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map((f) => (
            <button key={f.id} className="chip" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
              {f.label}
              <span className="chip-count">{f.id === "ALL" ? rows.length : rows.filter((r) => r.risk_tier === f.id).length}</span>
            </button>
          ))}
          <span className="mx-2 hidden h-5 w-px bg-line-2 sm:block" />
          <label className="sr-only" htmlFor="sort">Sort by</label>
          <select
            id="sort"
            value={sort}
            onChange={(e) => setSort(e.target.value as keyof typeof SORTS)}
            className="chip appearance-none bg-transparent pr-3"
          >
            {Object.entries(SORTS).map(([k, s]) => (
              <option key={k} value={k} className="bg-bg-2 text-fg">
                Sort · {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* column heads */}
      <div className="hidden grid-cols-[3rem_minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,2fr)_minmax(0,1.2fr)_6rem_2rem] gap-5 py-3 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-3 lg:grid">
        <span>#</span>
        <span>Shipment</span>
        <span>Chance late</span>
        <span>Expected delay · likely range</span>
        <span>Risk ahead</span>
        <span className="text-right">Cost</span>
        <span />
      </div>

      {loading && <Skeleton className="h-96 w-full" />}
      {!loading && !view.length && (
        <p className="py-16 text-center text-fg-2">
          No {FILTERS.find((f) => f.id === filter)?.label.toLowerCase()} shipments on this day.{" "}
          <button onClick={() => setFilter("ALL")} className="underline underline-offset-4 hover:text-fg">
            Show all
          </button>
        </p>
      )}

      <LayoutGroup>
        <ol>
          <AnimatePresence initial={false}>
            {shown.map((r, k) => (
              <motion.li
                key={r.shipment_id}
                layout
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.45, ease: EASE }}
              >
                <button
                  onClick={(e) => onSelect(r.shipment_id, e.currentTarget)}
                  className={`group grid w-full grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-3 border-b border-line py-5 text-left transition-colors hover:bg-bg-2 lg:grid-cols-[3rem_minmax(0,2.4fr)_minmax(0,1fr)_minmax(0,2fr)_minmax(0,1.2fr)_6rem_2rem] lg:gap-5 ${
                    r.shipment_id === selected ? "bg-bg-2" : ""
                  }`}
                  aria-current={r.shipment_id === selected}
                >
                  <span className="font-mono text-sm text-fg-3">{String(k + 1).padStart(2, "0")}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-3">
                      <span className="font-mono text-[0.95rem]">{r.shipment_id}</span>
                      <TierBadge tier={r.risk_tier} size="sm" />
                    </span>
                    <span className="mt-1 block truncate text-fg-2">{route(r.lane_id)}</span>
                  </span>
                  <span className="lg:order-none">
                    <span className="num text-[2rem]" style={{ color: TIER[r.risk_tier].ink }}>
                      {pct(Math.min(r.p_late, 0.99))}
                    </span>
                  </span>
                  <span className="col-span-3 lg:col-span-1">
                    <span className="flex items-baseline justify-between font-mono text-[0.85rem]">
                      <span className="text-fg">{delay(r.delay_hours.p50)}</span>
                      <span className="text-fg-3">
                        {delay(r.delay_hours.p10, { short: true })} … {delay(r.delay_hours.p90, { short: true })}
                      </span>
                    </span>
                    <RangeStrip {...r.delay_hours} min={span[0]} max={span[1]} tier={r.risk_tier} />
                  </span>
                  <span className="col-span-2 text-fg-2 lg:col-span-1">{groupName(r.main_stage)}</span>
                  <span className="text-right font-mono text-[0.95rem]">{usd(r.cost_usd.p50 ?? 0)}</span>
                  <ArrowUpRight size={18} className="hidden text-fg-3 transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-late lg:block" />
                </button>
              </motion.li>
            ))}
          </AnimatePresence>
        </ol>
      </LayoutGroup>

      {view.length > 10 && (
        <button
          onClick={() => setAll((a) => !a)}
          className="mx-auto mt-5 flex items-center gap-2 px-4 py-3.5 font-mono text-xs uppercase tracking-[0.18em] text-fg-2 hover:text-fg"
          aria-expanded={all}
        >
          {all ? "Show top 10" : `Show all ${view.length}`}
          <ChevronDown size={14} className={`transition-transform ${all ? "rotate-180" : ""}`} />
        </button>
      )}
    </div>
  );
}
