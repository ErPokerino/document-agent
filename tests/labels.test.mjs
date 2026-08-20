import assert from "node:assert/strict";
import test from "node:test";

import { draftFromModel, draftToLabels, labelsToDraft } from "../lib/labels.ts";

const entities = [
  { name: "currency", format: "currency", description: "" },
  { name: "total_amount", format: "decimal", description: "" },
  { name: "supplier_name", format: "text", description: "" },
];

test("an unlabelled document starts with every entity skipped", () => {
  const draft = labelsToDraft({}, entities);

  assert.deepEqual(Object.keys(draft), ["currency", "total_amount", "supplier_name"]);
  assert.equal(draft.currency.mode, "skip");
  assert.equal(draft.currency.text, "");
});

test("existing labels come back as values", () => {
  const draft = labelsToDraft({ currency: "EUR", total_amount: 125.31 }, entities);

  assert.deepEqual(draft.currency, { mode: "value", text: "EUR" });
  assert.deepEqual(draft.total_amount, { mode: "value", text: "125.31" });
  assert.equal(draft.supplier_name.mode, "skip");
});

test("an explicit null label comes back as absent, not as skipped", () => {
  const draft = labelsToDraft({ supplier_name: null }, entities);

  assert.equal(draft.supplier_name.mode, "absent");
});

test("skipped entities are left out of the saved labels", () => {
  const { labels, errors } = draftToLabels(
    { currency: { mode: "value", text: "EUR" }, total_amount: { mode: "skip", text: "" } },
    entities,
  );

  assert.deepEqual(errors, []);
  assert.deepEqual(labels, { currency: "EUR" });
  assert.equal("total_amount" in labels, false);
});

test("an absent entity is saved as an explicit null", () => {
  const { labels } = draftToLabels({ supplier_name: { mode: "absent", text: "" } }, entities);

  assert.equal("supplier_name" in labels, true);
  assert.equal(labels.supplier_name, null);
});

test("numbers are saved as numbers, not as text", () => {
  const { labels } = draftToLabels({ total_amount: { mode: "value", text: " 125.31 " } }, entities);

  assert.equal(labels.total_amount, 125.31);
  assert.equal(typeof labels.total_amount, "number");
});

test("a value that does not fit its format is reported instead of saved", () => {
  const { labels, errors } = draftToLabels(
    { total_amount: { mode: "value", text: "1.234,56" } },
    entities,
  );

  assert.deepEqual(labels, {});
  assert.equal(errors.length, 1);
  assert.match(errors[0], /total_amount/);
});

test("a currency is normalized to upper case", () => {
  const { labels } = draftToLabels({ currency: { mode: "value", text: "eur" } }, entities);

  assert.equal(labels.currency, "EUR");
});

test("a value mode with empty text is treated as not labelled", () => {
  const { labels, errors } = draftToLabels({ currency: { mode: "value", text: "   " } }, entities);

  assert.deepEqual(labels, {});
  assert.deepEqual(errors, []);
});

test("a round trip through the draft preserves the labels", () => {
  const original = { currency: "EUR", total_amount: 125.31, supplier_name: null };

  const { labels } = draftToLabels(labelsToDraft(original, entities), entities);

  assert.deepEqual(labels, original);
});

test("a model draft prefills the values it proposed", () => {
  const draft = draftFromModel({ currency: "EUR", total_amount: 125.31 }, entities);

  assert.deepEqual(draft.currency, { mode: "value", text: "EUR" });
  assert.deepEqual(draft.total_amount, { mode: "value", text: "125.31" });
});

test("a null proposed by the model is left unlabelled, not asserted as absent", () => {
  // "Absent in document" is a claim about the document. The model returning
  // nothing is not evidence of that, so the reviewer has to say so explicitly.
  const draft = draftFromModel({ supplier_name: null }, entities);

  assert.equal(draft.supplier_name.mode, "skip");
});

test("an entity the model never mentioned stays unlabelled", () => {
  const draft = draftFromModel({ currency: "EUR" }, entities);

  assert.equal(draft.supplier_name.mode, "skip");
});
