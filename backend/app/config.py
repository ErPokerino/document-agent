"""Where DocuFlow keeps its state, and who may call it — read from the environment.

On a developer machine nothing needs setting: data lives in `backend/data`,
the database is a SQLite file there, the frontend is on localhost:3000, Lab
runs execute inside the API process and nobody has to log in — as it always
has. Anywhere else — a container, a VM, a managed service on any cloud — the
same image is pointed at its storage, its database and its origin by
environment variables rather than by code, which is what keeps a deployment
from depending on one provider.

| Variable | Default | Meaning |
|---|---|---|
| `DOCUFLOW_DATA_DIR` | `backend/data` | Settings, datasets, models, caches, and the SQLite file |
| `DOCUFLOW_DATABASE_URL` | unset: SQLite in the data dir | A `postgresql://` address to keep the tables there instead |
| `DOCUFLOW_CORS_ORIGINS` | localhost and 127.0.0.1 on port 3000 | Comma-separated origins allowed to call the API |
| `DOCUFLOW_GCP_CREDENTIALS` | `<data dir>/gcp-service-account.json` | Service-account key for Document AI |
| `DOCUFLOW_GCP_RUNTIME_IDENTITY` | `false` | `true`: call Google APIs as the identity the platform gives the container, with no key file |
| `DOCUFLOW_LOGIN_USER`, `DOCUFLOW_LOGIN_PASSWORD` | unset: no login | The one account allowed in |
| `DOCUFLOW_SESSION_SECRET` | random per process | Signs the login cookie; set it so sessions outlive a restart |
| `DOCUFLOW_JOBS` | `in_process` | `cloud_run`: Lab runs, experiments and training run as Cloud Run job executions |
| `DOCUFLOW_JOBS_CLOUD_RUN_JOB` | — | With `cloud_run`: `projects/<p>/locations/<r>/jobs/<name>` |
| `DOCUFLOW_LM_STUDIO` | `on` | `off` where no LM Studio runs, such as a cloud deployment |
| `DOCUFLOW_GEMINI_VERTEX_PROJECT`, `DOCUFLOW_GEMINI_VERTEX_LOCATION` | unset: the Gemini API with a key | Gemini through Vertex AI in that project and location (`eu`, `global`, a region), as the runtime identity |
| `DOCUFLOW_MODEL_SERVER_URL` | unset | An OpenAI-compatible model server (llama.cpp, vLLM, Ollama…) |
| `DOCUFLOW_MODEL_SERVER_AUTH` | `none` | `bearer` (with `DOCUFLOW_MODEL_SERVER_TOKEN`) or `google_id_token` |
| `DOCUFLOW_MODEL_SERVER_CATALOG` | unset | A JSON file describing the server's models: parameters, quantization, size, vision |
"""

import os
import secrets
from pathlib import Path

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
# Generated once per process: without a configured secret, a restart signs
# everyone out, which is the right failure for a machine nobody configured.
_PROCESS_SECRET = secrets.token_hex(32)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def data_dir() -> Path:
    configured = _env("DOCUFLOW_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATA_DIR


def database_url() -> str:
    return _env("DOCUFLOW_DATABASE_URL")


def cors_origins() -> list[str]:
    configured = os.environ.get("DOCUFLOW_CORS_ORIGINS", "")
    origins = [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]
    return origins or list(DEFAULT_ORIGINS)


def gcp_credentials_path(data: Path) -> Path:
    configured = _env("DOCUFLOW_GCP_CREDENTIALS")
    return Path(configured).expanduser() if configured else data / "gcp-service-account.json"


def gcp_runtime_identity() -> bool:
    return _env("DOCUFLOW_GCP_RUNTIME_IDENTITY").lower() in ("1", "true", "yes")


def login() -> tuple[str, str] | None:
    """The account allowed in, or None when the app is open to whoever reaches it."""
    user, password = _env("DOCUFLOW_LOGIN_USER"), os.environ.get("DOCUFLOW_LOGIN_PASSWORD", "")
    return (user, password) if user and password else None


def session_secret() -> str:
    return _env("DOCUFLOW_SESSION_SECRET") or _PROCESS_SECRET


def jobs_backend() -> str:
    return _env("DOCUFLOW_JOBS") or "in_process"


def cloud_run_job() -> str:
    return _env("DOCUFLOW_JOBS_CLOUD_RUN_JOB")


def runtime_service_account() -> str:
    """The service account a deployment runs as, when it says so (shown, never used to sign)."""
    return _env("DOCUFLOW_RUNTIME_SERVICE_ACCOUNT")


def gemini_vertex() -> tuple[str, str] | None:
    """The project and location to reach Gemini through Vertex AI, or None for the Gemini API."""
    project, location = _env("DOCUFLOW_GEMINI_VERTEX_PROJECT"), _env("DOCUFLOW_GEMINI_VERTEX_LOCATION")
    return (project, location) if project and location else None


def model_garden_project() -> str:
    """Partners share the deployment's project and runtime identity."""
    return _env("DOCUFLOW_MODEL_GARDEN_PROJECT") or _env("DOCUFLOW_GEMINI_VERTEX_PROJECT")


def lm_studio_enabled() -> bool:
    return _env("DOCUFLOW_LM_STUDIO").lower() not in ("off", "false", "0", "no")


def model_server_url() -> str:
    return _env("DOCUFLOW_MODEL_SERVER_URL").rstrip("/")


def model_server_auth() -> str:
    return _env("DOCUFLOW_MODEL_SERVER_AUTH") or "none"


def model_server_token() -> str:
    return _env("DOCUFLOW_MODEL_SERVER_TOKEN")


def model_server_catalog() -> str:
    return _env("DOCUFLOW_MODEL_SERVER_CATALOG")
