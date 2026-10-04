# 0002 — A Lab run snapshots everything it ran with

**Context.** An accuracy figure is only comparable with another if both say
exactly what produced them. Datasets are edited, pipelines renamed, Google
moves processor defaults, registers change.

**Decision.** A Lab run stores its input PDFs by hash, the labels, the prompts,
the full pipeline definition, the model execution profile, pinned processor
versions, and the supplier register and rules, plus a fingerprint of all of it.
A retry replays the snapshot and refuses a different model profile. Facts a run
did not record stay unknown rather than being filled with today's values.

**Alternatives.** Recording names only — rejected: a retry with today's settings
would average two different experiments into one figure.

**Consequences.** Analytics groups runs by fingerprint. Every new store or
export keeps these fields.
