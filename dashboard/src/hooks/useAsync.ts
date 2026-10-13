import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data?: T;
  error?: Error;
  loading: boolean;
  /** Run the loader again (e.g. from an error state's "Try again" button). */
  retry: () => void;
}

/**
 * Resolve a promise-returning loader. Keeps the previous value while the next one loads, and
 * ignores responses that arrive after a newer request was started (no stale overwrite).
 * Returning `null` from the loader means "not ready yet" (e.g. waiting for the world clock).
 */
export function useAsync<T>(load: () => Promise<T> | null, deps: unknown[]): AsyncState<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({ loading: true });
  const [attempt, setAttempt] = useState(0);
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
    // The caller owns the dependency list (same contract as useEffect).
  }, [...deps, attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { ...state, retry };
}
