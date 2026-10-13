import { AnimatePresence, motion, useScroll } from "motion/react";
import {
  Bell,
  CirclePlay,
  Globe,
  Lightbulb,
  LogOut,
  Menu,
  Moon,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  ShieldCheck,
  Sun,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { focusSection, lockScroll, restoreFocus } from "../lib/focus";
import { GUIDE } from "../lib/guide";
import { PALETTE_SHORTCUT } from "./CommandPalette";
import { useStore } from "../lib/store";

export const SECTIONS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: "fleet", label: "Fleet", icon: Globe },
  { id: "shipment", label: "Shipment", icon: Package },
  { id: "fix", label: "Fix", icon: Wrench },
  { id: "alerts", label: "Alerts", icon: Bell },
  { id: "proof", label: "Proof", icon: ShieldCheck },
];

const RAIL_KEY = "cascade-rail";
const EASE = [0.16, 1, 0.3, 1] as const;

export function Logo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M4 8h8v6h8v6h8" fill="none" stroke="var(--late)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="28" cy="20" r="2.6" fill="var(--fg)" />
    </svg>
  );
}

function initialCollapsed() {
  try {
    return localStorage.getItem(RAIL_KEY) === "collapsed";
  } catch {
    return false;
  }
}

/** Scroll-spy: the last section whose top passed 40% of the viewport. Reads the live DOM on each
 *  (rAF-throttled) scroll, so lazily mounted sections are picked up without re-subscribing. */
function useActiveSection(mode: unknown) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      const line = innerHeight * 0.4;
      let cur: string | null = null;
      for (const id of ["top", ...SECTIONS.map((s) => s.id)]) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= line) cur = id;
      }
      setActive(cur);
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(update);
    };
    update();
    addEventListener("scroll", onScroll, { passive: true });
    addEventListener("resize", onScroll);
    return () => {
      removeEventListener("scroll", onScroll);
      removeEventListener("resize", onScroll);
      cancelAnimationFrame(raf);
    };
  }, [mode]);
  return active;
}

/** Where the numbers come from: the live API, or the recorded run (and why, after an outage). */
function SourceBadge({ compact }: { compact: boolean }) {
  const { mode, fallback } = useStore();
  if (!mode) return null;
  const live = mode === "live";
  const label = live ? "Live model" : fallback ? "Recorded run · API offline" : "Recorded run";
  return (
    <span
      className={`flex items-center gap-2 font-mono text-[0.7rem] uppercase tracking-[0.14em] text-fg-2 ${compact ? "justify-center py-1" : "px-1"}`}
      title={
        live
          ? "Connected to the CASCADE API: every number is computed now."
          : fallback
            ? `${fallback} Showing a recorded run of the same model.`
            : "Showing a recorded run of the real model (start the API for live answers)."
      }
      role="status"
    >
      <span className="relative flex size-2 shrink-0" aria-hidden>
        {live && <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-60" />}
        <span className={`relative size-2 rounded-full ${live ? "bg-ok" : fallback ? "bg-risk" : "bg-fg-3"}`} />
      </span>
      <span className={compact ? "sr-only" : "truncate"}>{label}</span>
    </span>
  );
}

/**
 * Section navigation as a left sidebar. From `lg` up it is a fixed rail that collapses to icons
 * (remembered per browser); below that a slim top bar opens the same sidebar as a drawer.
 * The rail's width is published as `--rail` on <html> so the page can make room for it.
 */
export function Nav() {
  const { mode, palette } = useStore();
  const active = useActiveSection(mode);
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  // One modal at a time: opening the palette (Ctrl K or "/") closes the drawer.
  useEffect(() => {
    if (palette) setOpen(false);
  }, [palette]);

  // Layout effect: the page makes room for the rail before the first paint, instead of sliding over.
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.dataset.rail = collapsed ? "collapsed" : "expanded";
    try {
      localStorage.setItem(RAIL_KEY, collapsed ? "collapsed" : "expanded");
    } catch {
      /* storage blocked */
    }
    return () => void delete root.dataset.rail;
  }, [collapsed]);

  return (
    <>
      <aside
        className="fixed inset-y-0 left-0 z-50 hidden w-[var(--rail)] border-r border-line bg-bg-2/95 backdrop-blur-md transition-[width] duration-300 ease-out-expo lg:block"
        aria-label="Sidebar"
      >
        <SidebarBody
          compact={collapsed}
          active={active}
          markerId="rail-marker"
          headerAction={
            <button
              onClick={() => setCollapsed((c) => !c)}
              className={`grid size-8 shrink-0 place-items-center rounded-[4px] text-fg-3 transition-colors hover:bg-bg-3 hover:text-fg ${collapsed ? "mx-auto" : "ml-auto"}`}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!collapsed}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          }
        />
        <ScrollProgress axis="y" />
      </aside>

      <MobileBar onOpen={() => setOpen(true)} />
      <Drawer open={open} onClose={close} active={active} />
    </>
  );
}

