#!/usr/bin/env python3
"""
UniFi Protect Client - Integration mit Ubiquiti UniFi Protect
"""

import json
import time
import threading
import logging
import requests
from typing import List, Dict, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class UniFiProtectClient:
    """Client für UniFi Protect API"""
    
    def __init__(self, config_manager, mqtt_client=None):
        self.config = config_manager
        self.mqtt_client = mqtt_client
        
        self.url = config_manager.get('unifi_protect.url', '')
        self.username = config_manager.get('unifi_protect.username', '')
        self.password = config_manager.get('unifi_protect.password', '')
        self.verify_ssl = config_manager.get('unifi_protect.verify_ssl', False)
        
        self._session: Optional[requests.Session] = None
        self._token: Optional[str] = None
        self._cookies = {}
        self._connected = False
        self._cameras: List[Dict] = []
        
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._update_interval = 60  # Sekunden
    
    def start(self):
        """Startet den UniFi Protect Client"""
        if not self.url or not self.username:
            logger.warning("UniFi Protect nicht konfiguriert")
            return
        
        self._running = True
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()
    
    def stop(self):
        """Stoppt den Client"""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=5)
        self._disconnect()
    
    def connect(self) -> bool:
        """Verbindet mit UniFi Protect"""
        try:
            self._session = requests.Session()
            self._session.verify = self.verify_ssl
            
            # Warnungen für selbst-signierte Zertifikate unterdrücken
            if not self.verify_ssl:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # Login
            login_url = urljoin(self.url, '/api/auth/login')
            
            response = self._session.post(
                login_url,
                json={
                    'username': self.username,
                    'password': self.password
                },
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                # Token aus Cookies oder Header extrahieren
                self._cookies = response.cookies.get_dict()
                
                # Authorization Header für zukünftige Requests
                if 'Authorization' in response.headers:
                    self._token = response.headers['Authorization']
                
                self._connected = True
                logger.info("UniFi Protect verbunden")
                return True
            else:
                logger.error(f"UniFi Protect Login fehlgeschlagen: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"UniFi Protect Verbindungsfehler: {e}")
            return False
    
    def _disconnect(self):
        """Trennt die Verbindung"""
        if self._session:
            try:
                logout_url = urljoin(self.url, '/api/auth/logout')
                self._session.post(logout_url)
            except:
                pass
            self._session.close()
        
        self._connected = False
        self._session = None
        self._token = None
    
    def _update_loop(self):
        """Update-Loop für Kamera-Informationen"""
        while self._running:
            try:
                if not self._connected:
                    self.connect()
                
                if self._connected:
                    self._fetch_cameras()
                    
                    # Kameras per MQTT veröffentlichen
                    if self.mqtt_client:
                        self._publish_cameras()
                
            except Exception as e:
                logger.error(f"UniFi Protect Update-Fehler: {e}")
                self._connected = False
            
            # Warten bis zum nächsten Update
            for _ in range(self._update_interval):
                if not self._running:
                    break
                time.sleep(1)
    
    def _fetch_cameras(self):
        """Holt die Kamera-Liste von UniFi Protect"""
        if not self._session:
            return
        
        try:
            # Bootstrap API für alle Daten
            bootstrap_url = urljoin(self.url, '/proxy/protect/api/bootstrap')
            
            headers = {}
            if self._token:
                headers['Authorization'] = self._token
            
            response = self._session.get(
                bootstrap_url,
                headers=headers,
                cookies=self._cookies
            )
            
            if response.status_code == 200:
                data = response.json()
                cameras = data.get('cameras', [])
                
                self._cameras = []
                for cam in cameras:
                    if cam.get('state') == 'CONNECTED':
                        camera_info = {
                            'id': cam.get('id', ''),
                            'name': cam.get('name', 'Unbekannt'),
                            'type': cam.get('type', ''),
                            'state': cam.get('state', ''),
                            'rtsp_url': self._get_rtsp_url(cam),
                            'snapshot_url': self._get_snapshot_url(cam)
                        }
                        self._cameras.append(camera_info)
                
                logger.info(f"UniFi Protect: {len(self._cameras)} Kameras gefunden")
                
            elif response.status_code == 401:
                logger.warning("UniFi Protect: Token abgelaufen, reconnect...")
                self._connected = False
            else:
                logger.error(f"UniFi Protect API-Fehler: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Kameras: {e}")
    
    def _get_rtsp_url(self, camera: Dict) -> str:
        """Generiert die RTSP URL für eine Kamera"""
        camera_id = camera.get('id', '')
        
        # UniFi Protect RTSPS URL Format
        # Für niedrigste Latenz den High-Quality Stream verwenden
        channels = camera.get('channels', [])
        
        for channel in channels:
            if channel.get('name') == 'High':
                rtsp_alias = channel.get('rtspAlias', '')
                if rtsp_alias:
                    # Host aus der URL extrahieren
                    from urllib.parse import urlparse
                    parsed = urlparse(self.url)
                    host = parsed.hostname
                    
                    return f"rtsps://{host}:7441/{rtsp_alias}"
        
        # Fallback: Standard RTSP URL
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        host = parsed.hostname
        
        return f"rtsps://{host}:7441/{camera_id}"
    
    def _get_snapshot_url(self, camera: Dict) -> str:
        """Generiert die Snapshot URL für eine Kamera"""
        camera_id = camera.get('id', '')
        return urljoin(self.url, f'/proxy/protect/api/cameras/{camera_id}/snapshot')
    
    def _publish_cameras(self):
        """Veröffentlicht die Kameras per MQTT"""
        if not self.mqtt_client:
            return
        
        cameras_data = []
        for cam in self._cameras:
            cameras_data.append({
                'id': cam['id'],
                'name': cam['name'],
                'type': 'unifi',
                'state': cam['state']
            })
        
        self.mqtt_client.publish('unifi/cameras', {'cameras': cameras_data}, retain=True)
    
    def get_cameras(self) -> List[Dict]:
        """Gibt die Liste der Kameras zurück"""
        return self._cameras.copy()
    
    def get_camera_by_id(self, camera_id: str) -> Optional[Dict]:
        """Findet eine Kamera anhand der ID"""
        for cam in self._cameras:
            if cam['id'] == camera_id:
                return cam
        return None
    
    def get_rtsp_url(self, camera_id: str) -> Optional[str]:
        """Gibt die RTSP URL einer Kamera zurück"""
        camera = self.get_camera_by_id(camera_id)
        if camera:
            return camera.get('rtsp_url')
        return None
    
    def is_connected(self) -> bool:
        """Prüft ob verbunden"""
        return self._connected
