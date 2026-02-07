#!/bin/bash

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (use sudo)"
  exit
fi

echo "Installing AI Assistant Service..."

# Copy service file
cp ai-assistant.service /etc/systemd/system/

# Reload daemon
systemctl daemon-reload

# Enable service to start on boot
systemctl enable ai-assistant

# Start service immediately
systemctl start ai-assistant

echo "✅ Service installed and started!"
echo "Check status with: systemctl status ai-assistant"
