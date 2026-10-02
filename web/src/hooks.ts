import { DependencyList, useCallback, useEffect, useRef, useState } from "react";

/** Loads data for the given dependencies; a newer request replaces an older one still on its way. */
export function useLoad<T>(load: () => Promise<T> | null, deps: DependencyList) {
  const [state, setState] = useState<{ data: T | null; error: string; loading: boolean }>({ data: null, error: "", loading: false });
  const latest = useRef(0);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const request = load();
    const id = ++latest.current;
    if (!request) {
      setState({ data: null, error: "", loading: false });
      return;
    }
    setState((s) => ({ ...s, error: "", loading: true }));
    request.then(
      (data) => { if (id === latest.current) setState({ data, error: "", loading: false }); },
      (error) => { if (id === latest.current) setState({ data: null, error: error?.message ?? String(error), loading: false }); },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, version]);
  const reload = useCallback(() => setVersion((n) => n + 1), []);
  return { ...state, reload };
}

/** A value that follows its source after it has stopped changing for a moment (typing, cursor moves). */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
