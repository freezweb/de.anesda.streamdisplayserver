#!/usr/bin/env python3
"""
MQTT Client - MQTT Kommunikation für Stream Display Server
"""

import json
import threading
import time
import logging
from typing import Callable, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTClient:
    """MQTT Client für Stream Display Server"""
    
    def __init__(self, config_manager, stream_player):
        self.config = config_manager
        self.player = stream_player
        self.client = None
        self._connected = False
        self._running = False
        self._thread = None
        
    def start(self):
        """Startet den MQTT Client"""
        self._running = True
        self._connect()
        
    def stop(self):
        """Stoppt den MQTT Client"""
        self._running = False
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        logger.info("MQTT Client gestoppt")
    
    def _connect(self):
        """Stellt Verbindung zum MQTT Broker her"""
        try:
            broker = self.config.get('mqtt.broker', 'localhost')
            port = self.config.get('mqtt.port', 1883)
            username = self.config.get('mqtt.username', '')
            password = self.config.get('mqtt.password', '')
            client_id = self.config.get('mqtt.client_id', 'streamdisplay-server')
            
            logger.info(f"Verbinde zu MQTT Broker: {broker}:{port}")
            
            self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
            
            if username:
                self.client.username_pw_set(username, password)
            
            # Callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            
            # Last Will
            prefix = self.config.get('mqtt.topic_prefix', 'streamdisplay')
            self.client.will_set(
                f"{prefix}/status",
                json.dumps({'status': 'offline'}),
                qos=1,
                retain=True
            )
            
            self.client.connect_async(broker, port, keepalive=60)
            self.client.loop_start()
            
        except Exception as e:
            logger.error(f"MQTT Verbindungsfehler: {e}")
            self._connected = False
    
    def reconnect(self):
        """Verbindung neu aufbauen"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        self._connect()
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback bei erfolgreicher Verbindung"""
        if rc == 0:
            self._connected = True
            logger.info("MQTT verbunden")
            
            prefix = self.config.get('mqtt.topic_prefix', 'streamdisplay')
            
            # Topics abonnieren
            topics = [
                (f"{prefix}/switch", 0),
                (f"{prefix}/stop", 0),
                (f"{prefix}/reload", 0),
                (f"{prefix}/command", 0),
            ]
            
            for topic, qos in topics:
                client.subscribe(topic, qos)
                logger.info(f"Abonniert: {topic}")
            
            # Status veröffentlichen
            self.publish_status()
            self.publish_cameras()
            
        else:
            logger.error(f"MQTT Verbindung fehlgeschlagen: {rc}")
            self._connected = False
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback bei Verbindungsabbruch"""
        self._connected = False
        logger.warning(f"MQTT Verbindung getrennt: {rc}")
        
        # Automatischer Reconnect
        if self._running:
            time.sleep(5)
            self._connect()
    
    def _on_message(self, client, userdata, msg):
        """Callback bei eingehender Nachricht"""
        try:
            prefix = self.config.get('mqtt.topic_prefix', 'streamdisplay')
            topic = msg.topic
            payload = msg.payload.decode('utf-8') if msg.payload else ''
            
            logger.info(f"MQTT Nachricht empfangen: {topic} = {payload}")
            
            if topic == f"{prefix}/switch":
                self._handle_switch(payload)
            elif topic == f"{prefix}/stop":
                self._handle_stop()
            elif topic == f"{prefix}/reload":
                self._handle_reload()
            elif topic == f"{prefix}/command":
                self._handle_command(payload)
                
        except Exception as e:
            logger.error(f"Fehler bei MQTT Nachrichtenverarbeitung: {e}")
    
    def _handle_switch(self, payload: str):
        """Verarbeitet Stream-Wechsel Befehl"""
        try:
            data = json.loads(payload) if payload.startswith('{') else {'url': payload}
            
            url = data.get('url')
            camera_id = data.get('camera_id')
            stream_id = data.get('stream_id')
            
            if camera_id:
                # UniFi Kamera
                from modules.unifi_protect import UniFiProtectClient
                # TODO: Kamera-URL abrufen
                pass
            elif stream_id:
                # Custom Stream
                streams = self.config.get('streams.custom_streams', [])
                stream = next((s for s in streams if s.get('id') == stream_id), None)
                if stream:
                    url = stream.get('url')
            
            if url:
                logger.info(f"Wechsle zu Stream: {url}")
                self.player.play(url)
                self.publish_status()
            else:
                logger.warning("Keine Stream-URL gefunden")
                
        except Exception as e:
            logger.error(f"Fehler beim Stream-Wechsel: {e}")
    
    def _handle_stop(self):
        """Verarbeitet Stop-Befehl"""
        logger.info("Stoppe Stream")
        self.player.stop()
        self.publish_status()
    
    def _handle_reload(self):
        """Verarbeitet Reload-Befehl"""
        logger.info("Lade Konfiguration neu")
        self.config.reload()
        self.publish_status()
        self.publish_cameras()
    
    def _handle_command(self, payload: str):
        """Verarbeitet allgemeine Befehle"""
        try:
            data = json.loads(payload)
            command = data.get('command')
            
            if command == 'status':
                self.publish_status()
            elif command == 'cameras':
                self.publish_cameras()
            elif command == 'restart':
                import os
                os.system('sudo systemctl restart streamdisplay')
                
        except Exception as e:
            logger.error(f"Fehler bei Befehlsverarbeitung: {e}")
    
    def publish(self, topic_suffix: str, payload: dict, retain: bool = False):
        """Veröffentlicht eine Nachricht"""
        if not self._connected or not self.client:
            return
        
        prefix = self.config.get('mqtt.topic_prefix', 'streamdisplay')
        topic = f"{prefix}/{topic_suffix}"
        
        try:
            self.client.publish(
                topic,
                json.dumps(payload),
                qos=1,
                retain=retain
            )
        except Exception as e:
            logger.error(f"Fehler beim Veröffentlichen: {e}")
    
    def publish_status(self):
        """Veröffentlicht den aktuellen Status"""
        status = {
            'status': self.player.get_status(),
            'current_stream': self.player.get_current_stream(),
            'timestamp': time.time()
        }
        self.publish('status', status, retain=True)
        
        # Aktuellen Stream separat veröffentlichen
        self.publish('current', {
            'url': self.player.get_current_stream(),
            'status': self.player.get_status()
        }, retain=True)
    
    def publish_cameras(self):
        """Veröffentlicht die verfügbaren Kameras/Streams"""
        cameras = []
        
        # Custom Streams
        custom_streams = self.config.get('streams.custom_streams', [])
        for stream in custom_streams:
            cameras.append({
                'id': stream.get('id', ''),
                'name': stream.get('name', ''),
                'type': 'custom'
            })
        
        self.publish('cameras', {'cameras': cameras}, retain=True)
    
    def is_connected(self) -> bool:
        """Prüft ob MQTT verbunden ist"""
        return self._connected
