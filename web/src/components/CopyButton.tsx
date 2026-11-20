import { useCopy } from "../hooks/useCopy";
import { Icon } from "./Icon";

export function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, copy] = useCopy();
  return (
    <button type="button" className="btn small" onClick={() => void copy(value)} aria-label={`Copy ${label}`}>
      <Icon name="copy" size={14} /> {copied ? "Copied" : "Copy"}
    </button>
  );
}
