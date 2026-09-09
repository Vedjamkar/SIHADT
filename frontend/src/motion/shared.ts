/*
  shared.ts
  ---------------------------------------------------------------------------
  Small helpers shared by every animation in this module.

  The rule that matters most here: NOTHING in this codebase ever ships an
  element parked at opacity:0 waiting for a script that might not run.
  components.css never sets a resting opacity/visibility of 0 on any
  data-anim target — every element is fully visible at rest before any
  animation module has loaded. gsap.fromTo() below is used specifically
  because it always writes both the start AND end state itself, and the
  reduced-motion branch always calls gsap.set(...) to the final state
  before returning — so even a thrown error or an early return still
  leaves content visible.
*/

export type AnimTarget = Element | null | undefined;

/** True when the user (OS-level) has asked for reduced motion. */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  try {
    if (window.localStorage.getItem("debug-force-reduced-motion") === "1") return true;
  } catch {
    // ignore
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Resolves a single element from an Element, a React ref-like object, or null. */
export function resolveEl(target: AnimTarget): Element | null {
  return target ?? null;
}

/** Query all direct/nested descendants carrying a given data-anim value. */
export function queryAnimChildren(root: Element, animValue: string): Element[] {
  return Array.from(root.querySelectorAll(`[data-anim="${animValue}"]`));
}
