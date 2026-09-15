# FASTA class filter

This Azure Function is triggered when a JSON file is created in the
`pipeline-triggers` container. The trigger file identifies a source FASTA blob:

```json
{
  "source_blob_url": "https://stolargefilesdeva8usci.blob.core.windows.net/sequences/bold.fasta",
  "target_class": "Insecta"
}
```

The source account must be one of the storage accounts configured in
`projectdata_storage_accounts`. The function streams the source rather than
loading it into memory. `target_class` is required and matched
case-insensitively. Matching records are written to
`<target_class lowercase>.fasta` in the `filtered-sequences` container of the
Terraform-managed ML storage account. For example, `Insecta` writes to
`insecta.fasta` and `Aves` writes to `aves.fasta`.

FASTA headers must include a class field. The key is case-insensitive, `=` and
`:` separators are supported, BOLD's `c__<class>` rank prefix is supported, and
fields may be separated by spaces, pipes, or semicolons:

```text
>record-1|kingdom=Animalia|phylum=Arthropoda|class=Insecta|order=Lepidoptera
ACGT
```

```text
>BOLD|record-1|COI-5P k__Animalia;p__Arthropoda;c__Insecta;o__Lepidoptera
ACGT
```

Records without a class field are skipped. Reprocessing a trigger overwrites
the derived output blob, making Event Grid retries idempotent.

## Deployment

Create the infrastructure, then deploy the Function package using the Terraform
outputs:

```bash
./infra/deploy.sh hack --apply

export TF_DATA_DIR="$PWD/infra/.terraform/hack"
resource_group="$(terraform -chdir=infra output -raw resource_group_name)"
function_app="$(terraform -chdir=infra output -raw class_filter_function_app_name)"
./services/class_filter/deploy.sh "$resource_group" "$function_app"
```