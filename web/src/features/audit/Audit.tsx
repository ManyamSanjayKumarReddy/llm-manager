import { useState } from "react";

import { api } from "../../api/client";
import { Pagination } from "../../components/Pagination";
import { Reveal } from "../../components/Reveal";
import { SearchBox } from "../../components/SearchBox";
import { Deco } from "../../components/Stickers";
import { Alert, Empty, PageHead } from "../../components/ui";
import { usePagedList } from "../../hooks/usePagedList";
import { dateTime } from "../../lib/format";

export function Audit() {
  const [search, setSearch] = useState("");
  const audit = usePagedList((q) => api.audit({ ...q, q: search }), { q: search });
  return (
    <div className="page">
      <PageHead eyebrow="Security" title="Audit trail">
        Who signed in, who changed what, and from where. Newest first.
      </PageHead>
      {audit.error ? <Alert notice={{ kind: "error", text: audit.error }} /> : null}
      <Reveal>
        <section className="surface stack">
          <div className="toolbar">
            <SearchBox label="Search the audit trail" placeholder="Search who, action or target" value={search} onChange={setSearch} />
          </div>
          {!audit.loading && audit.total === 0 ? (
            search ? (
              <p className="no-match">Nothing matches “{search}”.</p>
            ) : (
              <Empty sticker={<Deco name="eye" size={110} />} title="Nothing recorded yet">Sign-ins and changes will appear here.</Empty>
            )
          ) : (
            <div className={`table-wrap ${audit.fetching ? "fetching" : ""}`}>
              <table className="cards">
                <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>IP</th><th>Detail</th></tr></thead>
                <tbody>
                  {audit.items.map((entry, i) => (
                    <tr key={`${entry.ts}-${i}`}>
                      <td className="primary dim">{dateTime(entry.ts)}</td>
                      <td data-label="Who">{entry.actor}</td>
                      <td data-label="Action"><span className="action-chip">{entry.action}</span></td>
                      <td data-label="Target">{entry.target ?? ""}</td>
                      <td data-label="IP" className="mono dim">{entry.ip ?? ""}</td>
                      <td data-label="Detail" className="dim">{entry.detail ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={audit.page} pages={audit.pages} total={audit.total} pageSize={audit.pageSize} noun="entries" onPage={audit.setPage} onPageSize={audit.setPageSize} />
        </section>
      </Reveal>
    </div>
  );
}
