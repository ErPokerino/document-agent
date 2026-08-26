"use client";

import { ScanSearch } from "lucide-react";
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
 * The page, with a box drawn round each value that was found on it.
 *
 * Rendered as an image rather than shown in the PDF viewer: nothing outside
 * that viewer can know where it put the page, so nothing can be laid over it
 * accurately. Coordinates are normalized, so they hold at any size.
 *
 * A field with no box is a field the OCR never showed — inferred, normalized
 * beyond recognition, or simply not on the page. It is left unmarked rather
 * than pointed somewhere plausible.
 */
export function PageHighlight({ runId, locations, active, onActive }: Props) {
  const pages = [...new Set(locations.map((location) => location.page))].sort((a, b) => a - b);
  const activeLocation = locations.find((location) => location.entity === active) ?? null;
  const [page, setPage] = useState(pages[0] ?? 0);
  const shown = activeLocation ? activeLocation.page : page;

  if (locations.length === 0) return null;

  const onThisPage = locations.filter((location) => location.page === shown);

  return (
    <section className="highlight-panel">
      <div className="panel-heading">
        <div><h2>Where it was found</h2></div>
        <span className="result-badge complete"><ScanSearch size={10} /> {locations.length} located</span>
      </div>
      <p className="panel-copy">
        Hover a field above to pick it out. A field with no box was never read off the page by OCR.
      </p>

      {pages.length > 1 && (
        <div className="highlight-pages">
          {pages.map((candidate) => (
            <button
              key={candidate}
              type="button"
              className={`entity-toggle ${candidate === shown ? "" : "off"}`}
              onClick={() => setPage(candidate)}
            >
              Page {candidate + 1}
            </button>
          ))}
        </div>
      )}

      <div className="highlight-stage">
        <img src={apiUrls.runPage(runId, shown)} alt={`Page ${shown + 1}`} />
        {onThisPage.map((location) => {
          const isActive = location.entity === active;
          return (
            <button
              key={location.entity}
              type="button"
              className={`highlight-box ${isActive ? "active" : ""}`}
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
          );
        })}
      </div>
    </section>
  );
}
