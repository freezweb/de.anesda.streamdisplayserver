#!/usr/bin/env python3
"""
Config Manager - Konfigurationsverwaltung
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """Verwaltet die Konfiguration des Stream Display Servers"""
    
    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config = {}
        self._lock = threading.Lock()
        self._load()
    
    def _load(self):
        """Lädt die Konfiguration aus der Datei"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.info(f"Konfiguration geladen von {self.config_path}")
            else:
                self._create_default()
        except Exception as e:
            logger.error(f"Fehler beim Laden der Konfiguration: {e}")
            self._create_default()
    
    def _create_default(self):
        """Erstellt eine Standard-Konfiguration"""
        self.config = {
            "mqtt": {
                "broker": "localhost",
                "port": 1883,
                "username": "",
                "password": "",
                "topic_prefix": "streamdisplay",
                "client_id": "streamdisplay-server"
            },
            "unifi_protect": {
                "enabled": False,
                "url": "https://192.168.1.1",
                "username": "",
                "password": "",
                "verify_ssl": False
            },
            "streams": {
                "default_stream": "",
                "fallback_image": "/opt/streamdisplay/fallback.png",
                "custom_streams": []
            },
            "player": {
                "hardware_acceleration": True,
                "buffer_time_ms": 500,
                "reconnect_delay_ms": 2000,
                "max_reconnect_attempts": 10
            },
            "webui": {
                "port": 80,
                "auth_enabled": False,
                "username": "admin",
                "password": "admin"
            }
        }
        self.save()
    
    def save(self):
        """Speichert die Konfiguration in die Datei"""
        with self._lock:
            try:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=4, ensure_ascii=False)
                logger.info("Konfiguration gespeichert")
            except Exception as e:
                logger.error(f"Fehler beim Speichern der Konfiguration: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Holt einen Konfigurationswert (mit Punkt-Notation für verschachtelte Werte)
        z.B. get('mqtt.broker')
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any):
        """
        Setzt einen Konfigurationswert (mit Punkt-Notation für verschachtelte Werte)
        z.B. set('mqtt.broker', 'localhost')
        """
        with self._lock:
            keys = key.split('.')
            config = self.config
            
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]
            
            config[keys[-1]] = value
    
    def get_all(self) -> dict:
        """Gibt die gesamte Konfiguration zurück"""
        return self.config.copy()
    
    def update(self, new_config: dict):
        """Aktualisiert die Konfiguration mit einem neuen Dictionary"""
        with self._lock:
            self._deep_update(self.config, new_config)
    
    def _deep_update(self, base: dict, updates: dict):
        """Rekursives Update eines Dictionaries"""
        for key, value in updates.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value
    
    def reload(self):
        """Lädt die Konfiguration neu aus der Datei"""
        self._load()
