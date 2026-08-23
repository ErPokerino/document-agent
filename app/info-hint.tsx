"use client";

import { Info } from "lucide-react";

type Props = {
  /** The explanation. Shown on hover and on keyboard focus. */
  text: string;
  /** Which side to open on, when the default would run off the panel. */
  align?: "start" | "end";
  /**
   * Which way to open. The default is upwards; inside a scrolling container
   * that clips its overflow — a table header, say — upwards is cut off, and
   * downwards stays in view.
   */
  placement?: "above" | "below";
};

/**
 * An "i" that explains a control, instead of a line of small print under it.
 *
 * A real button so it is reachable by keyboard, and the text is also its
 * accessible name, so a screen reader gets the explanation without hovering.
 */
export function InfoHint({ text, align = "start", placement = "above" }: Props) {
  return (
    <button type="button" className={`info-hint ${align} ${placement}`} aria-label={text}>
      <Info size={12} aria-hidden="true" />
      <span className="info-hint-bubble" role="tooltip">{text}</span>
    </button>
  );
}
