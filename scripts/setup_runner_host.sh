#!/usr/bin/env bash
# Host Setup Script: Docker CE + gVisor (runsc) on Ubuntu 24.04 LTS
# Target: AI-Powered Software Development Platform — Dedicated Runner VM (Issue #200 / F20)

set -euo pipefail

echo "=========================================================="
echo " Setting up AI Platform Secure Runner Host (Docker + gVisor) "
echo "=========================================================="

echo "[1/4] Installing Docker CE and Containerd..."
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[2/4] Downloading and Installing Google gVisor (runsc)..."
ARCH=$(uname -m)
URL="https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}"
wget -q "${URL}/runsc" "${URL}/runsc.sha512"
sha512sum -c runsc.sha512
chmod a+rx runsc
sudo mv runsc /usr/local/bin/
rm -f runsc.sha512

echo "[3/4] Registering runsc OCI runtime with Docker daemon..."
sudo /usr/local/bin/runsc install
sudo systemctl restart docker

# Verify runsc is available in Docker runtimes
if sudo docker info --format '{{json .Runtimes.runsc}}' | grep -q "runsc"; then
    echo "SUCCESS: gVisor (runsc) OCI runtime is active in Docker daemon."
else
    echo "WARNING: runsc was installed but not detected in Docker daemon runtimes."
fi

echo "[4/4] Pre-pulling pinned language base images..."
sudo docker pull python:3.12-slim
sudo docker pull node:20-slim

echo "=========================================================="
echo " Runner Host Setup Complete! Ready for Runner Service deployment."
echo "=========================================================="
