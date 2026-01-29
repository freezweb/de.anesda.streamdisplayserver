#!/usr/bin/env python3
"""
UniFi Protect Client - Integration mit Ubiquiti UniFi Protect
Basierend auf UniFi Protect API v6.2.88
"""

import json
import time
import threading
import logging
import requests
from typing import List, Dict, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


class UniFiProtectClient:
    """Client für UniFi Protect API"""
    
    def __init__(self, config_manager, mqtt_client=None):
        self.config = config_manager
        self.mqtt_client = mqtt_client
        
        self.url = config_manager.get('unifi_protect.url', '').rstrip('/')
        self.api_key = config_manager.get('unifi_protect.api_key', '')
        self.username = config_manager.get('unifi_protect.username', '')
        self.password = config_manager.get('unifi_protect.password', '')
        self.verify_ssl = config_manager.get('unifi_protect.verify_ssl', False)
        
        self._session: Optional[requests.Session] = None
        self._token: Optional[str] = None
        self._cookies = {}
        self._connected = False
        self._cameras: List[Dict] = []
        self._nvr_info: Dict = {}
        
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._update_interval = 60  # Sekunden
        
        # API Base Path - UniFi Protect verwendet verschiedene Pfade
        # Cloud Key: /proxy/protect/api/
        # UNVR/NVR Pro: /api/ oder /proxy/protect/api/
        self._api_paths = [
            '/proxy/protect/api',
            '/api',
            '/protect/api'
        ]
        self._active_api_path = None
    
    def start(self):
        """Startet den UniFi Protect Client"""
        if not self.url or (not self.api_key and not self.username):
            logger.warning("UniFi Protect nicht konfiguriert (URL und API-Key oder Username benötigt)")
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
            
            # Standard Headers
            self._session.headers.update({
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            })
            
            # API-Key Authentifizierung (bevorzugt für NVR Pro)
            if self.api_key:
                # Verschiedene Header-Formate probieren
                auth_headers = [
                    {'X-API-KEY': self.api_key},
                    {'Authorization': f'Bearer {self.api_key}'},
                ]
                
                for headers in auth_headers:
                    self._session.headers.update(headers)
                    
                    # Versuche verschiedene API-Pfade
                    for api_path in self._api_paths:
                        try:
                            # Teste mit Cameras-Endpoint (laut API-Doku)
                            test_url = f"{self.url}{api_path}/cameras"
                            logger.debug(f"Teste API-Pfad: {test_url}")
                            
                            response = self._session.get(test_url, timeout=10)
                            
                            if response.status_code == 200:
                                self._active_api_path = api_path
                                self._connected = True
                                logger.info(f"UniFi Protect verbunden (API-Key, Pfad: {api_path})")
                                return True
                            elif response.status_code == 401:
                                logger.debug(f"API-Pfad {api_path} mit Header {headers}: 401 Unauthorized")
                            elif response.status_code == 404:
                                logger.debug(f"API-Pfad {api_path}: nicht gefunden")
                            else:
                                logger.debug(f"API-Pfad {api_path}: Status {response.status_code}")
                        except requests.exceptions.RequestException as e:
                            logger.debug(f"API-Pfad {api_path} Fehler: {e}")
                    
                    # Header zurücksetzen für nächsten Versuch
                    for key in headers:
                        self._session.headers.pop(key, None)
                
                logger.warning("UniFi Protect: API-Key Authentifizierung fehlgeschlagen bei allen Pfaden")
            
            # Fallback: Username/Password Login (für Cloud Key)
            if self.username and self.password:
                return self._login_with_credentials()
            
            return False
                
        except Exception as e:
            logger.error(f"UniFi Protect Verbindungsfehler: {e}")
            return False
    
    def _login_with_credentials(self) -> bool:
        """Login mit Username/Password"""
        login_endpoints = [
            '/api/auth/login',
            '/proxy/protect/api/auth/login',
            '/api/users/login'
        ]
        
        for endpoint in login_endpoints:
            try:
                login_url = f"{self.url}{endpoint}"
                logger.debug(f"Versuche Login: {login_url}")
                
                response = self._session.post(
                    login_url,
                    json={
                        'username': self.username,
                        'password': self.password,
                        'remember': True
                    },
                    timeout=10
                )
                
                if response.status_code == 200:
                    self._cookies = response.cookies.get_dict()
                    
                    # Authorization Header für zukünftige Requests
                    if 'Authorization' in response.headers:
                        self._token = response.headers['Authorization']
                        self._session.headers['Authorization'] = self._token
                    
                    # CSRF Token
                    csrf = response.headers.get('X-CSRF-Token')
                    if csrf:
                        self._session.headers['X-CSRF-Token'] = csrf
                    
                    # Ermittle aktiven API-Pfad
                    for api_path in self._api_paths:
                        test_url = f"{self.url}{api_path}/cameras"
                        try:
                            test_resp = self._session.get(test_url, timeout=5)
                            if test_resp.status_code == 200:
                                self._active_api_path = api_path
                                break
                        except:
                            pass
                    
                    self._connected = True
                    logger.info(f"UniFi Protect verbunden (Login, Pfad: {self._active_api_path})")
                    return True
                    
            except requests.exceptions.RequestException as e:
                logger.debug(f"Login Endpoint {endpoint} Fehler: {e}")
        
        logger.error("UniFi Protect: Login mit allen Endpoints fehlgeschlagen")
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
        if not self._session or not self._active_api_path:
            return
        
        try:
            # GET /cameras Endpoint (laut API-Dokumentation)
            cameras_url = f"{self.url}{self._active_api_path}/cameras"
            
            response = self._session.get(
                cameras_url,
                cookies=self._cookies,
                timeout=15
            )
            
            if response.status_code == 200:
                cameras = response.json()
                
                self._cameras = []
                for cam in cameras:
                    if cam.get('state') == 'CONNECTED':
                        camera_info = {
                            'id': cam.get('id', ''),
                            'name': cam.get('name', 'Unbekannt'),
                            'type': cam.get('modelKey', 'camera'),
                            'model': cam.get('type', ''),
                            'state': cam.get('state', ''),
                            'mac': cam.get('mac', ''),
                            'rtsp_url': None,  # Wird bei Bedarf abgerufen
                            'snapshot_url': self._get_snapshot_url(cam.get('id', ''))
                        }
                        
                        # Versuche existierende RTSPS Streams abzurufen
                        rtsp_url = self._get_existing_rtsps_stream(cam.get('id', ''))
                        if rtsp_url:
                            camera_info['rtsp_url'] = rtsp_url
                        else:
                            # Generiere Standard RTSP URL aus channels
                            camera_info['rtsp_url'] = self._get_rtsp_url_from_channels(cam)
                        
                        self._cameras.append(camera_info)
                
                logger.info(f"UniFi Protect: {len(self._cameras)} Kameras gefunden")
                
            elif response.status_code == 401:
                logger.warning("UniFi Protect: Token abgelaufen, reconnect...")
                self._connected = False
            else:
                logger.error(f"UniFi Protect API-Fehler: {response.status_code} - {response.text[:200]}")
                
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Kameras: {e}")
    
    def _get_existing_rtsps_stream(self, camera_id: str) -> Optional[str]:
        """Holt existierende RTSPS Stream URL für eine Kamera"""
        if not camera_id or not self._session:
            return None
        
        try:
            # GET /cameras/{id}/rtsps-stream (laut API-Dokumentation)
            stream_url = f"{self.url}{self._active_api_path}/cameras/{camera_id}/rtsps-stream"
            response = self._session.get(stream_url, timeout=10)
            
            if response.status_code == 200:
                streams = response.json()
                # Bevorzuge "high" Qualität, dann "medium", dann "low"
                for quality in ['high', 'medium', 'low']:
                    if streams.get(quality):
                        return streams[quality]
        except Exception as e:
            logger.debug(f"Konnte RTSPS Stream nicht abrufen: {e}")
        
        return None
    
    def create_rtsps_stream(self, camera_id: str, qualities: List[str] = None) -> Dict:
        """Erstellt RTSPS Streams für eine Kamera"""
        if qualities is None:
            qualities = ['high']
        
        if not self._session or not self._active_api_path:
            return {}
        
        try:
            # POST /cameras/{id}/rtsps-stream (laut API-Dokumentation)
            stream_url = f"{self.url}{self._active_api_path}/cameras/{camera_id}/rtsps-stream"
            
            response = self._session.post(
                stream_url,
                json={'qualities': qualities},
                timeout=15
            )
            
            if response.status_code == 200:
                streams = response.json()
                logger.info(f"RTSPS Streams erstellt für Kamera {camera_id}: {list(streams.keys())}")
                return streams
            else:
                logger.error(f"Fehler beim Erstellen von RTSPS Streams: {response.status_code}")
                
        except Exception as e:
            logger.error(f"RTSPS Stream Erstellung fehlgeschlagen: {e}")
        
        return {}
    
    def _get_rtsp_url_from_channels(self, camera: Dict) -> str:
        """Generiert die RTSP URL aus den Kamera-Channels"""
        camera_id = camera.get('id', '')
        
        # UniFi Protect RTSPS URL Format
        channels = camera.get('channels', [])
        
        for channel in channels:
            if channel.get('name') == 'High' or channel.get('id') == 0:
                rtsp_alias = channel.get('rtspAlias', '')
                if rtsp_alias:
                    parsed = urlparse(self.url)
                    host = parsed.hostname
                    return f"rtsps://{host}:7441/{rtsp_alias}"
        
        # Fallback: Standard URL
        parsed = urlparse(self.url)
        host = parsed.hostname
        return f"rtsps://{host}:7441/{camera_id}"
    
    def _get_snapshot_url(self, camera_id: str) -> str:
        """Generiert die Snapshot URL für eine Kamera"""
        if self._active_api_path:
            return f"{self.url}{self._active_api_path}/cameras/{camera_id}/snapshot"
        return f"{self.url}/proxy/protect/api/cameras/{camera_id}/snapshot"
    
    def get_camera_snapshot(self, camera_id: str, high_quality: bool = True) -> Optional[bytes]:
        """Holt einen Snapshot von einer Kamera"""
        if not self._session or not self._active_api_path:
            return None
        
        try:
            # GET /cameras/{id}/snapshot (laut API-Dokumentation)
            url = f"{self.url}{self._active_api_path}/cameras/{camera_id}/snapshot"
            params = {'highQuality': 'true' if high_quality else 'false'}
            
            response = self._session.get(url, params=params, timeout=15)
            
            if response.status_code == 200:
                return response.content
                
        except Exception as e:
            logger.error(f"Snapshot abrufen fehlgeschlagen: {e}")
        
        return None
    
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
    
    def get_nvr_info(self) -> Dict:
        """Holt NVR Informationen"""
        if not self._session or not self._active_api_path:
            return {}
        
        try:
            # GET /nvr (laut API-Dokumentation)
            url = f"{self.url}{self._active_api_path}/nvr"
            response = self._session.get(url, timeout=10)
            
            if response.status_code == 200:
                self._nvr_info = response.json()
                return self._nvr_info
                
        except Exception as e:
            logger.error(f"NVR Info abrufen fehlgeschlagen: {e}")
        
        return {}
    
    def get_liveviews(self) -> List[Dict]:
        """Holt alle Liveviews"""
        if not self._session or not self._active_api_path:
            return []
        
        try:
            # GET /liveviews (laut API-Dokumentation)
            url = f"{self.url}{self._active_api_path}/liveviews"
            response = self._session.get(url, timeout=10)
            
            if response.status_code == 200:
                return response.json()
                
        except Exception as e:
            logger.error(f"Liveviews abrufen fehlgeschlagen: {e}")
        
        return []
    
    def get_viewers(self) -> List[Dict]:
        """Holt alle Viewers (Display-Geräte)"""
        if not self._session or not self._active_api_path:
            return []
        
        try:
            # GET /viewers (laut API-Dokumentation)
            url = f"{self.url}{self._active_api_path}/viewers"
            response = self._session.get(url, timeout=10)
            
            if response.status_code == 200:
                return response.json()
                
        except Exception as e:
            logger.error(f"Viewers abrufen fehlgeschlagen: {e}")
        
        return []
    
    def is_connected(self) -> bool:
        """Prüft ob verbunden"""
        return self._connected
    
    def get_api_info(self) -> Dict:
        """Gibt Debug-Informationen über die API-Verbindung zurück"""
        return {
            'connected': self._connected,
            'url': self.url,
            'api_path': self._active_api_path,
            'auth_method': 'api_key' if self.api_key else 'credentials',
            'camera_count': len(self._cameras)
        }
