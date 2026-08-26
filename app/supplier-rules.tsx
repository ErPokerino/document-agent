"use client";

import { Plus, Trash2, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { EntityDefinition, SupplierRuleModel } from "../lib/types";
import { InfoHint } from "./info-hint";

type Props = {
  idSubject: string;
  supplierName: string;
  entities: EntityDefinition[];
  onError: (message: string) => void;
  /** So the row above can say how many rules it carries without opening. */
  onCountChange: (count: number) => void;
};

const KINDS = [
  {
    value: "fixed" as const,
    label: "Always this value",
    hint: "Whatever the model read, this field is set to the value below.",
  },
  {
    value: "regex" as const,
    label: "Read it with a pattern",
    hint: "Searched in the page text when a step read one, otherwise in the value the model returned. The first capture group is taken, or the whole match if there is none.",
  },
  {
    value: "prompt" as const,
    label: "Ask the model again",
    hint: "One more call, about this field alone. Costs a request per document, so it is worth keeping for what a pattern cannot express.",
  },
];

/**
 * The corrections written for one supplier.
 *
 * They live beside the register because that is what they key on: the id, not
 * the name. Several spellings of a supplier resolve to the same id, and the id
 * is the thing that is either right or wrong.
 */
export function SupplierRules({ idSubject, supplierName, entities, onError, onCountChange }: Props) {
  const [rules, setRules] = useState<SupplierRuleModel[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .supplierRules(idSubject)
      .then((found) => {
        if (cancelled) return;
        setRules(found);
        onCountChange(found.length);
      })
      .catch(() => {
        if (!cancelled) setRules([]);
      });
    return () => {
      cancelled = true;
    };
  }, [idSubject]);

  async function guard(work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
    } catch (error) {
      onError(error instanceof Error ? error.message : "That rule could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const refresh = async () => {
    const found = await api.supplierRules(idSubject);
    setRules(found);
    onCountChange(found.length);
  };

  if (rules === null) return <p className="field-help">Reading the rules…</p>;

  return (
    <div className="supplier-rules">
      <div className="supplier-rules-head">
        <span>
          Rules for {supplierName}
          <InfoHint text="Applied after this supplier has been identified, to its documents only. A rule that sets a value or reads one with a pattern costs nothing. Asking the model again is one extra call per document, and only the fields named are asked about — the rest of the extraction is left alone." />
        </span>
        <button
          type="button"
          className="secondary-button small"
          disabled={busy || entities.length === 0}
          onClick={() =>
            guard(async () => {
              await api.addSupplierRule({
                id_subject: idSubject,
                entity: entities[0].name,
                kind: "fixed",
                value: "",
                pattern: "",
                prompt: "",
                note: "",
              });
              await refresh();
            })
          }
        >
          <Plus size={13} /> Add rule
        </button>
      </div>

      {rules.length === 0 ? (
        <p className="field-help">
          None yet. Every document from this supplier is extracted exactly like any other.
        </p>
      ) : (
        <ul className="supplier-rule-list">
          {rules.map((rule) => {
            const kind = KINDS.find((candidate) => candidate.value === rule.kind) ?? KINDS[0];
            const save = (changes: Partial<SupplierRuleModel>) =>
              guard(async () => {
                await api.updateSupplierRule(rule.id!, changes);
                await refresh();
              });
            return (
              <li key={rule.id}>
                <div className="supplier-rule-row">
                  <label>
                    <span>Field</span>
                    <select value={rule.entity} onChange={(event) => save({ entity: event.target.value })}>
                      {entities.map((entity) => (
                        <option key={entity.name} value={entity.name}>{entity.name}</option>
                      ))}
                      {!entities.some((entity) => entity.name === rule.entity) && (
                        <option value={rule.entity}>{rule.entity} (no longer configured)</option>
                      )}
                    </select>
                  </label>
                  <label>
                    <span>Rule</span>
                    <select value={rule.kind} onChange={(event) => save({ kind: event.target.value as SupplierRuleModel["kind"] })}>
                      {KINDS.map((candidate) => (
                        <option key={candidate.value} value={candidate.value}>{candidate.label}</option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`Remove the ${rule.entity} rule`}
                    disabled={busy}
                    onClick={() => guard(async () => { await api.deleteSupplierRule(rule.id!); await refresh(); })}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                {rule.kind === "fixed" && (
                  <input
                    className="text-input"
                    aria-label={`Value for ${rule.entity}`}
                    placeholder="EUR"
                    defaultValue={rule.value}
                    onBlur={(event) => event.target.value !== rule.value && save({ value: event.target.value })}
                  />
                )}
                {rule.kind === "regex" && (
                  <input
                    className="text-input mono"
                    aria-label={`Pattern for ${rule.entity}`}
                    placeholder="Ns\\. Rif\\.\\s*(\\S+)"
                    defaultValue={rule.pattern}
                    onBlur={(event) => event.target.value !== rule.pattern && save({ pattern: event.target.value })}
                  />
                )}
                {rule.kind === "prompt" && (
                  <textarea
                    className="text-input"
                    rows={2}
                    aria-label={`Instruction for ${rule.entity}`}
                    placeholder="The invoice number is the one beside the stamp, not the one in the header."
                    defaultValue={rule.prompt}
                    onBlur={(event) => event.target.value !== rule.prompt && save({ prompt: event.target.value })}
                  />
                )}
                <p className="field-help">{kind.hint}</p>
              </li>
            );
          })}
        </ul>
      )}

      <p className="field-help">
        <Wand2 size={11} /> A pipeline only applies these if it has a Supplier rules step, after the
        register lookup that identifies the supplier.
      </p>
    </div>
  );
}
