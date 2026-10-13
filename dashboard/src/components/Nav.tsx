import { AnimatePresence, motion, useScroll } from "motion/react";
import {
  Bell,
  CirclePlay,
  Flag,
  Globe,
  Lightbulb,
  LogOut,
  Menu,
  Moon,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  Sun,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { GUIDE } from "../lib/guide";
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

/** Scroll-spy: the section whose top passed 40% of the viewport. */
function useActiveSection(mode: unknown) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    const els = ["top", ...SECTIONS.map((s) => s.id)].map((id) => document.getElementById(id)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(e.target.id);
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [mode]);
  return active;
}

/**
 * Section navigation as a left sidebar. From `lg` up it is a fixed rail that collapses to icons
 * (remembered per browser); below that a slim top bar opens the same sidebar as a drawer.
 * The rail's width is published as `--rail` on <html> so the page can make room for it.
 */
export function Nav() {
  const { mode } = useStore();
  const active = useActiveSection(mode);
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
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

      <nav aria-label="Sections" className="flex-1 overflow-y-auto overscroll-contain py-4">
        <YourTask compact={compact} onNavigate={onNavigate} />
        {!compact && <p className="eyebrow mb-2 mt-6 px-5 text-[0.75rem]">Overview</p>}
        <ul className={compact ? "px-2" : "px-3"}>
          <NavItem id="top" label="Replay" icon={CirclePlay} active={active === "top"} compact={compact} markerId={markerId} onNavigate={onNavigate} />
        </ul>
        {!compact ? <p className="eyebrow mb-2 mt-5 px-5 text-[0.75rem]">Sections</p> : <div className="mx-4 my-4 border-t border-line" />}
        <ul className={`space-y-0.5 ${compact ? "px-2" : "px-3"}`}>
          {SECTIONS.map((s, k) => (
            <NavItem
              key={s.id}
              id={s.id}
              label={s.label}
              index={k + 1}
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

function NavItem({
  id,
  label,
  index,
  icon: Icon,
  active,
  compact,
  markerId,
  onNavigate,
}: {
  id: string;
  label: string;
  index?: number;
  icon: LucideIcon;
  active: boolean;
  compact: boolean;
  markerId: string;
  onNavigate?: () => void;
}) {
  const { role } = useStore();
  const question = GUIDE[id]?.question;
  const start = role?.opens === id;
  return (
    <li>
      <a
        href={`#${id}`}
        onClick={onNavigate}
        aria-current={active ? "location" : undefined}
        title={compact ? `${label}: ${question}${start ? " (start here)" : ""}` : undefined}
        className={`group relative flex items-center rounded-[4px] transition-colors ${
          compact ? "h-10 justify-center" : "min-h-10 gap-3 px-3 py-1.5"
        } ${active ? "bg-bg-3 text-fg" : "text-fg-3 hover:bg-bg-3/60 hover:text-fg"}`}
      >
        {active && (
          <motion.span
            layoutId={markerId}
            className="absolute inset-y-2 left-0 w-[2px] rounded-full bg-late"
            transition={{ duration: 0.35, ease: EASE }}
          />
        )}
        <Icon size={16} aria-hidden className={`shrink-0 self-start ${compact ? "self-center" : "mt-0.5"} ${active ? "text-late" : ""}`} />
        {compact && start && <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-late" aria-hidden />}
        {compact ? (
          <span className="sr-only">
            {label}: {question}
            {start && " (start here)"}
          </span>
        ) : (
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2 font-mono text-[0.78rem] uppercase tracking-[0.14em]">
              <span className="truncate">{label}</span>
              {start && (
                <span className="rounded-[3px] bg-late-wash px-1.5 py-px text-[0.75rem] tracking-[0.12em] text-late">Start</span>
              )}
              {index && <span className={`ml-auto text-[0.75rem] ${active ? "text-late" : "text-fg-3"}`}>0{index}</span>}
            </span>
            {question && (
              <span className={`mt-0.5 block text-[0.8rem] leading-snug ${active ? "text-fg-2" : "text-fg-3 group-hover:text-fg-2"}`}>
                {question}
              </span>
            )}
          </span>
        )}
      </a>
    </li>
  );
}

/** The signed-in role's job and where to begin, so nobody lands on the page without a next step. */
function YourTask({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const { role } = useStore();
  if (!role) return null;
  const k = SECTIONS.findIndex((s) => s.id === role.opens);
  const where = k < 0 ? "Replay" : `0${k + 1} ${SECTIONS[k].label}`;

  if (compact)
    return (
      <div className="px-2 pb-1">
        <a
          href={`#${role.opens}`}
          onClick={onNavigate}
          title={`Your task: ${role.task} Start at ${where}.`}
          className="grid h-10 place-items-center rounded-[4px] text-late transition-colors hover:bg-late-wash"
        >
          <Flag size={16} aria-hidden />
          <span className="sr-only">
            Your task: {role.task} Start at {where}.
          </span>
        </a>
      </div>
    );

  return (
    <section aria-labelledby="your-task" className="mx-3 rounded-[4px] border border-line bg-bg px-3.5 py-3">
      <p id="your-task" className="eyebrow flex items-center gap-2 text-[0.75rem]">
        <Flag size={12} aria-hidden className="text-late" />
        Your task
      </p>
      <p className="mt-2 text-[0.88rem] leading-snug text-fg">{role.task}</p>
      <a
        href={`#${role.opens}`}
        onClick={onNavigate}
        className="-my-1 mt-2 inline-flex items-center gap-1.5 py-2.5 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-late underline-offset-4 hover:underline"
      >
        Start at {where} →
      </a>
    </section>
  );
}

function SidebarFooter({ compact }: { compact: boolean }) {
  const { mode, theme, toggleTheme, tips, toggleTips, auth, signOut } = useStore();
  const user = auth.session?.user;
  const [signOutFailed, setSignOutFailed] = useState(false);
  const initials = user?.name.split(" ").map((p) => p[0]).join("").slice(0, 2);
  const modeLabel = mode === "live" ? "Live model" : "Recorded run";
  const modeTitle = mode === "live" ? "Connected to the CASCADE API" : "Showing a recorded run of the real model";

  const iconBtn = "grid size-9 shrink-0 place-items-center rounded-[4px] text-fg-2 transition-colors hover:bg-bg-3 hover:text-fg";

  return (
    <div className={`shrink-0 border-t border-line py-3 ${compact ? "space-y-1 px-2" : "space-y-2 px-3"}`}>
      <div className={compact ? "flex flex-col items-center gap-1" : "flex items-center gap-1"}>
        {mode && (
          <div
            className={`flex h-9 items-center gap-2.5 font-mono text-[0.75rem] uppercase tracking-[0.14em] text-fg-2 ${compact ? "justify-center" : "mr-auto px-3"}`}
            title={modeTitle}
          >
            <span className="relative flex size-2 shrink-0">
              {mode === "live" && <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-60" />}
              <span className={`relative size-2 rounded-full ${mode === "live" ? "bg-ok" : "bg-fg-3"}`} />
            </span>
            <span className={compact ? "sr-only" : ""}>{modeLabel}</span>
          </div>
        )}
        <button
          onClick={toggleTips}
          aria-pressed={tips}
          className={`${iconBtn} ${tips ? "text-[var(--risk-ink)]" : ""} ${!mode && !compact ? "ml-auto" : ""}`}
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
      </div>

      {user && (
        <button
          onClick={async () => {
            const ok = await signOut();
            setSignOutFailed(!ok);
            if (ok) scrollTo({ top: 0 });
          }}
          className={`group flex w-full items-center gap-3 rounded-[4px] border p-1.5 text-left transition-colors hover:text-fg ${
            signOutFailed ? "border-late text-late" : "border-line text-fg-2 hover:border-fg-2"
          } ${compact ? "justify-center" : ""}`}
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
            <span className="min-w-0 flex-1" aria-hidden>
              <span className="block truncate text-[0.85rem] leading-tight text-fg">{signOutFailed ? "Retry sign-out" : user.name}</span>
              <span className="block truncate font-mono text-[0.75rem] uppercase tracking-[0.12em] text-fg-3">{user.title}</span>
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
    const focusables = () =>
      Array.from(panel.current?.querySelectorAll<HTMLElement>("a[href], button:not([disabled])") ?? []);
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
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
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    addEventListener("keydown", onKey);
    return () => {
      removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      opener?.focus();
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
