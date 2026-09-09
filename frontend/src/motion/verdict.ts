import gsap from "gsap";
import { prefersReducedMotion, resolveEl, type AnimTarget } from "./shared";

/**
 * animateVerdictReveal
 * ---------------------------------------------------------------------
 * Plays once on the whole result surface (verdict card, reasons, and
 * binding axis together) the moment a result is known and rendered.
 *
 * A verdict arriving should feel considered, not celebratory — this is
 * the single most emotionally loaded moment in the app (it may be
 * telling someone their document looks forged). So: a slow, single,
 * settling motion on the result AS A WHOLE, not three separate staged
 * reveals stacked down the page — restraint is the aesthetic here. No
 * bounce, no scale-overshoot, no colour flash.
 *
 * The element must already be laid out with its final verdict styling
 * (colour classes etc. applied by React) before this is called — this
 * function only animates opacity/position, never colour.
 */
export function animateVerdictReveal(target: AnimTarget) {
  const el = resolveEl(target);
  if (!el) return null;

  if (prefersReducedMotion()) {
    gsap.set(el, { opacity: 1, y: 0, clearProps: "transform" });
    return null;
  }

  return gsap.fromTo(
    el,
    { opacity: 0, y: 14 },
    {
      opacity: 1,
      y: 0,
      duration: 0.5,
      ease: "power2.out",
    }
  );
}
