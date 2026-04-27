# Azure Deployment

Three options, pick one.

| Option | When to use | State store | Cost (rough) |
|---|---|---|---|
| **Container Apps** (`container-apps/`) | Production. Managed, observable, single-replica polling. | **Azure Cache for Redis (Basic C0)** | ~$15–20/mo bot + ~$16/mo Redis |
| **Container Instances** (`container-instances/`) | Quick demo / staging. One container group with a Redis sidecar. | Redis sidecar (ephemeral!) | ~$10/mo |
| **VM** (`vm/`) | You want SSH and full control. Runs `docker compose` via systemd. | Redis container in compose | B1s ≈ $7.5/mo |

> ⚠️ Telegram polling holds a long-lived HTTP request, so `minReplicas` must be **1** for Container Apps and you should never run two replicas of the same bot token simultaneously (Telegram returns `Conflict: terminated by other getUpdates request`).

## Common prerequisites

```bash
az login
az account set --subscription "<your-subscription>"
```

Push your image to a registry your Azure subscription can reach (ACR, GHCR, Docker Hub).
For ACR with admin user disabled, attach a managed identity; the bicep template here uses a registry password parameter for simplicity.

## Container Apps (recommended)

```bash
export AZ_RG=tgmgmt-rg
export AZ_LOCATION=southeastasia
export AZ_IMAGE=ghcr.io/yourname/tgmgmt:latest
export TGMGMT_BOT_TOKEN=123:abc
./container-apps/deploy.sh
```

Tail logs:

```bash
az containerapp logs show -g $AZ_RG -n tgmgmt-bot --follow
```

## Container Instances

```bash
export AZ_RG=tgmgmt-rg
export AZ_LOCATION=southeastasia
export AZ_IMAGE=ghcr.io/yourname/tgmgmt:latest
export TGMGMT_BOT_TOKEN=123:abc
./container-instances/deploy.sh
```

## VM (docker compose)

```bash
export AZ_RG=tgmgmt-rg
export AZ_LOCATION=southeastasia
export TGMGMT_BOT_TOKEN=123:abc
export REPO_URL=https://github.com/yourname/TGManagementBot.git
./vm/deploy.sh
```
