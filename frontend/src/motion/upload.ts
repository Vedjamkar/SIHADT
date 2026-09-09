import gsap from "gsap";
import { prefersReducedMotion, resolveEl, type AnimTarget } from "./shared";

export type UploadState = "idle" | "dragging" | "uploading" | "done" | "error";

/**
 * animateUploadState
 * ---------------------------------------------------------------------
 * Drives the upload dropzone (`data-anim="upload-zone"`) through its
 * states. Every transition is subtle on purpose:
 *
 *  - dragging:  a small, calm lift (scale 1.005->1.015) — invites the
 *               drop without lurching.
 *  - uploading: a slow, gentle breathing opacity loop on the zone's
 *               icon (`[data-anim="upload-icon"]`) if present, so it
 *               reads as "working", not "loading spinner panic". The
 *               returned timeline should be killed by the caller when
 *               the state changes away from "uploading".
 *  - done:      a single quiet settle back to rest. No checkmark pop,
 *               no confetti — a completed upload is not the verdict,
 *               it is just the file being ready to look at.
 *  - error:     a brief, small, low-amplitude horizontal settle (a few
 *               pixels, two cycles) — enough to draw the eye without
 *               reading as a siren or an accusation. Most flagged
 *               uploads belong to honest people with a bad scan.
 *
 * Returns the underlying GSAP tween/timeline (or null if it no-opped)
 * so callers MAY kill it on unmount or before the next state change;
 * this is optional — nothing leaks if it isn't.
 */
export function animateUploadState(target: AnimTarget, state: UploadState) {
  const el = resolveEl(target);
  if (!el) return null;

  if (prefersReducedMotion()) {
    gsap.set(el, { opacity: 1, scale: 1, x: 0 });
    return null;
  }

  switch (state) {
    case "dragging":
      return gsap.to(el, {
        scale: 1.015,
        duration: 0.24,
        ease: "power2.out",
      });

    case "uploading": {
      const icon = el.querySelector('[data-anim="upload-icon"]') ?? el;
      gsap.to(el, { scale: 1, duration: 0.2, ease: "power2.out" });
      return gsap.to(icon, {
        opacity: 0.45,
        duration: 0.9,
        ease: "sine.inOut",
        repeat: -1,
        yoyo: true,
      });
    }

    case "done":
      return gsap.fromTo(
        el,
        { scale: 1.01 },
        { scale: 1, opacity: 1, duration: 0.4, ease: "power2.out" }
      );

    case "error":
      return gsap.fromTo(
        el,
        { x: 0 },
        {
          x: 4,
          duration: 0.07,
          ease: "power1.inOut",
          repeat: 3,
          yoyo: true,
          onComplete: () => gsap.set(el, { x: 0 }),
        }
      );

    case "idle":
    default:
      return gsap.to(el, {
        scale: 1,
        opacity: 1,
        x: 0,
        duration: 0.3,
        ease: "power2.out",
      });
  }
}
