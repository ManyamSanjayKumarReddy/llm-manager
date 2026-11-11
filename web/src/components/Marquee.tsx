/** A looping ticker of short labels. The list is doubled so the loop is seamless. */
export function Marquee({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  const row = [...items, ...items, ...items, ...items];
  return (
    <div className="marquee" aria-hidden="true">
      <div className="marquee-track">
        {[0, 1].map((copy) => (
          <div className="marquee-item" key={copy}>
            {row.map((label, i) => (
              <span key={`${label}-${i}`}>{label}</span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
