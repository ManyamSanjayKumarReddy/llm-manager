import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | undefined;
  error: string | undefined;
  loading: boolean;
  reload: () => Promise<void>;
}

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong.";
}

/**
 * Run ``load`` on mount (and when ``reload`` is called); optionally repeat every ``everyMs``.
 * Changing ``key`` loads again straight away (e.g. when a filter changes).
 */
export function useAsync<T>(load: () => Promise<T>, everyMs?: number, key?: unknown): AsyncState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  const reload = useCallback(async () => {
    try {
      setData(await loadRef.current());
      setError(undefined);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    if (!everyMs) return undefined;
    // Poll only while the tab is visible, so a forgotten tab does not keep the router busy.
    const timer = setInterval(() => {
      if (!document.hidden) void reload();
    }, everyMs);
    return () => {
      clearInterval(timer);
    };
  }, [reload, everyMs, key]);

  return { data, error, loading, reload };
}
