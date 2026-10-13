import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MotionConfig } from "motion/react";
// Only the subsets the UI uses (Latin; Greek for "λ"). The browser still downloads a face only
// when a glyph in its unicode-range appears, but shipping fewer @font-face rules keeps the CSS lean.
import "@fontsource/big-shoulders-display/latin-500";
import "@fontsource/big-shoulders-display/latin-700";
import "@fontsource/big-shoulders-display/latin-800";
import "@fontsource/ibm-plex-sans/latin-400";
import "@fontsource/ibm-plex-sans/latin-500";
import "@fontsource/ibm-plex-sans/latin-600";
import "@fontsource/ibm-plex-sans/greek-400";
import "@fontsource/ibm-plex-mono/latin-400";
import "@fontsource/ibm-plex-mono/latin-500";
import "./index.css";
import { App } from "./App";
import { StoreProvider } from "./lib/store";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <StoreProvider>
        <App />
      </StoreProvider>
    </MotionConfig>
  </StrictMode>,
);
