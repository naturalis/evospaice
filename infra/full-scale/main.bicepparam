using './main.bicep'

param resourceGroupName = 'rg-evoispace-tree-lp'
param location = 'swedencentral'
param imageTag = 'replace-with-an-immutable-tag'
param runPrefix = 'runs/insecta-20260914-001'
param sourceResourceGroupName = 'rg-ai-seq-h3-hack-e1lkzk'
param sourceStorageAccountName = 'mlstaiseqhacke1lkzk'
param sourceContainerName = 'embedding-results'
param sourcePrefix = 'insecta/0x8df1258ad040f84'
param maxPartitionRecords = 50000
param maxWorkerExecutions = 10
param workloadProfileType = 'E16'
