#!/usr/bin/env python3
"""
Stream Display Server - Hauptapplikation
MQTT-gesteuerter RTSP Stream Display für Raspberry Pi
"""

import json
import os
import sys
import signal
import threading
import logging
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

from modules.config_manager import ConfigManager
from modules.mqtt_client import MQTTClient
from modules.stream_player import StreamPlayer
from modules.unifi_protect import UniFiProtectClient

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/streamdisplay/server.log')
    ]
)
logger = logging.getLogger(__name__)

# Flask App
app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
CORS(app)

# Globale Instanzen
config_manager = None
mqtt_client = None
stream_player = None
unifi_client = None

# Konfigurationspfade
BASE_DIR = Path('/opt/streamdisplay')
CONFIG_FILE = BASE_DIR / 'config.json'
UPLOAD_FOLDER = BASE_DIR / 'uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def init_components():
    """Initialisiert alle Komponenten"""
    global config_manager, mqtt_client, stream_player, unifi_client
    
    logger.info("Initialisiere Komponenten...")
    
    # Config Manager
    config_manager = ConfigManager(str(CONFIG_FILE))
    
    # Stream Player
    stream_player = StreamPlayer(config_manager)
    
    # MQTT Client
    mqtt_client = MQTTClient(config_manager, stream_player)
    
    # UniFi Protect Client (optional)
    if config_manager.get('unifi_protect.enabled', False):
        unifi_client = UniFiProtectClient(config_manager, mqtt_client)
        unifi_client.start()
    
    # MQTT starten
    mqtt_client.start()
    
    # Standard-Stream starten
    default_stream = config_manager.get('streams.default_stream', '')
    if default_stream:
        logger.info(f"Starte Standard-Stream: {default_stream}")
        stream_player.play(default_stream)
    
    logger.info("Alle Komponenten initialisiert")


def shutdown_components():
    """Beendet alle Komponenten sauber"""
    global mqtt_client, stream_player, unifi_client
    
    logger.info("Beende Komponenten...")
    
    if stream_player:
        stream_player.stop()
    
    if mqtt_client:
        mqtt_client.stop()
    
    if unifi_client:
        unifi_client.stop()
    
    logger.info("Alle Komponenten beendet")


# Signal Handler für sauberes Beenden
def signal_handler(signum, frame):
    logger.info(f"Signal {signum} empfangen, beende...")
    shutdown_components()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ============== Web Routes ==============

@app.route('/')
def index():
    """Hauptseite"""
    return render_template('index.html')


@app.route('/api/status')
def get_status():
    """Aktueller Status"""
    return jsonify({
        'status': stream_player.get_status() if stream_player else 'stopped',
        'current_stream': stream_player.get_current_stream() if stream_player else None,
        'mqtt_connected': mqtt_client.is_connected() if mqtt_client else False,
        'unifi_enabled': config_manager.get('unifi_protect.enabled', False) if config_manager else False
    })


@app.route('/api/config', methods=['GET'])
def get_config():
    """Konfiguration abrufen"""
    config = config_manager.get_all()
    # Passwörter maskieren
    if 'mqtt' in config and 'password' in config['mqtt']:
        config['mqtt']['password'] = '***' if config['mqtt']['password'] else ''
    if 'unifi_protect' in config and 'password' in config['unifi_protect']:
        config['unifi_protect']['password'] = '***' if config['unifi_protect']['password'] else ''
    return jsonify(config)


