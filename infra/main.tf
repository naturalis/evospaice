resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

data "azurerm_client_config" "current" {}

data "azurerm_storage_account" "projectdata" {
  provider = azurerm.projectdata

  for_each = {
    for account in var.projectdata_storage_accounts :
    account.projectdata_storage_account_name => account
  }

  name                = each.value.projectdata_storage_account_name
  resource_group_name = each.value.projectdata_storage_resource_group_name
}

locals {
  suffix              = random_string.suffix.result
  resource_group_name = coalesce(var.resource_group_name, "rg-ai-seq-h3-${var.environment}-${local.suffix}")
  name_prefix         = "ai-seq-${var.environment}-${local.suffix}"
  compact_name_prefix = "aiseq${var.environment}${local.suffix}"

  key_vault_name          = "kv-${local.name_prefix}"
  log_analytics_name      = "law-${local.name_prefix}"
  app_insights_name       = "appi-${local.name_prefix}"
  ml_storage_account_name = "mlst${local.compact_name_prefix}"
  ml_container_registry_name = coalesce(
    var.ml_container_registry_name,
    "acr${local.compact_name_prefix}"
  )
  ml_workspace_name = "mlws-${local.name_prefix}"
  aml_identity_name = "uid-aml-${local.name_prefix}"

  common_tags = {
    environment = var.environment
    pipeline    = "h3"
  }

  datastore_account_names = {
    for key, sa in data.azurerm_storage_account.projectdata :
    key => sa.name
  }
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.location
  tags     = local.common_tags
}

resource "azurerm_user_assigned_identity" "uai_ml_identity" {
  name                = local.aml_identity_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.common_tags
}

