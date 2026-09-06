"""Resolve an extractor once, so a changed default cannot alter a Lab run."""

from app.services.document_ai import DocumentAiClient, DocumentAiError


async def resolve_extractor(client: DocumentAiClient, processor_id: str) -> dict[str, str | None]:
    prefix = f"projects/{client.project_id}/locations/{client.location}/processors/"
    processor, _, requested = processor_id.partition("/processorVersions/")
    resource = prefix + processor
    identity = {"project_id": client.project_id, "location": client.location, "processor_id": processor, "display_name": None, "version": requested if requested not in ("", "stable", "rc", "foundation") else None, "base_model": None}
    try:
        metadata = await client.metadata(resource)
        identity["display_name"] = metadata.get("displayName") or None
        # Google canonicalizes a project id to its numeric project number.
        canonical = metadata.get("name") or resource
        version = canonical + "/processorVersions/" + requested if requested else metadata.get("defaultProcessorVersion")
        for alias in metadata.get("processorVersionAliases") or []:
            if alias.get("alias") == version:
                version = alias.get("processorVersion")
                break
        if version and version.startswith(canonical + "/processorVersions/"):
            identity["version"] = version.rsplit("/", 1)[-1]
            details = await client.metadata(resource + "/processorVersions/" + identity["version"])
            custom = (details.get("genAiModelInfo") or {}).get("customGenAiModelInfo") or {}
            identity["base_model"] = custom.get("baseProcessorVersionId") or None
    except DocumentAiError:
        # Metadata permission can be narrower than process permission. Unknown
        # facts stay unknown; the UI must not claim today's default was used.
        pass
    return identity
