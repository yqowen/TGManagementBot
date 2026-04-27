// Azure Container Apps deployment for TGManagementBot.
//
// Provisions:
//   * Log Analytics workspace
//   * Container Apps Environment
//   * Azure Cache for Redis (Basic C0) — managed Redis for state
//   * Container App running the bot image, with secrets wired from Key Vault-like secret refs
//   * User-assigned managed identity for ACR pull (optional)
//
// Polling bots cannot scale to zero (they hold a long-poll loop).
// We pin minReplicas = 1 and disable HTTP ingress.

@description('Resource name prefix; lowercase letters/numbers only.')
@minLength(3)
@maxLength(18)
param namePrefix string = 'tgmgmt'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Container image, e.g. myacr.azurecr.io/tgmgmt:latest')
param image string

@secure()
@description('Telegram bot token from BotFather.')
param botToken string

@description('Trusted bot user ids, comma-separated (may be empty).')
param trustedBotIds string = ''

@description('Allowed chat ids, comma-separated (may be empty = all).')
param allowedChatIds string = ''

@description('Container registry server (leave empty if image is public).')
param registryServer string = ''

@description('Registry username (leave empty for public/anonymous).')
param registryUsername string = ''

@secure()
@description('Registry password (leave empty for public/anonymous).')
param registryPassword string = ''

var logName = '${namePrefix}-logs'
var envName = '${namePrefix}-env'
var redisName = '${namePrefix}-redis-${uniqueString(resourceGroup().id)}'
var appName = '${namePrefix}-bot'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: redisName
  location: location
  properties: {
    sku: {
      name: 'Basic'
      family: 'C'
      capacity: 0
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
    }
  }
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var redisHost = '${redis.name}.redis.cache.windows.net'
var redisKey = redis.listKeys().primaryKey
// rediss:// for TLS (port 6380); urlencode the password defensively.
var redisUrl = 'rediss://:${uriComponent(redisKey)}@${redisHost}:6380/0'

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      // No HTTP ingress: polling only.
      ingress: null
      secrets: concat(
        [
          { name: 'bot-token', value: botToken }
          { name: 'redis-url', value: redisUrl }
        ],
        empty(registryPassword)
          ? []
          : [ { name: 'registry-password', value: registryPassword } ]
      )
      registries: empty(registryServer) ? [] : [
        {
          server: registryServer
          username: registryUsername
          passwordSecretRef: 'registry-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'bot'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'TGMGMT_BOT_TOKEN', secretRef: 'bot-token' }
            { name: 'TGMGMT_REDIS_URL', secretRef: 'redis-url' }
            { name: 'TGMGMT_TRUSTED_BOT_IDS', value: trustedBotIds }
            { name: 'TGMGMT_ALLOWED_CHAT_IDS', value: allowedChatIds }
            { name: 'TGMGMT_LOG_LEVEL', value: 'INFO' }
          ]
        }
      ]
      scale: {
        // Polling bots must keep exactly one replica running.
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output containerAppName string = app.name
output redisHost string = redisHost
output logAnalyticsWorkspace string = logs.name
