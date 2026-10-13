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

/** Scroll behaviour for scripted jumps: instant when the user asked for reduced motion. */
export function scrollBehavior(): ScrollBehavior {
  return matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
}

let locks = 0;
let saved = "";
/**
 * Stop the page behind a modal from scrolling. Counted, so overlapping modals (drawer and palette)
 * can open and close in any order without leaving the page locked. Returns the unlock function.
 */
export function lockScroll() {
  if (locks++ === 0) {
    saved = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  let done = false;
  return () => {
    if (done) return;
    done = true;
    if (--locks === 0) document.body.style.overflow = saved;
  };
}

/**
 * Return focus to whatever opened a modal, unless focus has already moved somewhere meaningful
 * (e.g. a section heading after a jump) or the opener has gone. `inside` is the closing modal.
 */
export function restoreFocus(opener: HTMLElement | null, inside: Element | null) {
  requestAnimationFrame(() => {
    const a = document.activeElement;
    const lost = !a || a === document.body || !a.isConnected || !!inside?.contains(a);
    if (lost && opener?.isConnected) opener.focus({ preventScroll: true });
  });
}
