/**
 * Visual skins — two complete looks over one set of components.
 *
 * `classic` is the app as built. `institute` is the "1a — The Institute"
 * design handoff (`docs/design/institute/README.md`): serif display type,
 * warm paper neutrals, square corners, no shadows.
 *
 * **The switch is a token swap, not a second component tree.** Every
 * skin-sensitive value in `globals.css` is a custom property, so a skin
 * is a block that redeclares those properties under a
 * `[data-skin="..."]` selector. Nothing renders conditionally on the
 * skin, so the two looks cannot drift apart in behaviour, and a page
 * built after this lands gets both for free.
 *
 * The choice lives in a cookie rather than `localStorage` for one
 * reason: the root layout is a server component and must stamp
 * `data-skin` into the HTML it sends. Reading the skin on the client
 * would mean a frame of the wrong look on every navigation.
 */

export const SKINS = ["classic", "institute"] as const;

export type Skin = (typeof SKINS)[number];

export const DEFAULT_SKIN: Skin = "classic";

export const SKIN_COOKIE = "ttli_skin";

/** How long the demo choice sticks. A year — it is a preference, not a session. */
export const SKIN_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

export const SKIN_LABELS: Record<Skin, string> = {
  classic: "Classic",
  institute: "Institute",
};

/**
 * Anything unrecognised falls back to the default rather than being
 * written into the DOM — the value reaches an attribute selector, and a
 * cookie is client-controlled input.
 */
export function parseSkin(value: string | undefined | null): Skin {
  return SKINS.includes(value as Skin) ? (value as Skin) : DEFAULT_SKIN;
}

/**
 * Whether the demo switcher is offered. Off unless explicitly enabled,
 * so a production tenant does not get a floating control letting anyone
 * restyle their site.
 */
export function skinSwitcherEnabled(): boolean {
  return process.env.NEXT_PUBLIC_SKIN_SWITCHER === "1";
}
