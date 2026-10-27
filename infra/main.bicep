@description('Existing Log Analytics workspace in this deployment resource group.')
param workspaceName string
@description('Existing private-network Container Apps managed environment resource ID.')
param containerAppsEnvironmentId string
@description('Build and publish this checker image before enabling collection.')
param checkerImage string
@description('Registry server if using ACR; grant AcrPull to the output identity before first successful execution.')
param registryServer string = ''
@minLength(1)
@maxLength(20)
param prefix string = 'env-overview'
param projectConfig object = loadJsonContent('../config/project.example.json')
@description('False permits Workbook/ingestion setup before image publication and private-network setup.')
param deployChecker bool = true
@description('Explicit opt-in to subscription Reader assignments. Otherwise grant discovery access separately.')
param assignDiscoveryRoles bool = false
param checkerSecrets array = []
param secretEnvironment array = []

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-identity'
  location: workspace.location
}

module monitoring './monitoring.bicep' = {
  name: '${prefix}-monitoring'
  params: {
    prefix: prefix
    location: workspace.location
    workspaceName: workspaceName
    principalId: identity.properties.principalId
  }
}

module discoveryRoles './discovery-role.bicep' = [for sub in projectConfig.subscriptions: if (assignDiscoveryRoles) {
  name: '${prefix}-reader-${uniqueString(sub)}'
  scope: subscription(sub)
  params: {
    principalId: identity.properties.principalId
  }
}]

module checker './checker.bicep' = if (deployChecker) {
  name: '${prefix}-job'
  params: {
    prefix: prefix
    location: workspace.location
    identityId: identity.id
    principalId: identity.properties.principalId
    clientId: identity.properties.clientId
    environmentId: containerAppsEnvironmentId
    image: checkerImage
    registryServer: registryServer
    projectConfig: projectConfig
    ingestionEndpoint: monitoring.outputs.endpoint
    ruleId: monitoring.outputs.ruleId
    checkerSecrets: checkerSecrets
    secretEnvironment: secretEnvironment
  }
}

module workbook './workbook.bicep' = {
  name: '${prefix}-workbook'
  params: {
    location: workspace.location
    workbookId: guid(resourceGroup().id, prefix, projectConfig.projectId)
    displayName: '${projectConfig.projectId} environment overview'
    workspaceId: workspace.id
  }
}

output workbookId string = workbook.outputs.id
output collectorPrincipalId string = identity.properties.principalId
output collectorClientId string = identity.properties.clientId
output ingestionEndpoint string = monitoring.outputs.endpoint
output dcrImmutableId string = monitoring.outputs.ruleId
