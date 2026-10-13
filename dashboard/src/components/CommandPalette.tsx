import { AnimatePresence, motion } from "motion/react";
import { CirclePlay, CornerDownLeft, Lightbulb, LogOut, Moon, Package, Search, Sun, type LucideIcon } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { pct, route } from "../lib/format";
import { GUIDE } from "../lib/guide";
import { useStore } from "../lib/store";
import { SECTIONS } from "./Nav";

const EASE = [0.16, 1, 0.3, 1] as const;
const MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
export const PALETTE_SHORTCUT = MAC ? "⌘K" : "Ctrl K";

interface Item {
  id: string;
  group: "Go to" | "Shipments" | "Actions";
  label: string;
  hint?: string;
  icon: LucideIcon;
  /** Extra words to match on. */
  keywords: string;
  run: () => void;
}

/** Rank: label starts with the query, then a word in the label does, then anything matches. */
function score(item: Item, q: string) {
  const label = item.label.toLowerCase();
  if (label.startsWith(q)) return 3;
  if (label.split(/[\s-]/).some((w) => w.startsWith(q))) return 2;
  return `${label} ${item.hint ?? ""} ${item.keywords}`.toLowerCase().includes(q) ? 1 : 0;
}

/**
 * ⌘K / Ctrl K command palette: jump to a section, open any shipment by ID, port or lane, or run an action.
 * WAI-ARIA combobox pattern: focus stays in the input, arrows move `aria-activedescendant` through a listbox.
 */
