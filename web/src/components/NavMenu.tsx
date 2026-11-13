import { useEffect, useRef, useState } from "react";

import { Link } from "../router/Link";
import { Icon } from "./Icon";

interface Entry {
  path: string;
  title: string;
}

/** A drop-down in the top navigation: a button that opens a short list of pages. */
export function NavMenu({ label, pages, current }: { label: string; pages: readonly Entry[]; current: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const active = pages.some((p) => p.path === current);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div
      ref={box}
      className="nav-group"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}
    >
      <button
        ref={button}
        type="button"
        className="nav-item"
        data-active={active}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => { setOpen((o) => !o); }}
      >
        {label} <Icon name="chevron-down" size={14} />
      </button>
      <div className="nav-menu" hidden={!open}>
        {pages.map((p) => (
          <Link key={p.path} to={p.path} className="nav-item" aria-current={p.path === current ? "page" : undefined} onClick={() => { setOpen(false); }}>
            {p.title}
          </Link>
        ))}
      </div>
    </div>
  );
}
