"use client";

import { Minus, Plus, Maximize2 } from "lucide-react";
import { useState } from "react";

import { apiUrls } from "../lib/api";
import type { FieldLocation } from "../lib/types";

type Props = {
  runId: number;
  locations: FieldLocation[];
  /** The field the reader is looking at, if any. */
  active: string | null;
  onActive: (entity: string | null) => void;
};

/**
 * The page with a box round each value that was found on it.
 *
 * One of the two things the preview panel can show, not a panel of its own:
 * two copies of the same document stacked down the page was the first attempt
 * and it read as a mistake.
 *
 * An image rather than the PDF viewer, because nothing outside that viewer can
 * know where it put the page, so nothing can be laid over it accurately.
 * Coordinates are normalized, so they hold at any size — which is what lets the
 * image simply fill the panel the iframe was filling.
 */
export function PageHighlight({ runId, locations, active, onActive }: Props) {
  const pages = [...new Set(locations.map((location) => location.page))].sort((a, b) => a - b);
  const activeLocation = locations.find((location) => location.entity === active) ?? null;
  // Following the reader: pointing at a field on another page turns to it.
  const shown = activeLocation ? activeLocation.page : pages[0] ?? 0;
  const onThisPage = locations.filter((location) => location.page === shown);
  // The boxes are positioned in percentages of the page, so the page can be
  // any width and they follow it. Zoom is that width.
  const [zoom, setZoom] = useState(1);
  const step = (by: number) => setZoom((current) => Math.min(4, Math.max(0.5, Math.round((current + by) * 10) / 10)));

  return (
    <div className="highlight-view">
      <div className="highlight-scroll">
        <div className="highlight-stage" style={{ width: `${zoom * 100}%` }}>
          <img src={apiUrls.runPage(runId, shown)} alt={`Page ${shown + 1}`} />
          {onThisPage.map((location) => (
            <button
              key={location.entity}
              type="button"
              className={`highlight-box ${location.entity === active ? "active" : ""}`}
              style={{
                left: `${location.left * 100}%`,
                top: `${location.top * 100}%`,
                width: `${Math.max(location.right - location.left, 0.004) * 100}%`,
                height: `${Math.max(location.bottom - location.top, 0.004) * 100}%`,
              }}
              title={location.entity}
              aria-label={`${location.entity} on page ${location.page + 1}`}
              onMouseEnter={() => onActive(location.entity)}
              onMouseLeave={() => onActive(null)}
              onFocus={() => onActive(location.entity)}
              onBlur={() => onActive(null)}
            >
              <span>{location.entity}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="highlight-note">
        <span>
          {pages.length > 1 && `Page ${shown + 1} of ${pages.length} with values. `}
          Hover a field to pick it out. A field with no box was never read off the page by OCR.
        </span>
        <span className="highlight-zoom">
          <button type="button" onClick={() => step(-0.25)} disabled={zoom <= 0.5} aria-label="Zoom out"><Minus size={12} /></button>
          <button type="button" onClick={() => setZoom(1)} aria-label="Fit the width" title="Fit the width">
            {zoom === 1 ? <Maximize2 size={11} /> : `${Math.round(zoom * 100)}%`}
          </button>
          <button type="button" onClick={() => step(0.25)} disabled={zoom >= 4} aria-label="Zoom in"><Plus size={12} /></button>
        </span>
      </div>
    </div>
  );
}
