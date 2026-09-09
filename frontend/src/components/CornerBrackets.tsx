/**
 * Registration brackets — the four corner marks a capture UI draws around
 * a document to say "this is what's being read," borrowed from the
 * identity-verification scanners this app takes its visual grammar from
 * (Onfido, Persona, Veriff, Sumsub, Jumio) and from Apple Notes / Adobe
 * Scan / Microsoft Lens's own edge-detection overlays. Purely decorative
 * here (no live edge detection exists), but functional in spirit: it
 * marks a frame as "a specimen under examination," never as "a photo in
 * a card."
 *
 * Used on the scan preview during a live check and on the home page's one
 * hero plate, so the two places in the app that carry real motion share
 * one visual language.
 */
export function CornerBrackets() {
  return (
    <>
      <span className="corner-bracket corner-bracket--tl" aria-hidden="true" />
      <span className="corner-bracket corner-bracket--tr" aria-hidden="true" />
      <span className="corner-bracket corner-bracket--bl" aria-hidden="true" />
      <span className="corner-bracket corner-bracket--br" aria-hidden="true" />
    </>
  );
}
