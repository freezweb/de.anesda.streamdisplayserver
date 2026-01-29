#!/bin/bash
#
# Stream Display Server - Installations-Script
# Automatische Installation auf Raspberry Pi
#

set -e

# Farben für Ausgabe
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Konfiguration
INSTALL_DIR="/opt/streamdisplay"
SERVICE_NAME="streamdisplay"
REPO_URL="https://github.com/YOUR_REPO/streamdisplayserver.git"
PYTHON_VERSION="python3"

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           Stream Display Server - Installer               ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Root-Rechte prüfen
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Bitte als root ausführen (sudo)${NC}"
    exit 1
fi

# Raspberry Pi prüfen
if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo -e "${YELLOW}Warnung: Dies scheint kein Raspberry Pi zu sein${NC}"
    read -p "Trotzdem fortfahren? (j/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Jj]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}[1/8] System aktualisieren...${NC}"
apt-get update -qq
apt-get upgrade -y -qq

echo -e "${GREEN}[2/8] Abhängigkeiten installieren...${NC}"
apt-get install -y -qq \
    $PYTHON_VERSION \
    python3-pip \
    python3-venv \
    mpv \
    feh \
    mosquitto \
    mosquitto-clients \
    git \
    curl \
    xserver-xorg \
    x11-xserver-utils \
    xinit \
    openbox \
    unclutter

echo -e "${GREEN}[3/8] Installationsverzeichnis erstellen...${NC}"
mkdir -p $INSTALL_DIR
mkdir -p $INSTALL_DIR/uploads
mkdir -p /var/log/streamdisplay

# Wenn Git-Repo existiert, klonen; sonst lokale Dateien kopieren
if [ -d ".git" ]; then
    echo -e "${GREEN}[4/8] Dateien kopieren...${NC}"
    cp -r ./* $INSTALL_DIR/
else
    echo -e "${GREEN}[4/8] Repository klonen...${NC}"
    if [ -d "$INSTALL_DIR/.git" ]; then
        cd $INSTALL_DIR
        git pull
    else
        git clone $REPO_URL $INSTALL_DIR
    fi
fi

echo -e "${GREEN}[5/8] Python-Umgebung einrichten...${NC}"
cd $INSTALL_DIR

# Virtual Environment erstellen
$PYTHON_VERSION -m venv venv
source venv/bin/activate

# Abhängigkeiten installieren
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Konfigurationsdatei erstellen falls nicht vorhanden
if [ ! -f "$INSTALL_DIR/config.json" ]; then
    cp $INSTALL_DIR/config.json.example $INSTALL_DIR/config.json
fi

echo -e "${GREEN}[6/8] Systemd-Service einrichten...${NC}"

# Haupt-Service
cat > /etc/systemd/system/streamdisplay.service << EOF
[Unit]
Description=Stream Display Server
After=network.target mosquitto.service
Wants=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment=DISPLAY=:0
Environment=XAUTHORITY=/root/.Xauthority
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/app.py
Restart=always
RestartSec=5
StandardOutput=append:/var/log/streamdisplay/server.log
StandardError=append:/var/log/streamdisplay/error.log

[Install]
WantedBy=multi-user.target
EOF

# X-Server Auto-Start Service
cat > /etc/systemd/system/streamdisplay-x.service << EOF
[Unit]
Description=Stream Display X Server
After=systemd-user-sessions.service
Before=streamdisplay.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/startx /usr/bin/openbox-session -- -nocursor
Restart=always
RestartSec=5
Environment=XDG_SESSION_TYPE=x11

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}[7/8] Auto-Start konfigurieren...${NC}"

# Autologin für Console einrichten
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I \$TERM
EOF

# X-Server Konfiguration
cat > /root/.xinitrc << EOF
#!/bin/bash
xset s off
xset -dpms
xset s noblank
unclutter -idle 0.5 -root &
exec openbox-session
EOF
chmod +x /root/.xinitrc

# Openbox Autostart
mkdir -p /root/.config/openbox
cat > /root/.config/openbox/autostart << EOF
# Bildschirmschoner deaktivieren
xset s off &
xset -dpms &
xset s noblank &

# Mauszeiger verstecken
unclutter -idle 0.5 -root &
EOF
chmod +x /root/.config/openbox/autostart

# Bash Profile für automatischen X-Start
cat > /root/.bash_profile << 'EOF'
# Auto-start X wenn auf tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx -- -nocursor
fi
EOF

# Mosquitto Konfiguration
if [ ! -f "/etc/mosquitto/conf.d/streamdisplay.conf" ]; then
    cat > /etc/mosquitto/conf.d/streamdisplay.conf << EOF
listener 1883
allow_anonymous true
EOF
fi

echo -e "${GREEN}[8/8] Services aktivieren und starten...${NC}"

# Services neu laden
systemctl daemon-reload

# Services aktivieren
systemctl enable mosquitto
systemctl enable streamdisplay

# Services starten
systemctl restart mosquitto
systemctl restart streamdisplay || true

# IP-Adresse ermitteln
IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Installation abgeschlossen!                     ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Web-Interface:    ${BLUE}http://${IP_ADDR}/${NC}"
echo -e "MQTT Broker:      ${BLUE}${IP_ADDR}:1883${NC}"
echo -e "Logs:             ${YELLOW}/var/log/streamdisplay/${NC}"
echo -e "Konfiguration:    ${YELLOW}${INSTALL_DIR}/config.json${NC}"
echo ""
echo -e "${YELLOW}Hinweis: Nach einem Neustart wird der Dienst automatisch gestartet.${NC}"
echo ""
read -p "Jetzt neustarten? (j/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Jj]$ ]]; then
    reboot
fi
