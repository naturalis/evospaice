terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }

  }

  backend "azurerm" {}


}

provider "azurerm" {
  features {}
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}

provider "azurerm" {
  alias = "projectdata"
  features {}
  subscription_id     = coalesce(var.projectdata_subscription_id, var.subscription_id)
  storage_use_azuread = true
}
