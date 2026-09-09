# Visual spec — measured, not invented

Direction chosen by Ved: **precise dark tech**, in the register of Linear and
Vercel. Animation budget: **one hero moment, everything else quiet.**

Everything below was read off the live sites with `getComputedStyle`, not
recalled or guessed. Where a number looks surprising, it is surprising because
it is real.

---

## The finding that matters most

**Premium dark tech sets large display type LIGHT and TIGHT.**

| | Linear | Vercel |
|---|---|---|
| H1 size | 64px | 64px |
| H1 line-height | 64px (1.0) | 64px (1.0) |
| **H1 weight** | **510** | **400** |
| **H1 letter-spacing** | **−1.408px (−0.022em)** | **−3.84px (−0.06em)** |

Neither uses bold. Both set line-height to exactly 1.0 at display size, and
both pull tracking negative — Vercel aggressively so.

Heavy headings with default tracking are most of what makes a page read as
generic. This is the single highest-leverage correction to make.

## Colour

| Role | Linear | Vercel | Use here |
|---|---|---|---|
| Page background | `#08090A` | `#000000` | `#08090A` — near-black with a faint cool cast reads less severe than pure black |
| Primary text | `#F7F8F8` | `#EDEDED` | `#F7F8F8` |
| Muted text | `#8A8F98` | — | `#8A8F98` |
| CTA | `#E5E5E6` bg, `#08090A` text | — | same: light pill on dark, inverted |

Note both keep primary text *off* pure white. Pure `#FFF` on pure `#000` is a
tell.

## Type

- Linear ships **Inter Variable**; Vercel ships **GeistSans**.
- Body text: **15px / 24px** (1.6). Not 16px.
- UI and CTA text: **13px**.
- The `artifact-design` guidance warns against Inter as an AI default — but
  here it is the *measured* choice of the named reference, so using it is
  grounded rather than lazy. Geist is the alternative and is closer to Vercel.

## Shape

- CTA `border-radius: 9999px` — a full pill. Padding is tight: `0 12px` at 13px.
- Cards and surfaces: subtle low-contrast borders, not drop shadows. Dark UI
  separates surfaces with a 1px border a few percent lighter than the ground,
  never with elevation shadows, which read as light-theme thinking.

## Motion — one moment, then silence

Spend the entire budget on the idea the product turns on:

> An ID card has two halves. The QR is signed; the printed face is just ink.
> A forger transplants a genuine QR onto a card carrying their own photo. We
> compare the photo sealed *inside* the signature against the one printed on
> the card.

That sequence — card splits into signed / unsigned zones, QR lifts and
transplants onto a forged card, the cross-check catches it — is worth real
choreography, because it teaches a mechanism a sentence cannot.

**Everywhere else: interaction feedback only.** State changes, hover, the
verdict arriving. No scroll-jacking, no parallax, no staggered reveals down
the page. In this register, restraint *is* the aesthetic — motion everywhere
is what made the previous attempt feel tacky.

## Non-negotiables that outrank all of the above

These are product decisions and survive any restyling:

1. Never render the word "verified", and never a bare green tick.
2. `verdict` and `identity_binding` are separate axes and must never merge
   into one badge.
3. `UNVERIFIABLE` reads neutral, never as a failure — it is the honest
   outcome for every PAN and every marksheet.
4. Always show the disclaimer and plain-language reasons.
5. Design for the false positive. Most flagged documents belong to honest
   people with bad scans. Nothing accusatory.
6. Nothing parked at `opacity: 0` awaiting a trigger; the page must read at
   rest under `prefers-reduced-motion`.
