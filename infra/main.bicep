targetScope = 'resourceGroup'

@description('Short lowercase service name used to generate globally unique resource names.')
@minLength(3)
@maxLength(20)
param serviceName string = 'evospaice'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Container image repository in the new registry.')
param imageRepository string = 'evospaice/tree-builder'

@description('Immutable container image tag to run.')
param imageTag string

@description('Blob container that holds inputs and outputs.')
param dataContainerName string = 'tree-runs'

@description('Blob prefix containing records.tsv, embeddings.npy, embedding-index.tsv, and trust-policy.json.')
param inputPrefix string

@description('Run-specific Blob prefix for immutable outputs.')
param outputPrefix string

@description('Maximum execution duration for one job replica, in seconds.')
@minValue(60)
param replicaTimeout int = 7200

@description('Container CPU cores. Consumption supports up to 4 cores per replica.')
param containerCpu string = '2.0'

@description('Container memory. Consumption supports up to 8 GiB per replica.')
param containerMemory string = '4Gi'

@description('Resource tags applied to the deployment.')
param tags object = {
  application: 'evospaice'
  workload: 'tree-builder'
}

var normalizedName = replace(toLower(serviceName), '-', '')
var suffix = uniqueString(subscription().subscriptionId, resourceGroup().id)
var registryName = take('${normalizedName}${suffix}', 50)
var storageName = take('${normalizedName}${suffix}', 24)
var jobIdentityName = '${serviceName}-tree-job'
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)
var blobContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${serviceName}-logs'
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${serviceName}-environment'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: dataContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource jobIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: jobIdentityName
  location: location
  tags: tags
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, jobIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: jobIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource blobContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dataContainer.id, jobIdentity.id, blobContributorRoleId)
  scope: dataContainer
  properties: {
    principalId: jobIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributorRoleId
  }
}

resource treeBuildJob 'Microsoft.App/jobs@2025-01-01' = {
  name: '${serviceName}-tree-build'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${jobIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: replicaTimeout
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: jobIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'tree-builder'
          image: '${registry.properties.loginServer}/${imageRepository}:${imageTag}'
          args: [
            'tree'
            '--storage-account-url'
            storage.properties.primaryEndpoints.blob
            '--container'
            dataContainer.name
            '--input-prefix'
            inputPrefix
            '--output-prefix'
            outputPrefix
          ]
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: jobIdentity.properties.clientId
            }
          ]
          resources: {
            cpu: json(containerCpu)
            memory: containerMemory
          }
        }
      ]
    }
  }
  dependsOn: [
    acrPullAssignment
    blobContributorAssignment
  ]
}

output registryLoginServer string = registry.properties.loginServer
output storageAccountName string = storage.name
output storageContainerName string = dataContainer.name
output jobName string = treeBuildJob.name
output jobIdentityClientId string = jobIdentity.properties.clientId
