param workspaceName string
param location string
param prefix string
param principalId string

var columns = loadJsonContent('columns.json')

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: workspaceName
}

resource table 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: workspace
  name: 'EnvironmentOverview_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    schema: {
      name: 'EnvironmentOverview_CL'
      columns: columns
    }
  }
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name: '${prefix}-ingest'
  location: location
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: '${prefix}-collection'
  location: location
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      'Custom-EnvironmentOverview': {
        columns: columns
      }
    }
    destinations: {
      logAnalytics: [
        {
          workspaceResourceId: workspace.id
          name: 'workspace'
        }
      ]
    }
    dataFlows: [
      {
        streams: ['Custom-EnvironmentOverview']
        destinations: ['workspace']
        transformKql: 'source'
        outputStream: 'Custom-EnvironmentOverview_CL'
      }
    ]
  }
  dependsOn: [table]
}

resource ingestionRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(dcr.id, principalId, 'ingestion')
  scope: dcr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = dce.properties.logsIngestion.endpoint
output ruleId string = dcr.properties.immutableId
