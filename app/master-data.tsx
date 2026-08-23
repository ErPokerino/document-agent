"use client";

import {
  AlertCircle,
  Check,
  FilterX,
  Library,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { InfoHint } from "./info-hint";
import type { Subject } from "../lib/types";

/** The reference tables a derived entity is looked up in. */
export function MasterData() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [query, setQuery] = useState("");
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [seeded, setSeeded] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh(search = query) {
    setSubjects(await api.subjects(search));
  }

  useEffect(() => {
    void api.subjects().then(setSubjects).catch((cause) => setError(String(cause)));
  }, []);

  // Search on the server: the register is the kind of table that outgrows the
  // browser long before anything else here does.
  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(query).catch(() => undefined), 200);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-layout wide">
      <div className="settings-intro">
        <Library size={19} />
        <div>
          <h2>Master Data</h2>
          <p>Reference tables the pipeline looks values up in, for fields no document carries.</p>
        </div>
      </div>

      {error && (
        <div className="alert error-alert" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
        </div>
      )}

      <div className="settings-card">
        <div className="settings-card-heading">
          <span className="settings-card-icon"><Library size={18} /></span>
          <div>
            <h3>
              Suppliers
              <InfoHint text="One row per supplier. The normalized name is what a lookup compares against: accents folded, punctuation dropped, legal forms like S.r.l. or Ltd removed." />
            </h3>
            <p>{subjects.length} registered · matched by name to fill id_subject.</p>
          </div>
          <button
            className="secondary-button small"
            disabled={busy}
            title="Add every supplier named in a labelled document that is not registered yet"
            onClick={() => guard(async () => {
              const added = await api.seedSubjects();
              setSeeded(added.length);
              await refresh();
            })}
          >
            {busy ? <LoaderCircle className="spin" size={13} /> : <RefreshCw size={13} />} From datasets
          </button>
        </div>

        {seeded !== null && (
          <p className="field-help good-note">
            <Check size={12} /> {seeded === 0 ? "Nothing to add: every labelled supplier is already registered." : `${seeded} added.`}
          </p>
        )}

        <form
          className="dataset-create"
          onSubmit={(event) => {
            event.preventDefault();
            const name = newName.trim();
            if (!name) return;
            void guard(async () => {
              await api.addSubject(name);
              setNewName("");
              await refresh();
            });
          }}
        >
          <input
            className="text-input"
            placeholder="Add a supplier by name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
          <button type="submit" className="secondary-button small" disabled={busy || !newName.trim()}>
            <Plus size={13} /> Add
          </button>
        </form>

        <div className="subject-search">
          <input
            className="text-input"
            placeholder="Search either spelling…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query && (
            <button className="secondary-button small ghost" onClick={() => setQuery("")}>
              <FilterX size={13} /> Clear
            </button>
          )}
        </div>

        {subjects.length === 0 ? (
          <p className="field-help">
            {query ? "No supplier matches that." : "The register is empty. Add one above, or fill it from the labelled documents."}
          </p>
        ) : (
          <div className="subject-list">
            {subjects.map((subject) => (
              <div className="subject-row" key={subject.id_subject}>
                {confirmingDelete === subject.id_subject ? (
                  <div className="row-confirm">
                    <span><strong>Remove {subject.name}?</strong> Documents already matched to it keep the id.</span>
                    <button className="secondary-button small ghost" onClick={() => setConfirmingDelete(null)}>Cancel</button>
                    <button
                      className="secondary-button small danger"
                      onClick={() => guard(async () => {
                        await api.deleteSubject(subject.id_subject);
                        setConfirmingDelete(null);
                        await refresh();
                      })}
                    >
                      <Trash2 size={13} /> Remove
                    </button>
                  </div>
                ) : editing === subject.id_subject ? (
                  <form
                    className="rename-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void guard(async () => {
                        await api.updateSubject(subject.id_subject, editValue.trim());
                        setEditing(null);
                        await refresh();
                      });
                    }}
                  >
                    {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
                    <input autoFocus value={editValue} onChange={(event) => setEditValue(event.target.value)} aria-label={`New name for ${subject.name}`} />
                    <button type="submit" className="secondary-button small"><Check size={13} /> Save</button>
                    <button type="button" className="secondary-button small ghost" onClick={() => setEditing(null)}>Cancel</button>
                  </form>
                ) : (
                  <>
                    <code className="subject-id">{subject.id_subject}</code>
                    <div className="subject-meta">
                      <strong>{subject.name}</strong>
                      <small>{subject.normalized_name}</small>
                    </div>
                    <span className={`status-tag ${subject.source === "manual" ? "" : "completed"}`}>{subject.source}</span>
                    <button
                      className="icon-button neutral"
                      aria-label={`Rename ${subject.name}`}
                      title="Rename"
                      onClick={() => { setEditing(subject.id_subject); setEditValue(subject.name); }}
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      className="icon-button"
                      aria-label={`Remove ${subject.name}`}
                      title="Remove"
                      onClick={() => setConfirmingDelete(subject.id_subject)}
                    >
                      <Trash2 size={15} />
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
