targetScope = 'resourceGroup'

param location string = resourceGroup().location
param clusterName string
@description('A distinct, demo-exclusive node RG name. AKS creates and owns this group; do not precreate it.')
param nodeResourceGroupName string
param controlPlaneIdentityName string
param kubeletIdentityName string
param workloadIdentityName string
param operatorObjectId string
@allowed(['User', 'ServicePrincipal', 'Group'])
param operatorPrincipalType string = 'User'
param grantOperatorClusterAdmin bool = true
param clusterAdminAssignmentName string = ''
param kubernetesVersion string = '1.34.10'
@description('Optional single-line ssh-rsa PUBLIC key generated for this demo in a private session. Never supply a private key. Empty omits the Linux profile and leaves key handling to AKS.')
param sshPublicKey string = ''
param linuxAdminUsername string = 'azureuser'
@description('Opt in only after verifying DisableSSHPreview is Registered and the ContainerService provider registration is refreshed. Disables node SSH, not Entra/kubectl administration.')
param disableNodeSsh bool = false
@description('Check regional SKU/zone restrictions AND family/regional vCPU quotas before deploying. Must support >=4 vCPUs and 4 GiB RAM for the system pool.')
param nodeVmSize string = 'Standard_D4s_v6'
@description('Empty means no explicit zone selection; e.g. [\'2\'] only after checking regional SKU availability.')
param availabilityZones array = []
@description('Optional public API server CIDRs, normally the operator egress IPv4 /32. Empty allows public API connectivity; Entra authentication and Azure RBAC remain required.')
param apiServerAuthorizedIPRanges array = []
param serviceCidr string = '10.0.0.0/16'
param dnsServiceIP string = '10.0.0.10'
param podCidr string = '10.244.0.0/16'
param federationName string = 'boring-agent'
@description('Private tag overrides merged over existing RG tags and durable demo labels. The RG itself is not modified.')
param tags object = {}
var resourceTags = union(resourceGroup().tags ?? {}, {
  workload: 'foundry-aks-agent'
  purpose: 'exclusive-demo'
}, tags)

resource controlPlaneIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: controlPlaneIdentityName
}
resource kubeletIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: kubeletIdentityName
}
resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: workloadIdentityName
}

// foundation.bicep must succeed first: MIO on the kubelet UAI and AcrPull are
// prerequisites, not assignments waiting on control-plane creation.
resource cluster 'Microsoft.ContainerService/managedClusters@2025-10-01' = {
  name: clusterName
  location: location
  tags: resourceTags
  sku: {
    name: 'Base'
    tier: 'Free'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${controlPlaneIdentity.id}': {}
    }
  }
  properties: {
    dnsPrefix: clusterName
    kubernetesVersion: kubernetesVersion
    linuxProfile: empty(sshPublicKey) ? null : {
      adminUsername: linuxAdminUsername
      ssh: {
        publicKeys: [
          {
            keyData: sshPublicKey
          }
        ]
      }
    }
    nodeResourceGroup: nodeResourceGroupName
    enableRBAC: true
    disableLocalAccounts: true
    aadProfile: {
      managed: true
      enableAzureRBAC: true
      tenantID: subscription().tenantId
    }
    apiServerAccessProfile: {
      authorizedIPRanges: apiServerAuthorizedIPRanges
      enablePrivateCluster: false
    }
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
    identityProfile: {
      kubeletidentity: {
        resourceId: kubeletIdentity.id
        clientId: kubeletIdentity.properties.clientId
        objectId: kubeletIdentity.properties.principalId
      }
    }
    agentPoolProfiles: [
      {
        name: 'system'
        count: 2
        vmSize: nodeVmSize
        osType: 'Linux'
        osSKU: 'Ubuntu'
        osDiskType: 'Managed'
        osDiskSizeGB: 128
        mode: 'System'
        type: 'VirtualMachineScaleSets'
        availabilityZones: availabilityZones
        maxPods: 110
        enableAutoScaling: false
        securityProfile: disableNodeSsh ? {
          sshAccess: 'Disabled'
        } : null
        upgradeSettings: {
          maxSurge: '1'
        }
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      loadBalancerSku: 'standard'
      outboundType: 'loadBalancer'
      serviceCidr: serviceCidr
      dnsServiceIP: dnsServiceIP
      podCidr: podCidr
    }
    autoUpgradeProfile: {
      upgradeChannel: 'none'
      nodeOSUpgradeChannel: 'NodeImage'
    }
  }
}

resource federation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = {
  parent: workloadIdentity
  name: federationName
  properties: {
    issuer: cluster.properties.oidcIssuerProfile.issuerURL
    subject: 'system:serviceaccount:boring-agent:boring-agent'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

resource clusterAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantOperatorClusterAdmin) {
  name: empty(clusterAdminAssignmentName) ? guid(cluster.id, operatorObjectId, 'Azure Kubernetes Service RBAC Cluster Admin') : clusterAdminAssignmentName
  scope: cluster
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b')
    principalId: operatorObjectId
    principalType: operatorPrincipalType
  }
}

output clusterId string = cluster.id
output oidcIssuer string = cluster.properties.oidcIssuerProfile.issuerURL
output nodeResourceGroup string = cluster.properties.nodeResourceGroup
