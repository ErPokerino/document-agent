"""How well a categorical field was classified, class by class.

Accuracy alone hides a rare class: a field that is "Invoice" nineteen times out
of twenty scores 95% by never answering anything else. Per-class recall and the
macro average of F1 do not, and the confusion matrix says which class is taken
for which.

The coverage curve answers the question an automatic pass has to: accepting
only the answers above a threshold, how many documents pass, and how many of
those are right. It is drawn along the step's own score where every answer has
one — a nearest-neighbour similarity does — and along the confidence band
otherwise, which gives three points rather than a curve and says so.
"""

from dataclasses import dataclass
from typing import Any, Callable

from app.domain.models import category_key
from app.evaluation.scoring import FieldOutcome

# The class of a document that has none, and the answer of a reader that gave
# none. Both are real outcomes: an abstention is not a wrong class, and a
# document labelled "no class" is one more class to get right.
NO_CLASS = "(none)"
CONFIDENCE_ORDER = {"high": 3.0, "medium": 2.0, "low": 1.0}
# Enough points to draw a curve, few enough to read as a table.
MAX_CURVE_POINTS = 40


@dataclass(frozen=True)
class ClassScore:
    label: str
    support: int
    predicted: int
    true_positive: int

    @property
    def precision(self) -> float | None:
        return self.true_positive / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.true_positive / self.support if self.support else None

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None:
            # Never predicted: no precision to speak of, and F1 is then zero
            # for a class that was there to be found.
            return 0.0 if self.support else None
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


@dataclass(frozen=True)
class CoveragePoint:
    threshold: float
    answered: int
    coverage: float
    accuracy: float


@dataclass(frozen=True)
class ClassificationReport:
    entity: str
    documents: int
    accuracy: float | None
    macro_f1: float | None
    classes: list[ClassScore]
    # Rows are what the label says, columns what came back, both in `labels`.
    labels: list[str]
    confusion: list[list[int]]
    # "score", "confidence", or "none" when nothing was answered.
    ranked_by: str
    coverage: list[CoveragePoint]


def _class_of(value: Any) -> tuple[str, str]:
    """The key two spellings of a class share, and how to show it."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return NO_CLASS, NO_CLASS
    shown = " ".join(str(value).split())
    return category_key(shown), shown


def classification_report(entity: str, outcomes: list[FieldOutcome]) -> ClassificationReport:
    scored = [outcome for outcome in outcomes if outcome.entity == entity]
    shown: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []
    for outcome in scored:
        expected_key, expected_shown = _class_of(outcome.expected)
        actual_key, actual_shown = _class_of(outcome.actual)
        shown.setdefault(expected_key, expected_shown)
        shown.setdefault(actual_key, actual_shown)
        pairs.append((expected_key, actual_key))

    def by_name(key: str) -> tuple[bool, str]:
        # "(none)" last, wherever it would sort.
        return key == NO_CLASS, shown[key].casefold()

    expected_keys = sorted({expected for expected, _ in pairs}, key=by_name)
    answered_only = sorted({actual for _, actual in pairs} - set(expected_keys), key=by_name)
    order = expected_keys + answered_only
    index = {key: position for position, key in enumerate(order)}
    confusion = [[0] * len(order) for _ in order]
    for expected, actual in pairs:
        confusion[index[expected]][index[actual]] += 1

    classes = [
        ClassScore(
            label=shown[key],
            support=sum(1 for expected, _ in pairs if expected == key),
            predicted=sum(1 for _, actual in pairs if actual == key),
            true_positive=sum(1 for expected, actual in pairs if expected == actual == key),
        )
        for key in expected_keys
    ]
    f1s = [score.f1 for score in classes if score.f1 is not None]
    matched = sum(outcome.matched for outcome in scored)
    ranked_by, coverage = coverage_curve(scored)

    return ClassificationReport(
        entity=entity,
        documents=len(scored),
        accuracy=matched / len(scored) if scored else None,
        macro_f1=sum(f1s) / len(f1s) if f1s else None,
        classes=classes,
        labels=[shown[key] for key in order],
        confusion=confusion,
        ranked_by=ranked_by,
        coverage=coverage,
    )


def coverage_curve(outcomes: list[FieldOutcome]) -> tuple[str, list[CoveragePoint]]:
    """What accepting only the surest answers would buy, threshold by threshold.

    Coverage is over every scored document, so abstaining shows as a curve
    that never reaches 100%; accuracy is over the answers kept.
    """
    answered = [outcome for outcome in outcomes if outcome.actual is not None]
    if not answered:
        return "none", []
    rank: Callable[[FieldOutcome], float]
    if all(outcome.score is not None for outcome in answered):
        ranked_by = "score"
        rank = lambda outcome: float(outcome.score)  # type: ignore[arg-type]  # noqa: E731
    else:
        ranked_by = "confidence"
        rank = lambda outcome: CONFIDENCE_ORDER.get(outcome.confidence, 0.0)  # noqa: E731

    thresholds = sorted({rank(outcome) for outcome in answered}, reverse=True)
    if len(thresholds) > MAX_CURVE_POINTS:
        stride = (len(thresholds) - 1) / (MAX_CURVE_POINTS - 1)
        thresholds = sorted({thresholds[round(position * stride)] for position in range(MAX_CURVE_POINTS)}, reverse=True)

    points = []
    for threshold in thresholds:
        kept = [outcome for outcome in answered if rank(outcome) >= threshold]
        points.append(
            CoveragePoint(
                threshold=round(threshold, 4),
                answered=len(kept),
                coverage=len(kept) / len(outcomes),
                accuracy=sum(outcome.matched for outcome in kept) / len(kept),
            )
        )
    return ranked_by, points
