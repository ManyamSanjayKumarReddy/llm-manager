export type Slot = number | "gap-start" | "gap-end";

/**
 * Page numbers to show: always the first and last, the current page and its neighbours.
 * A "…" never stands in for a single page (it would be shorter to just show the number).
 */
export function pageSlots(page: number, pages: number): Slot[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const from = Math.max(2, page - 1);
  const to = Math.min(pages - 1, page + 1);
  const slots: Slot[] = [1];
  if (from === 3) slots.push(2);
  else if (from > 3) slots.push("gap-start");
  for (let n = from; n <= to; n++) slots.push(n);
  if (to === pages - 2) slots.push(pages - 1);
  else if (to < pages - 2) slots.push("gap-end");
  slots.push(pages);
  return slots;
}
