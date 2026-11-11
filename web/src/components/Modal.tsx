import { useEffect, useRef, type ReactNode } from "react";

import { Icon } from "./Icon";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /** Read out by screen readers when the popup opens. */
  label: string;
  /** "lg" is a wide popup with its own header, scrolling body and footer; on a phone it fills the screen. */
  size?: "sm" | "lg";
}

/** A native <dialog>: focus trap, Escape to close and a dimmed backdrop come for free. */
export function Modal({ open, onClose, children, label, size = "sm" }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={size === "lg" ? "modal-lg" : undefined}
      aria-label={label}
      onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
    >
      {open ? children : null}
    </dialog>
  );
}

/** The title row of a large popup, with its close button. */
export function ModalHeader({ title, subtitle, onClose }: { title: string; subtitle?: string; onClose: () => void }) {
  return (
    <header className="modal-head">
      <div>
        <h2>{title}</h2>
        {subtitle ? <p className="dim">{subtitle}</p> : null}
      </div>
      <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
    </header>
  );
}
