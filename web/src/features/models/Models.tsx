import { useState } from "react";

import { api } from "../../api/client";
import type { ManagedModel } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal } from "../../components/Modal";
import { Pagination } from "../../components/Pagination";
import { Reveal } from "../../components/Reveal";
import { SearchBox } from "../../components/SearchBox";
import { Deco } from "../../components/Stickers";
import { Empty, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { AddModelDialog } from "./AddModelDialog";
import { ManageModelDialog } from "./ManageModelDialog";

export function Models() {
  const [search, setSearch] = useState("");
  const list = usePagedList((q) => api.models({ ...q, q: search }), { q: search }, { initialPageSize: 10, everyMs: 5000 });
  // Everything registered, for spotting shared GPUs, taken names and taken ports while adding one.
  const everything = useAsync(() => api.models({ page: 1, pageSize: 100 }), undefined, list.total);
  const servers = useAsync(() => api.servers(), undefined, list.total);
  const [adding, setAdding] = useState(false);
  const [managing, setManaging] = useState<string>();
  const managed = list.items.find((m) => m.name === managing);
  const noModelsAtAll = !list.loading && list.total === 0 && search === "";

  const addButton = (
    <button type="button" className="btn primary" onClick={() => { setAdding(true); }}>
      <Icon name="plus" size={16} /> Add model
    </button>
  );

  return (
    <div className="page">
      <PageHead eyebrow="Fleet" title="Models">
        The vLLM containers Wakeful manages. Open a model to change its priority or key, put it to sleep, or remove it.
      </PageHead>

      <Reveal>
        <section className="surface stack">
          {list.error ? <div className="alert error" role="alert">{list.error}</div> : null}

          {list.loading ? (
            // Until the first answer arrives, show neither layout: no button that is about to be replaced.
            <div className="skeleton" aria-hidden="true" />
          ) : noModelsAtAll ? (
            // Nothing registered yet: one clear call to action, no empty search bar beside it.
            <Empty sticker={<Deco name="rocket" size={110} />} title="No models yet" action={addButton}>
              Register a container you already run, or build the command to start a new one.
            </Empty>
          ) : (
            <>
              <div className="list-head">
                <SearchBox label="Search models" placeholder="Search models" value={search} onChange={setSearch} />
                {addButton}
              </div>
              {list.total === 0 ? (
                <p className="no-match">No models match “{search}”.</p>
              ) : (
                <div className={`table-wrap ${list.fetching ? "fetching" : ""}`}>
                  <table className="cards">
                    <thead>
                      <tr><th>Model</th><th>State</th><th>Server · GPUs</th><th>Priority</th><th>Sleeps after</th><th /></tr>
                    </thead>
                    <tbody>
                      {list.items.map((m) => <Row key={m.name} model={m} onOpen={() => { setManaging(m.name); }} />)}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
          <Pagination page={list.page} pages={list.pages} total={list.total} pageSize={list.pageSize} noun="models" onPage={list.setPage} onPageSize={list.setPageSize} />
        </section>
      </Reveal>

      <Modal open={adding} onClose={() => { setAdding(false); }} label="Add a model" size="lg">
        <AddModelDialog
          registered={everything.data?.items ?? []}
          servers={servers.data ?? []}
          onClose={() => { setAdding(false); }}
          onRegistered={() => { setAdding(false); void list.reload(); void everything.reload(); }}
        />
      </Modal>

      <Modal open={managed !== undefined} onClose={() => { setManaging(undefined); }} label="Manage model" size="lg">
        {managed ? (
          <ManageModelDialog
            model={managed}
            servers={servers.data ?? []}
            onClose={() => { setManaging(undefined); }}
            onChanged={(close) => { if (close) setManaging(undefined); void list.reload(); void everything.reload(); }}
          />
        ) : null}
      </Modal>
    </div>
  );
}

function Row({ model: m, onOpen }: { model: ManagedModel; onOpen: () => void }) {
  return (
    <tr>
      <td className="primary">
        <button type="button" className="row-link" onClick={onOpen} aria-label={`Manage ${m.name}`}>
          <strong>{m.name}</strong>
          <span className="dim mono small-text">{m.served_name ?? m.url}{m.has_api_key ? " · key stored" : ""}</span>
        </button>
      </td>
      <td data-label="State"><Pill>{m.state}</Pill></td>
      <td data-label="Server · GPUs"><span className="dim">{m.server}</span> {m.gpus.map((g) => <span key={g} className="gpu-chip">GPU {g}</span>)}</td>
      <td data-label="Priority" className="num">{m.priority === 0 ? <span className="dim">Normal</span> : <span className="prio">{m.priority}</span>}</td>
      <td data-label="Sleeps after" className="num dim">{m.idle_minutes} min</td>
      <td data-label="" className="r">
        <button type="button" className="icon-btn" onClick={onOpen} aria-label={`Open ${m.name}`} tabIndex={-1}><Icon name="chevron-right" /></button>
      </td>
    </tr>
  );
}