@app.route('/api/config', methods=['POST'])
def update_config():
    """Konfiguration aktualisieren"""
    try:
        new_config = request.json
        
        # Passwörter nur aktualisieren wenn geändert
        current_config = config_manager.get_all()
        if new_config.get('mqtt', {}).get('password') == '***':
            new_config['mqtt']['password'] = current_config.get('mqtt', {}).get('password', '')
        if new_config.get('unifi_protect', {}).get('password') == '***':
            new_config['unifi_protect']['password'] = current_config.get('unifi_protect', {}).get('password', '')
        
        config_manager.update(new_config)
        config_manager.save()
        
        # Komponenten neu initialisieren
        mqtt_client.reconnect()
        
        return jsonify({'success': True, 'message': 'Konfiguration gespeichert'})
    except Exception as e:
        logger.error(f"Fehler beim Speichern der Konfiguration: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/streams', methods=['GET'])
def get_streams():
    """Verfügbare Streams abrufen"""
    streams = []
    
    # Custom Streams
    custom_streams = config_manager.get('streams.custom_streams', [])
    for stream in custom_streams:
        streams.append({
            'id': stream.get('id', ''),
            'name': stream.get('name', ''),
            'url': stream.get('url', ''),
            'type': 'custom'
        })
    
    # UniFi Protect Kameras
    if unifi_client and unifi_client.is_connected():
        cameras = unifi_client.get_cameras()
        for cam in cameras:
            streams.append({
                'id': cam['id'],
                'name': cam['name'],
                'url': cam['rtsp_url'],
                'type': 'unifi'
            })
    
    return jsonify(streams)


@app.route('/api/streams', methods=['POST'])
def add_stream():
    """Neuen Stream hinzufügen"""
    try:
        stream_data = request.json
        custom_streams = config_manager.get('streams.custom_streams', [])
        
        # ID generieren
        stream_id = stream_data.get('id', f"stream_{len(custom_streams) + 1}")
        
        new_stream = {
            'id': stream_id,
            'name': stream_data.get('name', 'Neuer Stream'),
            'url': stream_data.get('url', '')
        }
        
        custom_streams.append(new_stream)
        config_manager.set('streams.custom_streams', custom_streams)
        config_manager.save()
        
        return jsonify({'success': True, 'stream': new_stream})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/streams/<stream_id>', methods=['DELETE'])
def delete_stream(stream_id):
    """Stream löschen"""
    try:
        custom_streams = config_manager.get('streams.custom_streams', [])
        custom_streams = [s for s in custom_streams if s.get('id') != stream_id]
        config_manager.set('streams.custom_streams', custom_streams)
        config_manager.save()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/play', methods=['POST'])
def play_stream():
    """Stream abspielen"""
    try:
        data = request.json
        url = data.get('url')
        stream_id = data.get('stream_id')
        
        if stream_id:
            # Stream anhand der ID finden
            streams = config_manager.get('streams.custom_streams', [])
            stream = next((s for s in streams if s.get('id') == stream_id), None)
            if stream:
                url = stream.get('url')
            elif unifi_client:
                cameras = unifi_client.get_cameras()
                camera = next((c for c in cameras if c['id'] == stream_id), None)
                if camera:
                    url = camera['rtsp_url']
        
        if not url:
            return jsonify({'success': False, 'error': 'Keine Stream-URL angegeben'}), 400
        
        stream_player.play(url)
        mqtt_client.publish_status()
        
        return jsonify({'success': True, 'url': url})
    except Exception as e:
        logger.error(f"Fehler beim Abspielen: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/stop', methods=['POST'])
def stop_stream():
    """Stream stoppen"""
    try:
        stream_player.stop()
        mqtt_client.publish_status()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/upload/fallback', methods=['POST'])
def upload_fallback():
    """Fallback-Bild hochladen"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Keine Datei'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Keine Datei ausgewählt'}), 400
        
        if file and allowed_file(file.filename):
            filename = 'fallback' + os.path.splitext(file.filename)[1]
            filepath = UPLOAD_FOLDER / filename
            UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            file.save(str(filepath))
            
            config_manager.set('streams.fallback_image', str(filepath))
            config_manager.save()
            
            return jsonify({'success': True, 'path': str(filepath)})
        
        return jsonify({'success': False, 'error': 'Ungültiger Dateityp'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/unifi/cameras')
def get_unifi_cameras():
    """UniFi Protect Kameras abrufen"""
    if not unifi_client:
        return jsonify({'success': False, 'error': 'UniFi Protect nicht aktiviert'}), 400
    
    try:
        cameras = unifi_client.get_cameras()
        return jsonify({'success': True, 'cameras': cameras})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/unifi/snapshot/<camera_id>')
def get_unifi_snapshot(camera_id):
    """Snapshot von einer UniFi Protect Kamera abrufen"""
    if not unifi_client:
        return jsonify({'success': False, 'error': 'UniFi Protect nicht aktiviert'}), 400
    
    try:
        snapshot = unifi_client.get_camera_snapshot(camera_id)
        if snapshot:
            from flask import Response
            return Response(snapshot, mimetype='image/jpeg')
        else:
            # Fallback: transparentes Placeholder-Bild
            return jsonify({'success': False, 'error': 'Snapshot nicht verfügbar'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/unifi/test', methods=['POST'])
def test_unifi_connection():
    """UniFi Protect Verbindung testen"""
    try:
        data = request.json
        test_client = UniFiProtectClient(config_manager)
        test_client.url = data.get('url')
        test_client.username = data.get('username')
        test_client.password = data.get('password')
        
        if test_client.connect():
            cameras = test_client.get_cameras()
            return jsonify({'success': True, 'camera_count': len(cameras)})
        else:
            return jsonify({'success': False, 'error': 'Verbindung fehlgeschlagen'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Hochgeladene Dateien bereitstellen"""
    return send_from_directory(str(UPLOAD_FOLDER), filename)


@app.route('/api/system/restart', methods=['POST'])
def restart_service():
    """Service neu starten"""
    try:
        os.system('sudo systemctl restart streamdisplay')
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/system/info')
def system_info():
    """Systeminformationen"""
    import subprocess
    
    try:
        # CPU Temperatur
        temp = subprocess.check_output(['vcgencmd', 'measure_temp']).decode().strip()
        temp = temp.replace("temp=", "").replace("'C", "°C")
        
        # Memory
        mem = subprocess.check_output(['free', '-h']).decode()
        
        # Uptime
        uptime = subprocess.check_output(['uptime', '-p']).decode().strip()
        
        return jsonify({
            'temperature': temp,
            'uptime': uptime,
            'hostname': os.uname().nodename
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def main():
    """Hauptfunktion"""
    # Verzeichnisse erstellen
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    Path('/var/log/streamdisplay').mkdir(parents=True, exist_ok=True)
    
    # Standard-Konfiguration erstellen wenn nicht vorhanden
    if not CONFIG_FILE.exists():
        import shutil
        example_config = Path(__file__).parent / 'config.json.example'
        if example_config.exists():
            shutil.copy(example_config, CONFIG_FILE)
    
    # Komponenten initialisieren
    init_components()
    
    # Webserver starten
    from waitress import serve
    port = config_manager.get('webui.port', 80)
    logger.info(f"Starte Webserver auf Port {port}")
    serve(app, host='0.0.0.0', port=port, threads=4)


if __name__ == '__main__':
    main()
