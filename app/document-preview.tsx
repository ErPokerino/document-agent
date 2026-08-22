"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

import { apiUrls } from "../lib/api";

export type PreviewTarget = { dataset: string; document: string };

/** The PDF beside the work: shared by labelling and by reading a run. */
export function DocumentPreview({
  target,
  onClose,
}: {
  target: PreviewTarget | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!target) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [target, onClose]);

  if (!target) return null;
  const href = apiUrls.documentFile(target.dataset, target.document);

  return (
    <div className="pdf-modal">
      {/* A real button, so dismissing the modal works from the keyboard too. */}
      <button className="pdf-modal-backdrop" aria-label="Close preview" onClick={onClose} />
      <div className="pdf-modal-panel" role="dialog" aria-modal="true" aria-label={`Preview of ${target.document}`}>
        <header>
          <strong>{target.document}</strong>
          <a className="secondary-button small ghost" href={href} target="_blank" rel="noreferrer">Open in a tab</a>
          <button className="icon-button" aria-label="Close preview" onClick={onClose}><X size={15} /></button>
        </header>
        <iframe src={href} title={`Preview of ${target.document}`} />
      </div>
    </div>
  );
}
