param location string
param workbookId string
param displayName string
param workspaceId string

resource workbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: workbookId
  location: location
  kind: 'shared'
  properties: {
    displayName: displayName
    serializedData: loadTextContent('../dist/workbook.json')
    version: '1.0'
    sourceId: workspaceId
    category: 'workbook'
  }
}

output id string = workbook.id
