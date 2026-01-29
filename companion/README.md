# Bitfocus Companion - Stream Display Integration

Diese Konfiguration ermöglicht die Steuerung des Stream Display Servers über Bitfocus Companion und Streamdeck.

## Voraussetzungen

1. **Bitfocus Companion** (https://bitfocus.io/companion)
2. **Generic MQTT Modul** muss in Companion installiert sein

## Installation

### Methode 1: Import der Konfiguration

1. Öffne Companion
2. Gehe zu "Import/Export"
3. Importiere die Datei `streamdisplay.companionconfig`
4. Passe die MQTT-Broker IP an (Standard: 10.1.1.161)

### Methode 2: Manuelle Einrichtung

1. **MQTT Instanz erstellen:**
   - Gehe zu "Connections"
   - Füge "Generic MQTT" hinzu
   - Konfiguriere:
     - Broker IP: IP des Raspberry Pi
     - Port: 1883
     - Client ID: companion-streamdisplay

2. **Buttons erstellen:**
   
   **Stream wechseln (per ID):**
   - Action: MQTT Publish
   - Topic: `streamdisplay/switch`
   - Payload: `{"stream_id": "stream_1"}`
   
   **Stream wechseln (per URL):**
   - Action: MQTT Publish
   - Topic: `streamdisplay/switch`
   - Payload: `{"url": "rtsp://server/stream"}`
   
   **Kamera wechseln (UniFi):**
   - Action: MQTT Publish
   - Topic: `streamdisplay/switch`
   - Payload: `{"camera_id": "kamera_id"}`
   
   **Stream stoppen:**
   - Action: MQTT Publish
   - Topic: `streamdisplay/stop`
   - Payload: (leer)
   
   **Konfiguration neu laden:**
   - Action: MQTT Publish
   - Topic: `streamdisplay/reload`
   - Payload: (leer)

## MQTT Topics

### Steuerung (Publish)

| Topic | Payload | Beschreibung |
|-------|---------|--------------|
| `streamdisplay/switch` | `{"url": "rtsp://..."}` | Stream per URL wechseln |
| `streamdisplay/switch` | `{"stream_id": "id"}` | Stream per ID wechseln |
| `streamdisplay/switch` | `{"camera_id": "id"}` | UniFi Kamera wechseln |
| `streamdisplay/stop` | - | Stream stoppen |
| `streamdisplay/reload` | - | Konfiguration neu laden |
| `streamdisplay/command` | `{"command": "restart"}` | Service neustarten |

### Status (Subscribe)

| Topic | Beschreibung |
|-------|--------------|
| `streamdisplay/status` | Aktueller Status (JSON) |
| `streamdisplay/current` | Aktueller Stream |
| `streamdisplay/cameras` | Verfügbare Kameras |

## Beispiel-Payloads

**Status-Nachricht:**
```json
{
    "status": "playing",
    "current_stream": "rtsp://192.168.1.100/stream1",
    "timestamp": 1706540000
}
```

**Kamera-Liste:**
```json
{
    "cameras": [
        {"id": "cam1", "name": "Eingang", "type": "unifi"},
        {"id": "stream_1", "name": "OBS Stream", "type": "custom"}
    ]
}
```

## Feedback einrichten

Für Status-Anzeige auf dem Streamdeck:

1. Button mit MQTT Variable Feedback erstellen
2. Topic: `streamdisplay/status`
3. Button-Farbe basierend auf Status ändern:
   - Grün: playing
   - Grau: stopped
   - Rot: error
   - Orange: reconnecting

## Troubleshooting

- **Keine Verbindung:** Prüfe ob Mosquitto auf dem Pi läuft: `sudo systemctl status mosquitto`
- **Befehle werden nicht ausgeführt:** Prüfe MQTT-Logs: `mosquitto_sub -h PI_IP -t "streamdisplay/#" -v`
- **Falscher Topic-Prefix:** Stelle sicher, dass der Prefix in der Stream Display Konfiguration übereinstimmt
