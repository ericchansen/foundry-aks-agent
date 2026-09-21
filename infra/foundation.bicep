targetScope = 'resourceGroup'

@description('All names must identify resources dedicated exclusively to this demo in the deployment resource group. Existing resources with these names are reconciled, not discovered.')
param location string = resourceGroup().location
param accountName string
param projectName string
param registryName string
param workspaceName string
param applicationInsightsName string
param workloadIdentityName string
param controlPlaneIdentityName string
param kubeletIdentityName string
param appInsightsConnectionName string = 'appinsights'
param modelDeploymentName string = 'gpt-4.1-mini'
param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'
param modelSku string = 'GlobalStandard'
@minValue(1)
param modelCapacity int = 1
param evaluationModelDeploymentName string = 'gpt-5-mini'
param evaluationModelName string = 'gpt-5-mini'
param evaluationModelVersion string = '2025-08-07'
param evaluationModelSku string = 'GlobalStandard'
@minValue(1)
param evaluationModelCapacity int = 10
@description('Entra object ID, not an application/client ID. No Microsoft Graph lookup is performed.')
param operatorObjectId string
@allowed(['User', 'ServicePrincipal', 'Group'])
param operatorPrincipalType string = 'User'
@description('Disable on subsequent deployments after explicitly removing the bootstrap role assignment. Incremental deployment does not revoke roles.')
param grantOperatorFoundryUser bool = true
@description('Private tag overrides merged over existing RG tags and durable demo labels. The RG itself is not modified.')
param tags object = {}
var resourceTags = union(resourceGroup().tags ?? {}, {
  workload: 'foundry-aks-agent'
  purpose: 'exclusive-demo'
}, tags)

// Supply existing assignment GUIDs when adopting assignments created outside Bicep.
// Azure rejects a duplicate (principal, role, scope) under a different GUID.
param modelUserAssignmentName string = ''
param acrPullAssignmentName string = ''
param identityOperatorAssignmentName string = ''
param foundryUserAssignmentName string = ''
param operatorMonitoringReaderAssignmentName string = ''
param operatorPrivilegedMonitoringDataReaderAssignmentName string = ''
param projectFoundryUserAssignmentName string = ''
param projectInsightsReaderAssignmentName string = ''
param projectMonitoringReaderAssignmentName string = ''
param projectLogAnalyticsReaderAssignmentName string = ''
param projectPrivilegedMonitoringDataReaderAssignmentName string = ''

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: workloadIdentityName
  location: location
  tags: resourceTags
}

resource controlPlaneIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: controlPlaneIdentityName
  location: location
  tags: resourceTags
}

resource kubeletIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: kubeletIdentityName
  location: location
  tags: resourceTags
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  tags: resourceTags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: resourceTags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  tags: resourceTags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
  }
}

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' = {
  name: accountName
  location: location
  tags: resourceTags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  parent: account
  name: projectName
  location: location
  tags: resourceTags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectName
    description: 'Dedicated AKS external-agent demo'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = {
  parent: account
  name: modelDeploymentName
  sku: {
    name: modelSku
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource evaluationModel 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = {
  parent: account
  name: evaluationModelDeploymentName
  dependsOn: [
    model
  ]
  sku: {
    name: evaluationModelSku
    capacity: evaluationModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: evaluationModelName
      version: evaluationModelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// Intentionally not output: the runtime obtains this value in memory.
resource connection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: appInsightsConnectionName
  properties: {
    authType: 'ApiKey'
    category: 'AppInsights'
    target: insights.properties.ConnectionString
    credentials: {
      key: insights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: insights.id
    }
  }
}

resource modelUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(modelUserAssignmentName) ? guid(account.id, workloadIdentity.id, 'Cognitive Services OpenAI User') : modelUserAssignmentName
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(acrPullAssignmentName) ? guid(registry.id, kubeletIdentity.id, 'AcrPull') : acrPullAssignmentName
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
    principalId: kubeletIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource identityOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(identityOperatorAssignmentName) ? guid(kubeletIdentity.id, controlPlaneIdentity.id, 'Managed Identity Operator') : identityOperatorAssignmentName
  scope: kubeletIdentity
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'f1a07417-d97a-45cb-824c-7a7467783830')
    principalId: controlPlaneIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource foundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantOperatorFoundryUser) {
  name: empty(foundryUserAssignmentName) ? guid(project.id, operatorObjectId, 'Azure AI User') : foundryUserAssignmentName
  scope: project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
    principalId: operatorObjectId
    principalType: operatorPrincipalType
  }
}

resource operatorMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(operatorMonitoringReaderAssignmentName) ? guid(insights.id, operatorObjectId, 'Monitoring Reader') : operatorMonitoringReaderAssignmentName
  scope: insights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '43d0d8ad-25c7-4714-9337-8ba259a9fe05')
    principalId: operatorObjectId
    principalType: operatorPrincipalType
  }
}

resource operatorPrivilegedMonitoringDataReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(operatorPrivilegedMonitoringDataReaderAssignmentName) ? guid(insights.id, operatorObjectId, 'Privileged Monitoring Data Reader') : operatorPrivilegedMonitoringDataReaderAssignmentName
  scope: insights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'dbc9c667-e97f-4491-aee6-90b9cf960190')
    principalId: operatorObjectId
    principalType: operatorPrincipalType
  }
}

resource projectFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(projectFoundryUserAssignmentName) ? guid(account.id, project.id, 'Foundry User') : projectFoundryUserAssignmentName
  scope: account
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectInsightsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(projectInsightsReaderAssignmentName) ? guid(insights.id, project.id, 'Reader') : projectInsightsReaderAssignmentName
  scope: insights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(projectMonitoringReaderAssignmentName) ? guid(insights.id, project.id, 'Monitoring Reader') : projectMonitoringReaderAssignmentName
  scope: insights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '43d0d8ad-25c7-4714-9337-8ba259a9fe05')
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectLogAnalyticsReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(projectLogAnalyticsReaderAssignmentName) ? guid(insights.id, project.id, 'Log Analytics Reader') : projectLogAnalyticsReaderAssignmentName
  scope: insights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource projectPrivilegedMonitoringDataReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: empty(projectPrivilegedMonitoringDataReaderAssignmentName) ? guid(insights.id, project.id, 'Privileged Monitoring Data Reader') : projectPrivilegedMonitoringDataReaderAssignmentName
  scope: insights
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'dbc9c667-e97f-4491-aee6-90b9cf960190')
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output registryLoginServer string = registry.properties.loginServer
output workloadClientId string = workloadIdentity.properties.clientId
output openAIEndpoint string = 'https://${accountName}.openai.azure.com/'
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
