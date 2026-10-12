import { useEffect, useRef, useState } from "react";

/** Resolve a promise-returning loader; keeps the previous value while the next one loads. */
export function useAsync<T>(load: () => Promise<T> | null, deps: unknown[]) {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  const seq = useRef(0);
  useEffect(() => {
    const p = load();
    if (!p) return;
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: undefined }));
    p.then(
      (data) => id === seq.current && setState({ data, loading: false }),
      (error: Error) => id === seq.current && setState((s) => ({ ...s, error, loading: false })),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}
