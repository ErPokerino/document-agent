"""Extraction by Google's Custom Extractor, instead of by a language model.

The processor is asked for the fields configured in Extraction and answers with
a value, a confidence and the box the value sits in. Three decisions follow
from that, and each is worth stating because each had an obvious alternative.

**The schema travels with the request.** A generative Custom Extractor accepts
a `schemaOverride` per call, so DocuFlow sends the fields it wants every time
rather than editing the processor's stored schema. The alternative — writing
Extraction's fields into the processor whenever someone edits them — would
make a remote resource shadow a local one, with two ways to fall out of step
and a failed write leaving them disagreeing silently. This way Extraction stays
the one place fields are defined, and the processor is configured once and then
left alone.

**Confidence comes from the processor.** Nothing here asks a model how sure it
is, because a number the extractor computed is worth more than an adjective a
model guessed. The number is kept as well as the band, since the band is only
what the rest of the app happens to read.

**Boxes come with the entities.** For every other pipeline a value's position
has to be searched for in the page text; here the processor says where it was,
so nothing is inferred.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import EntityDefinition, EntityFormat, FieldExtraction, model_entities
from app.services.field_validation import validate_result


# Where the processor's confidence stops meaning "sure". Document AI reports a
# float, and the rest of the app reads three words; these are the two edges
# between them. Set from what the processor returns on a legible field against
# a doubtful one, and deliberately not generous: an adjective that says "high"
# for a coin toss is worse than no adjective.
HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.60

# The document type the schema override describes. One type holding every
# configured field, which is the shape a flat extraction wants.
DOCUMENT_TYPE = "custom_extraction_document_type"

_VALUE_TYPES = {
    EntityFormat.text: "string",
    EntityFormat.currency: "string",
    EntityFormat.date: "datetime",
    EntityFormat.decimal: "number",
    EntityFormat.integer: "number",
}


@dataclass(frozen=True)
class Located:
    entity: str
    page: int
    left: float
    top: float
    right: float
    bottom: float


def schema_override(entities: list[EntityDefinition]) -> dict:
    """The fields to ask this processor for, as a DocumentSchema.

    Only the fields a document actually carries: one a pipeline step fills in
    afterwards — an internal id looked up in a register — is not on the page,
    and asking for it would invite the processor to invent one.

    Nothing is required. A document that does not carry a field should come
    back without it, not with a guess.

    A property carries a name, a type and an occurrence and nothing else — the
    API rejects a description on one. So the field's *name* is what tells a
    generative processor what to look for, and the description written in
    Extraction, which is the prompt every other path uses, cannot travel here.
    Names have to be descriptive for this step in a way they need not be for
    the others.
    """
    properties = [
        {
            "name": entity.name,
            "valueType": _VALUE_TYPES.get(entity.format, "string"),
            "occurrenceType": "OPTIONAL_ONCE",
        }
        for entity in model_entities(entities)
    ]
    return {
        "displayName": "DocuFlow extraction",
        "description": "The fields configured in Extraction.",
        "entityTypes": [
            {
                "name": DOCUMENT_TYPE,
                "baseTypes": ["document"],
                "properties": properties,
            }
        ],
    }


def confidence_band(score: float | None) -> str:
    """The processor's number as the word the rest of the app reads."""
    if score is None:
        return "low"
    if score >= HIGH_CONFIDENCE:
        return "high"
    if score >= MEDIUM_CONFIDENCE:
        return "medium"
    return "low"


def entities_from_response(
    document: dict,
    entities: list[EntityDefinition],
) -> dict[str, FieldExtraction]:
    """What the processor found, as the fields the app configured.

    Every configured field comes back, found or not, so the shape of the answer
    never depends on what happened to be on the page.
    """
    wanted = {entity.name: entity for entity in model_entities(entities)}
    answers: dict[str, dict] = {}
    for found in document.get("entities") or []:
        name = found.get("type")
        # A processor version can return more than it was asked for, and the
        # same field twice. The first answer for a field is the one it is most
        # sure of, and anything unconfigured is not ours to store.
        if name in wanted and name not in answers:
            answers[name] = found

    result: dict[str, FieldExtraction] = {}
    for name, definition in wanted.items():
        found = answers.get(name)
        if found is None:
            result[name] = FieldExtraction(value=None, confidence="low")
            continue
        score = _score(found)
        result[name] = FieldExtraction(
            value=_value(found, definition.format),
            confidence=confidence_band(score),
            score=score,
        )
    return result


