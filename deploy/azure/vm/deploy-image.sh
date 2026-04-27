#!/usr/bin/env bash
# Deploy TGManagementBot to an Azure VM that PULLS a prebuilt image from
# ghcr.io (or any registry). No source rsync, no in-VM build.
#
# Required env:
#   AZ_RG, AZ_LOCATION
#   TGMGMT_BOT_TOKEN
#   IMAGE                 e.g. ghcr.io/yqowen/tgmgmt:latest
# For private registries (GHCR private package, ACR, etc.):
#   REGISTRY              e.g. ghcr.io
#   REGISTRY_USER         e.g. yqowen
#   REGISTRY_PAT          a token with read:packages (NOT your normal PAT)
# Optional:
#   AZ_VM_SIZE            (default Standard_B1s)
#   AZ_ADMIN_USER         (default azureuser)
#   AZ_SSH_PUBKEY         (default ~/.ssh/id_rsa.pub)
#   AZ_SSH_PRIVKEY        (default ~/.ssh/id_rsa)
#   TGMGMT_TRUSTED_BOT_IDS, TGMGMT_ALLOWED_CHAT_IDS

set -euo pipefail

: "${AZ_RG:?AZ_RG required}"
: "${AZ_LOCATION:?AZ_LOCATION required}"
: "${TGMGMT_BOT_TOKEN:?TGMGMT_BOT_TOKEN required}"
: "${IMAGE:?IMAGE required, e.g. ghcr.io/yqowen/tgmgmt:latest}"

VM_NAME="tgmgmt-vm"
VM_SIZE="${AZ_VM_SIZE:-Standard_B1s}"
ADMIN_USER="${AZ_ADMIN_USER:-azureuser}"
SSH_PUBKEY="${AZ_SSH_PUBKEY:-$HOME/.ssh/id_rsa.pub}"
SSH_PRIVKEY="${AZ_SSH_PRIVKEY:-$HOME/.ssh/id_rsa}"
TRUSTED="${TGMGMT_TRUSTED_BOT_IDS:-}"
CHATS="${TGMGMT_ALLOWED_CHAT_IDS:-}"

[[ -f "$SSH_PUBKEY"  ]] || { echo "missing $SSH_PUBKEY"  >&2; exit 1; }
[[ -f "$SSH_PRIVKEY" ]] || { echo "missing $SSH_PRIVKEY" >&2; exit 1; }

CLOUD_INIT=$(mktemp); trap 'rm -f "$CLOUD_INIT"' EXIT
cat >"$CLOUD_INIT" <<'YAML'
#cloud-config
package_update: true
packages: [ca-certificates, curl, gnupg]
runcmd:
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - >-
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]
    https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo "$VERSION_CODENAME") stable"
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  - apt-get update
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  - mkdir -p /opt/tgmgmt
YAML

az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none

if az vm show -g "$AZ_RG" -n "$VM_NAME" >/dev/null 2>&1; then
  echo ">> Reusing existing VM $VM_NAME"
else
  echo ">> Creating VM $VM_NAME ($VM_SIZE)"
  az vm create \
    --resource-group "$AZ_RG" \
    --name "$VM_NAME" \
    --image Ubuntu2404 \
    --size "$VM_SIZE" \
    --admin-username "$ADMIN_USER" \
    --ssh-key-values "$SSH_PUBKEY" \
    --custom-data "$CLOUD_INIT" \
    --public-ip-sku Standard \
    --output table
fi

VM_IP=$(az vm show -d -g "$AZ_RG" -n "$VM_NAME" --query publicIps -o tsv)
echo ">> VM IP: $VM_IP"

echo ">> Waiting for SSH..."
for _ in {1..30}; do
  ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
      -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" 'true' 2>/dev/null && break
  sleep 5
done

echo ">> Waiting for cloud-init (Docker install)..."
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" 'sudo cloud-init status --wait' || true

# --- Optional registry login on the VM -----------------------------------
if [[ -n "${REGISTRY:-}" && -n "${REGISTRY_USER:-}" && -n "${REGISTRY_PAT:-}" ]]; then
  echo ">> Logging into $REGISTRY on the VM"
  ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" \
      "echo '$REGISTRY_PAT' | sudo docker login $REGISTRY -u '$REGISTRY_USER' --password-stdin"
fi

# --- Compose file & .env -------------------------------------------------
COMPOSE=$(cat <<COMPOSE
services:
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    restart: unless-stopped
    volumes: ["redis-data:/data"]
  bot:
    image: ${IMAGE}
    env_file: /opt/tgmgmt/.env
    environment:
      TGMGMT_REDIS_URL: redis://redis:6379/0
    depends_on: [redis]
    restart: unless-stopped
volumes:
  redis-data:
COMPOSE
)

echo ">> Writing /opt/tgmgmt/{compose.yml,.env}"
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" "sudo tee /opt/tgmgmt/compose.yml >/dev/null" <<<"$COMPOSE"
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" "sudo tee /opt/tgmgmt/.env >/dev/null" <<EOF
TGMGMT_BOT_TOKEN=${TGMGMT_BOT_TOKEN}
TGMGMT_TRUSTED_BOT_IDS=${TRUSTED}
TGMGMT_ALLOWED_CHAT_IDS=${CHATS}
TGMGMT_LOG_LEVEL=INFO
EOF
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" 'sudo chmod 600 /opt/tgmgmt/.env'

echo ">> Pulling & starting"
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" \
    'cd /opt/tgmgmt && sudo docker compose -f compose.yml pull && sudo docker compose -f compose.yml up -d'

echo
echo "Done."
echo "  ssh -i $SSH_PRIVKEY ${ADMIN_USER}@${VM_IP}"
echo "  ssh -i $SSH_PRIVKEY ${ADMIN_USER}@${VM_IP} 'cd /opt/tgmgmt && sudo docker compose -f compose.yml logs -f bot'"
echo
echo "To redeploy after pushing a new image to $IMAGE, just rerun this script."
