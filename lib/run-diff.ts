import type { EvaluationDetail, EvaluationDocumentResult, EvaluationFieldResult } from "./types";

/**
 * What moved between two runs, field by field.
 *
 * The aggregate views answer "which approach is better". They cannot answer
 * "did this change help", because a prompt edit that fixes two documents and
 * breaks two others reads as no change at all. This one names the fields.
 */

export type FieldSide = {
  value: EvaluationFieldResult["actual"];
  matched: boolean;
  confidence: string;
};

export type FieldChange = {
  document: string;
  entity: string;
  expected: EvaluationFieldResult["expected"];
  before: FieldSide | null;
  after: FieldSide | null;
  direction: "fixed" | "broken" | "changed" | "added" | "removed";
};

export type RunDiff = {
  fixed: FieldChange[];
  broken: FieldChange[];
  /** Wrong both times, but not the same wrong. The answer moved; the score did not. */
  changed: FieldChange[];
  added: FieldChange[];
  removed: FieldChange[];
  byDocument: { document: string; changes: FieldChange[] }[];
  onlyInBefore: string[];
  onlyInAfter: string[];
  failedBefore: string[];
  failedAfter: string[];
  summary: {
    fixed: number;
    broken: number;
    changed: number;
    added: number;
    removed: number;
    unchanged: number;
    /** Fixed minus broken: which way the run moved, in fields. */
    net: number;
  };
};

type RunLike = Pick<EvaluationDetail, "documents">;

function side(field: EvaluationFieldResult): FieldSide {
  return { value: field.actual, matched: field.matched, confidence: field.confidence };
}

function sameAnswer(left: EvaluationFieldResult, right: EvaluationFieldResult): boolean {
  // Compared as written, not as scored: two different wrong answers are worth
  // seeing even though neither counts.
  return String(left.actual ?? "") === String(right.actual ?? "");
}

function byName(run: RunLike): Map<string, EvaluationDocumentResult> {
  return new Map((run.documents ?? []).map((document) => [document.name, document]));
}

function fields(document: EvaluationDocumentResult | undefined): Map<string, EvaluationFieldResult> {
  return new Map((document?.items ?? []).map((field) => [field.entity, field]));
}

export function diffRuns(before: RunLike, after: RunLike): RunDiff {
  const beforeDocuments = byName(before);
  const afterDocuments = byName(after);

  const diff: RunDiff = {
    fixed: [], broken: [], changed: [], added: [], removed: [],
    byDocument: [],
    onlyInBefore: [], onlyInAfter: [],
    failedBefore: [], failedAfter: [],
    summary: { fixed: 0, broken: 0, changed: 0, added: 0, removed: 0, unchanged: 0, net: 0 },
  };

  for (const name of beforeDocuments.keys()) {
    if (!afterDocuments.has(name)) diff.onlyInBefore.push(name);
  }
  for (const name of afterDocuments.keys()) {
    if (!beforeDocuments.has(name)) diff.onlyInAfter.push(name);
  }

  const shared = [...beforeDocuments.keys()].filter((name) => afterDocuments.has(name));
  for (const name of shared) {
    const left = beforeDocuments.get(name);
    const right = afterDocuments.get(name);
    // A crashed document has no fields at all. Reading that as every field
    // regressing would bury the ones that genuinely moved.
    if (left?.status !== "ok") diff.failedBefore.push(name);
    if (right?.status !== "ok") diff.failedAfter.push(name);
    if (left?.status !== "ok" || right?.status !== "ok") continue;

    const leftFields = fields(left);
    const rightFields = fields(right);
    const changes: FieldChange[] = [];

    for (const [entity, leftField] of leftFields) {
      const rightField = rightFields.get(entity);
      if (rightField === undefined) {
        const change: FieldChange = {
          document: name, entity, expected: leftField.expected,
          before: side(leftField), after: null, direction: "removed",
        };
        diff.removed.push(change);
        changes.push(change);
        continue;
      }
      if (leftField.matched && rightField.matched) {
        diff.summary.unchanged += 1;
        continue;
      }
      if (!leftField.matched && !rightField.matched && sameAnswer(leftField, rightField)) {
        diff.summary.unchanged += 1;
        continue;
      }

      const direction: FieldChange["direction"] = rightField.matched
        ? "fixed"
        : leftField.matched
          ? "broken"
          : "changed";
      const change: FieldChange = {
        document: name, entity, expected: rightField.expected,
        before: side(leftField), after: side(rightField), direction,
      };
      diff[direction].push(change);
      changes.push(change);
    }

    for (const [entity, rightField] of rightFields) {
      if (leftFields.has(entity)) continue;
      const change: FieldChange = {
        document: name, entity, expected: rightField.expected,
        before: null, after: side(rightField), direction: "added",
      };
      diff.added.push(change);
      changes.push(change);
    }

    if (changes.length) diff.byDocument.push({ document: name, changes });
  }

  diff.summary.fixed = diff.fixed.length;
  diff.summary.broken = diff.broken.length;
  diff.summary.changed = diff.changed.length;
  diff.summary.added = diff.added.length;
  diff.summary.removed = diff.removed.length;
  diff.summary.net = diff.summary.fixed - diff.summary.broken;

  // Most disturbed document first: that is where an explanation is needed.
  diff.byDocument.sort(
    (a, b) => b.changes.length - a.changes.length || a.document.localeCompare(b.document),
  );
  return diff;
}