def locations_from_response(
    document: dict,
    entities: list[EntityDefinition],
) -> list[Located]:
    """The box round each value the processor placed on a page."""
    wanted = {entity.name for entity in model_entities(entities)}
    located: list[Located] = []
    seen: set[str] = set()

    for found in document.get("entities") or []:
        name = found.get("type")
        if name not in wanted or name in seen:
            continue
        refs = ((found.get("pageAnchor") or {}).get("pageRefs")) or []
        box = _box_of(refs)
        if box is None:
            continue
        seen.add(name)
        located.append(Located(entity=name, **box))
    return located


# -- reading one entity --------------------------------------------------------


def _score(found: dict) -> float | None:
    raw = found.get("confidence")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _value(found: dict, fmt: EntityFormat) -> str | float | int | None:
    normalized = found.get("normalizedValue") or {}
    text = (found.get("mentionText") or "").strip()

    if fmt is EntityFormat.date:
        date = normalized.get("dateValue") or {}
        year, month, day = date.get("year"), date.get("month"), date.get("day")
        if year and month and day:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        # The processor read something it could not resolve to a date. Keeping
        # it lets the reader see what it read; the app's own validation decides
        # whether it is usable.
        return normalized.get("text") or text or None

    if fmt in (EntityFormat.decimal, EntityFormat.integer):
        for candidate in (normalized.get("text"), text):
            number = _number(candidate)
            if number is not None:
                return int(number) if fmt is EntityFormat.integer else number
        return text or None

    return normalized.get("text") or text or None


def _number(text: object) -> float | None:
    if text is None:
        return None
    cleaned = str(text).strip().replace(" ", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _box_of(refs: list[dict]) -> dict | None:
    """One rectangle covering every reference, on the page the first one names.

    A value wrapped over two lines arrives as two references; the reader wants
    one box round the whole of it.
    """
    page: int | None = None
    xs: list[float] = []
    ys: list[float] = []

    for ref in refs:
        try:
            ref_page = int(ref.get("page") or 0)
        except (TypeError, ValueError):
            ref_page = 0
        if page is None:
            page = ref_page
        elif ref_page != page:
            # A box cannot span pages, and the first page is where the reader
            # is sent.
            continue
        vertices = ((ref.get("boundingPoly") or {}).get("normalizedVertices")) or []
        for vertex in vertices:
            xs.append(float(vertex.get("x", 0.0)))
            ys.append(float(vertex.get("y", 0.0)))

    if page is None or not xs or not ys:
        return None
    return {
        "page": page,
        "left": min(xs),
        "top": min(ys),
        "right": max(xs),
        "bottom": max(ys),
    }


def validated_entities_from_response(
    document: dict,
    entities: list[EntityDefinition],
) -> dict[str, FieldExtraction]:
    """What the processor found, put through the app's own validation.

    Whether a value is usable is the app's question, not the reader's: a
    currency here is a three-letter code whoever read the page, and a processor
    that answers `$` has to be corrected exactly as a model would be. Without
    this, one path quietly accepts what every other path rejects.

    The processor's confidence survives, because validation judges the format
    of a value and has nothing to say about how sure its reader was.
    """
    extracted = entities_from_response(document, entities)
    validated = validate_result(
        {
            name: {"value": field.value, "confidence": field.confidence}
            for name, field in extracted.items()
        },
        model_entities(entities),
    )
    return {
        name: field.model_copy(update={"score": extracted[name].score})
        if name in extracted
        else field
        for name, field in validated.items()
    }
