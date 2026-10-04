"""Where DocuFlow keeps its state, and who may call it — read from the environment.

On a developer machine nothing needs setting: data lives in `backend/data` and
the frontend is on localhost:3000, as it always has. Anywhere else — a
container, a VM, a managed service on any cloud — the same image is pointed at
its storage and its origin by environment variables rather than by code, which
is what keeps a deployment from depending on one provider.

| Variable | Default | Meaning |
|---|---|---|
| `DOCUFLOW_DATA_DIR` | `backend/data` | Settings, database, datasets, models, caches |
| `DOCUFLOW_CORS_ORIGINS` | localhost and 127.0.0.1 on port 3000 | Comma-separated origins allowed to call the API |
| `DOCUFLOW_GCP_CREDENTIALS` | `<data dir>/gcp-service-account.json` | Service-account key for Document AI |
"""

import os
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")


def data_dir() -> Path:
    configured = os.environ.get("DOCUFLOW_DATA_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATA_DIR


def cors_origins() -> list[str]:
    configured = os.environ.get("DOCUFLOW_CORS_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return origins or list(DEFAULT_ORIGINS)


def gcp_credentials_path(data: Path) -> Path:
    configured = os.environ.get("DOCUFLOW_GCP_CREDENTIALS", "").strip()
    return Path(configured).expanduser() if configured else data / "gcp-service-account.json"
