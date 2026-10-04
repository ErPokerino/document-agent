#!/usr/bin/env bash
# Create the Google Cloud resources DocuFlow runs on, for one target described
# by an env file (deploy/gcp/personal.env). Safe to run again: every resource
# that already exists is left as it is.
#
#   LOGIN_PASSWORD=... deploy/gcp/provision.sh deploy/gcp/personal.env
#
# LOGIN_PASSWORD is the password of the app's login screen; it goes straight
# into Secret Manager and nowhere else. Leave it unset on a re-run to keep the
# stored one. The database password and the session secret are generated.
set -euo pipefail

ENV_FILE=${1:?usage: provision.sh <env file>}
# shellcheck disable=SC1090
source "$ENV_FILE"

P=(--project "$PROJECT_ID" --quiet)
RUN_SA="$PREFIX-run@$PROJECT_ID.iam.gserviceaccount.com"
LLM_SA="$PREFIX-llm@$PROJECT_ID.iam.gserviceaccount.com"
BUILD_SA="$PREFIX-build@$PROJECT_ID.iam.gserviceaccount.com"

step() { printf '\n== %s\n' "$*"; }
random_hex() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }

step "APIs"
gcloud services enable "${P[@]}" \
  run.googleapis.com sqladmin.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudbuild.googleapis.com iam.googleapis.com \
  documentai.googleapis.com billingbudgets.googleapis.com

step "Artifact Registry repository $REPOSITORY"
gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" "${P[@]}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPOSITORY" --repository-format docker \
       --location "$REGION" --description "DocuFlow images" "${P[@]}"

step "Buckets"
for bucket in "$DATA_BUCKET" "$MODELS_BUCKET"; do
  gcloud storage buckets describe "gs://$bucket" "${P[@]}" >/dev/null 2>&1 \
    || gcloud storage buckets create "gs://$bucket" --location "$REGION" \
         --uniform-bucket-level-access --public-access-prevention "${P[@]}"
done

step "Service accounts"
for account in run llm build; do
  gcloud iam service-accounts describe "$PREFIX-$account@$PROJECT_ID.iam.gserviceaccount.com" "${P[@]}" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "$PREFIX-$account" --display-name "DocuFlow $account" "${P[@]}"
done

step "Cloud SQL instance $SQL_INSTANCE (several minutes the first time)"
if ! gcloud sql instances describe "$SQL_INSTANCE" "${P[@]}" >/dev/null 2>&1; then
  # Reachable only through the Cloud SQL connector: no authorised networks.
  gcloud sql instances create "$SQL_INSTANCE" --database-version POSTGRES_17 \
    --edition enterprise --tier "$SQL_TIER" --region "$REGION" --availability-type zonal \
    --storage-type SSD --storage-size 10 --backup-start-time 02:00 \
    --deletion-protection "${P[@]}"
fi
gcloud sql databases describe docuflow --instance "$SQL_INSTANCE" "${P[@]}" >/dev/null 2>&1 \
  || gcloud sql databases create docuflow --instance "$SQL_INSTANCE" "${P[@]}"

secret_exists() { gcloud secrets describe "$1" "${P[@]}" >/dev/null 2>&1; }
put_secret() {
  secret_exists "$1" || gcloud secrets create "$1" --replication-policy automatic "${P[@]}"
  printf '%s' "$2" | gcloud secrets versions add "$1" --data-file - "${P[@]}" >/dev/null
}

step "Database user and secrets"
if ! secret_exists "$PREFIX-database-url"; then
  password=$(random_hex)
  if gcloud sql users list --instance "$SQL_INSTANCE" "${P[@]}" --format 'value(name)' | grep -qx docuflow; then
    gcloud sql users set-password docuflow --instance "$SQL_INSTANCE" --password "$password" "${P[@]}"
  else
    gcloud sql users create docuflow --instance "$SQL_INSTANCE" --password "$password" "${P[@]}"
  fi
  put_secret "$PREFIX-database-url" \
    "postgresql://docuflow:$password@/docuflow?host=/cloudsql/$PROJECT_ID:$REGION:$SQL_INSTANCE"
fi
secret_exists "$PREFIX-session-secret" || put_secret "$PREFIX-session-secret" "$(random_hex)"
if [ -n "${LOGIN_PASSWORD:-}" ]; then
  put_secret "$PREFIX-login-password" "$LOGIN_PASSWORD"
elif ! secret_exists "$PREFIX-login-password"; then
  echo "LOGIN_PASSWORD is not set and no login password is stored." >&2
  exit 1
fi

step "Permissions"
# Viewer as well as API user: a Lab run pins each processor to the version it
# reads, and only a pinned reading may be cached; that needs the processor's
# metadata, which processing alone does not grant.
for role in roles/documentai.apiUser roles/documentai.viewer roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$RUN_SA" \
    --role "$role" --condition None "${P[@]}" >/dev/null
done
for secret in database-url session-secret login-password; do
  gcloud secrets add-iam-policy-binding "$PREFIX-$secret" --member "serviceAccount:$RUN_SA" \
    --role roles/secretmanager.secretAccessor "${P[@]}" >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$DATA_BUCKET" \
  --member "serviceAccount:$RUN_SA" --role roles/storage.objectUser "${P[@]}" >/dev/null
# The model server reads the models; the app and the worker read their catalog.
for account in "$LLM_SA" "$RUN_SA"; do
  gcloud storage buckets add-iam-policy-binding "gs://$MODELS_BUCKET" \
    --member "serviceAccount:$account" --role roles/storage.objectViewer "${P[@]}" >/dev/null
done
for role in roles/artifactregistry.writer roles/logging.logWriter roles/storage.objectViewer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$BUILD_SA" \
    --role "$role" --condition None "${P[@]}" >/dev/null
done

step "Monthly budget of $BUDGET_AMOUNT"
if ! gcloud billing budgets list --billing-account "$BILLING_ACCOUNT" --format 'value(displayName)' 2>/dev/null \
     | grep -qx "DocuFlow $PROJECT_ID"; then
  # Alerts by email to the billing account's administrators. A budget warns;
  # it does not stop spending.
  gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" \
    --display-name "DocuFlow $PROJECT_ID" --budget-amount "$BUDGET_AMOUNT" \
    --filter-projects "projects/$PROJECT_ID" \
    --threshold-rule percent=0.5 --threshold-rule percent=0.9 \
    --threshold-rule percent=1.0 --threshold-rule percent=1.0,basis=forecasted-spend
fi

step "Done"
