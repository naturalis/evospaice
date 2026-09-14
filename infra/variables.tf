variable "subscription_id" {
  description = "Azure subscription ID where resources will be created"
  type        = string
  default     = ""
}

variable "projectdata_subscription_id" {
  description = "Optional Azure subscription ID containing the external project data storage accounts. Defaults to subscription_id."
  type        = string
  default     = null

  validation {
    condition = var.projectdata_subscription_id == null ? true : can(
      regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$", var.projectdata_subscription_id)
    )
    error_message = "projectdata_subscription_id must be a valid Azure subscription ID when provided."
  }
}

variable "environment" {
  description = "Environment name (e.g. dev, tst, acc, prd)"
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9]{2,6}$", var.environment))
    error_message = "environment must be 2-6 lowercase alphanumeric characters."
  }
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "swedencentral"
}

variable "resource_group_name" {
  description = "Optional resource group name. When null, a name is generated from the environment and random suffix."
  type        = string
  default     = null

  validation {
    condition = var.resource_group_name == null ? true : (
      length(trimspace(var.resource_group_name)) >= 1 &&
      length(var.resource_group_name) <= 90 &&
      can(regex("^[A-Za-z0-9._()-]+$", var.resource_group_name)) &&
      !endswith(var.resource_group_name, ".")
    )
    error_message = "resource_group_name must be 1-90 characters, use Azure-supported characters, and not end with a period."
  }
}

variable "ml_container_registry_name" {
  description = "Optional name of the Azure Container Registry attached to the AML workspace. When null, a name is generated from the environment and random suffix."
  type        = string
  default     = null

  validation {
    condition = var.ml_container_registry_name == null ? true : can(
      regex("^[a-z0-9]{5,50}$", var.ml_container_registry_name)
    )
    error_message = "ml_container_registry_name must be 5-50 lowercase alphanumeric characters when provided."
  }
}

variable "key_vault_sku_name" {
  description = "SKU name for Key Vault"
  type        = string
  default     = "standard"
}

variable "key_vault_purge_protection_enabled" {
  description = "Whether purge protection is enabled for Key Vault"
  type        = bool
  default     = true
}

variable "key_vault_soft_delete_retention_days" {
  description = "Soft delete retention period in days for Key Vault"
  type        = number
  default     = 90

  validation {
    condition     = var.key_vault_soft_delete_retention_days >= 7 && var.key_vault_soft_delete_retention_days <= 90
    error_message = "key_vault_soft_delete_retention_days must be between 7 and 90."
  }
}

variable "key_vault_enable_rbac_authorization" {
  description = "Whether Azure RBAC is used for Key Vault data-plane authorization"
  type        = bool
  default     = true
}

variable "public_access_enabled" {
  description = "Whether public access is enabled (set to true only for experimentation environments, not recommended for production)"
  type        = bool
  default     = true
}


variable "log_analytics_workspace_sku" {
  description = "SKU for Log Analytics Workspace"
  type        = string
  default     = "PerGB2018"
}

variable "log_analytics_workspace_retention_in_days" {
  description = "Retention period in days for Log Analytics Workspace"
  type        = number
  default     = 30

  validation {
    condition     = var.log_analytics_workspace_retention_in_days >= 30 && var.log_analytics_workspace_retention_in_days <= 730
    error_message = "log_analytics_workspace_retention_in_days must be between 30 and 730."
  }
}

variable "application_insights_application_type" {
  description = "Application type for Application Insights"
  type        = string
  default     = "web"
}

variable "ml_storage_account_tier" {
  description = "Tier for ML storage account"
  type        = string
  default     = "Standard"
}

variable "ml_storage_account_replication_type" {
  description = "Replication type for ML storage account"
  type        = string
  default     = "LRS"
}

variable "ml_storage_min_tls_version" {
  description = "Minimum TLS version for ML storage account"
  type        = string
  default     = "TLS1_2"
}

variable "ml_workspace_sku_name" {
  description = "SKU for Azure Machine Learning workspace"
  type        = string
  default     = "Basic"
}

variable "embedding_compute_name" {
  description = "Existing Azure ML A100 compute cluster used for Omni-DNA embedding jobs"
  type        = string
  default     = "gpu-NC24ADS-a100-dedicated"
}

