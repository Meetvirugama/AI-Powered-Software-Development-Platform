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
GVISOR_VERSION="20241021.0"
RAW_ARCH=$(uname -m)
case "${RAW_ARCH}" in
  x86_64)
    ARCH="x86_64"
    EXPECTED_SHA512="258b8008b52bd317e4f0ac676298b497e6986c930f2affa34cfb75659c93135447ff572691a4750c32250d5df30479bf368bafbd5d7bbe6c3bd8473b861d329e"
    ;;
  aarch64|arm64)
    ARCH="aarch64"
    EXPECTED_SHA512="2e11d628c1f6209a5023d34bb9c8cc515a7a2f2acc11a46b79c8c6622544991e105ba67bc0ca3ec79845d6ee78ed9bb2cca6e8dfe8eb5e252a651904b745adb2"
    ;;
  *)
    echo "ERROR: Unsupported architecture for gVisor: ${RAW_ARCH}" >&2
    exit 1
    ;;
esac

URL="https://storage.googleapis.com/gvisor/releases/release/${GVISOR_VERSION}/${ARCH}"
echo "Downloading pinned gVisor (runsc) release ${GVISOR_VERSION} for ${ARCH}..."
wget -q -O runsc "${URL}/runsc"

# Verify against repository-stored trusted checksum BEFORE chmod or install
echo "${EXPECTED_SHA512}  runsc" | sha512sum -c - || {
    echo "ERROR: Checksum verification failed for runsc binary! Aborting installation." >&2
    rm -f runsc
    exit 1
}

chmod a+rx runsc
sudo mv runsc /usr/local/bin/runsc

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
