param location string
param prefix string
param identityId string
param principalId string
param clientId string
param environmentId string
param image string
param registryServer string = ''
param projectConfig object
param ingestionEndpoint string
param ruleId string
@description('Key Vault secret references only. Grant the identity access to these secrets separately.')
param checkerSecrets array = []
@description('Container env entries with name and secretRef, matching checkerSecrets and endpoint headerEnv names.')
param secretEnvironment array = []

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'ov${uniqueString(resourceGroup().id, prefix)}'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'collector-locks'
  properties: {
    publicAccess: 'None'
  }
}

resource leaseRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(container.id, principalId, 'lease')
  scope: container
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: '${prefix}-checker'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 55
      replicaRetryLimit: 0
      scheduleTriggerConfig: {
        cronExpression: '* * * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: empty(registryServer) ? [] : [
        {
          server: registryServer
          identity: identityId
        }
      ]
      secrets: [for secret in checkerSecrets: {
        name: secret.name
        keyVaultUrl: secret.keyVaultUrl
        identity: identityId
      }]
    }
    template: {
      containers: [
        {
          name: 'collector'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat([
            { name: 'PROJECT_CONFIG_JSON', value: string(projectConfig) }
            { name: 'AZURE_CLIENT_ID', value: clientId }
            { name: 'AZURE_TENANT_ID', value: projectConfig.tenantId }
            { name: 'INGESTION_ENDPOINT', value: ingestionEndpoint }
            { name: 'DCR_IMMUTABLE_ID', value: ruleId }
            { name: 'LEASE_BLOB_URL', value: '${storage.properties.primaryEndpoints.blob}collector-locks/${projectConfig.projectId}.lock' }
          ], secretEnvironment)
        }
      ]
    }
  }
  dependsOn: [leaseRole]
}

output jobId string = job.id
output leaseStorageAccount string = storage.name
