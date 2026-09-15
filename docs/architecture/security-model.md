# Security model

## Authentication

The pipeline uses Microsoft Entra managed identities for runtime access. Storage
account shared-key access is disabled where configured by Terraform.

Human deployment and operational access uses Azure CLI authentication:

```bash
az login
```

Credentials, access tokens, connection strings, and SAS values must not be
committed or written to application logs.

## Identities

### Azure ML identity

The AML workspace and compute use the Terraform-managed user-assigned identity.
It receives only the data and workspace roles needed to read inputs, write
outputs, pull/push workspace images, and run AML jobs.

### Function identities

Each Flex Consumption Function has a system-assigned identity. Functions use:

- `AzureWebJobsStorage__accountName` for identity-based host storage
- `ServiceBusConnection__fullyQualifiedNamespace` for identity-based messaging
- `DefaultAzureCredential` for Azure control-plane or Blob SDK access

The empty `AzureWebJobsStorage` value prevents a generated shared-key connection
string from taking precedence.

## RBAC boundaries

### Event Grid

- `Azure Service Bus Data Sender` on the Service Bus namespace

### Queue-consuming Functions

- `Azure Service Bus Data Receiver` on the Service Bus namespace

### Function runtime storage

- `Storage Blob Data Owner`
- `Storage Queue Data Contributor`
- `Storage Table Data Contributor`

### AML submitter Functions

- `AzureML Data Scientist` on the AML workspace
- `Storage Blob Data Contributor` on ML storage where required

### AML compute identity

- read access to input storage/datastores
- contributor access to output storage/datastores
- `AcrPull` and `AcrPush` on the workspace registry where required

Roles are scoped to the narrowest practical resource: container, storage account,
Service Bus namespace, or AML workspace.

## Event validation

Functions validate:

- HTTPS Blob URL
- expected storage host
- expected container
- expected filename suffix
- required JSON fields

Event Grid subscriptions also filter by container prefix and suffix. The species
splitter only accepts paths ending in `/index.faiss`.

## Network posture

The hack environment currently permits public network access to simplify
experimentation. Data-plane operations still require Entra authorization.
Production hardening should add private endpoints, VNet integration, restricted
firewalls, and private DNS for Storage, Service Bus, Key Vault, ACR, AML, and
Functions.

## Terraform state

Terraform state is stored remotely in Azure Blob Storage:

```text
resource group: rg-tfstate
storage account: natstoaiseqtfstatehack
container: tfstate
blob key: h3-hack.terraform.tfstate
```

Local `.terraform`, plan, and state artifacts are ignored. The provider lock file
is committed for reproducibility.

## SAS handling

Normal pipeline execution does not require SAS tokens. Manual large-blob
retrigger operations may use short-lived read-only user-delegation SAS tokens.
Generate them in shell variables, allow clock skew, avoid printing them, and let
them expire promptly.

## Data integrity

- Versioned paths include source ETags.
- Manifests include source identity and SHA-256 checksums.
- FAISS IDs are reconciled with Parquet metadata IDs.
- Downstream `index.faiss` is published only after its metadata and manifest.
- Old completed outputs are retained until replacement outputs validate.
