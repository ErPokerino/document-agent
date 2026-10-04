#!/usr/bin/env bash
# Build the images and deploy DocuFlow to the Google Cloud target an env file
# describes, after provision.sh has made its resources.
#
#   deploy/gcp/deploy.sh deploy/gcp/personal.env
#
# SKIP_BUILD=1 TAG=<tag> redeploys images already built. Everything else comes
# from the env file; nothing here names a project.
set -euo pipefail

ENV_FILE=${1:?usage: deploy.sh <env file>}
# shellcheck disable=SC1090
source "$ENV_FILE"
cd "$(dirname "$0")/../.."

P=(--project "$PROJECT_ID" --region "$REGION" --quiet)
export PREFIX REGION PROJECT_ID DATA_BUCKET MODELS_BUCKET SQL_INSTANCE LLM_MODEL_FILE LLM_PROJECTOR_FILE LLM_MODEL_NAME
export RUN_SA="$PREFIX-run@$PROJECT_ID.iam.gserviceaccount.com"
export LLM_SA="$PREFIX-llm@$PROJECT_ID.iam.gserviceaccount.com"
BUILD_SA="$PREFIX-build@$PROJECT_ID.iam.gserviceaccount.com"
export IMAGE_REPO="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY"
dirty=$([ -n "$(git status --porcelain)" ] && echo "-dirty" || true)
export TAG=${TAG:-$(git rev-parse --short=12 HEAD)$dirty}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

step() { printf '\n== %s\n' "$*"; }
# ${NAME} from the environment; anything else is left as written.
render() { perl -pe 's/\$\{(\w+)\}/exists $ENV{$1} ? $ENV{$1} : $&/ge' "$1"; }

if [ -z "${SKIP_BUILD:-}" ]; then
  step "Images $TAG (Cloud Build)"
  gcloud builds submit "${P[@]}" --config deploy/gcp/cloudbuild.yaml \
    --service-account "projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
    --substitutions "_REPO=$IMAGE_REPO,_TAG=$TAG,_LLAMA=$LLAMA_CPP_IMAGE" .
fi

step "Model server $PREFIX-llm"
render deploy/gcp/llm-service.yaml > "$work/llm.yaml"
gcloud run services replace "$work/llm.yaml" "${P[@]}"
gcloud run services add-iam-policy-binding "$PREFIX-llm" "${P[@]}" \
  --member "serviceAccount:$RUN_SA" --role roles/run.invoker >/dev/null
LLM_URL=$(gcloud run services describe "$PREFIX-llm" "${P[@]}" --format 'value(status.url)')

# The backend's configuration, shared by the app and the worker.
backend_env() {
  local pad=$1
  while IFS= read -r line; do printf '%s%s\n' "$pad" "$line"; done <<EOF
- name: DOCUFLOW_DATA_DIR
  value: /data
- name: DOCUFLOW_DATABASE_URL
  valueFrom: {secretKeyRef: {name: $PREFIX-database-url, key: latest}}
- name: DOCUFLOW_GCP_RUNTIME_IDENTITY
  value: "true"
- name: DOCUFLOW_LOGIN_USER
  value: "$LOGIN_USER"
- name: DOCUFLOW_LOGIN_PASSWORD
  valueFrom: {secretKeyRef: {name: $PREFIX-login-password, key: latest}}
- name: DOCUFLOW_SESSION_SECRET
  valueFrom: {secretKeyRef: {name: $PREFIX-session-secret, key: latest}}
- name: DOCUFLOW_JOBS
  value: cloud_run
- name: DOCUFLOW_JOBS_CLOUD_RUN_JOB
  value: projects/$PROJECT_ID/locations/$REGION/jobs/$PREFIX-worker
- name: DOCUFLOW_MODEL_SERVER_URL
  value: "$LLM_URL"
- name: DOCUFLOW_MODEL_SERVER_AUTH
  value: google_id_token
- name: DOCUFLOW_LM_STUDIO
  value: "off"
EOF
}

step "Worker job $PREFIX-worker"
BACKEND_ENV=$(backend_env "                ") render deploy/gcp/worker-job.yaml > "$work/worker.yaml"
gcloud run jobs replace "$work/worker.yaml" "${P[@]}"
# The app starts executions with the job id as an argument.
gcloud run jobs add-iam-policy-binding "$PREFIX-worker" "${P[@]}" \
  --member "serviceAccount:$RUN_SA" --role roles/run.developer >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$RUN_SA" --project "$PROJECT_ID" --quiet \
  --member "serviceAccount:$RUN_SA" --role roles/iam.serviceAccountUser >/dev/null

step "App $PREFIX"
BACKEND_ENV=$(backend_env "            ") render deploy/gcp/app-service.yaml > "$work/app.yaml"
gcloud run services replace "$work/app.yaml" "${P[@]}"
# Public: the app's own sign-in screen is the door.
gcloud run services add-iam-policy-binding "$PREFIX" "${P[@]}" \
  --member allUsers --role roles/run.invoker >/dev/null

step "Done"
gcloud run services describe "$PREFIX" "${P[@]}" --format 'value(status.url)'
