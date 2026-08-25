"use client";

import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Filter,
  FilterX,
  Library,
  LoaderCircle,
  Pencil,
  Download,
  Plus,
  UploadCloud,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, apiUrls } from "../lib/api";
import { InfoHint } from "./info-hint";
import type { MasterDataImport, MasterDataTable } from "../lib/types";

type Row = Record<string, string>;

/** The reference tables a derived entity is looked up in. */
export function MasterData() {
  const [tables, setTables] = useState<MasterDataTable[]>([]);
  const [imported, setImported] = useState<{ table: string; report: MasterDataImport } | null>(null);
  // One hidden input per table, since each imports into its own.
  const importInputs = useRef<Record<string, HTMLInputElement | null>>({});
  const [tableKey, setTableKey] = useState<string>("");
  const [rows, setRows] = useState<Row[]>([]);
  const [query, setQuery] = useState("");
  const [columnFilters, setColumnFilters] = useState<Row>({});
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sort, setSort] = useState<{ column: string; descending: boolean } | null>(null);
  // Collapsed by default once there are several: a register you are not
  // working on should cost one line, not a screenful.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<Row | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Row>({});
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [seeded, setSeeded] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const table = tables.find((candidate) => candidate.key === tableKey);

  useEffect(() => {
    void api
      .masterDataTables()
      .then((found) => {
        setTables(found);
        setTableKey((current) => current || found[0]?.key || "");
      })
      .catch((cause) => setError(String(cause)));
  }, []);

  const refresh = useCallback(async () => {
    if (!tableKey) return;
    setRows(
      await api.masterDataRows(tableKey, {
        query,
        sort: sort?.column ?? "",
        descending: sort?.descending ?? false,
        filters: columnFilters,
      }),
    );
  }, [tableKey, query, sort, columnFilters]);

  // Search and sort on the server: a reference table is the kind that outgrows
  // the browser long before anything else here does.
  useEffect(() => {
    const timer = window.setTimeout(() => void refresh().catch((cause) => setError(String(cause))), 200);
    return () => window.clearTimeout(timer);
  }, [refresh]);

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

  function toggleSort(column: string) {
    setSort((current) =>
      current?.column === column
        ? current.descending
          ? null
          : { column, descending: true }
        : { column, descending: false },
    );
  }

  function startAdding() {
    if (!table) return;
    // A generated column is left out of the draft: the store fills it in.
    setDraft(
      Object.fromEntries(
        table.columns.filter((column) => column.editable && !column.generated).map((c) => [c.key, ""]),
      ),
    );
  }

  const activeFilters = Object.values(columnFilters).filter((value) => value.trim()).length;
  const isCollapsed = (key: string) => collapsed.has(key);

  function toggleCollapsed(key: string) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
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
          <button onClick={() => setError(null)} aria-label="Close"><X size={15} /></button>
        </div>
      )}

      {tables.length > 1 && (
        <div className="table-tabs">
          {tables.map((candidate) => (
            <button
              key={candidate.key}
              className={`table-tab ${candidate.key === tableKey ? "active" : ""}`}
              onClick={() => { setTableKey(candidate.key); setQuery(""); setSort(null); setDraft(null); }}
            >
              {candidate.label}
            </button>
          ))}
        </div>
      )}

      {table && (
        <div className="settings-card">
          <div className="settings-card-heading">
            <button
              className="collapse-toggle"
              aria-expanded={!isCollapsed(table.key)}
              onClick={() => toggleCollapsed(table.key)}
            >
              {isCollapsed(table.key) ? <ChevronRight size={16} /> : <ChevronDown size={16} />}
              <span className="settings-card-icon"><Library size={18} /></span>
            </button>
            <div>
              <h3>{table.label}</h3>
              <p>
                {table.description} · {rows.length} row{rows.length === 1 ? "" : "s"}
                {query || activeFilters ? " matching" : ""}.
              </p>
            </div>
            <button className="secondary-button small" onClick={startAdding} disabled={busy || draft !== null}>
              <Plus size={13} /> Add row
            </button>
            {table.seed_entity && (
              <button
                className="secondary-button small"
                disabled={busy}
                title={`Add every ${table.seed_entity} named in a labelled document that is not here yet`}
                onClick={() => guard(async () => {
                  const added = await api.seedMasterDataRows(table.key);
                  setSeeded(added.length);
                  await refresh();
                })}
              >
                {busy ? <LoaderCircle className="spin" size={13} /> : <RefreshCw size={13} />} From datasets
              </button>
            )}
            <a
              className="secondary-button small"
              href={apiUrls.masterDataCsv(table.key)}
              download
              title="Download every row as CSV"
            >
              <Download size={13} /> Export
            </a>
            <button
              type="button"
              className="secondary-button small"
              disabled={busy}
              title="Add rows from a CSV. One already in the table is skipped, not duplicated."
              onClick={() => importInputs.current[table.key]?.click()}
            >
              <UploadCloud size={13} /> Import
            </button>
            <input
              ref={(element) => { importInputs.current[table.key] = element; }}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(event) => {
                const picked = event.target.files?.[0];
                event.target.value = "";
                if (!picked) return;
                void guard(async () => {
                  setImported({ table: table.key, report: await api.importMasterData(table.key, picked) });
                  await refresh();
                });
              }}
            />
          </div>

          {!isCollapsed(table.key) && (
          <>
          {imported && imported.table === table.key && (
            <div className="import-report">
              <p className="field-help good-note">
                {imported.report.added} row{imported.report.added === 1 ? "" : "s"} added
                {imported.report.skipped > 0 && `, ${imported.report.skipped} skipped`}.
              </p>
              {imported.report.reasons.length > 0 && (
                <ul>
                  {imported.report.reasons.slice(0, 8).map((reason) => <li key={reason}>{reason}</li>)}
                  {imported.report.reasons.length > 8 && (
                    <li>and {imported.report.reasons.length - 8} more.</li>
                  )}
                </ul>
              )}
            </div>
          )}
          {seeded !== null && (
            <p className="field-help good-note">
              <Check size={12} /> {seeded === 0 ? "Nothing to add: every labelled value is already here." : `${seeded} added.`}
            </p>
          )}

          <div className="subject-search">
            <input
              className="text-input"
              placeholder={`Search ${table.label.toLowerCase()}…`}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button
              className={`secondary-button small ${filtersOpen ? "" : "ghost"}`}
              aria-pressed={filtersOpen}
              onClick={() => setFiltersOpen(!filtersOpen)}
            >
              <Filter size={13} /> Per column{activeFilters ? ` · ${activeFilters}` : ""}
            </button>
            {(query || sort || activeFilters > 0) && (
              <button
                className="secondary-button small ghost"
                onClick={() => { setQuery(""); setSort(null); setColumnFilters({}); }}
              >
                <FilterX size={13} /> Reset
              </button>
            )}
          </div>

          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {table.columns.map((column) => (
                    <th
                      key={column.key}
                      aria-sort={
                        sort?.column === column.key ? (sort.descending ? "descending" : "ascending") : "none"
                      }
                    >
                      <button className="sort-button" onClick={() => toggleSort(column.key)}>
                        {column.label}
                        {sort?.column === column.key && (sort.descending ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                      </button>
                      {column.hint && <InfoHint text={column.hint} placement="below" />}
                    </th>
                  ))}
                  <th aria-label="Actions" />
                </tr>
                {filtersOpen && (
                  <tr className="filter-row">
                    {table.columns.map((column) => (
                      <td key={column.key}>
                        <input
                          value={columnFilters[column.key] ?? ""}
                          placeholder="contains…"
                          aria-label={`Filter by ${column.label}`}
                          onChange={(event) =>
                            setColumnFilters({ ...columnFilters, [column.key]: event.target.value })
                          }
                        />
                      </td>
                    ))}
                    <td />
                  </tr>
                )}
              </thead>
              <tbody>
                {draft && (
                  <tr className="data-row drafting">
                    {table.columns.map((column) => (
                      <td key={column.key}>
                        {column.editable && !column.generated ? (
                          <input
                            value={draft[column.key] ?? ""}
                            aria-label={column.label}
                            onChange={(event) => setDraft({ ...draft, [column.key]: event.target.value })}
                          />
                        ) : (
                          <span className="generated">
                            {column.generated ? "given automatically" : "—"}
                          </span>
                        )}
                      </td>
                    ))}
                    <td className="row-actions">
                      <button
                        className="secondary-button small"
                        disabled={busy}
                        onClick={() => guard(async () => {
                          await api.addMasterDataRow(table.key, draft);
                          setDraft(null);
                          await refresh();
                        })}
                      >
                        <Check size={13} /> Save
                      </button>
                      <button className="secondary-button small ghost" onClick={() => setDraft(null)}>Cancel</button>
                    </td>
                  </tr>
                )}

                {rows.map((row) => {
                  const identifier = row[table.id_column];
                  if (confirmingDelete === identifier) {
                    return (
                      <tr className="data-row" key={identifier}>
                        <td colSpan={table.columns.length + 1}>
                          <div className="row-confirm">
                            <span><strong>Remove {identifier}?</strong> Documents already matched to it keep the value.</span>
                            <button className="secondary-button small ghost" onClick={() => setConfirmingDelete(null)}>Cancel</button>
                            <button
                              className="secondary-button small danger"
                              onClick={() => guard(async () => {
                                await api.deleteMasterDataRow(table.key, identifier);
                                setConfirmingDelete(null);
                                await refresh();
                              })}
                            >
                              <Trash2 size={13} /> Remove
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  }
                  const isEditing = editing === identifier;
                  return (
                    <tr className="data-row" key={identifier}>
                      {table.columns.map((column) => (
                        <td key={column.key} className={column.kind}>
                          {isEditing && column.editable ? (
                            <input
                              value={editValues[column.key] ?? ""}
                              aria-label={`${column.label} of ${identifier}`}
                              onChange={(event) => setEditValues({ ...editValues, [column.key]: event.target.value })}
                            />
                          ) : column.kind === "identifier" ? (
                            <code>{row[column.key]}</code>
                          ) : column.kind === "timestamp" ? (
                            <span className="muted">{(row[column.key] ?? "").replace("T", " ").slice(0, 16)}</span>
                          ) : (
                            row[column.key]
                          )}
                        </td>
                      ))}
                      <td className="row-actions">
                        {isEditing ? (
                          <>
                            <button
                              className="secondary-button small"
                              disabled={busy}
                              onClick={() => guard(async () => {
                                await api.updateMasterDataRow(table.key, identifier, editValues);
                                setEditing(null);
                                await refresh();
                              })}
                            >
                              <Check size={13} /> Save
                            </button>
                            <button className="secondary-button small ghost" onClick={() => setEditing(null)}>Cancel</button>
                          </>
                        ) : (
                          <>
                            <button
                              className="icon-button neutral"
                              aria-label={`Edit ${identifier}`}
                              title="Edit"
                              onClick={() => {
                                setEditing(identifier);
                                setEditValues(
                                  Object.fromEntries(
                                    table.columns.filter((c) => c.editable).map((c) => [c.key, row[c.key] ?? ""]),
                                  ),
                                );
                              }}
                            >
                              <Pencil size={15} />
                            </button>
                            <button
                              className="icon-button"
                              aria-label={`Remove ${identifier}`}
                              title="Remove"
                              onClick={() => setConfirmingDelete(identifier)}
                            >
                              <Trash2 size={15} />
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {rows.length === 0 && !draft && (
            <p className="field-help">
              {query || activeFilters
                ? "Nothing matches that."
                : "This table is empty. Add a row, or fill it from the labelled documents."}
            </p>
          )}
          </>
          )}
        </div>
      )}
    </section>
  );
}
