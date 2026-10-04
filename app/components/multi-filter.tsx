"use client";
import { useEffect, useId, useRef, useState } from "react";

export function MultiFilter({ label, options, value, onChange }: {
  label: string; options: { value: string; label: string }[];
  value: string[]; onChange: (value: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const id = useId();
  const details = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (details.current && !details.current.contains(event.target as Node)) details.current.open = false;
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && details.current?.open) {
        details.current.open = false;
        details.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", closeOutside); document.removeEventListener("keydown", escape); };
  }, []);
  return <div className="multi-filter">
    <span id={id} className="filter-label">{label}</span>
    <details ref={details} onToggle={event => {
      if (!event.currentTarget.open) return;
      const menu = event.currentTarget.querySelector<HTMLElement>(".multi-filter-menu");
      if (menu) {
        menu.style.left = "0px";
        const bounds = menu.getBoundingClientRect();
        menu.style.left = `${Math.min(0, window.innerWidth - bounds.right - 12)}px`;
      }
    }}>
      <summary aria-label={`${label}: ${value.length ? `${value.length} selected` : "Any"}`}>{value.length ? `${value.length} selected` : "Any"}<span aria-hidden="true">⌄</span></summary>
      <div className="multi-filter-menu">
        <input aria-label={`Search ${label}`} placeholder="Search…" value={query} onChange={event => setQuery(event.target.value)} />
        <button type="button" className="secondary-button small" disabled={options.length === 0 || options.every(option => value.includes(option.value))} onClick={() => onChange(options.map(option => option.value))}>Select all</button>
        <button type="button" className="secondary-button small" disabled={!value.length} onClick={() => onChange([])}>Clear selection</button>
        <div className="multi-filter-options">
          {options.filter(option => option.label.toLowerCase().includes(query.toLowerCase())).map(option =>
            <label key={option.value}><input aria-label={option.label} type="checkbox" checked={value.includes(option.value)} onChange={() => onChange(value.includes(option.value) ? value.filter(item => item !== option.value) : [...value, option.value])} /><span>{option.label}</span></label>)}
          {!options.some(option => option.label.toLowerCase().includes(query.toLowerCase())) && <p>No matches</p>}
        </div>
      </div>
    </details>
  </div>;
}
