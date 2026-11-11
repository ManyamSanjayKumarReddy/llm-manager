import { useState } from "react";

import type { CommandLine } from "../../lib/vllmCommand";
import { useToast } from "../toast/context";

interface Props {
  lines: CommandLine[] | null;
  /** The text to copy (real secrets included). */
  command: string | null;
  hasSecrets: boolean;
  revealed: boolean;
  onReveal: (on: boolean) => void;
}

/** The container command, line by line, with the lines Wakeful adds picked out. */
export function CommandPanel({ lines, command, hasSecrets, revealed, onReveal }: Props) {
  const toast = useToast();
  const [wrap, setWrap] = useState(false);
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch {
      toast.show("error", "Could not copy. Select the command and copy it by hand.");
    }
  }

  return (
    <div className="command-panel">
      <div className="command-bar">
        <span className="legend"><i className="swatch" aria-hidden="true" /> added for sleep mode</span>
        <div className="command-tools">
          {hasSecrets ? (
            <button type="button" className="btn small" aria-pressed={revealed} onClick={() => { onReveal(!revealed); }}>{revealed ? "Hide keys" : "Show keys"}</button>
          ) : null}
          <button type="button" className="btn small" aria-pressed={wrap} onClick={() => { setWrap(!wrap); }}>Wrap lines</button>
          <button type="button" className="btn small primary" disabled={!command} onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
        </div>
      </div>
      <pre className={`command ${wrap ? "wrap" : ""}`} aria-label="Container command" tabIndex={0}>
        {lines ? (
          lines.map((line, i) => (
            <span key={`${i}-${line.text}`} className={`cmd-line ${line.router ? "router" : ""}`}>
              <code>{i === 0 ? "" : "  "}{line.text}{i < lines.length - 1 ? " \\" : ""}</code>
              {line.note ? <em className="cmd-note"># {line.note}</em> : null}
            </span>
          ))
        ) : (
          <code className="dim"># Fill in the model to see the command</code>
        )}
      </pre>
      {hasSecrets ? <p className="hint dim">Copying includes your real keys. Don’t paste the command into chats or tickets.</p> : null}
    </div>
  );
}
