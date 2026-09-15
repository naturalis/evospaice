output "resource_group_name" {
  description = "H1H3 resource group name"
  value       = azurerm_resource_group.this.name
}

output "key_vault_name" {
  description = "Machine Learning Workspace - Key Vault name"
  value       = azurerm_key_vault.ml.name
}

output "log_analytics_workspace_name" {
  description = "Machine Learning Workspace - Log Analytics Workspace name"
  value       = azurerm_log_analytics_workspace.ml.name
}

output "application_insights_name" {
  description = "Machine Learning Workspace - Application Insights name"
  value       = azurerm_application_insights.ml.name
}

output "ml_storage_account_name" {
  description = "Storage account name for Machine Learning Workspace"
  value       = azurerm_storage_account.ml.name
}

output "ml_container_registry_name" {
  description = "Azure Container Registry attached to the Machine Learning workspace"
  value       = azurerm_container_registry.ml.name
}

output "ml_workspace_name" {
  description = "Machine Learning Workspace name"
  value       = azapi_resource.ml.name
}


output "aml_compute_clusters" {
  description = "All Azure ML compute clusters (keyed by cluster identifier)"
  value = {
    for key, cluster in azurerm_machine_learning_compute_cluster.ml :
    key => {
      name = cluster.name
      id   = cluster.id
    }
  }
}

output "projectdata_datastore_name" {
  description = "Machine Learning Workspace projectdata datastore name"
  value       = try(azapi_resource.datastores["projectdata"].name, null)
}

output "sequences_datastore_name" {
  description = "Machine Learning Workspace sequences datastore name"
  value       = try(azapi_resource.datastores["sequences"].name, null)
}

output "datastore_names" {
  description = "All AML datastore names created in this workspace"
  value       = keys(azapi_resource.datastores)
}

output "class_filter_function_app_name" {
  description = "Function App that filters FASTA records by taxonomic class"
  value       = azurerm_function_app_flex_consumption.class_filter.name
}

output "class_filter_trigger_container_name" {
  description = "Blob container monitored for class-filter trigger files"
  value       = azurerm_storage_container.class_filter_triggers.name
}

output "class_filter_output_container_name" {
  description = "Blob container containing class-filtered FASTA files"
  value       = azurerm_storage_container.class_filter_output.name
}

output "class_filter_servicebus_queue_name" {
  description = "Service Bus queue receiving class-filter trigger events"
  value       = azurerm_servicebus_queue.class_filter.name
}

output "embedding_submitter_function_app_name" {
  description = "Function App that submits Omni-DNA jobs to Azure Machine Learning"
  value       = azurerm_function_app_flex_consumption.embedding_submitter.name
}

output "embedding_results_container_name" {
  description = "Blob container containing versioned FAISS embedding bundles"
  value       = azurerm_storage_container.embedding_results.name
}

output "embedding_results_datastore_name" {
  description = "Azure ML datastore containing versioned FAISS embedding bundles"
  value       = azapi_resource.embedding_results_datastore.name
}

output "filtered_sequences_datastore_name" {
  description = "Azure ML datastore containing class-filtered FASTA inputs"
  value       = azapi_resource.filtered_sequences_datastore.name
}

output "embedding_servicebus_queue_name" {
  description = "Service Bus queue receiving filtered FASTA creation events"
  value       = azurerm_servicebus_queue.embedding.name
}

output "species_splitter_function_app_name" {
  description = "Function App that submits per-species FAISS splitting jobs"
  value       = azurerm_function_app_flex_consumption.species_splitter.name
}

output "species_results_container_name" {
  description = "Blob container containing per-species FAISS bundles"
  value       = azurerm_storage_container.species_results.name
}

output "species_results_datastore_name" {
  description = "Azure ML datastore containing per-species FAISS bundles"
  value       = azapi_resource.species_results_datastore.name
}

output "species_splitter_servicebus_queue_name" {
  description = "Service Bus queue receiving completed embedding bundle events"
  value       = azurerm_servicebus_queue.species_splitter.name
}
