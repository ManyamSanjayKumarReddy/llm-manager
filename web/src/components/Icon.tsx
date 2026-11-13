const PATHS = {
  plus: "M12 5v14M5 12h14",
  "arrow-left": "M19 12H5M11 6l-6 6 6 6",
  "arrow-right": "M5 12h14M13 6l6 6-6 6",
  "chevron-down": "m6 9 6 6 6-6",
  "chevron-right": "m9 6 6 6-6 6",
  "chevron-left": "m15 6-6 6 6 6",
  "chevrons-left": "m11 17-5-5 5-5M18 17l-5-5 5-5",
  "chevrons-right": "m13 17 5-5-5-5M6 17l5-5-5-5",
  check: "m5 12.5 4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  copy: "M9 9h10v11H9zM5 15V4h10",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zM12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z",
  "eye-off": "M3 3l18 18M10.6 6.1A9.7 9.7 0 0 1 12 6c6.4 0 10 6 10 6a17 17 0 0 1-3.2 3.9M6.5 7.6A17 17 0 0 0 2 12s3.6 6 10 6c1.4 0 2.6-.3 3.8-.7M9.9 9.9a2.5 2.5 0 0 0 3.2 3.2",
  key: "M14 10a5 5 0 1 1-4.6-5M13 10l8 8M18 15l3 3M16 17l2 2",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  refresh: "M20 11a8 8 0 0 0-14-4M4 4v4h4M4 13a8 8 0 0 0 14 4M20 20v-4h-4",
  search: "M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM16 16l4 4",
} as const;

export type IconName = keyof typeof PATHS;

/** A small line icon that inherits the surrounding text colour and sits on the text baseline. */
export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  );
}
