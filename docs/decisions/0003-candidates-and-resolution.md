# 0003 — Steps propose candidates; a strategy chooses

**Context.** A field could come from a model, a Custom Extractor, a regex, a
register lookup or a trained model, and the last step to write it used to win.
Which source to trust per field was implicit in step order and unmeasurable.

**Decision.** The engine records a candidate for every field a step writes —
method, value, confidence, score — by object identity, so an agreeing method is
recorded too. A Resolve candidates step chooses by priority, confidence or
agreement; without it the last candidate is the value, as before.

**Alternatives.** Parallel branches merged at the end — deferred to a branching
engine. Comparing values to detect a write — rejected: it hides agreement.

**Consequences.** The Lab scores each method and the oracle, and can re-resolve
a stored run under another rule without running it.
