import gsap from "gsap";
import { prefersReducedMotion, resolveEl, type AnimTarget } from "./shared";

/**
 * animateChecklistStepActive
 * ---------------------------------------------------------------------
 * Marks one step "active" with a quiet pulse on its indicator dot
 * (`[data-anim="checklist-dot"]` inside the row). No spinner graphics —
 * a slow opacity breathe, matching the "considered, not frantic" motion
 * language used everywhere else in this app. This is real state
 * feedback (which step is current), not decoration.
 */
export function animateChecklistStepActive(target: AnimTarget) {
  const el = resolveEl(target);
  if (!el) return null;
  const dot = el.querySelector('[data-anim="checklist-dot"]') ?? el;

  if (prefersReducedMotion()) {
    gsap.set(dot, { opacity: 1 });
    return null;
  }

  return gsap.to(dot, {
    opacity: 0.4,
    duration: 0.55,
    ease: "sine.inOut",
    repeat: -1,
    yoyo: true,
  });
}

/**
 * animateChecklistStepDone
 * ---------------------------------------------------------------------
 * Settles a step into its completed state — kills any running pulse and
 * eases the row to full, quiet confidence rather than a checkmark pop.
 */
export function animateChecklistStepDone(target: AnimTarget) {
  const el = resolveEl(target);
  if (!el) return null;
  const dot = el.querySelector('[data-anim="checklist-dot"]') ?? el;

  gsap.killTweensOf(dot);

  if (prefersReducedMotion()) {
    gsap.set(dot, { opacity: 1, scale: 1 });
    return null;
  }

  return gsap.fromTo(
    dot,
    { opacity: 0.4, scale: 0.9 },
    { opacity: 1, scale: 1, duration: 0.28, ease: "power1.out" },
  );
}
