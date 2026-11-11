import { useEffect, useState } from "react";

import { Icon } from "./Icon";

const DEBOUNCE_MS = 300;

/** A search field that reports its text a moment after typing stops, so each key is not a request. */
export function SearchBox({ value, onChange, placeholder, label }: { value: string; onChange: (text: string) => void; placeholder: string; label: string }) {
  const [text, setText] = useState(value);
  useEffect(() => {
    if (text === value) return undefined;
    const timer = setTimeout(() => { onChange(text.trim()); }, DEBOUNCE_MS);
    return () => { clearTimeout(timer); };
  }, [text, value, onChange]);
  return (
    <div className="search">
      <Icon name="search" size={16} />
      <input className="input" type="search" aria-label={label} placeholder={placeholder} value={text} maxLength={100} onChange={(e) => { setText(e.target.value); }} />
    </div>
  );
}
