"""Which method was right, field by field, and what another strategy would have scored.

The Lab has always asked which pipeline wins. With candidates recorded, it can
ask one level down: for `currency`, how often was the model right, how often
the trained model, and how often was *any* of them right. That last number is
the ceiling a strategy can reach with these methods; the distance from the
resolved accuracy to it is what choosing better could still recover.

Re-resolving a stored run under another strategy reads no document and calls
nothing, so a strategy can be tried in milliseconds.
"""

from dataclasses import dataclass, field
from typing import Any

from app.domain.models import EntityDefinition, FieldCandidate
from app.evaluation.scoring import values_match
from app.pipeline.resolution import ResolutionConfig, resolve


@dataclass
class MethodTally:
    method: str
    documents: int = 0
    answered: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float | None:
        return self.correct / self.documents if self.documents else None


@dataclass
class EntityMethods:
    entity: str
    documents: int = 0
    resolved_correct: int = 0
    oracle_correct: int = 0
    methods: dict[str, MethodTally] = field(default_factory=dict)

    @property
    def resolved_accuracy(self) -> float | None:
        return self.resolved_correct / self.documents if self.documents else None

    @property
    def oracle_accuracy(self) -> float | None:
        return self.oracle_correct / self.documents if self.documents else None


def _candidates(item: Any) -> list[FieldCandidate]:
    return [FieldCandidate.model_validate(candidate) for candidate in item.candidates or []]


def method_report(entities: list[EntityDefinition], documents: list[Any]) -> list[EntityMethods]:
    """Per field, each method's accuracy, the resolved one, and the oracle."""
    by_name = {entity.name: entity for entity in entities}
    report: dict[str, EntityMethods] = {}
    for document in documents:
        for item in document.items:
            entity = by_name.get(item.entity)
            candidates = _candidates(item)
            if entity is None or not candidates:
                continue
            tally = report.setdefault(item.entity, EntityMethods(item.entity))
            tally.documents += 1
            tally.resolved_correct += int(item.matched)
            # A method's last word on the field is its answer.
            latest = {candidate.method: candidate for candidate in candidates}
            right = False
            for method, candidate in latest.items():
                scored = tally.methods.setdefault(method, MethodTally(method))
                scored.documents += 1
                scored.answered += int(candidate.value is not None)
                if values_match(item.expected, candidate.value, entity):
                    scored.correct += 1
                    right = True
            tally.oracle_correct += int(right)
    return [report[entity.name] for entity in entities if entity.name in report]


@dataclass
class Resimulated:
    matched: int = 0
    total: int = 0
    per_entity: dict[str, list[int]] = field(default_factory=dict)


def resimulate(entities: list[EntityDefinition], documents: list[Any], config: ResolutionConfig) -> Resimulated:
    """The run's score had its candidates been resolved under `config`.

    Fields recorded without candidates keep the score they had: there is
    nothing to choose between.
    """
    by_name = {entity.name: entity for entity in entities}
    result = Resimulated()
    for document in documents:
        for item in document.items:
            entity = by_name.get(item.entity)
            if entity is None:
                continue
            candidates = _candidates(item)
            if candidates:
                chosen = resolve(entity, candidates, config.rule_for(item.entity))
                actual = chosen.value if chosen is not None else None
                matched = values_match(item.expected, actual, entity)
            else:
                matched = item.matched
            tally = result.per_entity.setdefault(item.entity, [0, 0])
            tally[0] += int(matched)
            tally[1] += 1
            result.matched += int(matched)
            result.total += 1
    return result
