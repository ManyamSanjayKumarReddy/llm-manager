import { useCallback, useMemo, useState } from "react";

import type { ListQuery } from "../api/client";
import type { Page } from "../api/types";
import { useAsync } from "./useAsync";

export const PAGE_SIZES = [10, 25, 50, 100] as const;
const DEFAULT_SIZE = 25;

type Filters = Record<string, string | number | undefined>;

export interface PagedList<T> {
  items: T[];
  total: number;
  pages: number;
  page: number;
  pageSize: number;
  /** True until the first page has arrived. */
  loading: boolean;
  /** True while another page or filter is being fetched (the old rows stay on screen). */
  fetching: boolean;
  error: string | undefined;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  reload: () => Promise<void>;
}

/**
 * Server-side paging for one list. Changing a filter or the page size goes back to page 1, and
 * if the current page disappears (the last row on it was deleted) it steps back to the new last page.
 */
export function usePagedList<T>(
  load: (query: ListQuery) => Promise<Page<T>>,
  filters: Filters = {},
  options: { initialPageSize?: number; everyMs?: number } = {},
): PagedList<T> {
  const filterKey = JSON.stringify(filters);
  const [pageSize, setSize] = useState<number>(options.initialPageSize ?? DEFAULT_SIZE);
  // The page is remembered together with the filters it belongs to, so a filter change
  // resets it without needing an effect.
  const [position, setPosition] = useState({ page: 1, key: filterKey });
  const requested = position.key === filterKey ? position.page : 1;

  const [lastPages, setLastPages] = useState<number>();
  const page = lastPages === undefined ? requested : Math.min(requested, lastPages);

  const query = useMemo<ListQuery>(() => ({ ...filters, page, pageSize }), [filters, page, pageSize]);
  const state = useAsync(
    async () => {
      const result = await load(query);
      setLastPages(result.pages);
      return result;
    },
    options.everyMs,
    `${filterKey}|${page}|${pageSize}`,
  );

  const setPage = useCallback((next: number) => {
    setPosition({ page: Math.max(1, next), key: filterKey });
  }, [filterKey]);
  const setPageSize = useCallback((size: number) => {
    setSize(size);
    setPosition({ page: 1, key: filterKey });
  }, [filterKey]);

  const data = state.data;
  const fetching = data !== undefined && (data.page !== page || data.page_size !== pageSize);
  return {
    items: data?.items ?? [],
    total: data?.total ?? 0,
    pages: data?.pages ?? 1,
    page,
    pageSize,
    loading: state.loading,
    fetching,
    error: state.error,
    setPage,
    setPageSize,
    reload: state.reload,
  };
}
