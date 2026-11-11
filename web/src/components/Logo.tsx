import { BRAND } from "../brand";
import { Link } from "../router/Link";

/** Wordmark: a rounded tile holding a sleep-to-wake wave, then the product name. */
export function Logo({ size = 28, to }: { size?: number; to?: string }) {
  const mark = (
    <span className="logo">
      <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
        <defs>
          <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8bf3e6" />
            <stop offset="1" stopColor="#2e7dff" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="9" fill="url(#logo-g)" />
        <path
          d="M6 17c3 0 3-6 5.2-6S14 21 16 21s2.3-10 4.8-10S24 17 26 17"
          fill="none"
          stroke="#07080a"
          strokeWidth="2.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="logo-name">{BRAND.name}</span>
    </span>
  );
  return to === undefined ? (
    mark
  ) : (
    <Link className="logo-link" to={to} aria-label={`${BRAND.name} home`}>
      {mark}
    </Link>
  );
}
