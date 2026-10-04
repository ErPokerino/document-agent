# 0001 — Pipelines are ordered steps with declared contracts

**Context.** Extraction can be done many ways — page images or text, a local or
hosted model, Google's Custom Extractor — and followed by deterministic
corrections. Comparing them needs each way to be a configuration, not code.

**Decision.** A pipeline is an ordered list of steps. Each step declares what it
needs (`pdf`, `images`, `text`, `entities`) and what it produces; the compiler
refuses a pipeline whose needs are not met in order, and compiles every step
before the first document is read. Whether a pipeline calls a model or sends
pages to a cloud is read from its steps.

**Alternatives.** A free graph with branches — rejected until the engine can
run branches; a diagram must describe what will actually run. Hard-coded
pipelines — rejected: the point is to compare them.

**Consequences.** New capabilities are a contract and a compiler case. The
visual editor shows the same ordered steps as a flow.
