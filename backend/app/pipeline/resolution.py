"""Several methods propose a value for a field; a strategy chooses one.

A field used to get its value from whichever step wrote it last, so "which
source do we trust for this field" was implicit in step order. Now every step
that writes a field leaves a candidate — its method, value, confidence and
score — and a Resolve step states the choice: by priority between methods, by
confidence, or by agreement.

The same function resolves in a pipeline and in the Lab, where a run's stored
candidates can be resolved again under another strategy without reading a
single document again. That is the point: a strategy is cheap to try only if
trying it does not cost a run.

Without a Resolve step nothing changes: the last candidate is the value, which
is what step order always meant.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import EntityDefinition, EntityFormat, FieldCandidate, FieldExtraction, category_key

Strategy = Literal["last", "priority", "best_confidence", "agreement"]
STRATEGIES: tuple[str, ...] = ("last", "priority", "best_confidence", "agreement")
CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


class FieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Strategy = "last"
    # For `priority`: methods in order of trust. A method not listed is not
    # consulted at all, which is how a method is excluded for one field.
    priority: list[str] = Field(default_factory=list)
    # A candidate that carries a score below this is passed over. One with no
    # score — a model's answer — is not judged by it.
    minimum_score: float | None = Field(default=None, ge=0, le=1)


class ResolutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: FieldRule = Field(default_factory=FieldRule)
    fields: dict[str, FieldRule] = Field(default_factory=dict)

    def rule_for(self, entity: str) -> FieldRule:
        return self.fields.get(entity, self.default)


def same_value(left: Any, right: Any, entity: EntityDefinition) -> bool:
    """Two candidates agree when they would score the same against a label."""
    if left is None or right is None:
        return left is None and right is None
    if entity.format in (EntityFormat.decimal, EntityFormat.integer):
        try:
            return abs(float(left) - float(right)) < 0.005
        except (TypeError, ValueError):
            return False
    return category_key(left) == category_key(right)


def _usable(candidate: FieldCandidate, rule: FieldRule) -> bool:
    if candidate.value is None:
        return False
    if rule.minimum_score is not None and candidate.score is not None and candidate.score < rule.minimum_score:
        return False
    return True


def _from(candidate: FieldCandidate, candidates: list[FieldCandidate], note: str) -> FieldExtraction:
    return FieldExtraction(
        value=candidate.value,
        confidence=candidate.confidence,
        score=candidate.score,
        warning=candidate.warning,
        evidence=f"{note}: {candidate.method}" + (f" · {candidate.evidence}" if candidate.evidence else ""),
        candidates=candidates,
    )


def _none(candidates: list[FieldCandidate], warning: str) -> FieldExtraction:
    return FieldExtraction(value=None, confidence="low", warning=warning, candidates=candidates)


def resolve(entity: EntityDefinition, candidates: list[FieldCandidate], rule: FieldRule) -> FieldExtraction | None:
    """The field's value under `rule`, or None when no method proposed one."""
    if not candidates:
        return None
    if rule.strategy == "last":
        last = candidates[-1]
        return FieldExtraction(
            value=last.value, confidence=last.confidence, score=last.score,
            warning=last.warning, evidence=last.evidence, candidates=candidates,
        )

    usable = [candidate for candidate in candidates if _usable(candidate, rule)]

    if rule.strategy == "priority":
        latest = {candidate.method: candidate for candidate in candidates}
        for method in rule.priority:
            candidate = latest.get(method)
            if candidate is not None and _usable(candidate, rule):
                return _from(candidate, candidates, "First in priority")
        return _none(candidates, "No method in the priority list proposed a usable value.")

    if not usable:
        return _none(candidates, "No method proposed a usable value.")

    if rule.strategy == "best_confidence":
        # Later candidates win ties: a later step usually corrected an earlier one.
        best = max(
            enumerate(usable),
            key=lambda pair: (CONFIDENCE_RANK.get(pair[1].confidence, 0), pair[1].score if pair[1].score is not None else -1, pair[0]),
        )[1]
        return _from(best, candidates, "Most confident")

    # agreement: the value most methods proposed, each method counted once.
    latest_usable = list({candidate.method: candidate for candidate in usable}.values())
    groups: list[list[FieldCandidate]] = []
    for candidate in latest_usable:
        for group in groups:
            if same_value(group[0].value, candidate.value, entity):
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    groups.sort(key=len, reverse=True)
    if len(groups) > 1 and len(groups[0]) == len(groups[1]):
        tied = "; ".join(f"{group[0].value!r} ({', '.join(c.method for c in group)})" for group in groups if len(group) == len(groups[0]))
        return _none(candidates, f"The methods disagree: {tied}.")
    winner = groups[0]
    chosen = max(winner, key=lambda candidate: CONFIDENCE_RANK.get(candidate.confidence, 0))
    field = _from(chosen, candidates, f"Agreed by {len(winner)} of {len(latest_usable)}")
    if len(winner) > 1 and len(groups) == 1:
        # Independent methods giving the same answer is the only confidence
        # here that is not a method grading itself.
        field = field.model_copy(update={"confidence": "high"})
    return field


def resolve_all(
    entities: list[EntityDefinition],
    extraction: dict[str, FieldExtraction],
    config: ResolutionConfig,
) -> dict[str, FieldExtraction]:
    resolved = dict(extraction)
    for entity in entities:
        field = extraction.get(entity.name)
        if field is None or not field.candidates:
            continue
        chosen = resolve(entity, field.candidates, config.rule_for(entity.name))
        if chosen is not None:
            resolved[entity.name] = chosen
    return resolved
