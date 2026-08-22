import json
import os
from pathlib import Path

from pydantic import ValidationError

from app.domain.models import AppSettings, PromptConfiguration


OLD_SYSTEM_PROMPT = """Sei un agente di estrazione dati specializzato in fatture.
Analizza esclusivamente il contenuto visibile nelle pagine fornite.
Non inventare valori e non usare conoscenze non presenti nel documento.
Restituisci null quando un valore non è presente o non è leggibile.
"""

OLD_USER_PROMPT = """Estrai le entità configurate dalle pagine della fattura {page_range}.
Controlla con attenzione intestazione, riepilogo fiscale e importo finale da pagare.
Restituisci soltanto l'oggetto JSON richiesto.
"""

OLD_ENTITY_DESCRIPTIONS = {
    "date": "Data di emissione della fattura, non la data di scadenza. Normalizzala in YYYY-MM-DD.",
    "document_number": "Identificativo della fattura esattamente come riportato nel documento.",
    "supplier_name": "Ragione sociale o nome commerciale dell'emittente, mai quello del cliente.",
    "currency": "Valuta del totale finale come codice ISO 4217, ad esempio EUR, USD o GBP.",
    "total_amount": "Totale finale della fattura comprensivo di imposte, come numero positivo senza simboli o separatori delle migliaia.",
}


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        raw = self.path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
            return AppSettings.model_validate(self._migrate_defaults(data))
        except (json.JSONDecodeError, ValidationError, TypeError, AttributeError):
            # An unreadable settings file must not make every endpoint fail.
            # Keep the original for inspection and continue from the defaults.
            self.path.with_suffix(".corrupt.json").write_text(raw, encoding="utf-8")
            return AppSettings()

    @staticmethod
    def _migrate_defaults(data: dict) -> dict:
        """Translate only untouched legacy defaults, preserving user customizations."""
        data.pop("input_token_budget", None)
        # The page limit belongs to a pipeline now. app.services.migrations moves
        # the value across at startup; this only stops the stale key from
        # invalidating the whole file.
        data.pop("max_pages_to_analyze", None)
        prompts = data.get("prompts")
        if not isinstance(prompts, dict):
            return data

        defaults = PromptConfiguration()
        if prompts.get("system_prompt", "").strip() == OLD_SYSTEM_PROMPT.strip():
            prompts["system_prompt"] = defaults.system_prompt
        if prompts.get("user_prompt", "").strip() == OLD_USER_PROMPT.strip():
            prompts["user_prompt"] = defaults.user_prompt

        default_descriptions = {entity.name: entity.description for entity in defaults.entities}
        for entity in prompts.get("entities", []):
            if not isinstance(entity, dict):
                continue
            name = entity.get("name")
            description = entity.get("description")
            # Only a legacy default description is translated. `name` may belong
            # to a user-defined entity that has no default to fall back to.
            if description is not None and description == OLD_ENTITY_DESCRIPTIONS.get(name):
                entity["description"] = default_descriptions[name]
        return data

    def write(self, settings: AppSettings) -> AppSettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: an interrupted write can never leave a truncated
        # settings file behind, because the rename is atomic.
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(settings.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return settings
