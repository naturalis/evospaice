locals {
  class_filter_trigger_container_name = "pipeline-triggers"
  class_filter_output_container_name  = "filtered-sequences"
  class_filter_queue_name             = "fasta-filter-trigger-events"
  class_filter_storage_account_name   = "stfunc${local.compact_name_prefix}"
}

resource "azurerm_storage_container" "class_filter_triggers" {
  name               = local.class_filter_trigger_container_name
  storage_account_id = azurerm_storage_account.ml.id
}

resource "azurerm_storage_container" "class_filter_output" {
  name               = local.class_filter_output_container_name
  storage_account_id = azurerm_storage_account.ml.id
}

resource "azurerm_servicebus_namespace" "class_filter" {
  name                = "sb-classfilter-${var.environment}-${local.suffix}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  tags                = local.common_tags
}

resource "azurerm_servicebus_queue" "class_filter" {
  name                                 = local.class_filter_queue_name
  namespace_id                         = azurerm_servicebus_namespace.class_filter.id
  lock_duration                        = "PT5M"
  max_delivery_count                   = 10
  dead_lettering_on_message_expiration = true
}

resource "azurerm_eventgrid_system_topic" "class_filter" {
  name                = "evgt-classfilter-${var.environment}-${local.suffix}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  source_resource_id  = azurerm_storage_account.ml.id
  topic_type          = "Microsoft.Storage.StorageAccounts"

  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags
}

resource "azurerm_role_assignment" "class_filter_eventgrid_servicebus_sender" {
  scope                = azurerm_servicebus_namespace.class_filter.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_eventgrid_system_topic.class_filter.identity[0].principal_id
}

resource "azurerm_eventgrid_system_topic_event_subscription" "class_filter" {
  name                = "evsub-classfilter"
  resource_group_name = azurerm_resource_group.this.name
  system_topic        = azurerm_eventgrid_system_topic.class_filter.name

  included_event_types = [
    "Microsoft.Storage.BlobCreated",
  ]

  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${azurerm_storage_container.class_filter_triggers.name}/blobs/"
  }

  service_bus_queue_endpoint_id = azurerm_servicebus_queue.class_filter.id

  delivery_identity {
    type = "SystemAssigned"
  }

  depends_on = [
    azurerm_role_assignment.class_filter_eventgrid_servicebus_sender,
  ]
}

resource "azurerm_storage_account" "class_filter" {
  name                             = local.class_filter_storage_account_name
  resource_group_name              = azurerm_resource_group.this.name
  location                         = azurerm_resource_group.this.location
  account_tier                     = "Standard"
  account_replication_type         = "LRS"
  public_network_access_enabled    = var.public_access_enabled
  shared_access_key_enabled        = false
  default_to_oauth_authentication  = true
  allow_nested_items_to_be_public  = false
  https_traffic_only_enabled       = true
  min_tls_version                  = "TLS1_2"
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
}

resource "azurerm_storage_container" "class_filter_deployments" {
  name               = "deployments"
  storage_account_id = azurerm_storage_account.class_filter.id
}

resource "azurerm_service_plan" "class_filter" {
  name                = "asp-classfilter-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = local.common_tags
}

resource "azurerm_function_app_flex_consumption" "class_filter" {
  name                = "func-classfilter-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  service_plan_id     = azurerm_service_plan.class_filter.id
  https_only          = true

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.class_filter.primary_blob_endpoint}${azurerm_storage_container.class_filter_deployments.name}"
  storage_authentication_type = "SystemAssignedIdentity"

  runtime_name    = "python"
  runtime_version = "3.12"

  maximum_instance_count = 1

  site_config {
    application_insights_connection_string = azurerm_application_insights.ml.connection_string
  }

  app_settings = {
    AzureWebJobsStorage__accountName              = azurerm_storage_account.class_filter.name
    ServiceBusConnection__fullyQualifiedNamespace = "${azurerm_servicebus_namespace.class_filter.name}.servicebus.windows.net"
    ALLOWED_SOURCE_BLOB_HOSTS                     = join(",", [for account in data.azurerm_storage_account.projectdata : "${account.name}.blob.core.windows.net"])
    OUTPUT_STORAGE_ACCOUNT_URL                    = azurerm_storage_account.ml.primary_blob_endpoint
    OUTPUT_CONTAINER_NAME                         = azurerm_storage_container.class_filter_output.name
  }

  identity {
    type = "SystemAssigned"
  }

  tags = merge(local.common_tags, {
    "hidden-link: /app-insights-resource-id" = replace(
      azurerm_application_insights.ml.id,
      "Microsoft.Insights",
      "microsoft.insights"
    )
  })
}

resource "azurerm_role_assignment" "class_filter_servicebus_receiver" {
  scope                = azurerm_servicebus_namespace.class_filter.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}

resource "azurerm_role_assignment" "class_filter_runtime_blob_owner" {
  scope                = azurerm_storage_account.class_filter.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}

resource "azurerm_role_assignment" "class_filter_runtime_queue_contributor" {
  scope                = azurerm_storage_account.class_filter.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}

resource "azurerm_role_assignment" "class_filter_runtime_table_contributor" {
  scope                = azurerm_storage_account.class_filter.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}

resource "azurerm_role_assignment" "class_filter_trigger_reader" {
  scope                = azurerm_storage_container.class_filter_triggers.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}

resource "azurerm_role_assignment" "class_filter_output_contributor" {
  scope                = azurerm_storage_container.class_filter_output.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}

resource "azurerm_role_assignment" "class_filter_source_reader" {
  provider = azurerm.projectdata

  for_each             = data.azurerm_storage_account.projectdata
  scope                = each.value.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_function_app_flex_consumption.class_filter.identity[0].principal_id
}