import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";

import { ToastContext, type ToastKind } from "./context";

const LIFETIME_MS = 4500;

interface Item {
  id: number;
  kind: ToastKind;
  text: string;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const next = useRef(0);

  const show = useCallback((kind: ToastKind, text: string) => {
    const id = next.current++;
    setItems((prev) => [...prev, { id, kind, text }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((t) => t.id !== id));
    }, LIFETIME_MS);
  }, []);

  const api = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext value={api}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "error" ? "alert" : "status"}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext>
  );
}