export function CommandPalette() {
  const { palette: open, setPalette, world, select, theme, toggleTheme, tips, toggleTips, signOut, auth } = useStore();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const uid = useId();
  const fleet = useAsync(() => (open && world ? api.fleet(0, world.now) : null), [open, world?.now]);

  // Global shortcut. "/" also opens it, unless the user is typing somewhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && e.target.matches("input, textarea, select, [contenteditable]");
      if ((e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing && !open)) {
        e.preventDefault();
        setPalette(!open);
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open, setPalette]);

  const close = () => setPalette(false);
  const go = (id: string) => () => {
    close();
    // Let the dialog unmount (and return focus) before scrolling.
    requestAnimationFrame(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
      history.replaceState(null, "", `#${id}`);
    });
  };

  const items = useMemo<Item[]>(() => {
    const sections: Item[] = [{ id: "top", label: "Replay", icon: CirclePlay }, ...SECTIONS].map((s) => ({
      id: `go-${s.id}`,
      group: "Go to",
      label: s.label,
      hint: GUIDE[s.id]?.question,
      icon: s.icon,
      keywords: s.id,
      run: go(s.id),
    }));
    const ships: Item[] = [...(fleet.data?.fleet.active ?? [])]
      .sort((a, b) => b.p_late - a.p_late)
      .map((r) => ({
        id: `ship-${r.shipment_id}`,
        group: "Shipments",
        label: r.shipment_id,
        hint: `${route(r.lane_id)} · ${pct(Math.min(r.p_late, 0.99))} late`,
        icon: Package,
        keywords: `${r.lane_id} ${r.risk_tier.replace("_", " ")} shipment`,
        run: () => {
          close();
          requestAnimationFrame(() => select(r.shipment_id, true));
        },
      }));
    const actions: Item[] = [
      { id: "act-theme", group: "Actions", label: `Switch to ${theme === "dark" ? "light" : "dark"} theme`, icon: theme === "dark" ? Sun : Moon, keywords: "theme dark light mode appearance", run: () => (toggleTheme(), close()) },
      { id: "act-tips", group: "Actions", label: `${tips ? "Hide" : "Show"} how-to tips`, icon: Lightbulb, keywords: "help guide tips onboarding", run: () => (toggleTips(), close()) },
    ];
    if (auth.session) actions.push({ id: "act-out", group: "Actions", label: "Sign out", hint: auth.session.user.name, icon: LogOut, keywords: "log out logout exit account", run: () => (close(), void signOut()) });
    return [...sections, ...ships, ...actions];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fleet.data, theme, tips, auth.session]);

  const query = q.trim().toLowerCase();
  const results = useMemo(() => {
    // No query: every section and action, plus the five shipments most likely to be late.
    if (!query) return [...items.filter((i) => i.group !== "Shipments"), ...items.filter((i) => i.group === "Shipments").slice(0, 5)];
    return items
      .map((i) => ({ i, s: score(i, query) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s || items.indexOf(a.i) - items.indexOf(b.i))
      .map((x) => x.i)
      .slice(0, 40);
  }, [items, query]);
  const groups = (["Go to", "Shipments", "Actions"] as const)
    .map((g) => ({ g, rows: results.filter((r) => r.group === g) }))
    .filter((x) => x.rows.length);
  const flat = groups.flatMap((x) => x.rows);

  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    if (!open) return;
    setQ("");
    setActive(0);
    const opener = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => input.current?.focus());
    return () => {
      document.body.style.overflow = overflow;
      opener?.focus({ preventScroll: true });
    };
  }, [open]);
  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const n = flat.length;
    const move = { ArrowDown: active + 1, ArrowUp: active - 1, Home: 0, End: n - 1, PageDown: active + 5, PageUp: active - 5 }[e.key];
    if (move !== undefined && n) {
      e.preventDefault();
      setActive(e.key === "ArrowDown" || e.key === "ArrowUp" ? (move + n) % n : Math.max(0, Math.min(n - 1, move)));
    } else if (e.key === "Enter" && flat[active]) {
      e.preventDefault();
      flat[active].run();
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    } else if (e.key === "Tab") {
      e.preventDefault(); // the input is the only stop; arrows move through results
    }
  };

  const optionId = (k: number) => `${uid}-opt-${k}`;
  let k = -1;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[70] flex items-start justify-center px-4 pt-[12vh]">
          <motion.div
            className="absolute inset-0 bg-scrim backdrop-blur-[3px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={close}
            aria-hidden
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Search and commands"
            className="surface-overlay relative flex max-h-[min(34rem,76vh)] w-full max-w-xl flex-col overflow-hidden rounded-[8px]"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.99, transition: { duration: 0.12 } }}
            transition={{ duration: 0.28, ease: EASE }}
            onKeyDown={onKeyDown}
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search size={18} aria-hidden className="shrink-0 text-fg-3" />
              <input
                ref={input}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                role="combobox"
                aria-expanded="true"
                aria-controls={`${uid}-list`}
                aria-activedescendant={flat.length ? optionId(active) : undefined}
                aria-autocomplete="list"
                aria-label="Search sections, shipments and actions"
                placeholder="Search sections, shipments, ports, actions…"
                autoComplete="off"
                spellCheck={false}
                className="h-14 w-full bg-transparent text-[1.05rem] text-fg outline-none placeholder:text-fg-3"
              />
              <button onClick={close} className="kbd shrink-0 hover:text-fg" aria-label="Close search">
                Esc
              </button>
            </div>

            <ul ref={list} id={`${uid}-list`} role="listbox" aria-label="Results" className="flex-1 overflow-y-auto overscroll-contain p-2">
              {groups.map(({ g, rows }) => (
                <li key={g} role="presentation">
                  <p id={`${uid}-${g}`} className="eyebrow px-3 pb-1.5 pt-3 text-[0.75rem]">
                    {g}
                  </p>
                  <ul role="group" aria-labelledby={`${uid}-${g}`}>
                    {rows.map((it) => {
                      k++;
                      const idx = k;
                      const on = idx === active;
                      const Icon = it.icon;
                      return (
                        <li
                          key={it.id}
                          id={optionId(idx)}
                          role="option"
                          aria-selected={on}
                          data-index={idx}
                          onPointerMove={() => !on && setActive(idx)}
                          onClick={it.run}
                          className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-[5px] px-3 py-2 transition-colors duration-100 ${on ? "bg-bg-3 text-fg" : "text-fg-2"}`}
                        >
                          <Icon size={16} aria-hidden className={`shrink-0 ${on ? "text-late" : "text-fg-3"}`} />
                          <span className={`shrink-0 ${it.group === "Shipments" ? "font-mono text-[0.95rem]" : "text-[0.98rem]"}`}>{it.label}</span>
                          {it.hint && <span className="min-w-0 truncate text-[0.88rem] text-fg-3">{it.hint}</span>}
                          {on && <CornerDownLeft size={14} aria-hidden className="ml-auto shrink-0 text-fg-3" />}
                        </li>
                      );
                    })}
                  </ul>
                </li>
              ))}
              {!flat.length && (
                <li role="presentation" className="px-3 py-10 text-center text-fg-2">
                  {fleet.loading && query ? "Searching shipments…" : <>Nothing matches “{q.trim()}”. Try a shipment ID like SHP-000174, or a port.</>}
                </li>
              )}
            </ul>

            <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 font-mono text-[0.75rem] text-fg-3" aria-hidden>
              <span className="flex items-center gap-1.5"><span className="kbd">↑</span><span className="kbd">↓</span> move</span>
              <span className="flex items-center gap-1.5"><span className="kbd">↵</span> open</span>
              <span className="ml-auto flex items-center gap-1.5"><span className="kbd">{PALETTE_SHORTCUT}</span> toggle</span>
            </div>
            <p className="sr-only" aria-live="polite">
              {query ? `${flat.length} result${flat.length === 1 ? "" : "s"}` : ""}
            </p>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