resource "azurerm_storage_account" "ml" {
  name                             = local.ml_storage_account_name
  resource_group_name              = azurerm_resource_group.this.name
  location                         = azurerm_resource_group.this.location
  account_tier                     = var.ml_storage_account_tier
  account_replication_type         = var.ml_storage_account_replication_type
  public_network_access_enabled    = var.public_access_enabled
  shared_access_key_enabled        = false
  default_to_oauth_authentication  = true
  allow_nested_items_to_be_public  = false
  https_traffic_only_enabled       = true
  min_tls_version                  = var.ml_storage_min_tls_version
  cross_tenant_replication_enabled = false
  tags                             = local.common_tags

  blob_properties {
    delete_retention_policy {
      days = var.storage_blob_soft_delete_retention_days
    }
    container_delete_retention_policy {
      days = var.storage_container_soft_delete_retention_days
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_management_lock" "ml_storage" {
  name       = "prevent-accidental-deletion"
  scope      = azurerm_storage_account.ml.id
  lock_level = "CanNotDelete"
  notes      = "Protects the Azure ML storage account from accidental deletion."
}

# ── Diagnostic settings: blob data-plane operations → Log Analytics ──────────
# Routes StorageRead/Write/Delete and Transaction metrics for the blob service
# of the Terraform-managed ML storage account. Allows querying
# blob-level delete events (caller, timestamp, blob URI) via the
# `StorageBlobLogs` table.

locals {
  blob_diagnostic_targets = {
    ml = "${azurerm_storage_account.ml.id}/blobServices/default"
  }
}

resource "azurerm_monitor_diagnostic_setting" "blob" {
  for_each                   = local.blob_diagnostic_targets
  name                       = "diag-blob-${each.key}"
  target_resource_id         = each.value
  log_analytics_workspace_id = azurerm_log_analytics_workspace.ml.id

  enabled_log {
    category = "StorageWrite"
  }

  enabled_log {
    category = "StorageDelete"
  }

  enabled_metric {
    category = "Transaction"
  }
}

resource "azurerm_key_vault" "ml" {
  name                          = local.key_vault_name
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = var.key_vault_sku_name
  purge_protection_enabled      = var.key_vault_purge_protection_enabled
  soft_delete_retention_days    = var.key_vault_soft_delete_retention_days
  rbac_authorization_enabled    = var.key_vault_enable_rbac_authorization
  public_network_access_enabled = var.public_access_enabled
  tags                          = local.common_tags
}

resource "azurerm_log_analytics_workspace" "ml" {
  name                       = local.log_analytics_name
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  sku                        = var.log_analytics_workspace_sku
  retention_in_days          = var.log_analytics_workspace_retention_in_days
  internet_ingestion_enabled = var.public_access_enabled
  internet_query_enabled     = var.public_access_enabled
  tags                       = local.common_tags
}

resource "azurerm_application_insights" "ml" {
  name                = local.app_insights_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  application_type    = var.application_insights_application_type
  workspace_id        = azurerm_log_analytics_workspace.ml.id
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "administrators_kv_secrets_officer" {
  for_each             = toset(var.platform_admin_group_object_ids)
  scope                = azurerm_key_vault.ml.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "administrators_ml_storage_blob_reader" {
  for_each             = toset(var.data_scientist_group_object_ids)
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "ml_storage_blob_contributor" {
  for_each             = toset(var.ml_engineer_group_object_ids)
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "ml_storage_file_contributor" {
  for_each             = toset(var.ml_engineer_group_object_ids)
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Storage File Data Privileged Contributor"
  principal_id         = each.value
}

resource "azapi_resource" "ml" {
  type      = "Microsoft.MachineLearningServices/workspaces@2024-04-01"
  name      = local.ml_workspace_name
  parent_id = azurerm_resource_group.this.id
  location  = azurerm_resource_group.this.location

  schema_validation_enabled = false

  identity {
    type = "SystemAssigned, UserAssigned"
    identity_ids = [
      azurerm_user_assigned_identity.uai_ml_identity.id
    ]
  }

  body = {
    properties = {
      friendlyName                = local.ml_workspace_name
      storageAccount              = azurerm_storage_account.ml.id
      keyVault                    = replace(azurerm_key_vault.ml.id, "Microsoft.KeyVault", "Microsoft.Keyvault")
      applicationInsights         = replace(azurerm_application_insights.ml.id, "Microsoft.Insights", "Microsoft.insights")
      publicNetworkAccess         = var.public_access_enabled ? "Enabled" : "Disabled"
      systemDatastoresAuthMode    = "identity"
      primaryUserAssignedIdentity = azurerm_user_assigned_identity.uai_ml_identity.id
      containerRegistry           = azurerm_container_registry.ml.id
    }
    sku = {
      name = var.ml_workspace_sku_name
      tier = var.ml_workspace_sku_name
    }
    tags = local.common_tags
  }
}

resource "azurerm_machine_learning_compute_cluster" "ml" {
  for_each                      = var.aml_compute_clusters
  name                          = each.value.name
  location                      = azurerm_resource_group.this.location
  machine_learning_workspace_id = azapi_resource.ml.id
  vm_size                       = each.value.vm_size
  vm_priority                   = each.value.vm_priority
  tags                          = local.common_tags

  scale_settings {
    min_node_count                       = each.value.min_instances
    max_node_count                       = each.value.max_instances
    scale_down_nodes_after_idle_duration = each.value.scale_down_idle_duration
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.uai_ml_identity.id]
  }

  depends_on = [
    azurerm_role_assignment.uai_ml_data_scientist,
    azurerm_role_assignment.uai_ml_storage_blob_data_contributor,
    azurerm_role_assignment.uai_ml_storage_file_privileged_contributor
  ]
}

resource "azurerm_role_assignment" "uai_ml_storage_blob_data_contributor" {
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "uai_ml_storage_file_privileged_contributor" {
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Storage File Data Privileged Contributor"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "ml_appinsights_reader" {
  scope                = azurerm_application_insights.ml.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}


resource "azurerm_role_assignment" "ml_kv_secrets_officer" {
  scope                = azurerm_key_vault.ml.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}


resource "azurerm_role_assignment" "ml_kv_reader" {
  scope                = azurerm_key_vault.ml.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "ml_storage_reader" {
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_container_registry" "ml" {
  name                          = local.ml_container_registry_name
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  sku                           = "Basic"
  admin_enabled                 = false
  public_network_access_enabled = true
  zone_redundancy_enabled       = false
  tags                          = local.common_tags
}

resource "azurerm_role_assignment" "ml_acr_pull" {
  scope                = azurerm_container_registry.ml.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "ml_acr_push" {
  scope                = azurerm_container_registry.ml.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "uai_ml_data_scientist" {
  scope                = azapi_resource.ml.id
  role_definition_name = "AzureML Data Scientist"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "aml_data_scientist_administrators" {
  for_each             = setunion(toset(var.ml_engineer_group_object_ids), toset(var.data_scientist_group_object_ids))
  scope                = azapi_resource.ml.id
  role_definition_name = "AzureML Data Scientist"
  principal_id         = each.value
}

resource "azurerm_role_assignment" "uai_projectdata_storage_blob_reader" {
  provider = azurerm.projectdata

  for_each             = data.azurerm_storage_account.projectdata
  scope                = each.value.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.uai_ml_identity.principal_id
}

resource "azurerm_role_assignment" "data_scientists_projectdata_storage_blob_reader" {
  provider = azurerm.projectdata

  for_each = var.manage_data_scientist_projectdata_role_assignments ? {
    for pair in setproduct(toset(var.data_scientist_group_object_ids), toset(keys(data.azurerm_storage_account.projectdata))) :
    "${pair[0]}-${pair[1]}" => {
      principal_id = pair[0]
      account_id   = data.azurerm_storage_account.projectdata[pair[1]].id
    }
  } : {}

  scope                = each.value.account_id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = each.value.principal_id
}

resource "azapi_resource" "datastores" {
  for_each = {
    for ds in var.datastore_definitions :
    ds.datastore_name => ds
  }

  type      = "Microsoft.MachineLearningServices/workspaces/datastores@2024-04-01"
  name      = each.value.datastore_name
  parent_id = azapi_resource.ml.id

  schema_validation_enabled = false

  body = {
    properties = {
      datastoreType = "AzureDataLakeGen2"
      accountName   = local.datastore_account_names[each.value.storage_account]
      filesystem    = each.value.filesystem_name
      endpoint      = "core.windows.net"
      credentials = {
        credentialsType = "None"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = contains(keys(local.datastore_account_names), each.value.storage_account)
      error_message = "datastore_definitions.storage_account must be a projectdata storage account name from projectdata_storage_accounts."
    }
  }

  depends_on = [
    azurerm_role_assignment.uai_projectdata_storage_blob_reader
  ]
}
