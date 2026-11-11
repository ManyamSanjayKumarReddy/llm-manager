import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type Tone = "ok" | "idle" | "warn" | "bad";

const STATE_TONE: Record<string, Tone> = { awake: "ok", asleep: "idle", waking: "warn", sleeping: "warn", failed: "bad", down: "bad" };

/** A state label with a dot; colour follows the state (awake, asleep, waking, ...). */
export function Pill({ children, tone }: { children: string; tone?: Tone }) {
  const cls = tone ?? STATE_TONE[children] ?? "idle";
  return (
    <span className={`pill ${children in STATE_TONE ? children : cls}`}>
      <span className="dot" />
      {children}
    </span>
  );
}

export type Notice = { kind: "error" | "success"; text: string };

export function Alert({ notice }: { notice: Notice | undefined }) {
  if (!notice) return null;
  return (
    <div className={`alert ${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
      {notice.text}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
    </label>
  );
}

/**
 * The title block at the top of every page. Once it has scrolled out of view, a slim copy of it
 * stays pinned under the top navigation, so you always know where you are. The big block keeps its
 * place in the page, so nothing jumps when the bar appears.
 */
export function PageHead({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  const head = useRef<HTMLElement>(null);
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = head.current;
      if (!el) return;
      const nav = document.querySelector(".shell-bar")?.getBoundingClientRect().bottom ?? 0;
      setPinned(el.getBoundingClientRect().bottom < nav + 8);
    };
    const schedule = () => {
      if (frame === 0) frame = requestAnimationFrame(update);
    };
    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, []);

  return (
    <>
      <header className="page-head" ref={head}>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {children ? <p className="dim lead">{children}</p> : null}
      </header>
      {/* A repeat of the heading above, so it is hidden from screen readers. It is rendered at the
          top level of the document so no parent's styling can change where "fixed" is measured from. */}
      {createPortal(
        <div className={`page-pin ${pinned ? "on" : ""}`} aria-hidden="true">
          <div className="page-pin-inner">
            <span className="eyebrow">{eyebrow}</span>
            <strong>{title}</strong>
            {children ? <span className="pin-desc">{children}</span> : null}
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}

export function Empty({ sticker, title, children, action }: { sticker: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      {sticker}
      <strong>{title}</strong>
      {children ? <p className="dim">{children}</p> : null}
      {action ? <div className="empty-action">{action}</div> : null}
    </div>
  );
}
