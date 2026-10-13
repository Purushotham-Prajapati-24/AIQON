/**
 * Move keyboard focus to a section after a jump, without scrolling (the caller already scrolled).
 * Targets the section's heading block (`<id>-head`) when it has one, else the section itself.
 */
export function focusSection(id: string) {
  const el = document.getElementById(`${id}-head`) ?? document.getElementById(id);
  if (!el) return;
  el.tabIndex = -1;
  el.dataset.focusTarget = "";
  el.focus({ preventScroll: true });
}
