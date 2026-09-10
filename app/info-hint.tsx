"use client";

import { Info } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Props = {
  text: string;
  align?: "start" | "end";
  placement?: "above" | "below";
};

export function InfoHint({ text, align = "start", placement = "above" }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const bubble = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  function show() {
    if (timer.current) clearTimeout(timer.current);
    setOpen(true);
  }
  function leave() {
    timer.current = setTimeout(() => {
      if (document.activeElement !== trigger.current) setOpen(false);
    }, 150);
  }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useLayoutEffect(() => {
    if (!open) return;
    function position() {
      if (!trigger.current || !bubble.current) return;
      const anchor = trigger.current.getBoundingClientRect();
      const tip = bubble.current.getBoundingClientRect();
      const left = align === "end" ? anchor.right - tip.width : anchor.left;
      const above = anchor.top - tip.height - 8;
      const below = anchor.bottom + 8;
      const top = placement === "above"
        ? (above >= 12 ? above : below)
        : (below + tip.height <= window.innerHeight - 12 ? below : above);
      bubble.current.style.left = `${Math.max(12, Math.min(left, window.innerWidth - tip.width - 12))}px`;
      bubble.current.style.top = `${Math.max(12, Math.min(top, window.innerHeight - tip.height - 12))}px`;
    }
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true);
    function dismiss(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    function outside(event: PointerEvent) {
      if (!trigger.current?.contains(event.target as Node) && !bubble.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", dismiss);
    document.addEventListener("pointerdown", outside);
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
      document.removeEventListener("keydown", dismiss);
      document.removeEventListener("pointerdown", outside);
    };
  }, [open, align, placement, text]);

  return <>
    <button ref={trigger} type="button" className="info-hint" aria-label="More information" aria-describedby={open ? id : undefined}
      onMouseEnter={show} onMouseLeave={leave} onFocus={show} onBlur={leave} onClick={show}>
      <Info size={13} aria-hidden="true" />
    </button>
    {open && createPortal(<div ref={bubble} id={id} className="info-hint-bubble" role="tooltip" onMouseEnter={show} onMouseLeave={leave}>{text}</div>, document.body)}
  </>;
}
