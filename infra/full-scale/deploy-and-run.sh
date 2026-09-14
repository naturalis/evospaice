#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -lt 2 || $# -gt 4 ]]; then
  echo "Usage: $0 RECORD_BIN_MAP.parquet TRUST_POLICY.json [IMAGE_TAG] [RUN_PREFIX]" >&2
  exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd -- "$script_dir/../.." && pwd)
bin_mapping_path=$(realpath "$1")
trust_policy_path=$(realpath "$2")
image_tag=${3:-$(git -C "$repository_root" rev-parse HEAD)}
run_prefix=${4:-runs/insecta-$(date -u +%Y%m%dT%H%M%SZ)}
resource_group='rg-evoispace-tree-lp'
location='swedencentral'
source_account='mlstaiseqhacke1lkzk'
source_container='embedding-results'
source_prefix='insecta/0x8df1258ad040f84'
deployment_name="evospaice-full-scale-$(date -u +%Y%m%dT%H%M%SZ)"
temporary_directory=$(mktemp -d)
trap 'rm -rf "$temporary_directory"' EXIT

for required_file in "$bin_mapping_path" "$trust_policy_path"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Required input does not exist: $required_file" >&2
    exit 2
  fi
done

az deployment sub create \
  --name "$deployment_name" \
  --location "$location" \
  --template-file "$script_dir/main.bicep" \
  --parameters "$script_dir/main.bicepparam" \
  --parameters imageTag="$image_tag" runPrefix="$run_prefix" \
  --only-show-errors >/dev/null

output() {
  az deployment sub show \
    --name "$deployment_name" \
    --query "properties.outputs.$1.value" \
    --output tsv
}

registry_login_server=$(output registryLoginServer)
registry_name=${registry_login_server%%.*}
work_account=$(output workStorageAccountName)
work_container=$(output workContainerName)
prepare_job=$(output prepareJobName)
finalize_job=$(output finalizeJobName)
bin_mapping_object=$(output binMappingObject)
trust_policy_object=$(output trustPolicyObject)
final_manifest_object=$(output finalManifestObject)
staged_source_prefix="reference/embedding-exports/$source_prefix"

principal_id=$(az ad signed-in-user show --query id --output tsv)
storage_id=$(az storage account show \
  --name "$work_account" \
  --resource-group "$resource_group" \
  --query id \
  --output tsv)
az role assignment create \
  --assignee-object-id "$principal_id" \
  --assignee-principal-type User \
  --role 'Storage Blob Data Contributor' \
  --scope "$storage_id" \
  --only-show-errors >/dev/null

for attempt in {1..20}; do
  if az storage container show \
    --account-name "$work_account" \
    --name "$work_container" \
    --auth-mode login \
    --only-show-errors >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" -eq 20 ]]; then
    echo "Timed out waiting for work-account RBAC propagation" >&2
    exit 1
  fi
  sleep 15
done

az acr build \
  --registry "$registry_name" \
  --image "evospaice/tree-builder:$image_tag" \
  "$repository_root" \
  --only-show-errors

blob_exists() {
  az storage blob exists \
    --account-name "$work_account" \
    --container-name "$work_container" \
    --name "$1" \
    --auth-mode login \
    --query exists \
    --output tsv
}

for artifact in manifest.json records.parquet index.faiss; do
  destination_object="$staged_source_prefix/$artifact"
  if [[ $(blob_exists "$destination_object") == 'true' ]]; then
    continue
  fi
  local_path="$temporary_directory/$artifact"
  az storage blob download \
    --account-name "$source_account" \
    --container-name "$source_container" \
    --name "$source_prefix/$artifact" \
    --file "$local_path" \
    --auth-mode login \
    --overwrite true \
    --only-show-errors
  az storage blob upload \
    --account-name "$work_account" \
    --container-name "$work_container" \
    --name "$destination_object" \
    --file "$local_path" \
    --auth-mode login \
    --overwrite false \
    --only-show-errors
  rm -f "$local_path"
done

az storage blob upload \
  --account-name "$work_account" \
  --container-name "$work_container" \
  --name "$bin_mapping_object" \
  --file "$bin_mapping_path" \
  --auth-mode login \
  --overwrite false \
  --only-show-errors
az storage blob upload \
  --account-name "$work_account" \
  --container-name "$work_container" \
  --name "$trust_policy_object" \
  --file "$trust_policy_path" \
  --auth-mode login \
  --overwrite false \
  --only-show-errors

wait_for_execution() {
  local job_name=$1
  local execution_name=$2
  while true; do
    status=$(az containerapp job execution show \
      --name "$job_name" \
      --resource-group "$resource_group" \
      --job-execution-name "$execution_name" \
      --query properties.status \
      --output tsv)
    case "$status" in
      Succeeded)
        return 0
        ;;
      Failed|Stopped|Degraded)
        echo "$job_name execution $execution_name ended with status $status" >&2
        return 1
        ;;
    esac
    sleep 30
  done
}

prepare_execution=$(az containerapp job start \
  --name "$prepare_job" \
  --resource-group "$resource_group" \
  --query name \
  --output tsv)
wait_for_execution "$prepare_job" "$prepare_execution"

partition_manifest="$temporary_directory/partition-manifest.json"
az storage blob download \
  --account-name "$work_account" \
  --container-name "$work_container" \
  --name "$run_prefix/prepare/partition-manifest.json" \
  --file "$partition_manifest" \
  --auth-mode login \
  --overwrite true \
  --only-show-errors
expected_partitions=$(python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["partition_count"])' \
  "$partition_manifest")

while true; do
  completed_partitions=$(az storage blob list \
    --account-name "$work_account" \
    --container-name "$work_container" \
    --prefix "$run_prefix/work/completion/" \
    --auth-mode login \
    --query 'length(@)' \
    --output tsv)
  if [[ "$completed_partitions" -eq "$expected_partitions" ]]; then
    break
  fi
  if [[ "$completed_partitions" -gt "$expected_partitions" ]]; then
    echo "Completion marker count exceeds the partition manifest" >&2
    exit 1
  fi
  echo "Completed partitions: $completed_partitions/$expected_partitions"
  sleep 60
done

finalize_execution=$(az containerapp job start \
  --name "$finalize_job" \
  --resource-group "$resource_group" \
  --query name \
  --output tsv)
wait_for_execution "$finalize_job" "$finalize_execution"

echo "Tree manifest: https://$work_account.blob.core.windows.net/$work_container/$final_manifest_object"
