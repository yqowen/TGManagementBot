#!/usr/bin/env bash
# Quick deploy to Azure Container Instances (single container, simplest).
#
# Note: ACI does not give you a managed Redis; we run a sidecar Redis
# container in the same group. State lives in the container's writable
# layer — sufficient for evaluation, NOT recommended for production.
#
# Usage:
#   export AZ_RG=tgmgmt-rg
#   export AZ_LOCATION=southeastasia
#   export AZ_IMAGE=ghcr.io/youruser/tgmgmt:latest
#   export TGMGMT_BOT_TOKEN=123:abc
#   ./deploy.sh
set -euo pipefail

: "${AZ_RG:?AZ_RG required}"
: "${AZ_LOCATION:?AZ_LOCATION required}"
: "${AZ_IMAGE:?AZ_IMAGE required}"
: "${TGMGMT_BOT_TOKEN:?TGMGMT_BOT_TOKEN required}"

GROUP_NAME="tgmgmt-aci"

az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none

cat >/tmp/tgmgmt-aci.yaml <<YAML
apiVersion: '2023-05-01'
location: ${AZ_LOCATION}
name: ${GROUP_NAME}
properties:
  osType: Linux
  restartPolicy: Always
  containers:
    - name: redis
      properties:
        image: redis:7-alpine
        command: ["redis-server", "--appendonly", "yes"]
        resources:
          requests:
            cpu: 0.5
            memoryInGB: 0.5
        ports:
          - port: 6379
    - name: bot
      properties:
        image: ${AZ_IMAGE}
        resources:
          requests:
            cpu: 0.5
            memoryInGB: 1.0
        environmentVariables:
          - name: TGMGMT_BOT_TOKEN
            secureValue: ${TGMGMT_BOT_TOKEN}
          - name: TGMGMT_REDIS_URL
            value: redis://localhost:6379/0
          - name: TGMGMT_TRUSTED_BOT_IDS
            value: "${TGMGMT_TRUSTED_BOT_IDS:-}"
          - name: TGMGMT_ALLOWED_CHAT_IDS
            value: "${TGMGMT_ALLOWED_CHAT_IDS:-}"
          - name: TGMGMT_LOG_LEVEL
            value: INFO
type: Microsoft.ContainerInstance/containerGroups
YAML

echo ">> Creating ACI container group ${GROUP_NAME}"
az container create --resource-group "$AZ_RG" --file /tmp/tgmgmt-aci.yaml --output table

echo ">> Stream logs:"
echo "   az container logs -g $AZ_RG -n $GROUP_NAME --container-name bot --follow"
