import { useAsync } from "../hooks/useAsync";
import { api } from "../lib/api";
import { dayLong } from "../lib/format";
import { useStore } from "../lib/store";
import { Logo } from "./Nav";

export function Footer() {
  const { world, mode } = useStore();
  const model = useAsync(() => api.model(), []);
  return (
    <footer className="mt-24 border-t border-line">
      <div className="shell grid gap-10 py-14 md:grid-cols-12">
        <div className="md:col-span-6">
          <div className="flex items-center gap-3">
            <Logo className="size-9" />
            <span className="font-display text-[2.6rem] font-extrabold uppercase leading-none">Cascade</span>
          </div>
          <p className="mt-4 max-w-md text-fg-2">When it really arrives, how sure we are, which stage is to blame.</p>
        </div>
        <dl className="grid grid-cols-2 gap-6 font-mono text-[0.8rem] md:col-span-6 md:grid-cols-3">
          <div>
            <dt className="uppercase tracking-[0.14em] text-fg-3">Model</dt>
            <dd className="mt-1">v{model.data?.version ?? "…"}</dd>
          </div>
          <div>
            <dt className="uppercase tracking-[0.14em] text-fg-3">Data as of</dt>
            <dd className="mt-1">{world ? dayLong(world.now) + " 2025" : "…"}</dd>
          </div>
          <div>
            <dt className="uppercase tracking-[0.14em] text-fg-3">Source</dt>
            <dd className="mt-1">{mode === "live" ? "Live API" : "Recorded run"}</dd>
          </div>
        </dl>
      </div>
      <div className="shell flex flex-wrap justify-between gap-4 border-t border-line py-6 font-mono text-[0.72rem] uppercase tracking-[0.14em] text-fg-3">
        <span>Aiqon assessment · simulated shipments</span>
        <a href="#top" className="hover:text-fg">Back to top ↑</a>
      </div>
    </footer>
  );
}
