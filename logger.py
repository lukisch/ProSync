"""
ProSync Logging System
Singleton-Pattern Logger mit RotatingFileHandler
"""

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path


class ProSyncLogger:
    """
    Singleton Logger für ProSync.

    Schreibt Logs in prosync.log mit automatischer Rotation (max 5MB, 3 Backups).
    Format: [TIMESTAMP] [LEVEL] Message
    """

    _instance = None
    _logger = None

    def __new__(cls):
        """Singleton-Pattern: Nur eine Instanz erlaubt."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_logger()
        return cls._instance

    def _initialize_logger(self):
        """Initialisiert den Logger mit RotatingFileHandler."""
        if self._logger is not None:
            return

        # Logger erstellen
        self._logger = logging.getLogger("ProSync")
        self._logger.setLevel(logging.DEBUG)

        # Verhindere doppelte Handler
        if self._logger.handlers:
            return

        # Log-Datei im gleichen Verzeichnis wie die Anwendung
        log_dir = Path(__file__).parent
        log_file = log_dir / "prosync.log"

        # RotatingFileHandler (max 5MB, 3 Backups)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # Console Handler (optional, nur für Entwicklung)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)  # Nur Warnings/Errors auf Console

        # Formatter
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Handler hinzufügen
        self._logger.addHandler(file_handler)
        self._logger.addHandler(console_handler)

    def debug(self, message: str):
        """Log DEBUG message."""
        self._logger.debug(message)

    def info(self, message: str):
        """Log INFO message."""
        self._logger.info(message)

    def warning(self, message: str):
        """Log WARNING message."""
        self._logger.warning(message)

    def error(self, message: str):
        """Log ERROR message."""
        self._logger.error(message)

    def critical(self, message: str):
        """Log CRITICAL message."""
        self._logger.critical(message)


# Globale Logger-Instanz für einfachen Import
logger = ProSyncLogger()


# Convenience-Funktionen
def log_debug(message: str):
    """Log DEBUG message."""
    logger.debug(message)


def log_info(message: str):
    """Log INFO message."""
    logger.info(message)


def log_warning(message: str):
    """Log WARNING message."""
    logger.warning(message)


def log_error(message: str):
    """Log ERROR message."""
    logger.error(message)


def log_critical(message: str):
    """Log CRITICAL message."""
    logger.critical(message)
