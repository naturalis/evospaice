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
