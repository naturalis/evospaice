# Full-scale Insecta deployment

This deployment creates the partitioned Container Apps Jobs pipeline in the new
resource group `rg-evoispace-tree-lp`. It does not deploy, update, or assign RBAC in
`rg-ai-seq-h3-hack-e1lkzk`.

## Resources

The subscription-scope template creates:

- `rg-evoispace-tree-lp` in Sweden Central;
- an HNS-enabled ADLS Gen2 work account and private `tree-runs` container;
- `tree-subtrees` and `tree-subtrees-poison` queues;
- a Standard Azure Container Registry;
- a Container Apps environment with a configurable Dedicated memory profile;
- `evospaice-prepare-tree`, event-driven `evospaice-subtree-worker`, and
  `evospaice-finalize-tree` jobs;
- separate prepare/finalize and worker managed identities with scoped access
  only to resources in the new group; and
- Log Analytics integration.

The default `E16` profile, 64 GiB prepare/finalize containers, 32 GiB workers,
50,000-BIN shard cap, and ten concurrent workers are starting values. Confirm
regional SKU availability and benchmark the largest partition before a full
run.

## Required inputs

The existing embedding artifacts remain unchanged at:

```text
mlstaiseqhacke1lkzk / embedding-results /
  insecta/0x8df1258ad040f84/manifest.json
  insecta/0x8df1258ad040f84/records.parquet
  insecta/0x8df1258ad040f84/index.faiss
```

The operator script reads and stages these three blobs in the new account using
the signed-in user's existing access. It also requires:

1. `record-bin-map.parquet`, with unique `record_id: string` and non-null
   `bin_uri: string` columns and one row for every embedded record;
2. `trust-policy.json`, with the validated ranks/depths where embedding
   distances may resolve topology and assign branch lengths; and
3. permission to create subscription deployments, role assignments in the new
   group, ACR builds, and Container Apps Job executions.

The production `records.parquet` has no BIN identifier. The prepare job refuses
to build a sequence-per-tip tree when the mapping is absent or incomplete.

## Validate infrastructure

```bash
az bicep build --file infra/full-scale/resources.bicep
az bicep build --file infra/full-scale/main.bicep
az bicep build-params --file infra/full-scale/main.bicepparam
```

Review and replace the image tag and run prefix in
[main.bicepparam](main.bicepparam), and confirm that `E16` is available for
Container Apps workload profiles in Sweden Central.

## Deploy and run

The runner performs the complete operator-controlled sequence:

```bash
infra/full-scale/deploy-and-run.sh \
  /path/to/record-bin-map.parquet \
  /path/to/trust-policy.json \
  <immutable-image-tag> \
  runs/insecta-20260914-001
```

It:

1. deploys only `rg-evoispace-tree-lp` and its resources;
2. grants the signed-in operator Blob Data Contributor on the new work account;
3. builds the versioned image in the new ACR;
4. downloads each immutable source blob and uploads it to the new work account,
   deleting the local temporary copy before continuing;
5. uploads the BIN map and trust policy under the run prefix;
6. starts prepare and waits for it to succeed;
7. waits until every expected queue-driven partition has a durable completion
   marker;
8. starts finalization and waits for it to succeed; and
9. prints the final `tree-manifest.json` URL.

The source account is only read. The script contains no command that creates a
role assignment or writes a blob in the existing resource group.

## Publication contract

For a run prefix `runs/<run-id>`, preparation writes the partition manifest at:

```text
runs/<run-id>/prepare/partition-manifest.json
```

Workers write immutable subtree outputs and then completion markers at:

```text
runs/<run-id>/work/subtree-results/<partition-id>/
runs/<run-id>/work/completion/<partition-id>.json
```

Finalization verifies every marker, worker leaf count, and declared tree/root
representative checksum. It publishes data files first and writes this marker
last:

```text
runs/<run-id>/output/tree-manifest.json
```

A missing final manifest means the run is not published, even if partial files
exist.
