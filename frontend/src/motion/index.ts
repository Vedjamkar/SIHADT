/*
  src/motion/index.ts
  ---------------------------------------------------------------------------
  GSAP motion module for the document-verification app.

  MOTION BUDGET: almost all of it is spent on ONE sequence — see
  heroSequence.ts, played once on the home page. It teaches the mechanism
  the product turns on (a card's signed half vs its printed half) with real
  choreography, because that is worth it. The scan/capture choreography on
  the verify view (see ScanPreview.tsx) is the one other permitted place
  for real motion — the sweep and registration brackets that make the
  specimen read as something actually being examined. Everywhere else,
  motion is interaction feedback only: hover, drag, a state settling, the
  verdict arriving. No scroll-jacking, no parallax, no staggered reveals
  down the page — restraint is the aesthetic, and motion everywhere is
  what made an earlier attempt feel tacky.

  USAGE
  -----
  Components call these with a DOM node (e.g. a React ref's `.current`).
  Every function is a safe no-op if passed null/undefined (so it's safe
  to call from a ref callback before mount). Every function respects
  `prefers-reduced-motion` by *instantly* setting the final visible state
  instead of skipping the call outright — so nothing ever gets left
  invisible because motion was disabled.

  Elements are expected to already be visible at rest in CSS (see
  styles/ — no data-anim/data-seq target has a resting opacity or
  transform that hides it). These functions animate FROM a visible state
  TO a visible state; they never park content at opacity: 0 waiting for
  a trigger that might not fire.

  DATA-ANIM CONTRACT
  -------------------
  data-anim="verdict-card"     the whole result surface -> animateVerdictReveal
  data-anim="upload-zone"      the dropzone element -> animateUploadState
  data-anim="upload-icon"      (optional) icon inside the dropzone that
                                gets the "uploading" breathing loop
  data-anim="checklist-item"   each row in the checking-status list;
                                its [data-anim="checklist-dot"] is driven
                                by animateChecklistStepActive/Done
  data-anim="hero-sequence"    root of the one hero moment -> see
                                heroSequence.ts's createHeroSequence, which
                                reads its own data-seq="..." attributes.
*/

export { prefersReducedMotion } from "./shared";
export type { AnimTarget } from "./shared";

export { animateVerdictReveal } from "./verdict";
export { animateUploadState } from "./upload";
export type { UploadState } from "./upload";
export { animateChecklistStepActive, animateChecklistStepDone } from "./checklist";
export { createHeroSequence } from "./heroSequence";
export type { HeroSequenceHandle } from "./heroSequence";
