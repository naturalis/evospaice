targetScope = 'resourceGroup'

@description('Azure region for all new resources.')
param location string

@description('Immutable container image tag in the new registry.')
param imageTag string

@description('Run-specific prefix in the work storage account.')
param runPrefix string

@description('Existing source resource group, recorded for provenance only.')
param sourceResourceGroupName string

@description('Existing source storage account, recorded for provenance only.')
param sourceStorageAccountName string

@description('Existing source container, recorded for provenance only.')
param sourceContainerName string

@description('Existing source prefix copied into the new work account before execution.')
param sourcePrefix string

@description('Maximum selected BIN records in one worker partition.')
param maxPartitionRecords int

@description('Maximum concurrent subtree job executions.')
param maxWorkerExecutions int

@description('Dedicated Container Apps workload profile type.')
param workloadProfileType string

@description('Resource tags.')
param tags object

var serviceName = 'evospaice'
var suffix = uniqueString(subscription().subscriptionId, resourceGroup().id)
var registryName = take('${serviceName}${suffix}', 50)
var storageName = take('${serviceName}${suffix}', 24)
var workContainerName = 'tree-runs'
var workQueueName = 'tree-subtrees'
var poisonQueueName = 'tree-subtrees-poison'
var workloadProfileName = 'tree-memory'
var imageRepository = 'evospaice/tree-builder'
var prepareIdentityName = '${serviceName}-prepare-finalize'
var workerIdentityName = '${serviceName}-subtree-worker'
var stagedSourcePrefix = 'reference/embedding-exports/${sourcePrefix}'
var binMappingObject = '${runPrefix}/input/record-bin-map.parquet'
var trustPolicyObject = '${runPrefix}/input/trust-policy.json'
var outputPrefix = '${runPrefix}/output'
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)
var blobContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)
var queueSenderRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'
)
var queueProcessorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '8a0f0c08-91a1-4084-bc3d-661d67233fed'
)
var queueReaderRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '19e7f393-937e-4f77-808e-94535e297925'
)
var sourceProvenanceTags = union(tags, {
  sourceResourceGroup: sourceResourceGroupName
  sourceStorageAccount: sourceStorageAccountName
  sourceContainer: sourceContainerName
})

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${serviceName}-full-scale-logs'
  location: location
  tags: sourceProvenanceTags
  properties: {
    retentionInDays: 30
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: '${serviceName}-full-scale-environment'
  location: location
  tags: sourceProvenanceTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: workloadProfileName
        workloadProfileType: workloadProfileType
        minimumCount: 0
        maximumCount: maxWorkerExecutions + 2
      }
    ]
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: registryName
  location: location
  tags: sourceProvenanceTags
  sku: {
    name: 'Standard'
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
  tags: sourceProvenanceTags
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

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource workContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: workContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2024-01-01' = {
  parent: storage
  name: 'default'
}

resource workQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2024-01-01' = {
  parent: queueService
  name: workQueueName
}

resource poisonQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2024-01-01' = {
  parent: queueService
  name: poisonQueueName
}

resource prepareIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: prepareIdentityName
  location: location
  tags: sourceProvenanceTags
}

resource workerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: workerIdentityName
  location: location
  tags: sourceProvenanceTags
}

resource prepareAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, prepareIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: prepareIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource workerAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, workerIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource prepareBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workContainer.id, prepareIdentity.id, blobContributorRoleId)
  scope: workContainer
  properties: {
    principalId: prepareIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributorRoleId
  }
}

resource workerBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workContainer.id, workerIdentity.id, blobContributorRoleId)
  scope: workContainer
  properties: {
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobContributorRoleId
  }
}

resource prepareQueueSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workQueue.id, prepareIdentity.id, queueSenderRoleId)
  scope: workQueue
  properties: {
    principalId: prepareIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: queueSenderRoleId
  }
}

resource workerQueueProcessor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workQueue.id, workerIdentity.id, queueProcessorRoleId)
  scope: workQueue
  properties: {
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: queueProcessorRoleId
  }
}

resource workerQueueReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workQueue.id, workerIdentity.id, queueReaderRoleId)
  scope: workQueue
  properties: {
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: queueReaderRoleId
  }
}

resource workerPoisonSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(poisonQueue.id, workerIdentity.id, queueSenderRoleId)
  scope: poisonQueue
  properties: {
    principalId: workerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: queueSenderRoleId
  }
}

