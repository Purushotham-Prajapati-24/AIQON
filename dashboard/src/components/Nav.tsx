import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "motion/react";
import { LogOut, Menu, Moon, Sun, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useStore } from "../lib/store";

export const SECTIONS = [
  { id: "fleet", label: "Fleet" },
  { id: "shipment", label: "Shipment" },
  { id: "fix", label: "Fix" },
  { id: "alerts", label: "Alerts" },
  { id: "proof", label: "Proof" },
];

export function Logo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M4 8h8v6h8v6h8" fill="none" stroke="var(--late)" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="28" cy="20" r="2.6" fill="var(--fg)" />
    </svg>
  );
}

function SourceBadge() {
  const { mode, fallback } = useStore();
  if (!mode) return null;
  const live = mode === "live";
  return (
    <span
      className="hidden items-center gap-2 rounded-[4px] border border-line px-2.5 py-1.5 font-mono text-[0.7rem] uppercase tracking-[0.14em] text-fg-2 sm:inline-flex"
      title={
        live
          ? "Connected to the CASCADE API: every number is computed now."
          : fallback
            ? `${fallback} Showing a recorded run of the same model.`
            : "Showing a recorded run of the real model (start the API for live answers)."
      }
      role="status"
    >
      <span className="relative flex size-2" aria-hidden>
        {live && <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-60" />}
        <span className={`relative size-2 rounded-full ${live ? "bg-ok" : fallback ? "bg-risk" : "bg-fg-3"}`} />
      </span>
      {live ? "Live model" : fallback ? "Recorded run · API offline" : "Recorded run"}
    </span>
  );
}

export function Nav() {
  const { mode, theme, toggleTheme, auth, signOut } = useStore();
  const user = auth.session?.user;
  const { scrollY, scrollYProgress } = useScroll();
  const [solid, setSolid] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const menuBtn = useRef<HTMLButtonElement>(null);
  const [signOutFailed, setSignOutFailed] = useState(false);
  useMotionValueEvent(scrollY, "change", (v) => setSolid(v > 40));

  // Scroll-spy: the last section whose top passed 40% of the viewport. Reads the live DOM on each
  // (rAF-throttled) scroll, so lazily mounted sections are picked up without re-subscribing.
  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      const line = innerHeight * 0.4;
      let cur: string | null = null;
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= line) cur = s.id;
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

  // Mobile menu: Escape closes it and returns focus to the button.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        menuBtn.current?.focus();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,border-color] duration-500 ${
        solid || open ? "border-b border-line bg-bg/92 backdrop-blur-md" : "border-b border-transparent"
      }`}
    >
      <div className="shell flex h-16 items-center gap-6 md:h-[4.5rem]">
        <a href="#top" className="flex items-center gap-2.5" aria-label="CASCADE, back to top">
          <Logo className="size-7" />
          <span className="font-display text-[1.55rem] font-extrabold uppercase tracking-[0.04em]">Cascade</span>
        </a>
        <nav aria-label="Sections" className="ml-auto hidden md:block">
          <ul className="flex items-center gap-1">
            {SECTIONS.map((s, k) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  aria-current={active === s.id ? "location" : undefined}
                  className={`relative flex items-center gap-2 px-3 py-2 font-mono text-[0.78rem] uppercase tracking-[0.14em] transition-colors ${
                    active === s.id ? "text-fg" : "text-fg-3 hover:text-fg"
                  }`}
                >
                  <span className={active === s.id ? "text-late" : ""}>0{k + 1}</span>
                  {s.label}
                  {active === s.id && (
                    <motion.span layoutId="nav-dot" className="absolute inset-x-3 -bottom-px h-[2px] bg-late" />
                  )}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto flex items-center gap-2 md:ml-4">
          {user && (
            <button
              onClick={async () => {
                const ok = await signOut();
                setSignOutFailed(!ok);
                if (ok) scrollTo({ top: 0 });
              }}
              className={`group flex h-10 items-center gap-2.5 rounded-[4px] border py-1 md:h-9 pl-1 pr-2.5 transition-colors hover:text-fg ${signOutFailed ? "border-late text-late" : "border-line text-fg-2 hover:border-fg-2"}`}
              title={signOutFailed ? "Couldn't reach the server to end your session. Click to try again." : `Signed in as ${user.name} (${user.title}). Session ends ${new Date((auth.session?.expiresAt ?? 0) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.`}
            >
              <span className="grid size-7 place-items-center rounded-full bg-bg-3 font-mono text-[0.7rem] text-fg" aria-hidden>
                {user.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}
              </span>
              <span className="hidden font-mono text-[0.7rem] uppercase tracking-[0.14em] lg:inline">{signOutFailed ? "Retry sign-out" : user.name.split(" ")[0]}</span>
              <LogOut size={14} aria-hidden />
              <span className="sr-only">Sign out {user.name}</span>
            </button>
          )}
          <SourceBadge />
          <button
            onClick={toggleTheme}
            className="grid size-10 place-items-center rounded-[4px] border border-line text-fg-2 transition-colors hover:border-fg-2 hover:text-fg md:size-9"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            ref={menuBtn}
            onClick={() => setOpen((o) => !o)}
            className="grid size-10 place-items-center rounded-[4px] border border-line text-fg-2 transition-colors hover:border-fg-2 hover:text-fg md:hidden"
            aria-label={open ? "Close sections menu" : "Open sections menu"}
            aria-expanded={open}
            aria-controls="mobile-menu"
          >
            {open ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {open && (
          <motion.nav
            id="mobile-menu"
            aria-label="Sections"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden border-t border-line bg-bg shadow-[0_24px_48px_-24px_rgb(0_0_0/0.45)] md:hidden"
          >
            <ul className="shell grid py-2">
              {SECTIONS.map((s, k) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    onClick={() => setOpen(false)}
                    aria-current={active === s.id ? "location" : undefined}
                    className="flex items-baseline gap-4 border-b border-line py-4 font-display text-[1.6rem] font-bold uppercase leading-none last:border-b-0"
                  >
                    <span className="font-mono text-[0.78rem] text-late">0{k + 1}</span>
                    {s.label}
                  </a>
                </li>
              ))}
            </ul>
          </motion.nav>
        )}
      </AnimatePresence>
      <motion.div className="h-px origin-left bg-late" style={{ scaleX: scrollYProgress }} aria-hidden />
    </header>
  );
}
