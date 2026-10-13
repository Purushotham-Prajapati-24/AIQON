import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, Copy, Eye, EyeOff, LoaderCircle, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Contours } from "../components/Contours";
import { Logo } from "../components/Nav";
import { useAsync } from "../hooks/useAsync";
import { api, API } from "../lib/api";
import { day, dayLong } from "../lib/format";
import { roleById, type RoleId } from "../lib/roles";
import { session, SignInError, type User } from "../lib/session";
import { HERO_SHIPMENT, useStore } from "../lib/store";

const EASE = [0.16, 1, 0.3, 1] as const;
const OPENS: Record<string, string> = { fleet: "Fleet", shipment: "Shipment", proof: "Proof", top: "the story" };

/** Sign-in: one click on a demo account, or a username and password. The session is a signed JWT
 *  in an httpOnly cookie set by the API; offline previews say so instead of pretending. */
export function Login() {
  const { mode, theme, toggleTheme, signedIn, auth } = useStore();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const accounts = useAsync(() => session.demoUsers(), []);
  const users = accounts.data?.users ?? [];
  /** The server turned one-click demo sign-in off (CASCADE_DEMO_LOGIN=0, or required mode). */
  const noDemo = !!accounts.data && users.length === 0;
  const offline = accounts.data?.offline ?? mode === "snapshot";

  // Live figures for each account, only when the API lets anonymous reads through.
  const figures = useAsync(async () => {
    const m = await detectAnonymousReads();
    if (!m) return null;
    const world = await api.world();
    const [f, model, s] = await Promise.all([api.fleet(0, world.now), api.model(), api.moment(HERO_SHIPMENT, world.now)]);
    const late = f.fleet.active.filter((r) => r.risk_tier === "LATE").length;
    return {
      planner: { v: `${late} late`, l: `of ${f.fleet.active.length} on the way` },
      support: { v: day(s.ops.eta.p50), l: `${HERO_SHIPMENT} arrives` },
      analyst: { v: `−${Math.round(model.metrics.mae_improvement_vs_B1 * 100)}%`, l: "error vs simple rule" },
      first: { v: `${Math.round(s.ops.delay_hours.p50 / 24)} days`, l: "late at the door" },
      asOf: world.now,
    };
  }, [mode]);

  const run = async (key: string, fn: () => Promise<Parameters<typeof signedIn>[0]>) => {
    if (busy) return;
    setBusy(key);
    setError(null);
    try {
      const s = await fn();
      setTimeout(() => signedIn(s), 450);
    } catch (e) {
      setBusy(null);
      setError(
        e instanceof SignInError
          ? e.status === 429
            ? "Too many attempts. Wait a minute, then try again."
            : e.status === 401
              ? "That username and password don't match."
              : e.message
          : "Can't reach the CASCADE API. Check that it is running.",
      );
    }
  };
  const quick = (u: User) => run(u.id, () => session.signInAs(u.id));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === "INPUT") return;
      const k = Number(e.key);
      if (k >= 1 && k <= users.length && !e.metaKey && !e.ctrlKey && !e.altKey) quick(users[k - 1]);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  return (
    <motion.main
      key="login"
      className="relative isolate flex min-h-svh flex-col overflow-hidden"
      exit={{ opacity: 0, y: -24, transition: { duration: 0.5, ease: EASE } }}
    >
      <Contours className="inset-x-0 top-0 h-svh" />

      <header className="shell relative flex h-16 items-center gap-3 md:h-[4.5rem]">
        <Logo className="size-7" />
        <span className="font-display text-[1.55rem] font-extrabold uppercase tracking-[0.04em]">Cascade</span>
        <button
          onClick={toggleTheme}
          className="ml-auto grid size-9 place-items-center rounded-[4px] border border-line text-fg-2 transition-colors hover:border-fg-2 hover:text-fg"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      <div className="shell relative grid flex-1 items-center gap-12 py-8 lg:grid-cols-12 lg:gap-16 lg:py-10">
        {/* Accounts */}
        <section className="lg:col-span-7" aria-labelledby="signin-title">
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.1 }}
            className="eyebrow flex flex-wrap items-center gap-x-3 gap-y-1"
          >
            <span className="text-late">Shipment delay control</span>
            <span className="h-px w-6 bg-line-2" />
            {figures.data ? `Data as of ${dayLong(figures.data.asOf)}` : offline ? "Offline preview" : "Live model"}
          </motion.p>

          <h1 id="signin-title" className="mt-6 font-display text-[clamp(3.2rem,6.4vw,6rem)] font-extrabold uppercase leading-[0.86] tracking-[-0.015em]">
            {["Sign in", <span className="text-fg-3">to the delay desk.</span>].map((l, k) => (
              <span key={k} className="block overflow-hidden pb-[0.05em]">
                <motion.span className="block" initial={{ y: "108%" }} animate={{ y: "0%" }} transition={{ duration: 1.1, ease: EASE, delay: 0.1 + k * 0.1 }}>
                  {l}
                </motion.span>
              </span>
            ))}
          </h1>
          <p className="mt-5 max-w-lg text-[1.1rem] text-fg-2">
            {noDemo
              ? "Use the account your administrator gave you. Each account opens where that person starts their day."
              : "Pick a demo account to go straight in. Each one opens where that person starts their day."}
          </p>

          <ol className={`mt-9 border-t border-line ${noDemo ? "hidden" : ""}`} aria-label="Demo accounts">
            {accounts.loading && !users.length && [0, 1, 2, 3].map((k) => <li key={k} className="h-[5.25rem] animate-pulse border-b border-line bg-bg-2/40" />)}
            {accounts.error && <li className="py-6 text-late">Can't load demo accounts: {accounts.error.message}</li>}
            {users.map((u, k) => {
              const role = roleById(u.role);
              const fig = figures.data?.[u.role as RoleId];
              const on = busy === u.id;
              const dim = busy !== null && !on;
              return (
                <motion.li
                  key={u.id}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: dim ? 0.25 : 1, y: 0 }}
                  transition={{ duration: 0.7, ease: EASE, delay: busy ? 0 : 0.3 + k * 0.07 }}
                  className="border-b border-line"
                >
                  <button
                    onClick={() => quick(u)}
                    disabled={busy !== null}
                    aria-keyshortcuts={String(k + 1)}
                    aria-label={`Sign in as ${u.name}, ${u.title}`}
                    className="group relative grid w-full grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-x-4 overflow-hidden py-4 text-left md:grid-cols-[3.25rem_minmax(0,1fr)_minmax(0,10.5rem)_2rem] md:gap-x-6"
                  >
                    <motion.span aria-hidden className="absolute inset-0 -z-10 origin-left bg-late-wash" initial={false} animate={{ scaleX: on ? 1 : 0 }} transition={{ duration: 0.55, ease: EASE }} />
                    <span className="absolute inset-0 -z-20 bg-bg-2 opacity-0 transition-opacity duration-300 group-hover:opacity-100" aria-hidden />

                    <span
                      className={`grid size-11 place-items-center rounded-full border font-mono text-[0.85rem] transition-colors ${
                        on ? "border-late bg-late text-bg" : "border-line-2 text-fg-2 group-hover:border-late group-hover:text-late"
                      }`}
                      aria-hidden
                    >
                      {u.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}
                    </span>
                    <span className="min-w-0">
                      <span className="block truncate font-display text-[clamp(1.6rem,2.4vw,2.2rem)] font-extrabold uppercase leading-none transition-transform duration-500 ease-out group-hover:translate-x-1.5">
                        {u.name}
                      </span>
                      <span className="mt-1.5 block text-[0.95rem] text-fg-2 md:truncate">
                        {u.title} · {u.team}
                        {role && <span className="text-fg-3"> · opens on {OPENS[role.opens]}</span>}
                      </span>
                    </span>
                    <span className="hidden text-right md:block">
                      {fig ? (
                        <>
                          <span className="num block whitespace-nowrap text-[1.9rem] uppercase">{fig.v}</span>
                          <span className="mt-0.5 block whitespace-nowrap font-mono text-[0.75rem] uppercase tracking-[0.12em] text-fg-3">{fig.l}</span>
                        </>
                      ) : figures.loading ? (
                        <span className="inline-block h-9 w-24 animate-pulse rounded-[4px] bg-bg-3" />
                      ) : null}
                    </span>
                    <span className="justify-self-end">
                      {on ? (
                        <LoaderCircle size={20} className="animate-spin text-late" aria-label="Signing in" />
                      ) : (
                        <ArrowRight size={20} className="text-fg-3 transition-all duration-300 group-hover:translate-x-1 group-hover:text-late" />
                      )}
                    </span>
                  </button>
                </motion.li>
              );
            })}
          </ol>
          {!noDemo && <p className="mt-5 hidden font-mono text-[0.75rem] uppercase tracking-[0.16em] text-fg-3 sm:block">Press 1–4 to sign in as that account</p>}
        </section>

        {/* Credentials */}
        <motion.section
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: EASE, delay: 0.45 }}
          className="lg:col-span-5"
          aria-labelledby="form-title"
        >
          <CredentialsForm
            busy={busy === "form"}
            disabled={busy !== null}
            error={error}
            notice={auth.notice}
            hint={accounts.data?.passwordHint ?? null}
            offline={offline}
            onSubmit={(u, p) => run("form", () => session.signIn(u, p))}
          />
        </motion.section>
      </div>
    </motion.main>
  );
}

