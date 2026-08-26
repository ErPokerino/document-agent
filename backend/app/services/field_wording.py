"""What a field should look like, said once for everyone who asks.

Three readers are told the format of a value: Gemini's response schema, the
Custom Extractor's schema, and a local model through its prompt. Each used to
phrase it for itself, and the drift is not hypothetical — the same Custom
Extractor answered `$` for a currency given no description and `USD` when told
the code was ISO 4217.

So the sentence lives here, and the format instruction rides behind whatever
was written about the field in Extraction, which is the part a person meant.

It rides behind it **only when the description does not already say it**. That
is not tidiness: a description reading "Normalize it to YYYY-MM-DD" followed by
"Format the value as YYYY-MM-DD" made the Custom Extractor return no date at
all, every time, while either sentence alone worked every time. Repeating an
instruction to a generative reader is not free.
"""

from app.domain.models import EntityDefinition, EntityFormat


FORMAT_RIDERS = {
    EntityFormat.date: "Format the value as YYYY-MM-DD.",
    EntityFormat.currency: (
        "Give the three-letter ISO 4217 code in upper case, such as EUR, USD or GBP — "
        "never a currency symbol."
    ),
    EntityFormat.decimal: (
        "Give a plain decimal number, with a full stop for the decimal point and no "
        "thousands separator or currency symbol."
    ),
    EntityFormat.integer: "Give a whole number, with no thousands separator.",
}

# What a description has to contain for its format to count as already stated.
# Deliberately the distinctive token rather than a whole phrase: someone will
# write "as YYYY-MM-DD" or "in YYYY-MM-DD format", and both mean the rider
# would be a repetition.
ALREADY_SAID = {
    EntityFormat.date: ("yyyy-mm-dd",),
    EntityFormat.currency: ("iso 4217", "iso4217"),
    EntityFormat.decimal: ("thousands separator", "thousand separator", "decimal point"),
    EntityFormat.integer: ("thousands separator", "thousand separator", "whole number"),
}


def described_for_reader(entity: EntityDefinition) -> str:
    """The field's description, with what its format requires if it is missing."""
    written = (entity.description or "").strip()
    rider = FORMAT_RIDERS.get(entity.format, "")
    if not rider:
        return written

    lowered = written.lower()
    if any(marker in lowered for marker in ALREADY_SAID.get(entity.format, ())):
        return written
    return f"{written} {rider}".strip()
