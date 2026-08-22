"use client";

import { Info } from "lucide-react";

type Props = {
  /** The explanation. Shown on hover and on keyboard focus. */
  text: string;
  /** Which side to open on, when the default would run off the panel. */
  align?: "start" | "end";
};

/**
 * An "i" that explains a control, instead of a line of small print under it.
 *
 * A real button so it is reachable by keyboard, and the text is also its
 * accessible name, so a screen reader gets the explanation without hovering.
 */
export function InfoHint({ text, align = "start" }: Props) {
  return (
    <button type="button" className={`info-hint ${align}`} aria-label={text}>
      <Info size={12} aria-hidden="true" />
      <span className="info-hint-bubble" role="tooltip">{text}</span>
    </button>
  );
}