variable "embedding_environment_name" {
  description = "Existing Azure ML environment known to support Omni-DNA A100 inference"
  type        = string
  default     = "CliV2AnonymousEnvironment"
}

variable "embedding_environment_version" {
  description = "Version of the existing Azure ML Omni-DNA environment"
  type        = string
  default     = "6fe03960371c7f20a326998f37ea4cf7804e1d0c5c3326e8f5c905c0849c2e79"
}

variable "omni_dna_model_id" {
  description = "Hugging Face model identifier for Omni-DNA embedding inference"
  type        = string
  default     = "zehui127/Omni-DNA-20M"
}

variable "embedding_batch_size" {
  description = "Number of FASTA records embedded per A100 inference batch"
  type        = number
  default     = 256

  validation {
    condition     = var.embedding_batch_size >= 1 && var.embedding_batch_size <= 2048
    error_message = "embedding_batch_size must be between 1 and 2048."
  }
}

variable "embedding_max_length" {
  description = "Maximum tokenizer length used by the proven Omni-DNA encoder"
  type        = number
  default     = 1024

  validation {
    condition     = var.embedding_max_length >= 1 && var.embedding_max_length <= 1024
    error_message = "embedding_max_length must be between 1 and 1024."
  }
}

variable "storage_blob_soft_delete_retention_days" {
  description = "Number of days to retain soft-deleted blobs on storage accounts managed by this stack (1-365)."
  type        = number
  default     = 14
}

variable "storage_container_soft_delete_retention_days" {
  description = "Number of days to retain soft-deleted containers on storage accounts managed by this stack (1-365)."
  type        = number
  default     = 14
}

variable "aml_compute_clusters" {
  description = "Azure ML compute clusters to create, keyed by Terraform identifier"
  type = map(object({
    name                     = string
    vm_size                  = string
    vm_priority              = string
    min_instances            = number
    max_instances            = number
    scale_down_idle_duration = string
  }))

  default = {
    gpu_t4_lowpri = {
      name                     = "gpu-t4-lowpri"
      vm_size                  = "STANDARD_NC4AS_T4_V3"
      vm_priority              = "LowPriority"
      min_instances            = 0
      max_instances            = 8
      scale_down_idle_duration = "PT10M"
    }
    gpu_t4_dedicated = {
      name                     = "gpu-t4-dedicated"
      vm_size                  = "STANDARD_NC4AS_T4_V3"
      vm_priority              = "Dedicated"
      min_instances            = 0
      max_instances            = 8
      scale_down_idle_duration = "PT10M"
    }
  }

  validation {
    condition = alltrue([
      for c in values(var.aml_compute_clusters) :
      contains(["Dedicated", "LowPriority"], c.vm_priority)
    ])
    error_message = "Each aml_compute_clusters vm_priority must be either Dedicated or LowPriority."
  }

  validation {
    condition = alltrue([
      for c in values(var.aml_compute_clusters) :
      c.min_instances >= 0 && c.max_instances >= 1 && c.max_instances <= 16 && c.min_instances <= c.max_instances
    ])
    error_message = "Each aml_compute_clusters entry must satisfy: min_instances >= 0, max_instances between 1 and 16, and min_instances <= max_instances."
  }
}

variable "platform_admin_group_object_ids" {
  description = "Azure Entra ID group object IDs for platform administrators."
  type        = list(string)

  validation {
    condition     = length(var.platform_admin_group_object_ids) > 0
    error_message = "platform_admin_group_object_ids must contain at least one Entra group object ID."
  }

  validation {
    condition = alltrue([
      for id in var.platform_admin_group_object_ids :
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$", trimspace(id)))
    ])
    error_message = "Each platform_admin_group_object_ids value must be a valid Entra object ID (UUID)."
  }
}

variable "ml_engineer_group_object_ids" {
  description = "Azure Entra ID group object IDs for ML engineering responsibilities."
  type        = list(string)

  validation {
    condition     = length(var.ml_engineer_group_object_ids) > 0
    error_message = "ml_engineer_group_object_ids must contain at least one Entra group object ID."
  }

  validation {
    condition = alltrue([
      for id in var.ml_engineer_group_object_ids :
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$", trimspace(id)))
    ])
    error_message = "Each ml_engineer_group_object_ids value must be a valid Entra object ID (UUID)."
  }
}

