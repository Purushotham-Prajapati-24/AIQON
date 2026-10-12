import { motion } from "motion/react";
import { ArrowRight, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Contours } from "../components/Contours";
import { Logo } from "../components/Nav";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { day, dayLong } from "../lib/format";
import { ROLES, type Role, type RoleId } from "../lib/roles";
import { HERO_SHIPMENT, useStore } from "../lib/store";

const EASE = [0.16, 1, 0.3, 1] as const;

/** Entry screen: pick what you came to do. Each choice shows one live number so the page is useful before you click. */
export function Entry() {
  const { world, mode, theme, toggleTheme, setRole } = useStore();
  const [picked, setPicked] = useState<RoleId | null>(null);

  const live = useAsync(async () => {
    if (!world) return null;
    const [f, m, s] = await Promise.all([api.fleet(0, world.now), api.model(), api.moment(HERO_SHIPMENT, world.now)]);
    const late = f.fleet.active.filter((r) => r.risk_tier === "LATE").length;
    return {
      planner: { v: `${late} late`, l: `of ${f.fleet.active.length} on the way` },
      support: { v: day(s.ops.eta.p50), l: `${HERO_SHIPMENT} arrives` },
      analyst: { v: `−${Math.round(m.metrics.mae_improvement_vs_B1 * 100)}%`, l: "error vs a simple rule" },
      first: { v: `${Math.round(s.ops.delay_hours.p50 / 24)} days`, l: "late, from 46 h at the hub" },
    } as Record<RoleId, { v: string; l: string }>;
  }, [world?.now]);

  const pick = (r: Role) => {
    if (picked) return;
    setPicked(r.id);
    setTimeout(() => setRole(r.id), 650);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = Number(e.key);
      if (k >= 1 && k <= ROLES.length && !e.metaKey && !e.ctrlKey && !e.altKey) pick(ROLES[k - 1]);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  return (
    <motion.main
      key="entry"
      className="relative isolate flex min-h-svh flex-col overflow-hidden"
      exit={{ opacity: 0, y: -24, transition: { duration: 0.5, ease: EASE } }}
    >
      <Contours />

      <header className="shell relative flex h-16 items-center gap-3 md:h-[4.5rem]">
        <Logo className="size-7" />
        <span className="font-display text-[1.55rem] font-extrabold uppercase tracking-[0.04em]">Cascade</span>
        <button
          onClick={toggleTheme}
          className="ml-auto grid size-9 place-items-center rounded-[4px] border border-line text-fg-2 transition-colors hover:border-fg-2 hover:text-fg"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      <div className="shell relative flex flex-1 flex-col justify-center py-8 md:py-10">
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.1 }}
          className="eyebrow flex flex-wrap items-center gap-x-3 gap-y-1"
        >
          <span className="text-late">Shipment delay control</span>
          <span className="h-px w-6 bg-line-2" />
          {world ? `Data as of ${dayLong(world.now)}` : "Loading data"}
          {mode && (
            <>
              <span className="h-px w-6 bg-line-2" />
              {mode === "live" ? "Live model" : "Recorded run"}
            </>
          )}
        </motion.p>

        <h1 className="mt-6 font-display text-[clamp(3.2rem,7vw,6.5rem)] font-extrabold uppercase leading-[0.86] tracking-[-0.015em]">
          {["What do you", <span className="text-fg-3">need today?</span>].map((l, k) => (
            <span key={k} className="block overflow-hidden pb-[0.05em]">
              <motion.span className="block" initial={{ y: "108%" }} animate={{ y: "0%" }} transition={{ duration: 1.1, ease: EASE, delay: 0.1 + k * 0.1 }}>
                {l}
              </motion.span>
            </span>
          ))}
        </h1>

        <ol className="mt-10 border-t border-line md:mt-12" aria-label="Choose what you need">
          {ROLES.map((r, k) => {
            const fig = live.data?.[r.id];
            const dim = picked && picked !== r.id;
            const on = picked === r.id;
            return (
              <motion.li
                key={r.id}
                initial={{ opacity: 0, y: 24 }}
                animate={{ opacity: dim ? 0.2 : 1, y: 0 }}
                transition={{ duration: 0.8, ease: EASE, delay: picked ? 0 : 0.35 + k * 0.07 }}
                className="border-b border-line"
              >
                <button
                  onClick={() => pick(r)}
                  aria-keyshortcuts={String(k + 1)}
                  className={`group relative grid w-full grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 overflow-hidden py-6 text-left md:grid-cols-[3.5rem_minmax(0,1.1fr)_minmax(0,1.3fr)_minmax(0,0.9fr)_2.5rem] md:gap-x-8 md:py-5`}
                >
                  {/* hover / selection wash */}
                  <motion.span
                    aria-hidden
                    className="absolute inset-0 -z-10 origin-left bg-late-wash"
                    initial={false}
                    animate={{ scaleX: on ? 1 : 0 }}
                    transition={{ duration: 0.6, ease: EASE }}
                  />
                  <span className="absolute inset-0 -z-20 bg-bg-2 opacity-0 transition-opacity duration-300 group-hover:opacity-100" aria-hidden />

                  <span className={`font-mono text-sm transition-colors ${on ? "text-late" : "text-fg-3 group-hover:text-late"}`}>0{k + 1}</span>
                  <span className="font-display text-[clamp(2rem,3.6vw,3.4rem)] font-extrabold uppercase leading-none transition-transform duration-500 ease-out group-hover:translate-x-2">
                    {r.name}
                  </span>
                  <span className="col-span-3 col-start-2 text-[1.05rem] text-fg-2 md:col-span-1 md:col-start-auto">{r.task}</span>
                  <span className="col-span-2 col-start-2 flex items-baseline gap-3 md:col-span-1 md:col-start-auto md:block md:text-right">
                    {fig ? (
                      <>
                        <span className="num block whitespace-nowrap text-[clamp(1.8rem,2.6vw,2.6rem)] uppercase">{fig.v}</span>
                        <span className="mt-1 block font-mono text-[0.72rem] uppercase tracking-[0.14em] text-fg-3">{fig.l}</span>
                      </>
                    ) : (
                      <span className="inline-block h-10 w-28 animate-pulse rounded-[4px] bg-bg-3" />
                    )}
                  </span>
                  <ArrowRight
                    size={22}
                    className={`col-start-3 row-start-1 justify-self-end transition-all duration-300 md:col-start-auto md:row-start-auto ${
                      on ? "translate-x-1 text-late" : "text-fg-3 group-hover:translate-x-1 group-hover:text-late"
                    }`}
                  />
                </button>
              </motion.li>
            );
          })}
        </ol>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 0.9 }}
          className="mt-6 flex flex-wrap items-center justify-between gap-4 font-mono text-[0.72rem] uppercase tracking-[0.16em] text-fg-3"
        >
          <span className="hidden sm:inline">Press 1–4 · change any time from the top bar</span>
          <button onClick={() => pick(ROLES[3])} className="flex items-center gap-2 uppercase tracking-[0.16em] transition-colors hover:text-fg">
            Skip, show me everything <ArrowRight size={14} />
          </button>
        </motion.div>
      </div>
    </motion.main>
  );
}