/** True when data routes answer without a session (CASCADE_AUTH=optional or the offline preview). */
async function detectAnonymousReads(): Promise<boolean> {
  try {
    const r = await fetch(`${API}/v1/auth/config`, { credentials: "include" });
    if (!r.ok) return true; // older API without auth routes, or the recorded run: reads are open
    return (await r.json()).mode !== "required";
  } catch {
    return true;
  }
}

function CredentialsForm({
  busy,
  disabled,
  error,
  notice,
  hint,
  offline,
  onSubmit,
}: {
  busy: boolean;
  disabled: boolean;
  error: string | null;
  notice: string | null;
  hint: string | null;
  offline: boolean;
  onSubmit: (username: string, password: string) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);
  const userRef = useRef<HTMLInputElement>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return userRef.current?.focus();
    onSubmit(username.trim(), password);
  };
  const copy = async () => {
    if (!hint) return;
    try {
      await navigator.clipboard.writeText(hint);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setPassword(hint);
    }
  };

  return (
    <form onSubmit={submit} className="rounded-md border border-line-2 bg-bg-2/80 p-6 backdrop-blur-sm md:p-8" noValidate>
      <h2 id="form-title" className="font-display text-[2rem] font-extrabold uppercase leading-none">
        Use a password
      </h2>
      <p className="mt-2 text-[0.95rem] text-fg-2">Usernames are the first names: priya, marco, lena or reviewer.</p>

      <AnimatePresence>
        {notice && (
          <motion.p initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} role="status" className="mt-5 rounded-[4px] border border-risk/40 bg-risk/10 px-3 py-2 text-[0.92rem] text-fg">
            {notice}
          </motion.p>
        )}
      </AnimatePresence>

      <label htmlFor="username" className="eyebrow mt-7 block">
        Username
      </label>
      <input
        id="username"
        ref={userRef}
        autoComplete="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        disabled={disabled}
        className="mt-2 w-full rounded-[4px] border border-line-2 bg-bg px-4 py-3 text-[1.05rem] text-fg outline-none transition-colors placeholder:text-fg-3 focus:border-fg disabled:opacity-60"
        placeholder="priya"
      />

      <label htmlFor="password" className="eyebrow mt-5 block">
        Password
      </label>
      <div className="relative mt-2">
        <input
          id="password"
          type={show ? "text" : "password"}
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={disabled}
          aria-invalid={!!error}
          aria-describedby={error ? "signin-error" : undefined}
          className="w-full rounded-[4px] border border-line-2 bg-bg py-3 pl-4 pr-12 text-[1.05rem] text-fg outline-none transition-colors focus:border-fg disabled:opacity-60"
        />
        <button type="button" onClick={() => setShow((v) => !v)} className="absolute inset-y-0 right-0 grid w-12 place-items-center text-fg-3 hover:text-fg" aria-label={show ? "Hide password" : "Show password"}>
          {show ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>

      <AnimatePresence>
        {error && (
          <motion.p id="signin-error" role="alert" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-3 text-[0.92rem] text-late-ink">
            {error}
          </motion.p>
        )}
      </AnimatePresence>

      <button
        type="submit"
        disabled={disabled}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-[4px] bg-fg px-4 py-3.5 font-mono text-[0.85rem] uppercase tracking-[0.16em] text-bg transition-opacity hover:opacity-90 disabled:opacity-60"
      >
        {busy ? <LoaderCircle size={16} className="animate-spin" /> : null}
        {busy ? "Signing in" : "Sign in"}
      </button>

      {hint && (
        <div className="mt-6 flex items-center justify-between gap-3 border-t border-line pt-5 text-[0.9rem]">
          <span className="text-fg-2">
            Demo password <code className="ml-1 rounded-[3px] bg-bg-3 px-1.5 py-0.5 font-mono text-[0.85rem] text-fg">{hint}</code>
          </span>
          <button type="button" onClick={copy} className="chip" aria-label="Copy demo password">
            {copied ? <Check size={13} /> : <Copy size={13} />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}

      <p className="mt-5 font-mono text-[0.75rem] uppercase leading-relaxed tracking-[0.14em] text-fg-3">
        {offline ? "Offline preview · the API isn't running, so sign-in is simulated in this browser" : "Signed JWT session · httpOnly cookie · ends after 8 hours"}
      </p>
    </form>
  );
}
