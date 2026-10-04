#!/usr/bin/env bash
# Copy the model server's models to the models bucket and describe them there.
#
#   deploy/gcp/upload-models.sh deploy/gcp/personal.env ~/.lmstudio/models
#
# For each line of LLM_MODELS in the env file, the model file and its
# projector are found under the given folder (LM Studio's models folder, say)
# and copied to the bucket unless a copy of the same size is already there.
# Then two files are written beside them:
#   models.ini   the llama.cpp router's presets: one section per model id
#   models.json  what DocuFlow shows about each model: parameters, quantization,
#                size, whether it reads images
# Adding a model is a line in the env file and a run of this script; the
# server reads the list again when it starts.
set -euo pipefail

ENV_FILE=${1:?usage: upload-models.sh <env file> <folder holding the GGUF files>}
SOURCE=${2:?usage: upload-models.sh <env file> <folder holding the GGUF files>}
# shellcheck disable=SC1090
source "$ENV_FILE"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
bucket="gs://$MODELS_BUCKET"

trim() { local value="$*"; value="${value#"${value%%[![:space:]]*}"}"; printf '%s' "${value%"${value##*[![:space:]]}"}"; }
locate() { find "$SOURCE" -type f -name "$1" -print -quit; }
remote_size() { gcloud storage ls -l "$bucket/$1" --project "$PROJECT_ID" 2>/dev/null | awk 'NR==1 {print $1}'; }

upload() {
  local file=$1 local_path size
  local_path=$(locate "$file")
  [ -n "$local_path" ] || { echo "Not found under $SOURCE: $file" >&2; exit 1; }
  size=$(stat -c %s "$local_path")
  if [ "$(remote_size "$file")" = "$size" ]; then
    echo "already in the bucket: $file"
  else
    gcloud storage cp "$local_path" "$bucket/$file" --project "$PROJECT_ID"
  fi
  printf '%s' "$size"
}

{
  echo "version = 1"
  echo
  echo "; Written by deploy/gcp/upload-models.sh from LLM_MODELS. Do not edit here."
} > "$work/models.ini"
printf '{\n' > "$work/models.json"
first=1
while IFS='|' read -r id file projector parameters; do
  id=$(trim "$id"); file=$(trim "$file"); projector=$(trim "$projector"); parameters=$(trim "$parameters")
  [ -n "$id" ] || continue
  echo "== $id"
  bytes=$(upload "$file" | tail -n 1)
  {
    echo
    echo "[$id]"
    echo "model = /models/$file"
  } >> "$work/models.ini"
  vision=false
  if [ -n "$projector" ]; then
    bytes=$((bytes + $(upload "$projector" | tail -n 1)))
    echo "mmproj = /models/$projector" >> "$work/models.ini"
    vision=true
  fi
  quantization=$(printf '%s' "$file" | sed -nE 's/.*[-_.]((I?Q[0-9][A-Za-z0-9_]*)|BF16|F16|F32)\.gguf$/\1/p' | tr '[:lower:]' '[:upper:]')
  [ $first -eq 1 ] || printf ',\n' >> "$work/models.json"
  first=0
  printf '  "%s": {"file": "%s", "parameters": "%s", "quantization": "%s", "size_bytes": %s, "vision": %s}' \
    "$id" "$file" "$parameters" "$quantization" "$bytes" "$vision" >> "$work/models.json"
done <<< "$LLM_MODELS"
printf '\n}\n' >> "$work/models.json"

gcloud storage cp "$work/models.ini" "$work/models.json" "$bucket/" --project "$PROJECT_ID"
echo
cat "$work/models.json"