function SidebarBody({
  compact,
  active,
  markerId,
  headerAction,
  onNavigate,
}: {
  compact: boolean;
  active: string | null;
  markerId: string;
  headerAction: React.ReactNode;
  onNavigate?: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className={`flex h-16 shrink-0 items-center gap-2.5 border-b border-line md:h-[4.5rem] ${compact ? "flex-col justify-center px-2" : "px-5"}`}>
        {!compact && (
          <a href="#top" onClick={onNavigate} className="flex items-center gap-2.5" aria-label="CASCADE, back to top">
            <Logo className="size-7 shrink-0" />
            <span className="font-display text-[1.55rem] font-extrabold uppercase tracking-[0.04em]">Cascade</span>
          </a>
        )}
        {headerAction}
      </div>

      <div className={`pt-4 ${compact ? "px-2" : "px-3"}`}>
        <SearchButton compact={compact} onOpen={onNavigate} />
        <div className="mt-3">
          <SourceBadge compact={compact} />
        </div>
      </div>
      <nav aria-label="Sections" className="flex-1 overflow-y-auto overscroll-contain py-3">
        <ul className={`space-y-0.5 ${compact ? "px-2" : "px-3"}`}>
          {[{ id: "top", label: "Replay", icon: CirclePlay }, ...SECTIONS].map((s) => (
            <NavItem
              key={s.id}
              id={s.id}
              label={s.label}
              icon={s.icon}
              active={active === s.id}
              compact={compact}
              markerId={markerId}
              onNavigate={onNavigate}
            />
          ))}
        </ul>
      </nav>

      <SidebarFooter compact={compact} />
    </div>
  );
}

/** Opens the command palette; styled as a field so it reads as "search", with its shortcut on show. */
function SearchButton({ compact, onOpen }: { compact: boolean; onOpen?: () => void }) {
  const { setPalette } = useStore();
  return (
    <button
      onClick={() => {
        onOpen?.();
        setPalette(true);
      }}
      aria-keyshortcuts={PALETTE_SHORTCUT === "⌘K" ? "Meta+K" : "Control+K"}
      title={compact ? `Search (${PALETTE_SHORTCUT})` : undefined}
      className={`flex h-10 w-full items-center gap-3 rounded-[5px] border border-line-2 bg-bg text-fg-3 transition-colors hover:border-fg-3 hover:text-fg-2 ${
        compact ? "justify-center" : "px-3"
      }`}
    >
      <Search size={16} aria-hidden className="shrink-0" />
      {compact ? (
        <span className="sr-only">Search</span>
      ) : (
        <>
          <span className="text-[0.92rem]">Search</span>
          <span className="kbd kbd-hint ml-auto">{PALETTE_SHORTCUT}</span>
        </>
      )}
    </button>
  );
}

