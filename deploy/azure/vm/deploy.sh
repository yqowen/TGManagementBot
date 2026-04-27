#!/usr/bin/env bash
# Provision a small Ubuntu VM in Azure that runs TGManagementBot via
# docker compose. Suitable when you already have a fixed monthly budget
# and want full SSH access.
#
# Required env:
#   AZ_RG, AZ_LOCATION, TGMGMT_BOT_TOKEN
# Optional env:
#   AZ_VM_SIZE        (default: Standard_B1s)
#   AZ_ADMIN_USER     (default: azureuser)
#   AZ_SSH_PUBKEY     (default: ~/.ssh/id_rsa.pub)
#   REPO_URL          (default: this repo's GitHub URL)
#                      • https://github.com/...        — public HTTPS, no key needed
#                      • git@github.com:...            — private; set DEPLOY_KEY too
#   DEPLOY_KEY_FILE   (path to a PRIVATE SSH key with read access to REPO_URL,
#                      e.g. a GitHub deploy key). If set, baked into the VM.
#   TGMGMT_TRUSTED_BOT_IDS, TGMGMT_ALLOWED_CHAT_IDS
set -euo pipefail

: "${AZ_RG:?AZ_RG required}"
: "${AZ_LOCATION:?AZ_LOCATION required}"
: "${TGMGMT_BOT_TOKEN:?TGMGMT_BOT_TOKEN required}"

VM_NAME="tgmgmt-vm"
VM_SIZE="${AZ_VM_SIZE:-Standard_B1s}"
ADMIN_USER="${AZ_ADMIN_USER:-azureuser}"
SSH_PUBKEY="${AZ_SSH_PUBKEY:-$HOME/.ssh/id_rsa.pub}"
export REPO_URL="${REPO_URL:-https://github.com/yourname/TGManagementBot.git}"
export TGMGMT_BOT_TOKEN
export TGMGMT_TRUSTED_BOT_IDS="${TGMGMT_TRUSTED_BOT_IDS:-}"
export TGMGMT_ALLOWED_CHAT_IDS="${TGMGMT_ALLOWED_CHAT_IDS:-}"

# Indent the deploy key so it sits correctly under the YAML `content: |` block.
if [[ -n "${DEPLOY_KEY_FILE:-}" ]]; then
  if [[ ! -f "$DEPLOY_KEY_FILE" ]]; then
    echo "DEPLOY_KEY_FILE=$DEPLOY_KEY_FILE not found" >&2
    exit 1
  fi
  export DEPLOY_KEY_INDENTED="$(sed 's/^/      /' "$DEPLOY_KEY_FILE")"
else
  # Placeholder so envsubst doesn't leave a literal ${DEPLOY_KEY_INDENTED}.
  export DEPLOY_KEY_INDENTED="      # (no deploy key supplied)"
fi

if [[ ! -f "$SSH_PUBKEY" ]]; then
  echo "SSH public key not found at $SSH_PUBKEY" >&2
  exit 1
fi

az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none

RENDERED=$(mktemp)
trap 'rm -f "$RENDERED"' EXIT
envsubst < "$(dirname "$0")/cloud-init.yml" > "$RENDERED"

echo ">> Creating VM $VM_NAME ($VM_SIZE) in $AZ_RG"
az vm create \
  --resource-group "$AZ_RG" \
  --name "$VM_NAME" \
  --image Ubuntu2404 \
  --size "$VM_SIZE" \
  --admin-username "$ADMIN_USER" \
  --ssh-key-values "$SSH_PUBKEY" \
  --custom-data "$RENDERED" \
  --public-ip-sku Standard \
  --output table

echo ">> SSH:"
echo "   ssh ${ADMIN_USER}@\$(az vm show -d -g $AZ_RG -n $VM_NAME --query publicIps -o tsv)"
echo ">> Logs (after a minute):"
echo "   ssh ... 'cd /opt/tgmgmt/repo && sudo docker compose logs -f bot'"
