import { useEffect, useRef, useState } from "react";

import { api } from "../../api/client";
import { Icon } from "../../components/Icon";
import { ModalHeader } from "../../components/Modal";
import { useAsync } from "../../hooks/useAsync";

const TAILS = [100, 200, 500, 1000] as const;

/** The last lines a container printed. Refreshes by itself while open. */
export function LogsDialog({ server, name, onClose }: { server: string; name: string; onClose: () => void }) {
  const [tail, setTail] = useState<number>(200);
  const [wrap, setWrap] = useState(true);
  const logs = useAsync(() => api.containerLogs(server, name, tail), 5000, tail);
  const box = useRef<HTMLPreElement>(null);
  const text = logs.data?.text;

  // Follow the end of the output, like `docker logs -f`.
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <>
      <ModalHeader title={`Logs · ${name}`} subtitle={`The last lines on ${server}. Updates every few seconds.`} onClose={onClose} />
      <div className="modal-body fit">
        <div className="logs-bar">
          <label className="pager-size">
            <span className="dim">Lines</span>
            <select className="input" value={tail} onChange={(e) => { setTail(Number(e.target.value)); }} aria-label="Lines to show">
              {TAILS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button type="button" className="btn small" aria-pressed={wrap} onClick={() => { setWrap(!wrap); }}>Wrap lines</button>
          <button type="button" className="btn small" onClick={() => void logs.reload()}><Icon name="refresh" size={15} /> Refresh</button>
        </div>
        {logs.error ? <div className="alert error" role="alert">{logs.error}</div> : null}
        <pre ref={box} className={`logs ${wrap ? "wrap" : ""}`} aria-label="Log output" tabIndex={0}>
          {logs.loading ? "Loading…" : text === "" ? "Nothing printed yet." : text}
        </pre>
        {logs.data?.truncated ? <p className="hint dim">Only the end of the output is shown.</p> : null}
      </div>
    </>
  );
}
