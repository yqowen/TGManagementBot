#!/usr/bin/env bash
# Provision a VM AND push the local source over SSH (rsync). No GitHub,
# no registry, no deploy keys. Useful when the code stays on your laptop.
#
# Required env:
#   AZ_RG, AZ_LOCATION, TGMGMT_BOT_TOKEN
# Optional env:
#   AZ_VM_SIZE          (default: Standard_B1s)
#   AZ_ADMIN_USER       (default: azureuser)
#   AZ_SSH_PUBKEY       (default: ~/.ssh/id_rsa.pub)
#   AZ_SSH_PRIVKEY      (default: ~/.ssh/id_rsa) — used by rsync
#   TGMGMT_TRUSTED_BOT_IDS, TGMGMT_ALLOWED_CHAT_IDS
#
# Steps performed:
#   1. Create RG + VM (Ubuntu 24.04) with Docker pre-installed via cloud-init.
#   2. Wait for SSH to come up.
#   3. rsync the local repo to /opt/tgmgmt/repo on the VM.
#   4. Write /opt/tgmgmt/.env on the VM.
#   5. Start docker compose.

set -euo pipefail

: "${AZ_RG:?AZ_RG required}"
: "${AZ_LOCATION:?AZ_LOCATION required}"
: "${TGMGMT_BOT_TOKEN:?TGMGMT_BOT_TOKEN required}"

VM_NAME="tgmgmt-vm"
VM_SIZE="${AZ_VM_SIZE:-Standard_B1s}"
ADMIN_USER="${AZ_ADMIN_USER:-azureuser}"
SSH_PUBKEY="${AZ_SSH_PUBKEY:-$HOME/.ssh/id_rsa.pub}"
SSH_PRIVKEY="${AZ_SSH_PRIVKEY:-$HOME/.ssh/id_rsa}"
TRUSTED="${TGMGMT_TRUSTED_BOT_IDS:-}"
CHATS="${TGMGMT_ALLOWED_CHAT_IDS:-}"

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

[[ -f "$SSH_PUBKEY"  ]] || { echo "missing $SSH_PUBKEY"  >&2; exit 1; }
[[ -f "$SSH_PRIVKEY" ]] || { echo "missing $SSH_PRIVKEY" >&2; exit 1; }

# --- Minimal cloud-init: just install Docker, no git clone ------------------
CLOUD_INIT=$(mktemp); trap 'rm -f "$CLOUD_INIT"' EXIT
cat >"$CLOUD_INIT" <<'YAML'
#cloud-config
package_update: true
packages: [ca-certificates, curl, gnupg, rsync]
runcmd:
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - >-
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]
    https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo "$VERSION_CODENAME") stable"
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  - apt-get update
  - apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  - usermod -aG docker ${ADMIN_USER:-azureuser}
  - mkdir -p /opt/tgmgmt/repo
  - chown -R 1000:1000 /opt/tgmgmt
YAML

az group create --name "$AZ_RG" --location "$AZ_LOCATION" --output none

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

VM_IP=$(az vm show -d -g "$AZ_RG" -n "$VM_NAME" --query publicIps -o tsv)
echo ">> Public IP: $VM_IP"

echo ">> Waiting for SSH..."
for i in {1..30}; do
  if ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
        -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" 'true' 2>/dev/null; then
    break
  fi
  sleep 5
done

echo ">> Waiting for cloud-init to finish (Docker install)..."
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" \
    'sudo cloud-init status --wait' || true

echo ">> Rsyncing source from $REPO_ROOT"
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '.git' \
  --exclude 'audit.log' --exclude '.pytest_cache' --exclude '.ruff_cache' \
  -e "ssh -i $SSH_PRIVKEY -o StrictHostKeyChecking=accept-new" \
  "$REPO_ROOT/" "${ADMIN_USER}@${VM_IP}:/opt/tgmgmt/repo/"

echo ">> Writing .env"
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" "sudo tee /opt/tgmgmt/.env >/dev/null" <<EOF
TGMGMT_BOT_TOKEN=${TGMGMT_BOT_TOKEN}
TGMGMT_REDIS_URL=redis://redis:6379/0
TGMGMT_TRUSTED_BOT_IDS=${TRUSTED}
TGMGMT_ALLOWED_CHAT_IDS=${CHATS}
TGMGMT_LOG_LEVEL=INFO
EOF
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" 'sudo chmod 600 /opt/tgmgmt/.env'

echo ">> Building & starting containers"
ssh -i "$SSH_PRIVKEY" "${ADMIN_USER}@${VM_IP}" \
  'cd /opt/tgmgmt/repo && sudo docker compose --env-file /opt/tgmgmt/.env up -d --build'

echo
echo "Done. Useful commands:"
echo "  ssh -i $SSH_PRIVKEY ${ADMIN_USER}@${VM_IP}"
echo "  ssh -i $SSH_PRIVKEY ${ADMIN_USER}@${VM_IP} 'cd /opt/tgmgmt/repo && sudo docker compose logs -f bot'"
echo
echo "To redeploy after code changes, just rerun this script — rsync will sync diffs and rebuild."
