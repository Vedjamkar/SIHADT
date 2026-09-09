import type { IdentityBinding } from "../types/api";
import { BINDING_COPY } from "../lib/copy";

interface BindingBadgeProps {
  binding: IdentityBinding;
}

/**
 * Identity binding rendered as its own, separate axis from the document
 * verdict — a different visual language (horizontal strip, teal/cyan-grey
 * hue family used nowhere in the verdict palette) so it can never be
 * mistaken for part of the verdict. A GENUINE_SIGNED document with
 * NOT_BOUND identity is the exact case this project exists to represent
 * correctly, so this always renders as a physically separate section.
 */
export function BindingBadge({ binding }: BindingBadgeProps) {
  const copy = BINDING_COPY[binding];

  return (
    <section className="binding-axis" data-anim="binding-axis" aria-label="Identity binding">
      <span className="binding-axis__label">Identity binding</span>
      <span className={`binding-axis__state binding-axis__state--${copy.tone}`}>
        <span className="binding-axis__dot" aria-hidden="true" />
        {copy.title}
      </span>
      <p className="binding-axis__description">{copy.description}</p>
    </section>
  );
}
