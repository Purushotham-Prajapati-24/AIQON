import { Footer } from "./components/Footer";
import { Nav } from "./components/Nav";
import { Alerts } from "./sections/Alerts";
import { Fix } from "./sections/Fix";
import { Fleet } from "./sections/Fleet";
import { Hero } from "./sections/Hero";
import { Proof } from "./sections/Proof";
import { Shipment } from "./sections/Shipment";

export function App() {
  return (
    <>
      <a href="#fleet" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:bg-fg focus:px-3 focus:py-2 focus:text-bg">
        Skip to fleet
      </a>
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
    </>
  );
}
