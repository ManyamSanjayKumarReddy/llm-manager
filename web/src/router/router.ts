import { useSyncExternalStore } from "react";

// A tiny router on the browser's History API, so addresses look like /models instead of /#models.
// The server answers every non-API path with the app, so refreshing or sharing a link works.

const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

window.addEventListener("popstate", notify); // the browser's back and forward buttons

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Path and query as one string, so React can tell when it changed. */
function snapshot(): string {
  return window.location.pathname + window.location.search;
}

export interface Location {
  /** The path without a trailing slash, e.g. "/models/new" ("/" for the home page). */
  path: string;
  search: URLSearchParams;
}

export function parseLocation(raw: string): Location {
  const url = new URL(raw, "http://local");
  const path = url.pathname.length > 1 ? url.pathname.replace(/\/+$/, "") : url.pathname;
  return { path, search: url.searchParams };
}

/** The current location; the component re-renders when it changes. */
export function useLocation(): Location {
  const raw = useSyncExternalStore(subscribe, snapshot);
  return parseLocation(raw);
}

export interface NavigateOptions {
  /** Replace the current history entry instead of adding one (for redirects). */
  replace?: boolean;
}

/** Go to another page of this app without reloading it. */
export function navigate(to: string, options: NavigateOptions = {}): void {
  const target = new URL(to, window.location.origin);
  if (target.origin !== window.location.origin) {
    window.location.assign(to);
    return;
  }
  const next = target.pathname + target.search + target.hash;
  const here = window.location.pathname + window.location.search + window.location.hash;
  if (next !== here) {
    if (options.replace) window.history.replaceState(null, "", next);
    else window.history.pushState(null, "", next);
    notify();
  }
  if (target.hash === "") window.scrollTo({ top: 0 });
}
