import { AnimatePresence, motion } from "motion/react";
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { Footer } from "./components/Footer";
import { Logo, Nav } from "./components/Nav";
import { ErrorNote, SectionBoundary, Skeleton } from "./components/ui";
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
          <OpenAt target={location.hash.slice(1) || role.opens} />
          <Nav />
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
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Opens the page on the chosen section. Sections above it load data (and lazy chunks) and grow,
 *  so re-anchor a few times while the page settles, and stop as soon as the user scrolls themselves. */
function OpenAt({ target }: { target: string }) {
  useEffect(() => {
    let stop = false;
    const quit = () => (stop = true);
    const go = () => {
      if (stop) return;
      if (target === "top") scrollTo({ top: 0 });
      else document.getElementById(target)?.scrollIntoView();
    };
    const timers = [0, 300, 800, 1500, 2500].map((ms) => setTimeout(go, ms));
    const evs = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    evs.forEach((e) => addEventListener(e, quit, { passive: true }));
    return () => {
      timers.forEach(clearTimeout);
      evs.forEach((e) => removeEventListener(e, quit));
    };
  }, [target]);
  return null;
}
