import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { CreatedApiKey } from "../../api/types";
import { Modal } from "../../components/Modal";
import { Reveal } from "../../components/Reveal";
import { Deco } from "../../components/Stickers";
import { Empty, Field, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Pagination } from "../../components/Pagination";
import { SearchBox } from "../../components/SearchBox";
import { usePagedList } from "../../hooks/usePagedList";
import { ago } from "../../lib/format";
import { useToast } from "../toast/context";

export function ApiKeys() {
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const keys = usePagedList((q) => api.keys({ ...q, q: search, status: statusFilter }), { q: search, status: statusFilter });
  const filtered = search !== "" || statusFilter !== "";
  const models = useAsync(async () => Object.keys((await api.status()).models));
  const [created, setCreated] = useState<CreatedApiKey>();
  const [revoking, setRevoking] = useState<{ id: string; label: string }>();

  async function revoke() {
    if (!revoking) return;
    try {
      await api.revokeKey(revoking.id);
      toast.show("success", `“${revoking.label}” revoked.`);
      await keys.reload();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "Could not revoke the key.");
    }
    setRevoking(undefined);
  }

  return (
    <div className="page">
      <PageHead eyebrow="Access" title="API keys">
        Keys are how programs call your models. Each can be limited to certain models and a request rate.
      </PageHead>
      {created ? <NewToken created={created} onDone={() => { setCreated(undefined); }} /> : null}
      <Reveal>
        <NewKeyForm
          modelNames={models.data ?? []}
          onCreated={(key) => { setCreated(key); void keys.reload(); }}
          onError={(text) => { toast.show("error", text); }}
        />
      </Reveal>
      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>All keys</h2><span className="count">{keys.total} {filtered ? "match" : "total"}</span></div>
          <div className="toolbar">
            <SearchBox label="Search keys" placeholder="Search by label" value={search} onChange={setSearch} />
            <select className="input" aria-label="Filter by status" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); }}>
              <option value="">All keys</option>
              <option value="active">Active</option>
              <option value="revoked">Revoked</option>
            </select>
          </div>
          {keys.total === 0 && !keys.loading && filtered ? (
            <p className="no-match">No keys match your search.</p>
          ) : keys.total === 0 && !keys.loading ? (
            <Empty sticker={<Deco name="star" size={100} />} title="No API keys yet">Create one above to let a program call your models.</Empty>
          ) : (
            <div className={`table-wrap ${keys.fetching ? "fetching" : ""}`}>
              <table className="cards">
                <thead><tr><th>Label</th><th>Key</th><th>Models</th><th>Limit</th><th>Last used</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {keys.items.map((key) => (
                    <tr key={key.id}>
                      <td className="primary"><strong>{key.label}</strong><div className="dim">by {key.created_by ?? "unknown"}</div></td>
                      <td data-label="Key" className="mono">{key.prefix}…</td>
                      <td data-label="Models">{key.allowed_models ? key.allowed_models.join(", ") : "All models"}</td>
                      <td data-label="Limit" className="num">{key.rpm_limit ? `${key.rpm_limit}/min` : "None"}</td>
                      <td data-label="Last used" className="dim">{ago(key.last_used_at)}</td>
                      <td data-label="Status">{key.revoked_at ? <Pill tone="bad">revoked</Pill> : <Pill tone="ok">active</Pill>}</td>
                      <td data-label="" className="r">
                        {key.revoked_at ? null : (
                          <button className="btn small danger" type="button" onClick={() => { setRevoking({ id: key.id, label: key.label }); }}>Revoke</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={keys.page} pages={keys.pages} total={keys.total} pageSize={keys.pageSize} noun="keys" onPage={keys.setPage} onPageSize={keys.setPageSize} />
        </section>
      </Reveal>

      <Modal open={revoking !== undefined} onClose={() => { setRevoking(undefined); }} label="Revoke key">
        <form method="dialog" onSubmit={(e) => { e.preventDefault(); void revoke(); }}>
          <h2>Revoke “{revoking?.label}”?</h2>
          <p className="dim">Programs using this key stop working immediately. This cannot be undone.</p>
          <div className="actions">
            <button className="btn" type="button" onClick={() => { setRevoking(undefined); }}>Cancel</button>
            <button className="btn danger" type="submit">Revoke key</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function NewToken({ created, onDone }: { created: CreatedApiKey; onDone: () => void }) {
  const [copied, setCopied] = useState<"yes" | "failed">();
  async function copy() {
    try {
      await navigator.clipboard.writeText(created.token);
      setCopied("yes");
    } catch {
      setCopied("failed");
    }
  }
  return (
    <section className="surface glow token-card">
      <Deco name="rocket" size={120} />
      <div>
        <h2>“{created.label}” is ready</h2>
        <p className="dim">Copy the key now. It is shown only once and cannot be recovered, only replaced.</p>
        <code className="token-box">{created.token}</code>
        <div className="row">
          <button className="btn primary" type="button" onClick={() => void copy()}>
            {copied === "yes" ? "Copied" : copied === "failed" ? "Select and copy it manually" : "Copy key"}
          </button>
          <button className="btn" type="button" onClick={onDone}>I have saved it</button>
        </div>
      </div>
    </section>
  );
}

function NewKeyForm(props: { modelNames: string[]; onCreated: (key: CreatedApiKey) => void; onError: (message: string) => void }) {
  const [label, setLabel] = useState("");
  const [rpm, setRpm] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    try {
      const key = await api.createKey({
        label: label.trim(),
        allowed_models: chosen.length > 0 ? chosen : null,
        rpm_limit: rpm ? Number(rpm) : null,
      });
      setLabel("");
      setRpm("");
      setChosen([]);
      props.onCreated(key);
    } catch (err) {
      props.onError(err instanceof Error ? err.message : "Could not create the key.");
    }
  }

  return (
    <form className="surface stack" onSubmit={(e) => void submit(e)}>
      <h2>New key</h2>
      <div className="row">
        <Field label="Label">
          <input className="input" type="text" required maxLength={100} placeholder="e.g. ci-pipeline" value={label} onChange={(e) => { setLabel(e.target.value); }} />
        </Field>
        <Field label="Requests per minute">
          <input className="input" type="number" min={1} max={100000} placeholder="Unlimited" value={rpm} onChange={(e) => { setRpm(e.target.value); }} />
        </Field>
      </div>
      <div className="field">
        <span>Allowed models · none selected means all</span>
        <div className="chips">
          {props.modelNames.map((name) => (
            <label key={name} className="chip-check">
              <input type="checkbox" checked={chosen.includes(name)} onChange={(e) => { setChosen((prev) => (e.target.checked ? [...prev, name] : prev.filter((n) => n !== name))); }} />
              <span>{name}</span>
            </label>
          ))}
        </div>
      </div>
      <div><button className="btn primary" type="submit">Create key</button></div>
    </form>
  );
}
