import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, detectMode, type Mode } from "./api";
import type { World } from "./types";

interface Store {
  mode: Mode | null;
  world: World | null;
  /** Fleet clock, in days relative to the world's "now" (−21 … 0). */
  days: number;
  setDays: (d: number) => void;
  selected: string;
  /** Select a shipment and, optionally, bring its detail into view. */
  select: (sid: string, scroll?: boolean) => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
}

const Ctx = createContext<Store | null>(null);
export const HERO_SHIPMENT = "SHP-000174";

function initialTheme(): "dark" | "light" {
  try {
    const t = localStorage.getItem("cascade-theme");
    if (t === "dark" || t === "light") return t;
  } catch {
    /* storage blocked */
  }
  return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [world, setWorld] = useState<World | null>(null);
  const [days, setDays] = useState(0);
  const [selected, setSelected] = useState(HERO_SHIPMENT);
  const [theme, setTheme] = useState(initialTheme);

  useEffect(() => {
    detectMode().then(setMode);
    api.world().then(setWorld);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("cascade-theme", theme);
    } catch {
      /* storage blocked */
    }
  }, [theme]);

  const select = useCallback((sid: string, scroll = false) => {
    setSelected(sid);
    if (scroll) document.getElementById("shipment")?.scrollIntoView({ behavior: "smooth" });
  }, []);
  const toggleTheme = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);

  const value = useMemo(
    () => ({ mode, world, days, setDays, selected, select, theme, toggleTheme }),
    [mode, world, days, selected, select, theme, toggleTheme],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside StoreProvider");
  return s;
}
