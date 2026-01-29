#!/usr/bin/env python3
"""
Stream Player - RTSP Stream Wiedergabe mit mpv
Optimiert für niedrige Latenz auf Raspberry Pi 4
"""

import os
import subprocess
import threading
import time
import signal
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class StreamPlayer:
    """RTSP Stream Player mit mpv und Hardware-Beschleunigung"""
    
    def __init__(self, config_manager):
        self.config = config_manager
        self._process: Optional[subprocess.Popen] = None
        self._current_stream: Optional[str] = None
        self._status = 'stopped'
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = True
        
        # Fallback Image Prozess
        self._fallback_process: Optional[subprocess.Popen] = None
        
    def play(self, url: str):
        """Startet einen neuen Stream (mit nahtlosem Übergang)"""
        with self._lock:
            logger.info(f"Starte Stream: {url}")
            
            # Altes mpv beenden
            old_process = self._process
            
            # Neuen Stream starten
            try:
                self._start_mpv(url)
                self._current_stream = url
                self._status = 'starting'
                
                # Kurz warten und prüfen ob mpv noch läuft
                time.sleep(1.0)
                
                if self._process and self._process.poll() is None:
                    # mpv läuft tatsächlich
                    self._status = 'playing'
                    logger.info("Stream läuft erfolgreich")
                    
                    # Dann alten Prozess beenden (nahtloser Übergang)
                    if old_process:
                        self._terminate_process(old_process)
                    
                    # Fallback beenden falls aktiv
                    self._stop_fallback()
                    
                    # Monitor starten
                    self._start_monitor()
                else:
                    # mpv ist sofort abgestürzt
                    exit_code = self._process.returncode if self._process else -1
                    logger.error(f"mpv sofort beendet mit Code {exit_code}")
                    self._status = 'error'
                    self._current_stream = url  # Behalte URL für Anzeige
                    self._show_fallback()
                
            except Exception as e:
                logger.error(f"Fehler beim Starten des Streams: {e}")
                self._status = 'error'
                self._show_fallback()
    
    def stop(self):
        """Stoppt den aktuellen Stream"""
        with self._lock:
            logger.info("Stoppe Stream")
            self._stop_monitor()
            
            if self._process:
                self._terminate_process(self._process)
                self._process = None
            
            self._current_stream = None
            self._status = 'stopped'
            
            # Fallback anzeigen
            self._show_fallback()
    
    def _start_mpv(self, url: str):
        """Startet mpv mit optimierten Einstellungen für niedrige Latenz"""
        hw_accel = self.config.get('player.hardware_acceleration', True)
        buffer_time = self.config.get('player.buffer_time_ms', 500)
        
        # mpv Argumente für minimale Latenz
        args = [
            'mpv',
            url,
            '--fullscreen',
            '--no-border',
            '--no-osc',
            '--no-input-default-bindings',
            '--really-quiet',
            '--no-terminal',
            '--no-input-terminal',        # Keine Terminal-Eingabe erwarten
            '--input-ipc-server=/tmp/mpv-socket',  # IPC für Steuerung
            '--force-window=immediate',   # Fenster sofort erstellen
            '--keep-open=no',             # Nicht auf Eingabe warten am Ende
            '--idle=no',                  # Nicht im Idle-Modus starten
            # Niedrige Latenz Einstellungen
            '--profile=low-latency',
            '--untimed',
            f'--cache=no',
            '--demuxer-lavf-o=fflags=+nobuffer+discardcorrupt',
            '--demuxer-lavf-analyzeduration=0.1',
            '--demuxer-lavf-probesize=32',
            '--video-sync=audio',
            '--interpolation=no',
            '--vd-lavc-threads=4',
            # Netzwerk
            '--network-timeout=10',
            '--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=2',
            # Audio
            '--audio-channels=stereo',
            '--volume=100',
        ]
        
        # Hardware-Beschleunigung für Raspberry Pi
        if hw_accel:
            args.extend([
                '--hwdec=drm',
            ])
        
        # Video-Output: DRM direkt auf Framebuffer (ohne Desktop)
        env = os.environ.copy()
        args.extend([
            '--vo=drm',
            '--drm-connector=HDMI-A-1',
            '--drm-mode=1920x1080',
        ])
        logger.info("Verwende DRM Video-Output (Konsole)")
        
        logger.debug(f"mpv Befehl: {' '.join(args)}")
        
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            preexec_fn=os.setsid
        )
        
        logger.info(f"mpv gestartet (PID: {self._process.pid})")
    
    def _terminate_process(self, process: subprocess.Popen):
        """Beendet einen Prozess sauber"""
        if process and process.poll() is None:
            try:
                # Zuerst SIGTERM
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                
                # Warten
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # Dann SIGKILL
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()
                    
                logger.debug(f"Prozess {process.pid} beendet")
            except Exception as e:
                logger.warning(f"Fehler beim Beenden des Prozesses: {e}")
    
    def _start_monitor(self):
        """Startet den Monitor-Thread"""
        self._stop_monitor()
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
    
    def _stop_monitor(self):
        """Stoppt den Monitor-Thread"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1)
            self._monitor_thread = None
    
    def _monitor_loop(self):
        """Überwacht den Stream und startet bei Bedarf neu"""
        reconnect_delay = self.config.get('player.reconnect_delay_ms', 2000) / 1000
        max_attempts = self.config.get('player.max_reconnect_attempts', 10)
        attempts = 0
        
        while self._running and self._current_stream:
            time.sleep(1)
            
            if self._process and self._process.poll() is not None:
                # Prozess ist beendet
                exit_code = self._process.returncode
                logger.warning(f"mpv beendet mit Code {exit_code}")
                
                if attempts < max_attempts:
                    attempts += 1
                    logger.info(f"Reconnect Versuch {attempts}/{max_attempts}")
                    
                    self._status = 'reconnecting'
                    time.sleep(reconnect_delay)
                    
                    try:
                        self._start_mpv(self._current_stream)
                        # Kurz warten und prüfen ob mpv läuft
                        time.sleep(1.0)
                        
                        if self._process and self._process.poll() is None:
                            self._status = 'playing'
                            logger.info("Reconnect erfolgreich - Stream läuft")
                            # Bei Erfolg Zähler zurücksetzen
                            attempts = 0
                        else:
                            exit_code = self._process.returncode if self._process else -1
                            logger.warning(f"Reconnect fehlgeschlagen - mpv beendet mit Code {exit_code}")
                            # Zähler nicht zurücksetzen, weiter versuchen
                    except Exception as e:
                        logger.error(f"Reconnect fehlgeschlagen: {e}")
                else:
                    logger.error("Maximale Reconnect-Versuche erreicht")
                    self._status = 'error'
                    self._show_fallback()
                    break
            else:
                # Stream läuft, Zähler zurücksetzen
                attempts = 0
    
    def _show_fallback(self):
        """Zeigt das Fallback-Bild an"""
        fallback_image = self.config.get('streams.fallback_image', '')
        
        if fallback_image and Path(fallback_image).exists():
            logger.info(f"Zeige Fallback-Bild: {fallback_image}")
            
            try:
                env = os.environ.copy()
                if 'DISPLAY' not in env:
                    env['DISPLAY'] = ':0'
                
                # feh für Bildanzeige
                self._fallback_process = subprocess.Popen(
                    ['feh', '--fullscreen', '--auto-zoom', '--hide-pointer', fallback_image],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    preexec_fn=os.setsid
                )
            except Exception as e:
                logger.error(f"Fehler beim Anzeigen des Fallback-Bildes: {e}")
    
    def _stop_fallback(self):
        """Stoppt die Fallback-Anzeige"""
        if self._fallback_process:
            self._terminate_process(self._fallback_process)
            self._fallback_process = None
    
    def get_status(self) -> str:
        """Gibt den aktuellen Status zurück"""
        return self._status
    
    def get_current_stream(self) -> Optional[str]:
        """Gibt die aktuelle Stream-URL zurück"""
        return self._current_stream
    
    def is_playing(self) -> bool:
        """Prüft ob ein Stream läuft"""
        if self._status != 'playing':
            return False
        if self._process is None:
            return False
        # Prüfe ob Prozess noch läuft
        if self._process.poll() is not None:
            return False
        return True
    
    def get_detailed_status(self) -> dict:
        """Gibt detaillierten Status zurück"""
        process_running = self._process is not None and self._process.poll() is None
        return {
            'status': self._status,
            'stream': self._current_stream,
            'process_running': process_running,
            'pid': self._process.pid if self._process else None
        }
