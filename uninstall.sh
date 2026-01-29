#!/bin/bash
#
# Stream Display Server - Deinstallations-Script
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${RED}Stream Display Server - Deinstallation${NC}"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Bitte als root ausführen (sudo)${NC}"
    exit 1
fi

read -p "Wirklich deinstallieren? (j/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Jj]$ ]]; then
    exit 1
fi

echo "Stoppe Services..."
systemctl stop streamdisplay 2>/dev/null || true
systemctl stop streamdisplay-x 2>/dev/null || true

echo "Deaktiviere Services..."
systemctl disable streamdisplay 2>/dev/null || true
systemctl disable streamdisplay-x 2>/dev/null || true

echo "Entferne Service-Dateien..."
rm -f /etc/systemd/system/streamdisplay.service
rm -f /etc/systemd/system/streamdisplay-x.service
systemctl daemon-reload

read -p "Auch Konfiguration und Logs löschen? (j/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Jj]$ ]]; then
    rm -rf /opt/streamdisplay
    rm -rf /var/log/streamdisplay
fi

echo -e "${GREEN}Deinstallation abgeschlossen${NC}"
