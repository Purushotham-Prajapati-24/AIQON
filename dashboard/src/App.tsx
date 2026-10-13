import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { CommandPalette } from "./components/CommandPalette";
import { Footer } from "./components/Footer";
import { Logo, Nav } from "./components/Nav";
import { focusSection } from "./lib/focus";
import { useStore } from "./lib/store";
import { Alerts } from "./sections/Alerts";
import { Login } from "./sections/Login";
import { Fix } from "./sections/Fix";
import { Fleet } from "./sections/Fleet";
import { Hero } from "./sections/Hero";
import { Proof } from "./sections/Proof";
import { Shipment } from "./sections/Shipment";

export function App() {
  const { auth, role } = useStore();

  if (auth.status === "checking")
    return (
      <div className="grid min-h-svh place-items-center" aria-busy="true" aria-label="Checking your session">
        <Logo className="size-10 animate-pulse" />
      </div>
    );

  return (
    <AnimatePresence mode="wait">
      {auth.status === "out" || !role ? (
        <Login key="login" />
      ) : (
        <motion.div key={`app-${role.id}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6 }}>
          <a href="#fleet" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:bg-fg focus:px-3 focus:py-2 focus:text-bg">
            Skip to fleet
          </a>
          <OpenAt target={location.hash.slice(1) || role.opens} />
          <Nav />
          <CommandPalette />
          <Spotlight />
          <div className="transition-[padding] duration-300 ease-out-expo lg:pl-[var(--rail-offset)]">
            <main>
              <Hero />
              <Fleet />
              <Shipment />
              <Fix />
              <Alerts />
              <Proof />
            </main>
            <Footer />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** One delegated listener feeds the pointer position to whichever `[data-spotlight]` element is under it. */
function Spotlight() {
  useEffect(() => {
    if (!matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    let el: HTMLElement | null = null;
    const on = (e: PointerEvent) => {
      const t = (e.target as Element | null)?.closest?.<HTMLElement>("[data-spotlight]") ?? null;
      if (el && el !== t) el.style.removeProperty("--mx");
      el = t;
      if (!t) return;
      const r = t.getBoundingClientRect();
      t.style.setProperty("--mx", `${e.clientX - r.left}px`);
      t.style.setProperty("--my", `${e.clientY - r.top}px`);
    };
    addEventListener("pointermove", on, { passive: true });
    return () => removeEventListener("pointermove", on);
  }, []);
  return null;
}

/** Opens the page on the chosen section. Sections above it load data and grow, so re-anchor a few times
 *  while the page settles, and stop as soon as the user scrolls themselves. */
function OpenAt({ target }: { target: string }) {
  useEffect(() => {
    let stop = false;
    const quit = () => (stop = true);
    const go = () => {
      if (stop) return;
      if (target === "top") scrollTo({ top: 0 });
      else document.getElementById(target)?.scrollIntoView();
    };
    const timers = [0, 300, 800, 1500].map((ms) => setTimeout(go, ms));
    // Keyboard and screen-reader users continue from the section the page opened on, not wherever the
    // sign-in button used to be.
    timers.push(setTimeout(() => focusSection(target), 50));
    const evs = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    evs.forEach((e) => addEventListener(e, quit, { passive: true }));
    return () => {
      timers.forEach(clearTimeout);
      evs.forEach((e) => removeEventListener(e, quit));
    };
  }, [target]);
  return null;
}
