// Sign-in against the CASCADE API (JWT in an httpOnly cookie). When the API is not reachable
// (static preview of the recorded run) sign-in is simulated in this browser and labelled offline.
import { API, detectMode } from "./api";
import type { RoleId } from "./roles";

export interface User {
  id: string;
  name: string;
  role: RoleId;
  title: string;
  team: string;
}

export interface Session {
  user: User;
  /** Unix seconds. */
  expiresAt: number;
  /** "server": signed JWT cookie from the API. "offline": the API is down; nothing is signed. */
  kind: "server" | "offline";
}

export class SignInError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** The same demo accounts the API serves (src/cascade/serving/auth.py), for the offline preview. */
export const OFFLINE_USERS: User[] = [
  { id: "priya", name: "Priya Raman", role: "planner", title: "Ops planner", team: "Asia–Europe desk" },
  { id: "marco", name: "Marco Bianchi", role: "support", title: "Customer support", team: "Key accounts" },
  { id: "lena", name: "Lena Fischer", role: "analyst", title: "Network analyst", team: "Network design" },
  { id: "reviewer", name: "Aiqon Reviewer", role: "first", title: "Assessment reviewer", team: "Aiqon" },
];
export const DEMO_PASSWORD = "cascade-demo";
const OFFLINE_KEY = "cascade-offline-session";
const OFFLINE_TTL_S = 8 * 3600;

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    credentials: "include",
    headers: { "content-type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new SignInError(detail, r.status);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}

type ServerSession = { user: User; expires_at: number };
const fromServer = (s: ServerSession): Session => ({ user: s.user, expiresAt: s.expires_at, kind: "server" });

function readOffline(): Session | null {
  try {
    const s = JSON.parse(sessionStorage.getItem(OFFLINE_KEY) ?? "null") as Session | null;
    return s && s.expiresAt > Date.now() / 1000 ? s : null;
  } catch {
    return null;
  }
}
function writeOffline(user: User): Session {
  const s: Session = { user, expiresAt: Math.floor(Date.now() / 1000) + OFFLINE_TTL_S, kind: "offline" };
  try {
    sessionStorage.setItem(OFFLINE_KEY, JSON.stringify(s));
  } catch {
    /* storage blocked: the session lasts for this page only */
  }
  return s;
}

export const session = {
  /** The current session, or null if nobody is signed in. */
  async current(): Promise<Session | null> {
    if ((await detectMode()) === "snapshot") return readOffline();
    try {
      return fromServer(await call<ServerSession>("/v1/auth/me"));
    } catch {
      return null;
    }
  },

  async demoUsers(): Promise<{ users: User[]; passwordHint: string | null; offline: boolean }> {
    if ((await detectMode()) === "snapshot") return { users: OFFLINE_USERS, passwordHint: DEMO_PASSWORD, offline: true };
    const r = await call<{ users: User[]; password_hint: string | null }>("/v1/auth/demo-users");
    return { users: r.users, passwordHint: r.password_hint, offline: false };
  },

  async signIn(username: string, password: string): Promise<Session> {
    if ((await detectMode()) === "snapshot") {
      const user = OFFLINE_USERS.find((u) => u.id === username.trim().toLowerCase());
      if (!user || password !== DEMO_PASSWORD) throw new SignInError("wrong username or password", 401);
      return writeOffline(user);
    }
    return fromServer(
      await call<ServerSession>("/v1/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
    );
  },

  async signInAs(userId: string): Promise<Session> {
    if ((await detectMode()) === "snapshot") {
      const user = OFFLINE_USERS.find((u) => u.id === userId);
      if (!user) throw new SignInError(`unknown demo user ${userId}`, 404);
      return writeOffline(user);
    }
    return fromServer(
      await call<ServerSession>("/v1/auth/demo-login", { method: "POST", body: JSON.stringify({ user_id: userId }) }),
    );
  },

  /** Ends the session. Throws if the API could not clear the cookie, so the caller keeps the
   *  user signed in (a reload would restore the session) and can offer a retry. */
  async signOut(): Promise<void> {
    try {
      sessionStorage.removeItem(OFFLINE_KEY);
    } catch {
      /* storage blocked */
    }
    if ((await detectMode()) === "live") await call<void>("/v1/auth/logout", { method: "POST" });
  },
};
