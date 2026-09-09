import gsap from "gsap";
import { prefersReducedMotion } from "./shared";

/*
  heroSequence.ts
  ---------------------------------------------------------------------------
  THE one animated moment this app spends its motion budget on (see
  docs/DESIGN_SPEC.md "Motion — one moment, then silence"). It teaches the
  mechanism the whole product turns on:

    An ID card has two halves. The QR is signed; the printed face is just
    ink. A forger transplants a genuine QR onto a card carrying their own
    photo. We compare the photo sealed INSIDE the signature against the
    one printed on the card.

  This is deliberately NOT scroll-jacked, NOT pinned, and NOT scrubbed —
  no ScrollTrigger, no 400vh spacer, no ties to scroll position at all. It
  autoplays once, forward, when the home page mounts (it sits directly in
  the hero, above the fold, so there is nothing to scroll to first), and
  settles into a final state that is IDENTICAL to what plain CSS already
  renders at rest. That means:

    - No JS / reduced motion: the final, fully-annotated diagram (split
      card, transplanted QR, both readout pills) is simply visible,
      immediately, laid out in normal document flow. Nothing here is ever
      parked at opacity:0 waiting for a trigger that might not fire.
    - Motion allowed: this module hides the later beats for about two and
      a half seconds while it plays through, then leaves the DOM in that
      same resting state. A quiet "Replay" control lets anyone watch it
      again; it is not required reading.

  Expected DOM (all produced by HomeView; this module only reads
  data-seq attributes, it creates no elements):
    root                        [data-anim="hero-sequence"]
    [data-seq="split-front"]    the "printed" half of the card
    [data-seq="split-back"]     the "signed" half of the card
    [data-seq="part-transplant"] the whole transplant beat (container)
    [data-seq="transplant-arrow"]
    [data-seq="qr-dest"]        the QR appearing on the forged card
    [data-seq="forged-photo"]   the mismatched face on the forged card
    [data-seq="part-readout"]   the whole readout beat (container)
    [data-seq="readout-verdict"]
    [data-seq="readout-binding"]
*/

export interface HeroSequenceHandle {
  /** Re-runs the sequence from the start. No-ops under reduced motion. */
  replay: () => void;
  /** Stops any in-flight tween without disturbing the current DOM state. */
  kill: () => void;
}

export function createHeroSequence(root: HTMLElement): HeroSequenceHandle {
  const q = (name: string) => root.querySelector(`[data-seq="${name}"]`);
  const front = q("split-front");
  const back = q("split-back");
  const transplantPart = q("part-transplant");
  const arrow = q("transplant-arrow");
  const qrDest = q("qr-dest");
  const forgedPhoto = q("forged-photo");
  const readoutPart = q("part-readout");
  const readoutVerdict = q("readout-verdict");
  const readoutBinding = q("readout-binding");

  const allTargets = [
    front,
    back,
    transplantPart,
    arrow,
    qrDest,
    forgedPhoto,
    readoutPart,
    readoutVerdict,
    readoutBinding,
  ].filter((el): el is Element => el != null);

  let timeline: gsap.core.Timeline | null = null;

  function build(): gsap.core.Timeline | null {
    if (prefersReducedMotion() || allTargets.length === 0) {
      // Leave everything at its plain, fully-visible CSS resting state.
      gsap.set(allTargets, { clearProps: "all" });
      return null;
    }

    const tl = gsap.timeline({ paused: true, defaults: { ease: "power2.out" } });

    // Beat 0 — the card looks whole: pull the two halves together.
    if (front) tl.set(front, { x: 40 }, 0);
    if (back) tl.set(back, { x: -40 }, 0);
    if (transplantPart) tl.set(transplantPart, { opacity: 0, y: 10 }, 0);
    if (arrow) tl.set(arrow, { opacity: 0, x: -8 }, 0);
    if (qrDest) tl.set(qrDest, { opacity: 0, scale: 0.85 }, 0);
    if (forgedPhoto) tl.set(forgedPhoto, { opacity: 0.3 }, 0);
    if (readoutPart) tl.set(readoutPart, { opacity: 0, y: 10 }, 0);
    if (readoutVerdict) tl.set(readoutVerdict, { opacity: 0, y: 8 }, 0);
    if (readoutBinding) tl.set(readoutBinding, { opacity: 0, y: 8 }, 0);

    // Beat 1 — the card splits into its signed and unsigned zones.
    if (front) tl.to(front, { x: 0, duration: 0.7 }, 0.15);
    if (back) tl.to(back, { x: 0, duration: 0.7 }, 0.15);

    // Beat 2 — the genuine, signed QR transplants onto the forged card.
    if (transplantPart) tl.to(transplantPart, { opacity: 1, y: 0, duration: 0.4, ease: "power1.out" }, 1.05);
    if (arrow) tl.to(arrow, { opacity: 1, x: 0, duration: 0.3, ease: "power1.out" }, 1.2);
    if (qrDest) tl.to(qrDest, { opacity: 1, scale: 1, duration: 0.35 }, 1.35);
    if (forgedPhoto) tl.to(forgedPhoto, { opacity: 1, duration: 0.3, ease: "power1.out" }, 1.35);

    // Beat 3 — the cross-check catches it: two separate findings land,
    // never merged into one badge, with the smallest of pauses between
    // them so they read as two answers, not one.
    if (readoutPart) tl.to(readoutPart, { opacity: 1, y: 0, duration: 0.4, ease: "power1.out" }, 2.05);
    if (readoutVerdict) tl.to(readoutVerdict, { opacity: 1, y: 0, duration: 0.32, ease: "power1.out" }, 2.1);
    if (readoutBinding) tl.to(readoutBinding, { opacity: 1, y: 0, duration: 0.32, ease: "power1.out" }, 2.32);

    return tl;
  }

  timeline = build();
  timeline?.play(0);

  function replay() {
    if (prefersReducedMotion()) return;
    timeline?.kill();
    timeline = build();
    timeline?.play(0);
  }

  function kill() {
    timeline?.kill();
  }

  return { replay, kill };
}
