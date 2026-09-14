locals {
  species_splitter_queue_name           = "species-split-trigger-events"
  species_results_container_name        = "species-results"
  species_results_datastore_name        = "speciesresults"
  species_splitter_storage_account_name = "stsplit${local.compact_name_prefix}"
}

resource "azurerm_storage_container" "species_results" {
  name               = local.species_results_container_name
  storage_account_id = azurerm_storage_account.ml.id
}

resource "azapi_resource" "species_results_datastore" {
  type      = "Microsoft.MachineLearningServices/workspaces/datastores@2024-04-01"
  name      = local.species_results_datastore_name
  parent_id = azapi_resource.ml.id

  schema_validation_enabled = false

  body = {
    properties = {
      datastoreType = "AzureBlob"
      accountName   = azurerm_storage_account.ml.name
      containerName = azurerm_storage_container.species_results.name
      endpoint      = "core.windows.net"
      credentials = {
        credentialsType = "None"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.uai_ml_storage_blob_data_contributor,
  ]
}

resource "azurerm_servicebus_queue" "species_splitter" {
  name                                 = local.species_splitter_queue_name
  namespace_id                         = azurerm_servicebus_namespace.class_filter.id
  lock_duration                        = "PT5M"
  max_delivery_count                   = 10
  dead_lettering_on_message_expiration = true
}

resource "azurerm_eventgrid_system_topic_event_subscription" "species_splitter" {
  name                = "evsub-species-splitter"
  resource_group_name = azurerm_resource_group.this.name
  system_topic        = azurerm_eventgrid_system_topic.class_filter.name

  included_event_types = [
    "Microsoft.Storage.BlobCreated",
  ]

  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${azurerm_storage_container.embedding_results.name}/blobs/"
    subject_ends_with   = "/index.faiss"
  }

  service_bus_queue_endpoint_id = azurerm_servicebus_queue.species_splitter.id

  delivery_identity {
    type = "SystemAssigned"
  }

  depends_on = [
    azurerm_role_assignment.class_filter_eventgrid_servicebus_sender,
  ]
}

resource "azurerm_storage_account" "species_splitter" {
  name                             = local.species_splitter_storage_account_name
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

resource "azurerm_storage_container" "species_splitter_deployments" {
  name               = "deployments"
  storage_account_id = azurerm_storage_account.species_splitter.id
}

resource "azurerm_service_plan" "species_splitter" {
  name                = "asp-speciessplit-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = local.common_tags
}

resource "azurerm_function_app_flex_consumption" "species_splitter" {
  name                = "func-speciessplit-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  service_plan_id     = azurerm_service_plan.species_splitter.id
  https_only          = true

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.species_splitter.primary_blob_endpoint}${azurerm_storage_container.species_splitter_deployments.name}"
  storage_authentication_type = "SystemAssignedIdentity"

  runtime_name    = "python"
  runtime_version = "3.12"

  maximum_instance_count = 1

  site_config {
    application_insights_connection_string = azurerm_application_insights.ml.connection_string
  }

  app_settings = {
    AzureWebJobsStorage                           = ""
    AzureWebJobsStorage__accountName              = azurerm_storage_account.species_splitter.name
    ServiceBusConnection__fullyQualifiedNamespace = "${azurerm_servicebus_namespace.class_filter.name}.servicebus.windows.net"
    EMBEDDING_BLOB_HOST                           = azurerm_storage_account.ml.primary_blob_host
    EMBEDDING_CONTAINER                           = azurerm_storage_container.embedding_results.name
    AZURE_SUBSCRIPTION_ID                         = var.subscription_id
    AZURE_RESOURCE_GROUP                          = azurerm_resource_group.this.name
    AZUREML_WORKSPACE_NAME                        = azapi_resource.ml.name
    AZUREML_COMPUTE_NAME                          = var.species_splitter_compute_name
    AZUREML_IDENTITY_CLIENT_ID                    = azurerm_user_assigned_identity.uai_ml_identity.client_id
    AZUREML_INPUT_DATASTORE                       = azapi_resource.embedding_results_datastore.name
    AZUREML_OUTPUT_DATASTORE                      = azapi_resource.species_results_datastore.name
    AZUREML_ENVIRONMENT                           = "${azapi_resource.ml.id}/environments/${var.embedding_environment_name}/versions/${var.embedding_environment_version}"
    SPECIES_SPLITTER_SHARD_COUNT                  = tostring(var.species_splitter_shard_count)
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

  lifecycle {
    ignore_changes = [app_settings["AzureWebJobsStorage"]]
  }
}

resource "azurerm_role_assignment" "species_splitter_servicebus_receiver" {
  scope                = azurerm_servicebus_namespace.class_filter.id
  role_definition_name = "Azure Service Bus Data Receiver"
  principal_id         = azurerm_function_app_flex_consumption.species_splitter.identity[0].principal_id
}

resource "azurerm_role_assignment" "species_splitter_runtime_blob_owner" {
  scope                = azurerm_storage_account.species_splitter.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_function_app_flex_consumption.species_splitter.identity[0].principal_id
}

resource "azurerm_role_assignment" "species_splitter_runtime_queue_contributor" {
  scope                = azurerm_storage_account.species_splitter.id
  role_definition_name = "Storage Queue Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.species_splitter.identity[0].principal_id
}

resource "azurerm_role_assignment" "species_splitter_runtime_table_contributor" {
  scope                = azurerm_storage_account.species_splitter.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.species_splitter.identity[0].principal_id
}

resource "azurerm_role_assignment" "species_splitter_ml_data_scientist" {
  scope                = azapi_resource.ml.id
  role_definition_name = "AzureML Data Scientist"
  principal_id         = azurerm_function_app_flex_consumption.species_splitter.identity[0].principal_id
}

resource "azurerm_role_assignment" "species_splitter_storage_contributor" {
  scope                = azurerm_storage_account.ml.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_function_app_flex_consumption.species_splitter.identity[0].principal_id
}