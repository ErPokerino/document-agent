"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

import { apiUrls } from "../lib/api";

export type PreviewTarget = { dataset: string; document: string; evaluationId?: number };

/** The PDF beside the work: shared by labelling and by reading a run. */
export function DocumentPreview({
  target,
  onClose,
}: {
  target: PreviewTarget | null;
  onClose: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!target) return;
    const root = panel.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusable = () =>
      [...(root?.querySelectorAll<HTMLElement>("a[href], button:not([disabled]), iframe") ?? [])];
    focusable()[0]?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !root) return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [target, onClose]);

  if (!target) return null;
  const href = target.evaluationId === undefined
    ? apiUrls.documentFile(target.dataset, target.document)
    : apiUrls.evaluationDocument(target.evaluationId, target.document);

  return (
    <div className="pdf-modal">
      {/* A real button, so dismissing the modal works from the keyboard too. */}
      <button className="pdf-modal-backdrop" aria-label="Close preview" onClick={onClose} />
      <div ref={panel} className="pdf-modal-panel" role="dialog" aria-modal="true" aria-label={`Preview of ${target.document}`}>
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
