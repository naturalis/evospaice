subscription_id             = "caeead51-e874-4122-ba0e-c3c601c862ca"
projectdata_subscription_id = "61fc1530-1236-46e1-87d6-698d5edb186a"
environment                 = "hack"

platform_admin_group_object_ids = [
  "7a75a946-a136-47d0-a746-1cdc956bf6b6",
  "25a0e3e7-ab8b-41b3-85a5-e40ec8cf0729",
]

ml_engineer_group_object_ids = [
  "7a75a946-a136-47d0-a746-1cdc956bf6b6",
  "25a0e3e7-ab8b-41b3-85a5-e40ec8cf0729",
]

data_scientist_group_object_ids = [
  "7a75a946-a136-47d0-a746-1cdc956bf6b6",
  "25a0e3e7-ab8b-41b3-85a5-e40ec8cf0729",
]

manage_data_scientist_projectdata_role_assignments = false

aml_compute_clusters = {
  gpu_t4_lowpri = {
    name                     = "gpu-t4-lowpri"
    vm_size                  = "STANDARD_NC4AS_T4_V3"
    vm_priority              = "LowPriority"
    min_instances            = 0
    max_instances            = 4
    scale_down_idle_duration = "PT10M"
  }
  gpu_a100_lowpri = {
    name                     = "gpu-NC24ADS-a100-lowpri"
    vm_size                  = "STANDARD_NC24ADS_A100_V4"
    vm_priority              = "LowPriority"
    min_instances            = 0
    max_instances            = 2
    scale_down_idle_duration = "PT10M"
  }
  gpu_a100_lowpri_secondary = {
    name                     = "gpu-NC24ADS-a100-lowpri-2nd"
    vm_size                  = "STANDARD_NC24ADS_A100_V4"
    vm_priority              = "LowPriority"
    min_instances            = 0
    max_instances            = 2
    scale_down_idle_duration = "PT10M"
  }
}

projectdata_storage_accounts = [
  {
    projectdata_storage_account_name        = "stolargefilesdeva8usci"
    projectdata_storage_resource_group_name = "rg-ai-seq-dev-a8usci"
  },
  {
    projectdata_storage_account_name        = "stoblastresultsdeva8usci"
    projectdata_storage_resource_group_name = "rg-ai-seq-dev-a8usci"
  },
]

datastore_definitions = [
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
  {
    datastore_name  = "blastresults"
    filesystem_name = "results"
    storage_account = "stoblastresultsdeva8usci"
  },
]