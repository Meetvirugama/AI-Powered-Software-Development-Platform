# Azure Deployment Architecture & Operations Guide
**Target:** AI-Powered Software Development Platform — Secure Sandbox Execution Architecture (Issue #200 / F20)  
**Date:** November 2026  
**Status:** Deployment Guide  

---

## 1. Hosting Architecture & Tradeoff Evaluation

Our platform is currently hosted as:
- **Frontend:** Vercel (Next.js / React)
- **API Server:** Azure App Service (FastAPI / Linux B1/P1v2)
- **Database:** Supabase (PostgreSQL + pgvector)
- **Cache & Queue:** Upstash Redis

### Why Azure App Service Cannot Run Sibling Sandboxes
Azure App Service runs the API inside a managed, locked container environment without access to a Docker daemon or the ability to spawn sibling Docker containers (`docker-in-docker` is prohibited and insecure). Attempting to run untrusted repository code inside App Service would compromise the API host.

### Hosting Options Comparison:

| Option | Isolation Mechanism | Monthly Cost Estimate (USD) | gVisor Support? | Fits Azure for Students? | Recommendation |
|---|---|---|---|---|---|
| **Dedicated Linux VM (Standard_B2s)** | Docker + gVisor (`runsc`) on Ubuntu 24.04 | ~$30–38/mo (or spot/burstable) | **YES (Native `runsc`)** | **YES** | **Recommended (P0)** |
| **Azure Container Apps (ACA) Sessions** | Managed dynamic microVMs | Pay-per-session | Managed by Azure | Limited region support | Future Phase |
| **E2B Managed Cloud** | Cloud Firecracker Sandboxes | ~$50+/mo (usage-based) | Firecracker hypervisor | Requires external credit card | Alternative SaaS |

---

## 2. Minimal Practical VM Provisioning (Budget Aware)

To respect developer budgets and Azure for Students credit allocations:
- **Instance Type:** `Standard_B2s` (2 vCPUs, 4 GiB RAM, burstable).
- **OS:** Ubuntu 24.04 LTS x86_64.
- **Disk:** 30 GB Standard SSD (OS + container image cache + workspaces).
- **Concurrency Budget:** 3–5 concurrent tasks.
- **Automatic Cleanup:** Workspaces decommissioned immediately upon task completion; orphan sweeper terminates dangling containers.

---

## 3. Host Setup Script: Docker + gVisor (`setup_runner_host.sh`)

Run the following commands on the newly provisioned Ubuntu 24.04 Linux VM:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== 1. Install Docker Engine CE ==="
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io

echo "=== 2. Install gVisor (runsc) ==="
ARCH=$(uname -m)
URL="https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}"
wget "${URL}/runsc" "${URL}/runsc.sha512"
sha512sum -c runsc.sha512
chmod a+rx runsc
sudo mv runsc /usr/local/bin/

echo "=== 3. Configure Docker to use gVisor runtime ==="
sudo /usr/local/bin/runsc install
sudo systemctl restart docker

# Verify runsc in docker runtimes
sudo docker info --format '{{json .Runtimes.runsc}}'

echo "=== 4. Pull Pinned Language Base Images ==="
sudo docker pull python:3.12-slim
sudo docker pull node:20-slim

echo "=== Host Setup Complete ==="
```

---

## 4. Runner Service Systemd Unit (`/etc/systemd/system/runner-service.service`)

```ini
[Unit]
Description=AI Platform Secure Runner Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=runner
Group=docker
WorkingDirectory=/opt/ai-platform-runner/backend
Environment=PYTHONPATH=/opt/ai-platform-runner/backend
Environment=APP_ENV=production
Environment=RUNNER_AUTH_SECRET=configure-your-32-char-secret-here!
Environment=SANDBOX_BACKEND=container
Environment=SANDBOX_USE_GVISOR=true
ExecStart=/opt/ai-platform-runner/.venv/bin/uvicorn runner.main:app --host 0.0.0.0 --port 8080 --workers 4
Restart=always
RestartSec=5

# Process security
LimitNOFILE=65535
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

---

## 5. Network Security Group (NSG) Configuration

1. **Ingress Rules:**
   - **Rule 100 (Allow App Service):**
     - Source: Azure App Service Subnet (or App Service Outbound IPs)
     - Destination Port: `8080`
     - Protocol: TCP
     - Action: **Allow**
   - **Rule 110 (Allow Operator SSH):**
     - Source: Bastion / Operator IP
     - Destination Port: `22`
     - Action: **Allow**
   - **Rule 4096 (Deny All Ingress):**
     - Destination Port: `*`
     - Action: **Deny**

2. **Egress Rules:**
   - Allow outbound HTTPS (Port 443) to PyPI (`pypi.org`, `files.pythonhosted.org`) and npm (`registry.npmjs.org`) for Phase A dependency installation.
   - Deny outbound access to cloud internal metadata IP `169.254.169.254`.
