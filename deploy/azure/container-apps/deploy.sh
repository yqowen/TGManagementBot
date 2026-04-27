#!/usr/bin/env bash
# Deploy TGManagementBot to Azure Container Apps.
#
# Usage:
#   export AZ_RG=tgmgmt-rg
#   export AZ_LOCATION=southeastasia
#   export AZ_IMAGE=ghcr.io/youruser/tgmgmt:latest    # or your ACR image
#   export TGMGMT_BOT_TOKEN=123:abc
#   export TGMGMT_TRUSTED_BOT_IDS="111,222"           # optional
#   export TGMGMT_ALLOWED_CHAT_IDS=""                  # optional
#   ./deploy.sh
#
# Requires: az CLI logged in (az login), bicep extension auto-installed by az.

set -euo pipefail

: "${AZ_RG:?AZ_RG required}"
: "${AZ_LOCATION:?AZ_LOCATION required}"
: "${AZ_IMAGE:?AZ_IMAGE required}"
: "${TGMGMT_BOT_TOKEN:?TGMGMT_BOT_TOKEN required}"

TRUSTED="${TGMGMT_TRUSTED_BOT_IDS:-}"
CHATS="${TGMGMT_ALLOWED_CHAT_IDS:-}"
REG_SERVER="${AZ_REGISTRY_SERVER:-}"
REG_USER="${AZ_REGISTRY_USERNAME:-}"
REG_PASS="${AZ_REGISTRY_PASSWORD:-}"

echo ">> Ensuring resource group $AZ_RG in $AZ_LOCATION"
az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none

echo ">> Registering required providers (idempotent)"
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Cache; do
  az provider register --namespace "$ns" --output none || true
done

echo ">> Deploying Bicep template"
az deployment group create \
  --resource-group "$AZ_RG" \
  --template-file "$(dirname "$0")/main.bicep" \
  --parameters \
      image="$AZ_IMAGE" \
      botToken="$TGMGMT_BOT_TOKEN" \
      trustedBotIds="$TRUSTED" \
      allowedChatIds="$CHATS" \
      registryServer="$REG_SERVER" \
      registryUsername="$REG_USER" \
      registryPassword="$REG_PASS" \
  --output table

echo ">> Done. Tail logs with:"
echo "   az containerapp logs show -g $AZ_RG -n tgmgmt-bot --follow"