resource prepareJob 'Microsoft.App/jobs@2025-01-01' = {
  name: '${serviceName}-prepare-tree'
  location: location
  tags: sourceProvenanceTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${prepareIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: workloadProfileName
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 86400
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: prepareIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'prepare-tree'
          image: '${registry.properties.loginServer}/${imageRepository}:${imageTag}'
          args: [
            'tree-prepare'
            '--source-storage-account-url'
            storage.properties.primaryEndpoints.blob
            '--source-container'
            workContainer.name
            '--source-prefix'
            stagedSourcePrefix
            '--work-storage-account-url'
            storage.properties.primaryEndpoints.blob
            '--work-queue-account-url'
            storage.properties.primaryEndpoints.queue
            '--work-container'
            workContainer.name
            '--work-queue'
            workQueue.name
            '--poison-queue'
            poisonQueue.name
            '--run-prefix'
            runPrefix
            '--bin-mapping-object'
            binMappingObject
            '--trust-policy-object'
            trustPolicyObject
            '--partition-rank'
            'family'
            '--max-partition-records'
            string(maxPartitionRecords)
          ]
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: prepareIdentity.properties.clientId
            }
            {
              name: 'TMPDIR'
              value: '/scratch'
            }
          ]
          resources: {
            cpu: 8
            memory: '64Gi'
          }
          volumeMounts: [
            {
              volumeName: 'scratch'
              mountPath: '/scratch'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'scratch'
          storageType: 'EmptyDir'
        }
      ]
    }
  }
  dependsOn: [
    prepareAcrPull
    prepareBlobContributor
    prepareQueueSender
  ]
}

resource workerJob 'Microsoft.App/jobs@2025-01-01' = {
  name: '${serviceName}-subtree-worker'
  location: location
  tags: sourceProvenanceTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workerIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: workloadProfileName
    configuration: {
      triggerType: 'Event'
      replicaTimeout: 21600
      replicaRetryLimit: 0
      eventTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
        scale: {
          minExecutions: 0
          maxExecutions: maxWorkerExecutions
          pollingInterval: 30
          rules: [
            {
              name: 'partition-queue'
              type: 'azure-queue'
              identity: workerIdentity.id
              metadata: {
                accountName: storage.name
                queueName: workQueue.name
                queueLength: '1'
              }
            }
          ]
        }
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: workerIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'subtree-worker'
          image: '${registry.properties.loginServer}/${imageRepository}:${imageTag}'
          args: [
            'tree-worker'
            '--work-storage-account-url'
            storage.properties.primaryEndpoints.blob
            '--work-queue-account-url'
            storage.properties.primaryEndpoints.queue
            '--work-container'
            workContainer.name
            '--work-queue'
            workQueue.name
            '--poison-queue'
            poisonQueue.name
            '--visibility-timeout'
            '21600'
            '--max-dequeue-count'
            '3'
          ]
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: workerIdentity.properties.clientId
            }
            {
              name: 'TMPDIR'
              value: '/scratch'
            }
          ]
          resources: {
            cpu: 4
            memory: '32Gi'
          }
          volumeMounts: [
            {
              volumeName: 'scratch'
              mountPath: '/scratch'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'scratch'
          storageType: 'EmptyDir'
        }
      ]
    }
  }
  dependsOn: [
    workerAcrPull
    workerBlobContributor
    workerQueueProcessor
    workerQueueReader
    workerPoisonSender
  ]
}

resource finalizeJob 'Microsoft.App/jobs@2025-01-01' = {
  name: '${serviceName}-finalize-tree'
  location: location
  tags: sourceProvenanceTags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${prepareIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: workloadProfileName
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 86400
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: prepareIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'finalize-tree'
          image: '${registry.properties.loginServer}/${imageRepository}:${imageTag}'
          args: [
            'tree-finalize'
            '--work-storage-account-url'
            storage.properties.primaryEndpoints.blob
            '--work-container'
            workContainer.name
            '--run-prefix'
            runPrefix
            '--output-prefix'
            outputPrefix
          ]
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: prepareIdentity.properties.clientId
            }
            {
              name: 'TMPDIR'
              value: '/scratch'
            }
          ]
          resources: {
            cpu: 8
            memory: '64Gi'
          }
          volumeMounts: [
            {
              volumeName: 'scratch'
              mountPath: '/scratch'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'scratch'
          storageType: 'EmptyDir'
        }
      ]
    }
  }
  dependsOn: [
    prepareAcrPull
    prepareBlobContributor
  ]
}

output registryLoginServer string = registry.properties.loginServer
output workStorageAccountName string = storage.name
output workContainerName string = workContainer.name
output prepareJobName string = prepareJob.name
output workerJobName string = workerJob.name
output finalizeJobName string = finalizeJob.name
output stagedSourcePrefix string = stagedSourcePrefix
output binMappingObject string = binMappingObject
output trustPolicyObject string = trustPolicyObject
output finalManifestObject string = '${outputPrefix}/tree-manifest.json'
