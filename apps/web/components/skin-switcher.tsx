"use client";

/**
 * The demo control that flips between the two visual skins
 * (`lib/skin.ts`). Rendered from the root layout only when
 * `NEXT_PUBLIC_SKIN_SWITCHER=1`.
 *
 * It changes one attribute on `<html>` and writes a cookie. No reload,
 * no refetch, no re-render of the page below it: the skin is entirely a
 * CSS custom-property swap, so the browser repaints and that is the
 * whole operation. The cookie exists so the *next* server render agrees
 * with what is already on screen.
 *
 * Rendered as a radio group rather than a toggle button. Two named
 * looks are two choices, and a screen-reader user should hear which one
 * is current — "Institute, selected" — instead of a button whose label
 * has to encode both the current state and the action.
 */
import { useEffect, useState } from "react";

import {
  SKINS,
  SKIN_COOKIE,
  SKIN_COOKIE_MAX_AGE,
  SKIN_LABELS,
  type Skin,
} from "@/lib/skin";

export function SkinSwitcher({ initial }: { initial: Skin }) {
  const [skin, setSkin] = useState<Skin>(initial);

  // Both writes live in the effect rather than in the change handler:
  // they are the two side effects of the state changing, and the React
  // compiler's lint rules are right that an event handler is not where
  // a document-level mutation belongs.
  //
  // On the first render this is a no-op in substance — the server
  // already stamped `data-skin` and the cookie is where the value came
  // from — but running it anyway is what corrects a document restored
  // from the bfcache with a stale attribute, and refreshes a cookie
  // that has aged towards expiry.
  useEffect(() => {
    document.documentElement.dataset.skin = skin;
    // Lax, not Strict: a demo link shared into the session should keep
    // the look the reviewer picked. Not HttpOnly by necessity — this is
    // the one cookie the client itself has to write.
    document.cookie =
      `${SKIN_COOKIE}=${skin}; Path=/; Max-Age=${SKIN_COOKIE_MAX_AGE}; SameSite=Lax` +
      (location.protocol === "https:" ? "; Secure" : "");
  }, [skin]);

  return (
    <fieldset className="skin-switch" aria-label="Visual design">
      <legend className="skin-switch__legend">Design</legend>
      {SKINS.map((option) => (
        <label key={option} className="skin-switch__option">
          <input
            type="radio"
            name="ttli-skin"
            value={option}
            checked={skin === option}
            onChange={() => setSkin(option)}
          />
          <span>{SKIN_LABELS[option]}</span>
        </label>
      ))}
    </fieldset>
  );
}
