"""Where state lives and who may call, as the environment says — the same code on any host."""

from pathlib import Path

from app import config


def test_without_settings_data_stays_beside_the_backend(monkeypatch) -> None:
    monkeypatch.delenv("DOCUFLOW_DATA_DIR", raising=False)

    assert config.data_dir() == Path(config.__file__).resolve().parents[1] / "data"


def test_a_deployment_points_the_data_somewhere_else(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCUFLOW_DATA_DIR", str(tmp_path))

    assert config.data_dir() == tmp_path.resolve()
    assert config.gcp_credentials_path(config.data_dir()) == tmp_path.resolve() / "gcp-service-account.json"


def test_origins_are_a_comma_separated_list_without_trailing_slashes(monkeypatch) -> None:
    monkeypatch.setenv("DOCUFLOW_CORS_ORIGINS", "https://docuflow.example.com/, http://localhost:3000")

    assert config.cors_origins() == ["https://docuflow.example.com", "http://localhost:3000"]


def test_the_key_file_can_live_outside_the_data(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DOCUFLOW_GCP_CREDENTIALS", str(tmp_path / "key.json"))

    assert config.gcp_credentials_path(Path("/data")) == tmp_path / "key.json"
