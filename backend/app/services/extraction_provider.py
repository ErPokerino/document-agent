"""What every model that extracts fields is asked, stated once.

LM Studio and Gemini differ in transport and in schema dialect: LM Studio takes
JSON Schema and turns it into a grammar, Gemini takes a proto `Schema` with no
`pattern`. Everything else is the same question and used to be written twice —
which fields are asked for, how the request is worded, how long one value may
be, how much output an answer may need. Written twice, it drifted: Gemini went
on describing derived fields to the model after LM Studio stopped, and had no
ceiling on a value at all.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.services.field_wording import category_rider
from app.domain.models import (
    EntityDefinition,
    EntityFormat,
    FieldExtraction,
    PromptConfiguration,
    model_entities,
)


# Prefixed to the text an OCR or layout step produced, so the model knows
# where it came from and that it may trust it over its own reading.
DOCUMENT_TEXT_HEADER = (
    "A previous step read the document. Use this text as the source of truth for anything it contains:"
)

# The longest a single extracted value may be. A schema sent to LM Studio
# becomes a grammar, and a grammar permitting an unbounded string permits one
# forever: a model too small for the document cannot answer with invalid JSON,
# so it stays inside an open value and repeats until the token budget or the
# request timeout ends it — ten minutes a document, on this bench. Bounded, the
# same model fails one field instantly and the run carries on. Set well above
# any real invoice field, so it never truncates an answer that was going well.
VALUE_CHARACTER_CEILING = 200
# Characters per token in a value that has gone wrong. Measured on this bench:
# the runaway that the ceiling above was written against ran to 1,289
# characters in 600 tokens, and it was CJK fragments rather than prose, which
# would have run three to four. Two is the pessimistic end, which is where a
# ceiling belongs.
VALUE_CHARACTERS_PER_TOKEN = 2


def page_note(*, total_pages: int, processed_pages: int) -> str:
    """Tell the model how much of the document it is looking at.

    Both numbers, always. A model handed page 1 of a 7-page invoice and told
    nothing reads the first subtotal as the total; told the document is longer
    than what it can see, it returns null instead of guessing.
    """
    document = f"This document has {total_pages} page" + ("" if total_pages == 1 else "s")
    if processed_pages >= total_pages:
        if total_pages == 1:
            return f"{document}, and it is supplied here."
        return f"{document}, and all {total_pages} of them are supplied here."

    missing = total_pages - processed_pages
    seen = (
        "the first page only is supplied here"
        if processed_pages == 1
        else f"only the first {processed_pages} are supplied here"
    )
    return (
        f"{document}, and {seen}: {missing} page" + ("" if missing == 1 else "s") + " "
        "you cannot see follow. Do not infer anything from them. Return null for a value that "
        "is not visible on the pages you were given, and never treat a subtotal or a "
        "carried-forward amount as the final total."
    )


class ExtractionProvider(ABC):
    """A model that reads a document and answers with the configured fields."""

    last_prediction_stats: dict[str, int | float] | None = None

    @abstractmethod
    async def extract_entities(
        self,
        model: str,
        images: list[str],
        prompts: PromptConfiguration,
        page_range: str,
        total_pages: int,
        processed_pages: int,
        document_text: str = "",
    ) -> dict[str, FieldExtraction]:
        """The fields this model was asked for, validated."""

    # -- what is asked ------------------------------------------------------

    @staticmethod
    def _entity_lines(prompts: PromptConfiguration) -> str:
        """The fields the model is asked for. A derived one is never among them."""
        return "\n".join(
            f"- {entity.name} [{entity.format.value}]: {entity.description}"
            + (f" {category_rider(entity)}" if category_rider(entity) else "")
            for entity in model_entities(prompts.entities)
        )

    @staticmethod
    def _user_text(
        prompts: PromptConfiguration,
        page_range: str,
        *,
        total_pages: int,
        processed_pages: int,
        document_text: str = "",
    ) -> str:
        note = page_note(total_pages=total_pages, processed_pages=processed_pages)
        text = f"{prompts.user_prompt.replace('{page_range}', page_range).strip()}\n\n{note}"
        if document_text.strip():
            text = f"{text}\n\n{DOCUMENT_TEXT_HEADER}\n\n{document_text.strip()}"
        return text

    # -- how much of an answer there may be ---------------------------------

    @staticmethod
    def _value_token_ceiling(entity_format: EntityFormat) -> int:
        """The most tokens one value of this format may legally take.

        A date and a currency code are pinned by their own pattern and a number
        by what a number looks like; free text is the only value that can run
        all the way to VALUE_CHARACTER_CEILING.
        """
        if entity_format is EntityFormat.date:
            return 8
        if entity_format is EntityFormat.currency:
            return 4
        if entity_format in (EntityFormat.decimal, EntityFormat.integer):
            return 16
        return VALUE_CHARACTER_CEILING // VALUE_CHARACTERS_PER_TOKEN

    @staticmethod
    def _output_token_budget(entities: list[EntityDefinition]) -> int:
        """Room for the longest answer the schema still permits.

        The property names are part of the generated output, so a schema with
        long names needs a larger budget than one with short names: roughly one
        token per three characters of key, plus the value and the JSON
        punctuation around each property.

        The value allowance is derived from VALUE_CHARACTER_CEILING rather than
        picked, because the two have to agree. A flat 32 tokens a property was
        written before the ceiling existed and is a third of what one bounded
        free-text value can cost, so a schema with six or more text fields
        could be cut off mid-value with nothing wrong in what it was writing —
        the very failure the ceiling was added to remove. The grammar stops a
        runaway now; this number only has to stop truncating good answers.

        Derived entities are excluded because the schema excludes them: the
        model is never asked for a value it will not write.
        """
        entities = model_entities(entities)
        key_tokens = sum(max(1, len(entity.name) // 3) for entity in entities)
        value_tokens = sum(
            ExtractionProvider._value_token_ceiling(entity.format) for entity in entities
        )
        # Four a property for the quotes, the colon and the comma.
        return 128 + key_tokens + value_tokens + len(entities) * 4

    @staticmethod
    def _within_ceiling(
        extraction: dict[str, FieldExtraction], entities: list[EntityDefinition]
    ) -> dict[str, FieldExtraction]:
        """Clear a text value longer than any real field, as the grammar would have.

        A provider whose schema cannot carry a length bound still answers
        inside the same contract: a value past the ceiling is a runaway, not
        a reading.
        """
        bounded = dict(extraction)
        for entity in model_entities(entities):
            field = bounded.get(entity.name)
            value: Any = getattr(field, "value", None)
            if isinstance(value, str) and len(value) > VALUE_CHARACTER_CEILING:
                bounded[entity.name] = FieldExtraction(
                    value=None,
                    confidence="low",
                    warning=(
                        f"The model returned {len(value)} characters, past the "
                        f"{VALUE_CHARACTER_CEILING}-character ceiling for one field, "
                        "and the value was discarded."
                    ),
                )
        return bounded
