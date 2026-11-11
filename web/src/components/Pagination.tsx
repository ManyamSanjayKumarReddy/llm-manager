import { PAGE_SIZES } from "../hooks/usePagedList";
import { pageSlots } from "../lib/pageSlots";
import { Icon } from "./Icon";

interface Props {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  noun: string;
  onPage: (page: number) => void;
  onPageSize: (size: number) => void;
}

/** "Showing 26–50 of 132 keys", a rows-per-page choice and page buttons. */
export function Pagination({ page, pages, total, pageSize, noun, onPage, onPageSize }: Props) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="pager">
      <span className="pager-info dim" aria-live="polite">
        Showing <strong>{from}–{to}</strong> of <strong>{total}</strong> {noun}
      </span>
      <label className="pager-size">
        <span className="dim">Rows</span>
        <select className="input" value={pageSize} onChange={(e) => { onPageSize(Number(e.target.value)); }} aria-label="Rows per page">
          {PAGE_SIZES.map((size) => (
            <option key={size} value={size}>{size}</option>
          ))}
        </select>
      </label>
      {pages > 1 ? (
        <nav className="pager-nav" aria-label="Pagination">
          <button type="button" className="page-btn" aria-label="First page" disabled={page === 1} onClick={() => { onPage(1); }}><Icon name="chevrons-left" size={16} /></button>
          <button type="button" className="page-btn" aria-label="Previous page" disabled={page === 1} onClick={() => { onPage(page - 1); }}><Icon name="chevron-left" size={16} /></button>
          {pageSlots(page, pages).map((slot) =>
            typeof slot === "number" ? (
              <button key={slot} type="button" className="page-btn" aria-label={`Page ${slot}`} aria-current={slot === page ? "page" : undefined} onClick={() => { onPage(slot); }}>
                {slot}
              </button>
            ) : (
              <span key={slot} className="page-gap" aria-hidden="true">…</span>
            ),
          )}
          <button type="button" className="page-btn" aria-label="Next page" disabled={page === pages} onClick={() => { onPage(page + 1); }}><Icon name="chevron-right" size={16} /></button>
          <button type="button" className="page-btn" aria-label="Last page" disabled={page === pages} onClick={() => { onPage(pages); }}><Icon name="chevrons-right" size={16} /></button>
        </nav>
      ) : null}
    </div>
  );
}
