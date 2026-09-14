targetScope = 'subscription'

@description('New resource group for the full-scale tree pipeline. The existing embedding resource group is never modified.')
param resourceGroupName string = 'rg-evoispace-tree-lp'

@description('Azure region for all new resources.')
param location string = 'swedencentral'

@description('Immutable container image tag in the new registry.')
param imageTag string

@description('Run-specific prefix in the new work storage account.')
param runPrefix string

@description('Existing resource group containing the immutable embedding export.')
param sourceResourceGroupName string = 'rg-ai-seq-h3-hack-e1lkzk'

@description('Existing storage account containing the immutable embedding export.')
param sourceStorageAccountName string = 'mlstaiseqhacke1lkzk'

@description('Existing container containing the embedding export.')
param sourceContainerName string = 'embedding-results'

@description('Existing blob prefix containing manifest.json, records.parquet, and index.faiss.')
param sourcePrefix string = 'insecta/0x8df1258ad040f84'

@description('Maximum selected BIN records in one worker partition.')
@minValue(2)
param maxPartitionRecords int = 50000

@description('Maximum concurrent subtree job executions.')
@minValue(1)
param maxWorkerExecutions int = 10

@description('Dedicated Container Apps workload profile type available in the selected region.')
param workloadProfileType string = 'E16'

@description('Tags applied to all new resources.')
param tags object = {
  application: 'evospaice'
  workload: 'full-scale-tree-builder'
  environment: 'production'
}

resource pipelineResourceGroup 'Microsoft.Resources/resourceGroups@2024-11-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module pipeline './resources.bicep' = {
  scope: pipelineResourceGroup
  params: {
    location: location
    imageTag: imageTag
    runPrefix: runPrefix
    sourceResourceGroupName: sourceResourceGroupName
    sourceStorageAccountName: sourceStorageAccountName
    sourceContainerName: sourceContainerName
    sourcePrefix: sourcePrefix
    maxPartitionRecords: maxPartitionRecords
    maxWorkerExecutions: maxWorkerExecutions
    workloadProfileType: workloadProfileType
    tags: tags
  }
}

output resourceGroupName string = pipelineResourceGroup.name
output registryLoginServer string = pipeline.outputs.registryLoginServer
output workStorageAccountName string = pipeline.outputs.workStorageAccountName
output workContainerName string = pipeline.outputs.workContainerName
output prepareJobName string = pipeline.outputs.prepareJobName
output workerJobName string = pipeline.outputs.workerJobName
output finalizeJobName string = pipeline.outputs.finalizeJobName
output binMappingObject string = pipeline.outputs.binMappingObject
output trustPolicyObject string = pipeline.outputs.trustPolicyObject
output finalManifestObject string = pipeline.outputs.finalManifestObject
