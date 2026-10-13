import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, detectMode, fallbackReason, onModeChange, type Mode } from "./api";
import { roleById, type Role } from "./roles";
import { session as auth, type Session } from "./session";
import type { World } from "./types";

interface Store {
  mode: Mode | null;
  /** Set when the live API went away mid-session and the app switched to the recorded run. */
  fallback: string | null;
  world: World | null;
  worldError: Error | null;
  retryWorld: () => void;
  /** Fleet clock, in days relative to the world's "now" (−21 … 0). */
  days: number;
  setDays: (d: number) => void;
  selected: string;
  /** Select a shipment and, optionally, bring its detail into view. */
  select: (sid: string, scroll?: boolean) => void;
  theme: "dark" | "light";
  toggleTheme: () => void;
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

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function initialTheme(): "dark" | "light" {
  // index.html sets data-theme before first paint (no flash); read it back so React agrees.
  const t = document.documentElement.dataset.theme;
  if (t === "dark" || t === "light") return t;
  return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [fallback, setFallback] = useState<string | null>(null);
  const [world, setWorld] = useState<World | null>(null);
  const [worldError, setWorldError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [days, setDays] = useState(0);
  const [selected, setSelected] = useState(HERO_SHIPMENT);
  const [theme, setTheme] = useState(initialTheme);
  const [authState, setAuth] = useState<Store["auth"]>({ status: "checking", session: null, notice: null });

  useEffect(() => {
    detectMode().then(setMode);
    auth.current().then((s) => setAuth({ status: s ? "in" : "out", session: s, notice: null }));
    const onSignedOut = () =>
      setAuth({ status: "out", session: null, notice: "Your session ended. Sign in again to continue." });
    addEventListener("cascade:signed-out", onSignedOut);
    const offMode = onModeChange((m) => {
      setMode(m);
      setFallback(fallbackReason());
    });
    return () => {
      removeEventListener("cascade:signed-out", onSignedOut);
      offMode();
    };
  }, []);

  // Data loads only for a signed-in user (in CASCADE_AUTH=required mode it would be refused).
  // Re-runs on retry and when the source changes (e.g. live -> recorded after an outage).
  useEffect(() => {
    if (authState.status !== "in") return;
    let alive = true;
    setWorldError(null);
    api.world().then(
      (w) => alive && setWorld(w),
      (e: Error) => alive && setWorldError(e),
    );
    return () => {
      alive = false;
    };
  }, [attempt, mode, authState.status]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]:not([media])')?.setAttribute("content", theme === "light" ? "#f3f0e8" : "#0a0f12");
    try {
      localStorage.setItem("cascade-theme", theme);
    } catch {
      /* storage blocked */
    }
  }, [theme]);

  const select = useCallback((sid: string, scroll = false) => {
    setSelected(sid);
    if (scroll)
      document.getElementById("shipment")?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" });
  }, []);
  const retryWorld = useCallback(() => setAttempt((a) => a + 1), []);
  const signedIn = useCallback((s: Session) => setAuth({ status: "in", session: s, notice: null }), []);
  const sessionKind = authState.session?.kind;
  const signOut = useCallback(
    async (notice?: string) => {
      try {
        await auth.signOut(sessionKind);
      } catch {
        return false;
      }
      setAuth({ status: "out", session: null, notice: notice ?? null });
      return true;
    },
    [sessionKind],
  );
  const role = useMemo(() => roleById(authState.session?.user.role ?? null), [authState.session]);
  const toggleTheme = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);

  const value = useMemo(
    () => ({
      mode, fallback, world, worldError, retryWorld, days, setDays, selected, select, theme, toggleTheme,
      auth: authState, role, signedIn, signOut,
    }),
    [mode, fallback, world, worldError, retryWorld, days, selected, select, theme, toggleTheme, authState, role, signedIn, signOut],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStore outside StoreProvider");
  return s;
}