variable "data_scientist_group_object_ids" {
  description = "Azure Entra ID group object IDs for data science responsibilities."
  type        = list(string)

  validation {
    condition     = length(var.data_scientist_group_object_ids) > 0
    error_message = "data_scientist_group_object_ids must contain at least one Entra group object ID."
  }

  validation {
    condition = alltrue([
      for id in var.data_scientist_group_object_ids :
      can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$", trimspace(id)))
    ])
    error_message = "Each data_scientist_group_object_ids value must be a valid Entra object ID (UUID)."
  }
}

variable "manage_data_scientist_projectdata_role_assignments" {
  description = "Whether this stack manages data-scientist reader roles on external project data storage accounts."
  type        = bool
  default     = true
}


variable "tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
  default     = ""
}

variable "projectdata_storage_accounts" {
  description = "Projectdata storage account inputs. Each object includes projectdata_storage_account_name and projectdata_storage_resource_group_name."
  type = list(object({
    projectdata_storage_account_name        = string
    projectdata_storage_resource_group_name = string
  }))

  default = [
    {
      projectdata_storage_account_name        = "stolargefilesdeva8usci"
      projectdata_storage_resource_group_name = "rg-ai-seq-dev-a8usci"
    }
  ]

  validation {
    condition     = length(var.projectdata_storage_accounts) > 0
    error_message = "projectdata_storage_accounts must contain at least one object."
  }

  validation {
    condition = alltrue([
      for account in var.projectdata_storage_accounts :
      can(regex("^[a-z0-9]{3,24}$", trimspace(account.projectdata_storage_account_name)))
    ])
    error_message = "Each projectdata_storage_account_name must be 3-24 lowercase alphanumeric characters."
  }

  validation {
    condition = alltrue([
      for account in var.projectdata_storage_accounts :
      trimspace(account.projectdata_storage_resource_group_name) != ""
    ])
    error_message = "Each projectdata_storage_resource_group_name must be a non-empty resource group name."
  }

  validation {
    condition = length(distinct([
      for account in var.projectdata_storage_accounts :
      lower(trimspace(account.projectdata_storage_account_name))
    ])) == length(var.projectdata_storage_accounts)
    error_message = "projectdata_storage_account_name values in projectdata_storage_accounts must be unique (case-insensitive)."
  }
}

variable "datastore_definitions" {
  description = "AML datastore definitions and target storage account from projectdata_storage_accounts"
  type = list(object({
    datastore_name  = string
    filesystem_name = string
    storage_account = string
  }))

  default = [
    {
      datastore_name  = "projectdata"
      filesystem_name = "referencedata"
      storage_account = "stolargefilesdeva8usci"
    },
    {
      datastore_name  = "sequences"
      filesystem_name = "sequences"
      storage_account = "stolargefilesdeva8usci"
    },
  ]

  validation {
    condition = alltrue([
      for ds in var.datastore_definitions :
      trimspace(ds.datastore_name) != "" && trimspace(ds.filesystem_name) != "" && trimspace(ds.storage_account) != ""
    ])
    error_message = "Each datastore definition must include non-empty datastore_name, filesystem_name, and storage_account values."
  }

  validation {
    condition = length(distinct([
      for ds in var.datastore_definitions : lower(trimspace(ds.datastore_name))
    ])) == length(var.datastore_definitions)
    error_message = "datastore_definitions datastore_name values must be unique (case-insensitive)."
  }

  validation {
    condition = alltrue([
      for ds in var.datastore_definitions :
      can(regex("^[a-zA-Z0-9_-]{1,255}$", trimspace(ds.datastore_name))) &&
      can(regex("^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$", trimspace(ds.filesystem_name)))
    ])
    error_message = "datastore_name must be 1-255 chars using letters, numbers, underscore, or hyphen; filesystem_name must be a valid ADLS container name."
  }

  validation {
    condition = alltrue([
      for ds in var.datastore_definitions :
      contains(
        toset([
          for account in var.projectdata_storage_accounts :
          lower(trimspace(account.projectdata_storage_account_name))
        ]),
        lower(trimspace(ds.storage_account))
      )
    ])
    error_message = "storage_account must be one of the projectdata_storage_account_name values from projectdata_storage_accounts."
  }

}