function NavItem({
  id,
  label,
  icon: Icon,
  active,
  compact,
  markerId,
  onNavigate,
}: {
  id: string;
  label: string;
  icon: LucideIcon;
  active: boolean;
  compact: boolean;
  markerId: string;
  onNavigate?: () => void;
}) {
  const { role } = useStore();
  const start = role?.opens === id;
  const hint = [GUIDE[id]?.question, start && role ? `Start here: ${role.task}` : null].filter(Boolean).join(" · ");
  return (
    <li>
      <a
        href={`#${id}`}
        onClick={() => {
          // Keyboard and screen-reader users continue from the section, not the sidebar. Next frame: following
          // the hash link itself drops focus to <body>. Queued before onNavigate so it runs before the drawer's
          // focus restore, which then sees focus already placed.
          requestAnimationFrame(() => focusSection(id));
          onNavigate?.();
        }}
        aria-current={active ? "location" : undefined}
        title={compact ? `${label} · ${hint}` : hint}
        className={`relative flex h-10 items-center rounded-[4px] font-mono text-[0.78rem] uppercase tracking-[0.14em] transition-colors ${
          compact ? "justify-center" : "gap-3 px-3"
        } ${active ? "bg-bg-3 text-fg" : "text-fg-3 hover:bg-bg-3/60 hover:text-fg"}`}
      >
        {active && (
          <motion.span
            layoutId={markerId}
            className="absolute inset-y-2 left-0 w-[2px] rounded-full bg-late"
            transition={{ duration: 0.35, ease: EASE }}
          />
        )}
        <Icon size={16} aria-hidden className={`shrink-0 ${active ? "text-late" : ""}`} />
        {compact && start && <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-late" aria-hidden />}
        <span className={compact ? "sr-only" : "truncate"}>{label}</span>
        {start &&
          (compact ? (
            <span className="sr-only">, start here</span>
          ) : (
            <span className="ml-auto rounded-[3px] border border-late/50 px-1.5 text-[0.75rem] leading-[1.15rem] tracking-[0.12em] text-late">Start</span>
          ))}
      </a>
    </li>
  );
}

function SidebarFooter({ compact }: { compact: boolean }) {
  const { theme, toggleTheme, tips, toggleTips, auth, signOut } = useStore();
  const user = auth.session?.user;
  const [signOutFailed, setSignOutFailed] = useState(false);
  const initials = user?.name.split(" ").map((p) => p[0]).join("").slice(0, 2);

  const iconBtn = "grid size-9 shrink-0 place-items-center rounded-[4px] text-fg-2 transition-colors hover:bg-bg-3 hover:text-fg";

  return (
    <div className={`flex shrink-0 gap-1 border-t border-line py-3 ${compact ? "flex-col items-center px-2" : "items-center px-3"}`}>
        <button
          onClick={toggleTips}
          aria-pressed={tips}
          className={`${iconBtn} ${tips ? "text-[var(--risk-ink)]" : ""}`}
          aria-label="How-to tips"
          title={tips ? "Hide the how-to tips in each section" : "Show what you can do in each section"}
        >
          <Lightbulb size={16} aria-hidden />
        </button>
        <button
          onClick={toggleTheme}
          className={iconBtn}
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
        </button>

      {user && (
        <button
          onClick={async () => {
            const ok = await signOut();
            setSignOutFailed(!ok);
            if (ok) scrollTo({ top: 0 });
          }}
          className={`group flex items-center gap-2.5 rounded-[4px] border p-1 text-left transition-colors hover:text-fg ${
            signOutFailed ? "border-late text-late" : "border-transparent text-fg-2 hover:border-line-2"
          } ${compact ? "order-last mt-1" : "order-first mr-auto min-w-0 flex-1 pr-2"}`}
          title={
            signOutFailed
              ? "Couldn't reach the server to end your session. Click to try again."
              : `Signed in as ${user.name} (${user.title}). Session ends ${new Date((auth.session?.expiresAt ?? 0) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.`
          }
        >
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-bg-3 font-mono text-[0.75rem] text-fg" aria-hidden>
            {initials}
          </span>
          {!compact && (
            <span className="min-w-0 flex-1 truncate text-[0.9rem] text-fg" aria-hidden>
              {signOutFailed ? "Retry" : user.name.split(" ")[0]}
            </span>
          )}
          {!compact && <LogOut size={14} aria-hidden className="mr-1.5 shrink-0" />}
          <span className="sr-only">Sign out {user.name}</span>
        </button>
      )}
    </div>
  );
}

function ScrollProgress({ axis }: { axis: "x" | "y" }) {
  const { scrollYProgress } = useScroll();
  return axis === "y" ? (
    <motion.div aria-hidden className="absolute -right-px top-0 h-full w-px origin-top bg-late" style={{ scaleY: scrollYProgress }} />
  ) : (
    <motion.div aria-hidden className="absolute inset-x-0 -bottom-px h-px origin-left bg-late" style={{ scaleX: scrollYProgress }} />
  );
}

/** Below `lg`: brand plus a button that opens the sidebar as a drawer. */
function MobileBar({ onOpen }: { onOpen: () => void }) {
  const { setPalette } = useStore();
  return (
    <header className="fixed inset-x-0 top-0 z-40 border-b border-line bg-bg/92 backdrop-blur-md lg:hidden">
      <div className="shell flex h-16 items-center gap-3 md:h-[4.5rem]">
        <button
          onClick={onOpen}
          className="-ml-2.5 grid size-11 place-items-center rounded-[4px] text-fg-2 transition-colors hover:bg-bg-3 hover:text-fg"
          aria-label="Open navigation"
          aria-haspopup="dialog"
        >
          <Menu size={20} />
        </button>
        <a href="#top" className="flex h-11 items-center gap-2.5" aria-label="CASCADE, back to top">
          <Logo className="size-7" />
          <span className="font-display text-[1.55rem] font-extrabold uppercase tracking-[0.04em]">Cascade</span>
        </a>
        <button
          onClick={() => setPalette(true)}
          className="-mr-2.5 ml-auto grid size-11 place-items-center rounded-[4px] text-fg-2 transition-colors hover:bg-bg-3 hover:text-fg"
          aria-label="Search"
        >
          <Search size={19} />
        </button>
      </div>
      <ScrollProgress axis="x" />
    </header>
  );
}

function Drawer({ open, onClose, active }: { open: boolean; onClose: () => void; active: string | null }) {
  const panel = useRef<HTMLDivElement>(null);

  // Modal behaviour: Esc closes, Tab stays inside, the page behind doesn't scroll, focus returns on close.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const el = panel.current;
    const focusables = () =>
      Array.from(panel.current?.querySelectorAll<HTMLElement>("a[href], button:not([disabled])") ?? []);
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return; // handled by something on top (the palette)
      if (e.key === "Escape") return onClose();
      if (e.key !== "Tab") return;
      const f = focusables();
      if (!f.length) return;
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    const unlock = lockScroll();
    addEventListener("keydown", onKey);
    return () => {
      removeEventListener("keydown", onKey);
      unlock();
      // After a link, focus is already on that section; only fall back to the Menu button when it was lost.
      restoreFocus(opener, el);
    };
  }, [open, onClose]);

  // Close if the viewport grows past the breakpoint where the fixed rail takes over.
  useEffect(() => {
    if (!open) return;
    const mq = matchMedia("(min-width: 64rem)");
    const onChange = () => mq.matches && onClose();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-[55] lg:hidden">
          <motion.div
            className="absolute inset-0 bg-bg/70 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25 }}
            onClick={onClose}
            aria-hidden
          />
          <motion.div
            ref={panel}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute inset-y-0 left-0 w-[min(18rem,85vw)] border-r border-line bg-bg-2 shadow-2xl"
            initial={{ x: "-100%" }}
            animate={{ x: 0 }}
            exit={{ x: "-100%" }}
            transition={{ duration: 0.35, ease: EASE }}
          >
            <SidebarBody
              compact={false}
              active={active}
              markerId="drawer-marker"
              onNavigate={onClose}
              headerAction={
                <button
                  onClick={onClose}
                  className="ml-auto grid size-8 place-items-center rounded-[4px] text-fg-3 transition-colors hover:bg-bg-3 hover:text-fg"
                  aria-label="Close navigation"
                >
                  <X size={16} />
                </button>
              }
            />
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
