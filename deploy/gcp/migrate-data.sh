#!/usr/bin/env bash
# Move a local installation's data to a deployed one, once: the files to the
# data bucket, the SQLite history into Cloud SQL.
#
#   PYTHON=.venv/Scripts/python.exe deploy/gcp/migrate-data.sh deploy/gcp/personal.env backend/data
#
# Left behind on purpose: the service-account key (the deployment uses its
# own identity), the Gemini key (blanked in the copied settings; enter it in
# LLM once deployed), and backup or corrupt copies of files. The settings are
# pointed at the model server. Run after deploy.sh, which makes the worker
# job that copies the database from inside Google Cloud.
set -euo pipefail

ENV_FILE=${1:?usage: migrate-data.sh <env file> <data dir>}
DATA_DIR=${2:?usage: migrate-data.sh <env file> <data dir>}
PYTHON=${PYTHON:-python3}
# shellcheck disable=SC1090
source "$ENV_FILE"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
step() { printf '\n== %s\n' "$*"; }

step "Snapshot of the local database"
# The backup API reads a consistent copy, write-ahead log included, while the
# local app may still be running.
"$PYTHON" - "$DATA_DIR/docuflow.db" "$work/docuflow.db" <<'EOF'
import sqlite3, sys
source, target = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
source.backup(target)
target.close(); source.close()
EOF

step "Settings, without keys"
"$PYTHON" - "$DATA_DIR/settings.json" "$work/settings.json" "$LLM_MODEL_NAME" <<'EOF'
import json, sys
settings = json.load(open(sys.argv[1], encoding="utf-8"))
settings.setdefault("gemini", {})["api_key"] = ""
settings["provider"], settings["model"] = "model_server", sys.argv[3]
json.dump(settings, open(sys.argv[2], "w", encoding="utf-8"), indent=2, ensure_ascii=False)
EOF

step "Files to gs://$DATA_BUCKET"
for folder in datasets pipelines artifacts documents evaluation-inputs reading-cache; do
  if [ -d "$DATA_DIR/$folder" ]; then
    gcloud storage rsync --recursive --project "$PROJECT_ID" \
      --exclude '.*\.bak$|.*\.corrupt.*|.*\.tmp$' \
      "$DATA_DIR/$folder" "gs://$DATA_BUCKET/$folder"
  fi
done
gcloud storage cp "$work/settings.json" "gs://$DATA_BUCKET/settings.json" --project "$PROJECT_ID"
gcloud storage cp "$work/docuflow.db" "gs://$DATA_BUCKET/migration/docuflow.db" --project "$PROJECT_ID"

step "History into Cloud SQL (a worker execution)"
gcloud run jobs execute "$PREFIX-worker" --project "$PROJECT_ID" --region "$REGION" --wait \
  --args migrate-sqlite,/data/migration/docuflow.db
gcloud storage rm "gs://$DATA_BUCKET/migration/docuflow.db" --project "$PROJECT_ID"

step "Done"
