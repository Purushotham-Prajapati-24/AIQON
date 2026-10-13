import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, detectMode, type Mode } from "./api";
import { roleById, type Role } from "./roles";
import { session as auth, type Session } from "./session";
import { focusSection } from "./focus";
import type { World } from "./types";

/** Where a shipment was opened from, so the Shipment section can offer a way back. */
export interface Origin {
  label: string;
  section: string;
  el: Element | null;
}

interface Store {
  mode: Mode | null;
  world: World | null;
  /** Fleet clock, in days relative to the world's "now" (−21 … 0). */
  days: number;
  setDays: (d: number) => void;
  selected: string;
  /** Select a shipment and, optionally, bring its detail into view (remembering `from` for the way back). */
  select: (sid: string, scroll?: boolean, from?: Origin) => void;
  origin: Origin | null;
  /** Return to where the current shipment was opened from. */
  goBack: () => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
  /** Show the "what you can do here" strip under each section heading. */
  /** Command palette (⌘K). */
  palette: boolean;
  setPalette: (open: boolean) => void;
  tips: boolean;
  toggleTips: () => void;
  /** "checking" while the saved session is verified; "out" shows the sign-in screen. */
  auth: { status: "checking" | "in" | "out"; session: Session | null; notice: string | null };
  /** The signed-in user's role: where the page opens and how explanations are worded. */
  role: Role | null;
  signedIn: (s: Session) => void;
  /** False when the API could not end the session; the user stays signed in. */
  signOut: (notice?: string) => Promise<boolean>;
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

function initialTips() {
  try {
    return localStorage.getItem("cascade-tips") !== "off";
  } catch {
    return true;
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [world, setWorld] = useState<World | null>(null);
  const [days, setDays] = useState(0);
  const [selected, setSelected] = useState(HERO_SHIPMENT);
  const [theme, setTheme] = useState(initialTheme);
  const [tips, setTips] = useState(initialTips);
  const [palette, setPalette] = useState(false);
  const [origin, setOrigin] = useState<Origin | null>(null);
  const [authState, setAuth] = useState<Store["auth"]>({ status: "checking", session: null, notice: null });

  useEffect(() => {
    detectMode().then(setMode);
    auth.current().then((s) => setAuth({ status: s ? "in" : "out", session: s, notice: null }));
    const onSignedOut = () =>
      setAuth({ status: "out", session: null, notice: "Your session ended. Sign in again to continue." });
    addEventListener("cascade:signed-out", onSignedOut);
    return () => removeEventListener("cascade:signed-out", onSignedOut);
  }, []);

  // Data loads only for a signed-in user (in CASCADE_AUTH=required mode it would be refused).
  useEffect(() => {
    if (authState.status === "in") api.world().then(setWorld, () => undefined);
  }, [authState.status]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("cascade-theme", theme);
    } catch {
      /* storage blocked */
    }
  }, [theme]);

  useEffect(() => {
    try {
      localStorage.setItem("cascade-tips", tips ? "on" : "off");
    } catch {
      /* storage blocked */
    }
  }, [tips]);

  const select = useCallback((sid: string, scroll = false, from?: Origin) => {
    setSelected(sid);
    setOrigin(scroll && from ? from : null);
    if (scroll) {
      document.getElementById("shipment")?.scrollIntoView({ behavior: "smooth" });
      focusSection("shipment");
    }
  }, []);
  const goBack = useCallback(() => {
    if (!origin) return;
    const el = (origin.el?.isConnected ? origin.el : document.getElementById(origin.section)) as HTMLElement | null;
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    if (el && el.tabIndex >= 0) el.focus({ preventScroll: true });
    else focusSection(origin.section);
    setOrigin(null);
  }, [origin]);
  const signedIn = useCallback((s: Session) => setAuth({ status: "in", session: s, notice: null }), []);
  const signOut = useCallback(async (notice?: string) => {
    try {
      await auth.signOut();
    } catch {
      return false;
    }
    setAuth({ status: "out", session: null, notice: notice ?? null });
    return true;
  }, []);
  const role = useMemo(() => roleById(authState.session?.user.role ?? null), [authState.session]);
  const toggleTheme = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  const toggleTips = useCallback(() => setTips((t) => !t), []);

  const value = useMemo(
    () => ({ mode, world, days, setDays, selected, select, origin, goBack, theme, toggleTheme, palette, setPalette, tips, toggleTips, auth: authState, role, signedIn, signOut }),
    [mode, world, days, selected, select, origin, goBack, theme, toggleTheme, palette, tips, toggleTips, authState, role, signedIn, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside StoreProvider");
  return s;
}
