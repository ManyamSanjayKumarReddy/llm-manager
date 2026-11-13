import { useEffect } from "react";

import { BRAND } from "./brand";
import { Logo } from "./components/Logo";
import { NavMenu } from "./components/NavMenu";
import { AuthProvider } from "./features/auth/AuthProvider";
import { useAuth, useUser } from "./features/auth/context";
import { LoginPage } from "./features/auth/LoginPage";
import { Landing } from "./features/landing/Landing";
import { NotFound } from "./features/NotFound";
import { ToastProvider } from "./features/toast/ToastProvider";
import { useSmoothScroll } from "./hooks/useSmoothScroll";
import { findPage, PAGES, safeNext, type DashboardPage } from "./pages";
import { Link } from "./router/Link";
import { navigate, useLocation } from "./router/router";

export function App() {
  useSmoothScroll();
  return (
    <AuthProvider>
      <ToastProvider>
        <Root />
      </ToastProvider>
    </AuthProvider>
  );
}

/** Decides what the current address shows, for someone signed in or not. */
function Root() {
  const { state } = useAuth();
  const { path, search } = useLocation();
  const signedIn = state.status === "authenticated";
  const role = state.status === "authenticated" ? state.user.role : undefined;
  const page = findPage(path);

  let redirect: string | undefined;
  if (state.status === "anonymous" && page) redirect = `/signin?next=${encodeURIComponent(path)}`;
  else if (signedIn && path === "/signin") redirect = safeNext(search.get("next"));
  else if (signedIn && page?.admin && role !== "admin") redirect = "/overview";

  useEffect(() => {
    if (redirect) navigate(redirect, { replace: true });
  }, [redirect]);

  if (state.status === "loading" || redirect) return null;
  if (path === "/") return <Landing signedIn={signedIn} />;
  if (path === "/signin") return <LoginPage />;
  if (signedIn && page) return <Shell page={page} />;
  return <NotFound signedIn={signedIn} />;
}

/** The navigation: pages sharing a group become one drop-down; a group left with a single page is a plain link. */
function navEntries(tabs: DashboardPage[]): { label: string; pages: DashboardPage[] }[] {
  const entries: { label: string; pages: DashboardPage[] }[] = [];
  for (const tab of tabs) {
    const group = tab.group ? entries.find((e) => e.label === tab.group) : undefined;
    if (group) group.pages.push(tab);
    else entries.push({ label: tab.group ?? tab.title, pages: [tab] });
  }
  return entries;
}

function Shell({ page }: { page: DashboardPage }) {
  const me = useUser();
  const { signOut } = useAuth();
  // Admin-only tabs are enforced by the API too; hiding them here is just tidiness.
  const tabs = PAGES.filter((p) => p.nav && (!p.admin || me.role === "admin"));
  const highlighted = page.parent ?? page.path;
  const entries = navEntries(tabs);

  useEffect(() => {
    document.title = `${page.title} · ${BRAND.name}`;
  }, [page.title]);

  // The pinned page title sits directly under the navigation, which is taller on phones.
  useEffect(() => {
    const bar = document.querySelector<HTMLElement>(".shell-bar");
    if (!bar) return undefined;
    const apply = () => { document.documentElement.style.setProperty("--header-h", `${bar.offsetHeight}px`); };
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(bar);
    return () => { observer.disconnect(); };
  }, []);

  return (
    <>
      <header className="shell-bar">
        <Logo to="/" />
        <nav className="shell-nav" aria-label="Sections">
          {entries.map(({ label, pages }) => {
            const only = pages.length === 1 ? pages[0] : undefined;
            return only ? (
              <Link key={only.path} to={only.path} className="nav-item" aria-current={only.path === highlighted ? "page" : undefined}>
                {only.title}
              </Link>
            ) : (
              <NavMenu key={label} label={label} pages={pages} current={highlighted} />
            );
          })}
        </nav>
        <div className="who">
          <span className="avatar" aria-hidden="true">{me.username.slice(0, 1)}</span>
          <span className="who-text">
            {me.username}
            <small>{me.role}</small>
          </span>
          <button className="btn small" type="button" onClick={() => void signOut()}>Sign out</button>
        </div>
      </header>
      {/* key: switching screens starts the new one fresh and stops the old one's polling */}
      <div key={page.path}>{page.view}</div>
      <footer className="footer">{BRAND.name} · models on demand</footer>
    </>
  );
}
