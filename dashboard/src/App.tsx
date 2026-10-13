import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { Footer } from "./components/Footer";
import { Logo, Nav } from "./components/Nav";
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
          <main>
            <Hero />
            <Fleet />
            <Shipment />
            <Fix />
            <Alerts />
            <Proof />
          </main>
          <Footer />
        </motion.div>
      )}
    </AnimatePresence>
  );
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
    const evs = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    evs.forEach((e) => addEventListener(e, quit, { passive: true }));
    return () => {
      timers.forEach(clearTimeout);
      evs.forEach((e) => removeEventListener(e, quit));
    };
  }, [target]);
  return null;
}
