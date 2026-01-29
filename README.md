# Stream Display Server

Ein MQTT-gesteuerter RTSP Stream Display Server für Raspberry Pi 4.

## Features

- 🎥 RTSP Stream Wiedergabe im Vollbild mit minimaler Latenz
- 🔄 Nahtlose Umschaltung zwischen Streams (kein Schwarzbild)
- 📡 MQTT Steuerung für einfache Integration
- 🌐 Web-Interface für Konfiguration und manuelle Steuerung
- 📹 UniFi Protect API Integration
- 🎮 Bitfocus Companion Template für Streamdeck
- 🖼️ Fallback-Logo bei Stream-Unterbrechung
- 🚀 Automatischer Start beim Booten

## Installation

Führe einfach folgenden Befehl auf dem Raspberry Pi aus:

```bash
curl -sSL https://raw.githubusercontent.com/YOUR_REPO/streamdisplayserver/main/install.sh | sudo bash
```

Oder manuell:

```bash
git clone https://github.com/YOUR_REPO/streamdisplayserver.git
cd streamdisplayserver
sudo ./install.sh
```

## Konfiguration

Nach der Installation ist das Web-Interface unter `http://<raspberry-ip>/` erreichbar.

### Einstellungen

- **MQTT Broker**: IP/Hostname des MQTT Brokers
- **MQTT Port**: Standard 1883
- **MQTT Topic Prefix**: z.B. `streamdisplay`
- **UniFi Protect URL**: URL zur UniFi Protect Instanz
- **UniFi Protect API Key**: API-Schlüssel für UniFi Protect
- **Standard Stream**: Stream der nach dem Boot angezeigt wird
- **Fallback Logo**: Bild das bei Stream-Unterbrechung angezeigt wird

## MQTT Topics

### Steuerung

| Topic | Payload | Beschreibung |
|-------|---------|--------------|
| `streamdisplay/switch` | `{"url": "rtsp://..."}` | Stream wechseln |
| `streamdisplay/switch` | `{"camera_id": "camera1"}` | Zu Kamera wechseln |
| `streamdisplay/stop` | - | Stream stoppen |
| `streamdisplay/reload` | - | Konfiguration neu laden |

### Status

| Topic | Beschreibung |
|-------|--------------|
| `streamdisplay/status` | Aktueller Status (playing/stopped/error) |
| `streamdisplay/current` | Aktueller Stream |
| `streamdisplay/cameras` | Verfügbare Kameras (JSON Array) |

## Bitfocus Companion

Importiere die Datei `companion/streamdisplay.companionconfig` in Bitfocus Companion.

## Hardware-Anforderungen

- Raspberry Pi 4 (4GB RAM empfohlen)
- HDMI Ausgang
- Netzwerkverbindung

## Technologie

- Python 3.9+
- Flask (Web-Interface)
- mpv (Video Player mit Hardware-Beschleunigung)
- Paho MQTT Client
- UniFi Protect API

## Lizenz

MIT License
