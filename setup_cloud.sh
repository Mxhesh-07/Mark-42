#!/bin/bash
# J.A.R.V.I.S. — Cloud Setup Script for Oracle Cloud Ubuntu
# Run this on your Oracle Cloud VM

echo "=========================================="
echo "  J.A.R.V.I.S. Cloud Setup"
echo "=========================================="

echo "[1/6] Updating system..."
sudo apt update && sudo apt upgrade -y

echo "[2/6] Installing Python and dependencies..."
sudo apt install -y python3 python3-pip python3-venv git

echo "[3/6] Installing Python packages..."
pip3 install --break-system-packages google-genai google-generativeai numpy playwright beautifulsoup4 requests psutil

echo "[4/6] Installing Playwright browsers..."
playwright install chromium
playwright install-deps chromium

echo "[5/6] Creating directories..."
mkdir -p ~/jarvis-cloud/config
mkdir -p ~/jarvis-cloud/memory

echo "[6/6] Done! Next steps:"
echo "  1. Upload your project files to ~/jarvis-cloud/"
echo "  2. Copy config files to ~/jarvis-cloud/config/"
echo "  3. Run: python3 ~/jarvis-cloud/cloud_jarvis.py"

echo "=========================================="
echo "  Setup complete, sir."
echo "=========================================="
