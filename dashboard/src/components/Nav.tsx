import { motion, useMotionValueEvent, useScroll } from "motion/react";
import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
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

export function Nav() {
  const { mode, theme, toggleTheme } = useStore();
  const { scrollY, scrollYProgress } = useScroll();
  const [solid, setSolid] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  useMotionValueEvent(scrollY, "change", (v) => setSolid(v > 40));

  // Scroll-spy: the section whose top passed 40% of the viewport.
  useEffect(() => {
    const els = SECTIONS.map((s) => document.getElementById(s.id)).filter(Boolean) as HTMLElement[];
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) setActive(e.target.id);
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [mode]);

  return (
    <header
      className={`fixed inset-x-0 top-0 z-50 transition-[background-color,border-color] duration-500 ${
        solid ? "border-b border-line bg-bg/92 backdrop-blur-md" : "border-b border-transparent"
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
          {mode && (
            <span
              className="hidden items-center gap-2 rounded-[4px] border border-line px-2.5 py-1.5 font-mono text-[0.7rem] uppercase tracking-[0.14em] text-fg-2 sm:inline-flex"
              title={mode === "live" ? "Connected to the CASCADE API" : "Showing a recorded run of the real model"}
            >
              <span className="relative flex size-2">
                {mode === "live" && <span className="absolute inset-0 animate-ping rounded-full bg-ok opacity-60" />}
                <span className={`relative size-2 rounded-full ${mode === "live" ? "bg-ok" : "bg-fg-3"}`} />
              </span>
              {mode === "live" ? "Live model" : "Recorded run"}
            </span>
          )}
          <button
            onClick={toggleTheme}
            className="grid size-9 place-items-center rounded-[4px] border border-line text-fg-2 transition-colors hover:border-fg-2 hover:text-fg"
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </div>
      <motion.div className="h-px origin-left bg-late" style={{ scaleX: scrollYProgress }} />
    </header>
  );
}
