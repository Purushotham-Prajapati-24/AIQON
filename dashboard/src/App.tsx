import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { CommandPalette } from "./components/CommandPalette";
import { Footer } from "./components/Footer";
import { Logo, Nav } from "./components/Nav";
import { ErrorNote, SectionBoundary, Skeleton } from "./components/ui";
import { focusSection } from "./lib/focus";
import { useStore } from "./lib/store";
import { Login } from "./sections/Login";
import { Hero } from "./sections/Hero";

// Above the fold loads eagerly; everything below is split into its own chunk and fetched in
// parallel right after the first paint, so the hero renders from a much smaller bundle.
const Fleet = lazy(() => import("./sections/Fleet").then((m) => ({ default: m.Fleet })));
const Shipment = lazy(() => import("./sections/Shipment").then((m) => ({ default: m.Shipment })));
const Fix = lazy(() => import("./sections/Fix").then((m) => ({ default: m.Fix })));
const Alerts = lazy(() => import("./sections/Alerts").then((m) => ({ default: m.Alerts })));
const Proof = lazy(() => import("./sections/Proof").then((m) => ({ default: m.Proof })));

function Lazy({ id, name, children }: { id: string; name: string; children: ReactNode }) {
  return (
    <SectionBoundary name={name}>
      <Suspense
        fallback={
          <section id={id} className="shell py-24">
            <Skeleton className="h-[60vh] w-full" label={`Loading ${name}`} />
          </section>
        }
      >
        {children}
      </Suspense>
    </SectionBoundary>
  );
}

export function App() {
  const { auth, role, worldError, retryWorld } = useStore();

  if (auth.status === "checking")
    return (
      <div className="grid min-h-svh place-items-center" role="status" aria-busy="true" aria-label="Checking your session">
        <Logo className="size-10 animate-pulse" />
      </div>
    );

  return (
    <AnimatePresence mode="wait">
      {auth.status === "out" || !role ? (
        <SectionBoundary name="Sign in" key="login">
          <Login />
        </SectionBoundary>
      ) : (
        <motion.div key={`app-${role.id}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.6 }}>
          <a
            href="#fleet"
            className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:bg-fg focus:px-3 focus:py-2 focus:text-bg"
          >
            Skip to fleet
          </a>
          <OpenAt fallback={role.opens} />
          <Nav />
          <CommandPalette />
          <Spotlight />
          <div className="transition-[padding] duration-300 ease-out-expo lg:pl-[var(--rail-offset)]">
            <main>
              {worldError && (
                <div className="shell pt-28">
                  <ErrorNote error={worldError} onRetry={retryWorld} />
                </div>
              )}
              <SectionBoundary name="Overview">
                <Hero />
              </SectionBoundary>
              <Lazy id="fleet" name="Fleet">
                <Fleet />
              </Lazy>
              <Lazy id="shipment" name="Shipment">
                <Shipment />
              </Lazy>
              <Lazy id="fix" name="Fix">
                <Fix />
              </Lazy>
              <Lazy id="alerts" name="Alerts">
                <Alerts />
              </Lazy>
              <Lazy id="proof" name="Proof">
                <Proof />
              </Lazy>
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

/** Opens the page on the chosen section. Sections above it load data (and lazy chunks) and grow,
 *  so re-anchor a few times while the page settles, and stop as soon as the user scrolls themselves. */
function OpenAt({ fallback }: { fallback: string }) {
  // Read once per sign-in: later in-page links change the hash, and must not re-run the jump.
  const [target] = useState(() => location.hash.slice(1) || fallback);
  useEffect(() => {
    let stop = false;
    const quit = () => (stop = true);
    const go = () => {
      if (stop) return;
      if (target === "top") scrollTo({ top: 0 });
      else document.getElementById(target)?.scrollIntoView();
    };
    const timers = [0, 300, 800, 1500, 2500].map((ms) => setTimeout(go, ms));
    // Keyboard and screen-reader users continue from the section the page opened on, not wherever the
    // sign-in button used to be. Sections below the hero are lazy: if focus landed on a loading placeholder
    // that has since been replaced, try again once the real section has mounted.
    const focus = () => {
      const a = document.activeElement;
      if (!stop && (!a || a === document.body || !a.isConnected)) focusSection(target);
    };
    timers.push(...[50, 800, 1500].map((ms) => setTimeout(focus, ms)));
    const evs = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    evs.forEach((e) => addEventListener(e, quit, { passive: true }));
    return () => {
      timers.forEach(clearTimeout);
      evs.forEach((e) => removeEventListener(e, quit));
    };
  }, [target]);
  return null;
}
