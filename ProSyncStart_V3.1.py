import sys
import os
import json
import uuid
import hashlib
import shutil
import sqlite3
import time
import subprocess
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QToolBar, QMenu, QHBoxLayout, QPushButton, QProgressBar, QLabel,
    QDialog, QFormLayout, QLineEdit, QComboBox, QCheckBox, QDialogButtonBox,
    QFileDialog, QMessageBox, QSystemTrayIcon, QStyle, QSizePolicy, QSplitter,
    QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QTimer, QLockFile, QDir
from PyQt6.QtGui import QAction, QActionGroup, QIcon

# ProSync Logger
from logger import log_debug, log_info, log_warning, log_error

# Windows UTF-8 Fix
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Windows Registry Support (Optional)
try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False

# ---------------- CONSTANTS ----------------
DB_CONNECTION_TIMEOUT = 5.0  # Seconds for SQLite database connection timeout
SEARCH_RESULT_LIMIT = 500    # Maximum number of search results

# FileSyncWorker Progress Percentages
PROGRESS_CHECKPOINT = 10   # WAL checkpoint phase
PROGRESS_PREPARE = 30      # Target directory creation
PROGRESS_COPY = 50         # File copy phase
PROGRESS_VERIFY = 90       # Verification phase
PROGRESS_DONE = 100        # Completion

# Dialog Dimensions
DIALOG_WIDTH = 500         # Default width for ConnectionDialog
DIALOG_HEIGHT = 600        # Default height for ConnectionDialog (increased for safety info)

# ---------------- DATABASE SAFETY MANAGER ----------------
class DatabaseSafetyManager:
    """
    V3.1 IMPROVED: Option D - Separate handling for folder vs. file connections.

    For FOLDER connections:
    - Critical DBs are auto-excluded
    - User gets warning
    - Suggestion to create FILE connection for DB

    For FILE connections:
    - Enforce one-way for critical DBs
    - Auto-enable WAL checkpoint
    - Prevent two-way sync
    """

    # Database file extensions
    DB_EXTENSIONS = {
        ".sqlite", ".sqlite3", ".db", ".db3",
        ".mdb", ".accdb"  # MS Access
    }

    # MS Access lock files
    ACCESS_LOCK_EXTENSIONS = {
        ".ldb", ".laccdb"
    }

    @classmethod
    def is_database_file(cls, filepath: str) -> bool:
        """
        Prüft ob eine Datei eine Datenbank ist (anhand der Dateiendung).

        Args:
            filepath: Pfad zur zu prüfenden Datei

        Returns:
            True wenn die Datei eine bekannte Datenbank-Endung hat
        """
        ext = Path(filepath).suffix.lower()
        return ext in cls.DB_EXTENSIONS

    @classmethod
    def is_access_lock_file(cls, filepath: str) -> bool:
        """
        Prüft ob eine Datei eine MS Access Lock-Datei ist.

        MS Access erstellt .ldb (Access 2003) oder .laccdb (Access 2007+) Lock-Dateien
        wenn eine Datenbank geöffnet ist. Diese sollten nie kopiert werden.

        Args:
            filepath: Pfad zur zu prüfenden Datei

        Returns:
            True wenn die Datei eine MS Access Lock-Datei ist (.ldb, .laccdb)
        """
        ext = Path(filepath).suffix.lower()
        return ext in cls.ACCESS_LOCK_EXTENSIONS

    @classmethod
    def is_sqlite_database(cls, filepath: str) -> bool:
        """
        Prüft ob eine Datei eine SQLite-Datenbank ist (durch Lesen des Headers).

        Liest die ersten 16 Bytes der Datei und prüft auf die SQLite-Magic-Number
        "SQLite format 3". Dies ist zuverlässiger als nur die Dateiendung zu prüfen.

        Args:
            filepath: Pfad zur zu prüfenden Datei

        Returns:
            True wenn die Datei eine gültige SQLite 3 Datenbank ist
        """
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, 'rb') as f:
                header = f.read(16)
                return header.startswith(b'SQLite format 3')
        except (OSError, IOError):
            return False

    @classmethod
    def check_wal_mode(cls, db_path: str) -> bool:
        """
        Prüft ob eine SQLite-Datenbank im WAL-Modus läuft.

        Args:
            db_path: Pfad zur SQLite-Datenbankdatei

        Returns:
            True wenn die Datenbank im WAL-Modus ist, sonst False
        """
        if not os.path.exists(db_path):
            return False
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=DB_CONNECTION_TIMEOUT)
            cur = conn.cursor()
            cur.execute("PRAGMA journal_mode;")
            mode = cur.fetchone()[0].upper()
            conn.close()
            return mode == "WAL"
        except (sqlite3.Error, OSError):
            return False

    @classmethod
    def scan_directory_for_databases(cls, directory: str) -> list:
        """
        Scannt ein Verzeichnis nach Datenbankdateien und analysiert sie.

        Args:
            directory: Pfad zum zu scannenden Verzeichnis

        Returns:
            Liste von Dicts mit Datenbank-Metadaten (type, wal_mode, size_mb, etc.)
        """
        databases = []
        if not os.path.exists(directory):
            return databases

        try:
            for root, dirs, files in os.walk(directory):
                # Skip hidden and cache directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

                for file in files:
                    filepath = os.path.join(root, file)
                    if cls.is_database_file(filepath):
                        db_info = cls._analyze_database_file(filepath, directory)
                        databases.append(db_info)

        except Exception as e:
            log_error(f"Error scanning directory: {e}")

        return databases

    @classmethod
    def _analyze_database_file(cls, filepath: str, base_directory: str) -> dict:
        """Analysiert eine einzelne Datenbankdatei und gibt Metadaten zurück."""
        db_info = {
            "path": filepath,
            "name": os.path.basename(filepath),
            "relative_path": os.path.relpath(filepath, base_directory),
            "type": "unknown",
            "wal_mode": False,
            "has_wal_files": False,
            "size_mb": 0,
            "is_critical": False
        }

        # Analyze SQLite databases
        if cls.is_sqlite_database(filepath):
            db_info["type"] = "sqlite"
            db_info["wal_mode"] = cls.check_wal_mode(filepath)
            db_info["has_wal_files"] = (
                os.path.exists(filepath + "-wal") or
                os.path.exists(filepath + "-shm")
            )
            db_info["is_critical"] = db_info["wal_mode"] or db_info["has_wal_files"]

        # Analyze MS Access databases
        elif filepath.endswith(('.mdb', '.accdb')):
            db_info["type"] = "ms_access"

        # Get file size
        try:
            db_info["size_mb"] = os.path.getsize(filepath) / (1024 * 1024)
        except OSError:
            pass

        return db_info

    @classmethod
    def apply_safe_settings_folder(cls, conn_config: dict, databases: list) -> tuple:
        """
        V3.1 NEW: Apply safe settings for FOLDER connections.

        Strategy:
        - Exclude critical databases from folder sync
        - Keep two-way for all other files
        - Suggest creating FILE connections for excluded DBs

        Returns: (modified_config, warnings_list, excluded_dbs_list, was_changed)
        """
        warnings = []
        excluded_dbs = []
        was_changed = False

        # Filtere kritische Datenbanken (WAL-Modus oder WAL-Dateien vorhanden)
        critical_dbs = [db for db in databases if db.get("is_critical")]

        if critical_dbs:
            # Initialisiere exclude_patterns falls noch nicht vorhanden
            if "exclude_patterns" not in conn_config:
                conn_config["exclude_patterns"] = []

            # Verwende Set für schnellere Duplikatsprüfung
            current_excludes = set(conn_config["exclude_patterns"])

            for db in critical_dbs:
                db_name = db["name"]

                # Schließe die Datenbankdatei selbst aus
                if db_name not in current_excludes:
                    conn_config["exclude_patterns"].append(db_name)
                    was_changed = True

                # Schließe zugehörige WAL-Dateien aus (SQLite Write-Ahead Log)
                # -wal: Write-Ahead Log Datei
                # -shm: Shared Memory Datei
                # -journal: Rollback Journal (für Non-WAL Mode)
                wal_patterns = [
                    db_name + "-wal",
                    db_name + "-shm",
                    db_name + "-journal"
                ]

                for pattern in wal_patterns:
                    if pattern not in current_excludes:
                        conn_config["exclude_patterns"].append(pattern)
                        was_changed = True

                excluded_dbs.append(db)

            # Add general unsafe patterns
            for pattern in ["*.lock", "*.lck", "*.tmp", ".DS_Store", "Thumbs.db",
                          "__pycache__", "*.pyc"]:
                if pattern not in current_excludes:
                    conn_config["exclude_patterns"].append(pattern)
                    was_changed = True

            if excluded_dbs:
                warnings.append(f"⚠ {len(excluded_dbs)} kritische Datenbank(en) ausgeschlossen")
                warnings.append("💡 Erstelle Datei-Verbindungen für einzelne DB-Sync")

                # Speichere Metadaten über ausgeschlossene DBs für spätere Referenz
                # (z.B. um dem User zu zeigen welche DBs ausgeschlossen wurden)
                conn_config["_auto_excluded_dbs"] = [
                    {
                        "name": db["name"],
                        "size_mb": db["size_mb"],
                        "type": db["type"],
                        "wal_mode": db.get("wal_mode", False),
                        "relative_path": db.get("relative_path", db["name"])
                    }
                    for db in excluded_dbs
                ]

        # MS Access lock files
        access_dbs = [db for db in databases if db.get("type") == "ms_access"]
        if access_dbs:
            lock_patterns = ["*.ldb", "*.laccdb"]
            current_excludes = set(conn_config.get("exclude_patterns", []))

            for pattern in lock_patterns:
                if pattern not in current_excludes:
                    if "exclude_patterns" not in conn_config:
                        conn_config["exclude_patterns"] = []
                    conn_config["exclude_patterns"].append(pattern)
                    was_changed = True

            if was_changed:
                warnings.append("✓ MS Access Lock-Dateien ausgeschlossen (.ldb, .laccdb)")

        # Add safety metadata
        if databases:
            conn_config["_safety_analysis"] = {
                "databases_found": len(databases),
                "critical_databases": len(critical_dbs),
                "excluded_databases": len(excluded_dbs),
                "total_db_size_mb": sum(db.get("size_mb", 0) for db in databases),
                "last_check": datetime.now().isoformat(),
                "auto_configured": True,
                "version": "3.1",
                "connection_type": "folder"
            }

        return (conn_config, warnings, excluded_dbs, was_changed)

    @classmethod
    def apply_safe_settings_file(cls, conn_config: dict) -> tuple:
        """
        V3.1 NEW: Apply safe settings for FILE connections.

        Strategy:
        - Enforce one-way for critical database files
        - Enable WAL checkpoint for SQLite WAL databases
        - Disable auto-sync by default

        Returns: (modified_config, warnings_list, was_changed)
        """
        warnings = []
        was_changed = False

        source_file = conn_config.get("source_file", "")

        if not source_file or not os.path.exists(source_file):
            return (conn_config, warnings, was_changed)

        filename = os.path.basename(source_file)

        # Check if database file
        if cls.is_database_file(source_file):
            db_info = {
                "name": filename,
                "type": "unknown",
                "wal_mode": False,
                "size_mb": 0,
                "is_critical": False
            }

            # Analyze SQLite
            if cls.is_sqlite_database(source_file):
                db_info["type"] = "sqlite"
                db_info["wal_mode"] = cls.check_wal_mode(source_file)
                db_info["is_critical"] = db_info["wal_mode"]

                # Enable checkpoint for WAL databases
                if db_info["wal_mode"]:
                    if not conn_config.get("checkpoint_before_sync"):
                        conn_config["checkpoint_before_sync"] = True
                        warnings.append("✓ WAL-Checkpoint vor Sync aktiviert")
                        was_changed = True

            elif source_file.endswith(('.mdb', '.accdb')):
                db_info["type"] = "ms_access"

            # Get size
            try:
                db_info["size_mb"] = os.path.getsize(source_file) / (1024 * 1024)
            except OSError:
                pass

            # Enforce one-way for critical databases
            if db_info["is_critical"] or db_info["type"] in ["sqlite", "ms_access"]:
                if conn_config.get("mode") != "one_way":
                    conn_config["mode"] = "one_way"
                    warnings.append("⚠ Modus auf one_way gesetzt (kritische Datenbank)")
                    was_changed = True

                # Disable auto-sync
                if conn_config.get("autosync", {}).get("enabled", False):
                    conn_config["autosync"]["enabled"] = False
                    conn_config["autosync"]["_reason"] = "Manuelle Sync empfohlen für Datenbanken"
                    warnings.append("⚠ Auto-sync deaktiviert (manueller Sync empfohlen)")
                    was_changed = True

            # Add metadata
            conn_config["_file_analysis"] = {
                "filename": filename,
                "type": db_info["type"],
                "size_mb": db_info["size_mb"],
                "wal_mode": db_info.get("wal_mode", False),
                "is_critical": db_info["is_critical"],
                "checkpoint_enabled": conn_config.get("checkpoint_before_sync", False),
                "last_check": datetime.now().isoformat(),
                "version": "3.1",
                "connection_type": "file"
            }

        return (conn_config, warnings, was_changed)

    @classmethod
    def checkpoint_sqlite_database(cls, db_path: str) -> bool:
        """
        Führt einen WAL-Checkpoint auf einer SQLite-Datenbank aus.

        WAL (Write-Ahead Logging) speichert Änderungen zunächst in einer separaten
        -wal Datei. Ein Checkpoint merged diese Änderungen zurück in die Hauptdatei.
        Dies ist wichtig vor dem Kopieren, um einen konsistenten Zustand zu garantieren.

        Args:
            db_path: Pfad zur SQLite-Datenbankdatei

        Returns:
            True wenn erfolgreich, False bei Fehler
        """
        if not os.path.exists(db_path):
            return False

        try:
            # Verbinde zur DB mit 30s Timeout (falls gerade gelockt)
            conn = sqlite3.connect(db_path, timeout=30.0)

            # PRAGMA wal_checkpoint(FULL) führt folgende Schritte aus:
            # 1. Blockiert alle Writer
            # 2. Merged alle WAL-Änderungen in die Haupt-DB
            # 3. Truncated die -wal Datei
            # 4. Gibt Locks frei
            conn.execute("PRAGMA wal_checkpoint(FULL);")
            conn.commit()
            conn.close()

            log_info(f"✓ WAL checkpoint successful: {os.path.basename(db_path)}")
            return True
        except Exception as e:
            log_warning(f"⚠ WAL checkpoint failed: {e}")
            return False

# ---------------- CONNECTION TYPES (V3.1 NEW) ----------------
class ConnectionType:
    """V3.1 NEW: Connection type constants."""
    FOLDER = "folder"  # Sync entire folder
    FILE = "file"      # Sync single file only

# ---------------- AUTOSTART MANAGER ----------------
class AutostartManager:
    """
    Verwaltet den Windows-Autostart für ProSync über die Registry.

    Nutzt den Run-Schlüssel in HKEY_CURRENT_USER um die Anwendung
    beim Windows-Start automatisch zu starten. Windows-spezifisch (winreg).
    """

    APP_NAME = "ProSync"

    @staticmethod
    def set_autostart(enable=True):
        """
        Aktiviert oder deaktiviert den Windows-Autostart für ProSync.

        Args:
            enable: True = Autostart aktivieren, False = deaktivieren

        Returns:
            True bei Erfolg, False bei Fehler oder fehlender winreg-Unterstützung
        """
        if not HAS_WINREG: return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            if enable:
                if getattr(sys, 'frozen', False):
                    exe_path = f'"{sys.executable}"'
                else:
                    script_path = os.path.abspath(__file__)
                    exe_path = f'"{sys.executable}" "{script_path}"'
                winreg.SetValueEx(key, AutostartManager.APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, AutostartManager.APP_NAME)
                except FileNotFoundError: pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            log_error(f"Registry Fehler: {e}")
            return False

    @staticmethod
    def is_autostart_enabled():
        """
        Prüft ob ProSync im Windows-Autostart eingetragen ist.

        Returns:
            True wenn Autostart aktiv, False sonst
        """
        if not HAS_WINREG: return False
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, AutostartManager.APP_NAME)
            winreg.CloseKey(key)
            return True
        except (FileNotFoundError, OSError):
            return False

# ---------------- CONFIG ----------------
class ConfigManager:
    """
    Verwaltet die ProSync-Konfigurationsdatei (JSON).

    Die Konfiguration enthält App-Einstellungen und alle Sync-Verbindungen.
    Automatisches Laden/Speichern bei Änderungen.
    """

    def __init__(self, path):
        """
        Initialisiert den ConfigManager und lädt die Konfiguration.

        Args:
            path: Pfad zur Konfigurationsdatei (ProSync_config.json)
        """
        self.path = path
        self.data = {"app": {}, "connections": []}
        self.load()

    def load(self):
        """
        Lädt die Konfiguration aus der JSON-Datei.

        Bei Fehler oder fehlender Datei wird eine neue Config erstellt.
        """
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                log_error(f"Config load error: {e}")
                self.save()
        else:
            self.save()

    def save(self):
        """
        Speichert die Konfiguration in die JSON-Datei.

        Erstellt das Verzeichnis falls es nicht existiert.
        """
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def list_connections(self):
        """
        Gibt alle gespeicherten Sync-Verbindungen zurück.

        Returns:
            Liste von Connection-Dicts
        """
        return self.data.get("connections", [])

    def add_or_update_connection(self, conn):
        """
        Fügt eine neue Verbindung hinzu oder aktualisiert eine bestehende.

        Die Verbindung wird anhand der ID identifiziert. Speichert automatisch.

        Args:
            conn: Connection-Dict mit mindestens {"id": "..."}
        """
        conns = self.data.get("connections", [])
        found = False
        for i, c in enumerate(conns):
            if c.get("id") == conn.get("id"):
                conns[i] = conn
                found = True
                break
        if not found:
            conns.append(conn)
        self.data["connections"] = conns
        self.save()

    def remove_connection(self, conn_id):
        """
        Entfernt eine Verbindung anhand der ID.

        Args:
            conn_id: ID der zu entfernenden Verbindung
        """
        self.data["connections"] = [c for c in self.data.get("connections", [])
                                    if c.get("id") != conn_id]
        self.save()

# ---------------- DB ----------------
DDL = """
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, content_hash TEXT UNIQUE, size INTEGER, mime TEXT, first_seen TEXT);
CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY, file_id INTEGER, name TEXT, path TEXT, mtime TEXT, ctime TEXT, version_index INTEGER, source_side TEXT);
CREATE TABLE IF NOT EXISTS tags(id INTEGER PRIMARY KEY, file_id INTEGER, tag TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, file_id INTEGER, event_type TEXT, details TEXT, ts TEXT);
"""

class ConnectionDB:
    """
    Indexierungs-Datenbank für ProSync-Verbindungen.

    Speichert Dateiversionen, Hashes, Tags und Events für Suchfunktion.
    V3 IMPROVED: WAL checkpoint on close, 30s timeout, busy_timeout.
    """

    def __init__(self, db_path):
        """
        Initialisiert die Indexierungs-Datenbank.

        Args:
            db_path: Pfad zur SQLite-Datenbankdatei
        """
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        # V3 FIX: Added timeout and better isolation
        self.conn = sqlite3.connect(
            db_path,
            check_same_thread=False,
            timeout=30.0  # V3: Prevent immediate lock errors
        )
        self.conn.execute("PRAGMA busy_timeout=30000;")  # V3: 30 second busy timeout
        self.conn.executescript(DDL)

    def close(self):
        """V3 IMPROVED: WAL checkpoint before close."""
        if self.conn:
            try:
                # V3 FIX: Checkpoint WAL to merge changes
                self.conn.execute("PRAGMA wal_checkpoint(FULL);")
                self.conn.commit()
            except Exception as e:
                log_warning(f"Warning: WAL checkpoint failed: {e}")
            finally:
                self.conn.close()

    def get_file_id(self, content_hash, size):
        """
        Gibt die ID einer Datei anhand ihres Hash zurück oder erstellt einen neuen Eintrag.

        Args:
            content_hash: SHA256-Hash der Datei
            size: Größe der Datei in Bytes

        Returns:
            File-ID (Integer)
        """
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM files WHERE content_hash=?", (content_hash,))
        row = cur.fetchone()
        if row: return row[0]
        ts = datetime.utcnow().isoformat()
        cur.execute("INSERT INTO files(content_hash,size,first_seen) VALUES (?,?,?)",
                   (content_hash, size, ts))
        self.conn.commit()
        return cur.lastrowid

    def log_version(self, name, path, mtime, size, content_hash, side):
        """
        Loggt eine neue Dateiversionen in die Datenbank.

        Args:
            name: Dateiname
            path: Pfad zur Datei
            mtime: Modification Time (ISO-Format)
            size: Größe in Bytes
            content_hash: SHA256-Hash
            side: "source" oder "target"

        Returns:
            File-ID (Integer)
        """
        fid = self.get_file_id(content_hash, size)
        cur = self.conn.cursor()
        cur.execute("SELECT id, version_index FROM versions WHERE path=? AND mtime=?",
                   (path, mtime))
        if cur.fetchone():
            return fid

        cur.execute("SELECT MAX(version_index) FROM versions WHERE file_id=?", (fid,))
        res = cur.fetchone()
        idx = (res[0] + 1) if res and res[0] else 1

        ctime = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO versions(file_id,name,path,mtime,ctime,version_index,source_side) VALUES (?,?,?,?,?,?,?)",
            (fid, name, path, mtime, ctime, idx, side)
        )
        self.conn.commit()
        return fid

    def add_tag(self, fid, tag):
        """
        Fügt einen Tag zu einer Datei hinzu.

        Args:
            fid: File-ID
            tag: Tag-String
        """
        self.conn.execute("INSERT OR IGNORE INTO tags(file_id,tag) VALUES (?,?)", (fid, tag))
        self.conn.commit()

# ---------------- SYNC LOGIC ----------------
def sha256_file(path: str, chunk_size: int = 1024*1024) -> str:
    """
    Berechnet SHA256-Hash einer Datei mit chunk-basiertem Lesen.

    Args:
        path: Pfad zur Datei
        chunk_size: Größe der gelesenen Chunks in Bytes (Standard: 1MB)

    Returns:
        SHA256-Hash als Hexadezimal-String, oder "ERROR" bei Fehler
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
    except (OSError, PermissionError) as e:
        log_error(f"Hash error for {path}: {e}")
        return "ERROR"
    return h.hexdigest()

class SyncWalker:
    """V3 IMPROVED: Better pattern matching for excludes."""
    def scan(self, root_path, exclude_patterns=None):
        """
        Scannt ein Verzeichnis und erstellt einen File-Tree.

        V3 NEW: Unterstützt glob-style Exclude-Patterns.

        Args:
            root_path: Wurzelverzeichnis zum Scannen
            exclude_patterns: Liste von Glob-Patterns (z.B. ["*.sqlite-wal", "__pycache__"])

        Returns:
            Dict mit relativem Pfad als Key und File-Metadaten als Value
            Format: {rel_path: {"mtime": float, "size": int, "abs_path": str}}
        """
        if exclude_patterns is None:
            exclude_patterns = []

        tree = {}
        if not os.path.exists(root_path):
            return tree

        for root, dirs, files in os.walk(root_path):
            # V3 FIX: Filter directories
            dirs[:] = [d for d in dirs if not self._should_exclude(d, exclude_patterns)]

            for f in files:
                # V3 FIX: Check exclude patterns
                if self._should_exclude(f, exclude_patterns):
                    continue

                abs_p = os.path.join(root, f)
                rel_p = os.path.relpath(abs_p, root_path)

                try:
                    stat = os.stat(abs_p)
                    tree[rel_p] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                        "abs_path": abs_p
                    }
                except OSError:
                    # File may have been deleted during scan
                    pass

        return tree

    def _should_exclude(self, name: str, patterns: list) -> bool:
        """
        Prüft ob eine Datei/Ordner ausgeschlossen werden soll.

        V3 NEW: Verwendet fnmatch für Glob-Pattern-Matching.

        Args:
            name: Datei- oder Ordnername (nicht vollständiger Pfad)
            patterns: Liste von Glob-Patterns (z.B. ["*.wal", "temp_*"])

        Returns:
            True wenn der Name auf ein Pattern matcht, sonst False
        """
        for pattern in patterns:
            if fnmatch(name, pattern):
                return True
        return False


class FileSyncWorker(QThread):
    """
    V3.1 NEW: Worker for single-file synchronization.

    Simplified logic:
    - Only syncs one file
    - Supports one-way mode
    - WAL checkpoint before sync
    - No directory scanning needed
    """

    progress = pyqtSignal(int, str)
    status = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.conn_id = cfg.get("id")
        self.is_killed = False
        self.is_paused = False

    def run(self):
        try:
            source_file = self.cfg.get("source_file", "")
            target_file = self.cfg.get("target_file", "")

            if not source_file or not target_file:
                self.error.emit("Quell- oder Ziel-Datei nicht angegeben")
                return

            # Check if source exists
            if not os.path.exists(source_file):
                self.error.emit(f"Quelldatei nicht gefunden: {source_file}")
                return

            filename = os.path.basename(source_file)
            self.status.emit(f"[{self.cfg.get('name')}] Bereite Sync vor...")

            # Step 1: WAL Checkpoint if needed
            if self.cfg.get("checkpoint_before_sync"):
                self.progress.emit(PROGRESS_CHECKPOINT, "checkpoint")
                self.status.emit(f"Checkpoint: {filename}")

                if DatabaseSafetyManager.checkpoint_sqlite_database(source_file):
                    self.status.emit(f"✓ Checkpoint erfolgreich: {filename}")
                else:
                    self.status.emit(f"⚠ Checkpoint fehlgeschlagen (Sync wird fortgesetzt)")

            if self.is_killed:
                return

            # Step 2: Create target directory
            self.progress.emit(PROGRESS_PREPARE, "prepare")
            target_dir = os.path.dirname(target_file)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)

            # Step 3: Copy file
            self.progress.emit(PROGRESS_COPY, "copy")
            self.status.emit(f"Kopiere: {filename}")

            try:
                shutil.copy2(source_file, target_file)
                self.status.emit(f"✓ Datei kopiert: {filename}")
            except (OSError, IOError, PermissionError, shutil.Error) as e:
                self.error.emit(f"Fehler beim Kopieren: {e}")
                return

            # Step 4: Verify
            self.progress.emit(PROGRESS_VERIFY, "verify")

            if os.path.exists(target_file):
                src_size = os.path.getsize(source_file)
                tgt_size = os.path.getsize(target_file)

                if src_size == tgt_size:
                    self.status.emit(f"✓ Verifizierung erfolgreich ({src_size:,} Bytes)")
                else:
                    self.error.emit(f"Größen stimmen nicht überein! ({src_size} vs {tgt_size})")
                    return

            # Done!
            self.progress.emit(PROGRESS_DONE, "done")
            self.status.emit(f"✓ Sync abgeschlossen: {filename}")
            self.finished.emit()

        except Exception as e:
            self.error.emit(f"Fehler: {str(e)}")

    def kill(self):
        """Stoppt den Worker sofort (bei nächster Prüfung)."""
        self.is_killed = True

    def pause(self):
        """Pausiert den Worker."""
        self.is_paused = True

    def resume(self):
        """Setzt den Worker fort."""
        self.is_paused = False

# ---------------- FOLDER SYNC WORKER (V3.1 IMPROVED) ----------------

class FolderSyncWorker(QThread):
    """
    V3.1 IMPROVED: Worker for folder synchronization.

    Now respects exclude_patterns for databases.
    """

    progress = pyqtSignal(int, str)
    status = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, cfg, db=None):
        super().__init__()
        self.cfg = cfg
        self.db = db  # Optional database for indexing
        self.conn_id = cfg.get("id")
        self.is_killed = False
        self.is_paused = False
        self._last_pct = -1

    def run(self):
        try:
            mode = self.cfg.get("mode", "two_way")
            conflict_policy = self.cfg.get("conflict_policy", "source")
            src_root = self.cfg["source"]
            tgt_root = self.cfg["target"]

            # V3.1: Get exclude patterns
            exclude_patterns = self.cfg.get("exclude_patterns", [])

            # 1. Scan
            self.status.emit(f"[{self.cfg['name']}] Scanne Quelle...")
            src_tree = SyncWalker().scan(src_root, exclude_patterns)

            tgt_tree = {}
            if mode != "index_only":
                self.status.emit(f"[{self.cfg['name']}] Scanne Ziel...")
                tgt_tree = SyncWalker().scan(tgt_root, exclude_patterns)

            # 2. Compare
            self.status.emit(f"[{self.cfg['name']}] Vergleiche...")
            all_files = set(src_tree.keys()) | set(tgt_tree.keys())
            actions = []

            for f in all_files:
                in_src = f in src_tree
                in_tgt = f in tgt_tree

                if in_src and not in_tgt:
                    if mode in ["mirror", "update", "two_way"]:
                        actions.append(("COPY_L2R", f))
                    elif mode == "index_only":
                        actions.append(("INDEX_SRC", f))

                elif in_tgt and not in_src:
                    if mode == "mirror":
                        actions.append(("DELETE_R", f))
                    elif mode == "two_way":
                        actions.append(("COPY_R2L", f))

                elif in_src and in_tgt:
                    s_meta = src_tree[f]
                    t_meta = tgt_tree[f]

                    if s_meta["size"] != t_meta["size"] or abs(s_meta["mtime"] - t_meta["mtime"]) > 1:
                        if mode == "mirror" or mode == "update":
                            actions.append(("COPY_L2R", f))
                        elif mode == "two_way":
                            if conflict_policy == "source":
                                actions.append(("COPY_L2R", f))
                            elif conflict_policy == "target":
                                actions.append(("COPY_R2L", f))
                            else:  # newest
                                if s_meta["mtime"] > t_meta["mtime"]:
                                    actions.append(("COPY_L2R", f))
                                else:
                                    actions.append(("COPY_R2L", f))
                    else:
                        if mode == "index_only":
                            actions.append(("INDEX_SRC", f))
                        else:
                            actions.append(("INDEX_BOTH", f))

            # 3. Execute
            total = len(actions)
            for i, (act, rel_path) in enumerate(actions):
                if self.is_killed:
                    break

                while self.is_paused:
                    if self.is_killed:
                        break
                    time.sleep(0.5)

                pct = int((i / max(1, total)) * 100)
                if pct != self._last_pct:
                    self.progress.emit(pct, "sync")
                    self._last_pct = pct

                s_abs = os.path.join(src_root, rel_path)
                t_abs = os.path.join(tgt_root, rel_path) if tgt_root else ""

                try:
                    if act == "COPY_L2R":
                        self.status.emit(f"Kopiere -> {rel_path}")
                        os.makedirs(os.path.dirname(t_abs), exist_ok=True)
                        shutil.copy2(s_abs, t_abs)
                        if self.db:
                            self._db_log(self.db, s_abs, "source")
                            self._db_log(self.db, t_abs, "target")

                    elif act == "COPY_R2L":
                        self.status.emit(f"Kopiere <- {rel_path}")
                        os.makedirs(os.path.dirname(s_abs), exist_ok=True)
                        shutil.copy2(t_abs, s_abs)
                        if self.db:
                            self._db_log(self.db, s_abs, "source")

                    elif act == "DELETE_R":
                        self.status.emit(f"Lösche Ziel: {rel_path}")
                        if os.path.exists(t_abs):
                            os.remove(t_abs)

                    elif act == "INDEX_SRC":
                        if self.db and os.path.exists(s_abs):
                            self._db_log(self.db, s_abs, "source")

                    elif act == "INDEX_BOTH":
                        if self.db:
                            if os.path.exists(s_abs):
                                self._db_log(self.db, s_abs, "source")
                            if t_abs and os.path.exists(t_abs):
                                self._db_log(self.db, t_abs, "target")

                except Exception as e:
                    log_error(f"Error {act} on {rel_path}: {e}")

            self.progress.emit(100, "done")
            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))

    def _db_log(self, db, path, side):
        """Log file version to database (if indexing enabled)."""
        if not db:
            return
        try:
            stat = os.stat(path)
            h = sha256_file(path)
            mtime_iso = datetime.fromtimestamp(stat.st_mtime).isoformat()
            fid = db.log_version(os.path.basename(path), path, mtime_iso,
                               stat.st_size, h, side)

            if self.cfg.get("structure", {}).get("auto_tags"):
                root = self.cfg.get(side)
                if root and path.startswith(root):
                    rel = os.path.relpath(path, root)
                    dirs = os.path.dirname(rel).split(os.sep)
                    for d in dirs:
                        if d and d != ".":
                            db.add_tag(fid, d)
        except (OSError, sqlite3.Error, ValueError) as e:
            log_error(f"DB logging error for {path}: {e}")

    def kill(self):
        """Stoppt den Worker sofort (bei nächster Prüfung)."""
        self.is_killed = True

    def pause(self):
        """Pausiert den Worker."""
        self.is_paused = True

    def resume(self):
        """Setzt den Worker fort."""
        self.is_paused = False
# ---------------- SCHEDULER ----------------
class ConnectionScheduler(QObject):
    """
    Verwaltet zeitgesteuerte automatische Synchronisationen.

    Nutzt QTimer um für jede Verbindung mit aktiviertem autosync
    periodisch das trigger_sync Signal zu emittieren. Die MainWindow
    führt dann die eigentliche Synchronisation durch.
    """

    trigger_sync = pyqtSignal(dict)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.timers = {}

    def update_all(self):
        """
        Aktualisiert die Timer für alle Verbindungen.

        Ruft update_connection() für jede gespeicherte Verbindung auf.
        """
        for conn in self.cfg.list_connections():
            self.update_connection(conn)

    def update_connection(self, conn):
        """
        Erstellt/aktualisiert den Timer für eine Verbindung.

        Entfernt alte Timer falls vorhanden. Erstellt neuen QTimer wenn
        autosync aktiviert ist mit dem konfigurierten Intervall.

        Args:
            conn: Connection-Dict mit autosync-Konfiguration
        """
        cid = conn["id"]
        if cid in self.timers:
            self.timers[cid].stop()
            del self.timers[cid]

        autosync = conn.get("autosync", {})
        if autosync.get("enabled", False):
            interval_min = autosync.get("interval_minutes", 15)
            timer = QTimer()
            timer.setSingleShot(False)
            timer.timeout.connect(lambda c=conn: self.trigger_sync.emit(c))
            timer.start(max(1, interval_min) * 60 * 1000)
            self.timers[cid] = timer

    def stop_all(self):
        """
        Stoppt alle laufenden Timer und löscht die Timer-Liste.

        Wird beim Beenden der Anwendung aufgerufen.
        """
        for t in self.timers.values():
            t.stop()
        self.timers.clear()

# ---------------- GUI ----------------
class ConnectionDialog(QDialog):
    """V3 IMPROVED: Integrated database safety scanner."""

    def __init__(self, parent=None, existing=None):
        super().__init__(parent)
        self.setWindowTitle("Synchronisierung einrichten")
        self.existing = existing
        self.resize(DIALOG_WIDTH, DIALOG_HEIGHT)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(existing["name"] if existing else "")
        self.source = QLineEdit(existing["source"] if existing else "")
        self.target = QLineEdit(existing["target"] if existing else "")

        self.mode = QComboBox()
        self.mode.addItems(["mirror", "update", "two_way", "index_only", "one_way"])  # V3: Added one_way
        if existing:
            self.mode.setCurrentText(existing.get("mode", "mirror"))
        self.mode.currentTextChanged.connect(self.on_mode_change)

        self.conflict = QComboBox()
        self.conflict.addItems(["source", "target", "newest"])  # V3: Changed order (source first)
        if existing:
            self.conflict.setCurrentText(existing.get("conflict_policy", "source"))

        btn_src = QPushButton("📂")
        btn_src.clicked.connect(lambda: self.pick(self.source))
        btn_tgt = QPushButton("📂")
        btn_tgt.clicked.connect(lambda: self.pick(self.target))

        h_src = QHBoxLayout()
        h_src.addWidget(self.source)
        h_src.addWidget(btn_src)

        h_tgt = QHBoxLayout()
        h_tgt.addWidget(self.target)
        h_tgt.addWidget(btn_tgt)

        form.addRow("Name der Aufgabe", self.name)
        form.addRow("Quelle", h_src)
        form.addRow("Ziel", h_tgt)
        form.addRow("Sync-Modus", self.mode)
        form.addRow("Bei Konflikt", self.conflict)

        # Indexierung optional machen
        self.chk_indexing = QCheckBox("Datenbank-Indexierung & Historie aktivieren")
        self.chk_indexing.setToolTip("Erstellt eine DB für Suche und Versionierung.")
        if existing:
            self.chk_indexing.setChecked(existing.get("indexing", True))
        else:
            self.chk_indexing.setChecked(True)
        self.chk_indexing.stateChanged.connect(self.on_indexing_change)
        form.addRow("", self.chk_indexing)

        self.chk_tags = QCheckBox("Auto-Tags aus Ordnernamen")
        if existing and "structure" in existing:
            self.chk_tags.setChecked(existing["structure"].get("auto_tags", True))
        else:
            self.chk_tags.setChecked(True)
        form.addRow("", self.chk_tags)

        self.db_container = QWidget()
        db_lay = QHBoxLayout(self.db_container)
        db_lay.setContentsMargins(0,0,0,0)
        self.db_path = QLineEdit(existing["db_path"] if existing else "")
        btn_db = QPushButton("💾")
        btn_db.clicked.connect(lambda: self.pick_file(self.db_path))
        db_lay.addWidget(self.db_path)
        db_lay.addWidget(btn_db)

        form.addRow("Datenbank-Datei", self.db_container)

        lay.addLayout(form)

        # V3 NEW: Database Safety Scanner
        lay.addWidget(self._create_safety_scanner())

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        # Initialize UI state
        self.on_mode_change(self.mode.currentText())
        self.on_indexing_change()

    def _create_safety_scanner(self):
        """Erstellt das Database Safety Scanner Widget."""
        safety_box = QWidget()
        safety_box.setStyleSheet(
            "background-color: #f0f0f0; border: 1px solid #ccc; "
            "border-radius: 4px; padding: 8px;"
        )
        safety_lay = QVBoxLayout(safety_box)

        lbl_safety_title = QLabel("<b>🛡️ Datenbank-Sicherheitsprüfung (V3)</b>")
        safety_lay.addWidget(lbl_safety_title)

        btn_scan = QPushButton("🔍 Quelle auf Datenbanken scannen")
        btn_scan.clicked.connect(self.scan_for_databases)
        safety_lay.addWidget(btn_scan)

        self.safety_info = QTextEdit()
        self.safety_info.setReadOnly(True)
        self.safety_info.setMaximumHeight(100)
        self.safety_info.setPlaceholderText(
            "Klicke 'Scannen' um Datenbanken zu erkennen und "
            "sichere Einstellungen zu erhalten."
        )
        safety_lay.addWidget(self.safety_info)

        return safety_box

    def scan_for_databases(self):
        """V3 NEW: Scan source directory for databases and show recommendations."""
        source = self.source.text().strip()
        if not source or not os.path.exists(source):
            self.safety_info.setText("⚠ Bitte gültiges Quellverzeichnis angeben!")
            return

        self.safety_info.setText("🔍 Scanne Verzeichnis...")
        QApplication.processEvents()

        # Scan for databases
        databases = DatabaseSafetyManager.scan_directory_for_databases(source)

        if not databases:
            self.safety_info.setText("✓ Keine Datenbanken gefunden.\nStandard-Einstellungen sind sicher.")
            return

        # Analyze databases
        has_wal = any(db["wal_mode"] or db["has_wal_files"] for db in databases)

        info_lines = [f"📊 {len(databases)} Datenbank(en) gefunden:\n"]

        for db in databases[:5]:  # Show max 5
            wal_status = "⚠ WAL" if db["wal_mode"] else "✓"
            info_lines.append(f"  {wal_status} {db['name']} ({db['size_mb']:.1f} MB)")

        if len(databases) > 5:
            info_lines.append(f"  ... und {len(databases) - 5} weitere")

        if has_wal:
            info_lines.append("\n🛡️ EMPFOHLENE EINSTELLUNGEN:")
            info_lines.append("  • Modus: one_way (statt two_way)")
            info_lines.append("  • Konflikt: source (statt newest)")
            info_lines.append("  • Auto-Sync: DEAKTIVIERT")
            info_lines.append("\nWAL-Dateien werden automatisch ausgeschlossen!")
        else:
            info_lines.append("\n✓ Keine WAL-Datenbanken.")
            info_lines.append("Standard-Einstellungen sind sicher.")

        self.safety_info.setText("\n".join(info_lines))

    def on_mode_change(self, txt):
        is_index_only = (txt == "index_only")
        self.target.setEnabled(not is_index_only)
        self.conflict.setEnabled(not is_index_only)
        if is_index_only:
            self.chk_indexing.setChecked(True)
            self.chk_indexing.setEnabled(False)
        else:
            self.chk_indexing.setEnabled(True)

    def on_indexing_change(self):
        enabled = self.chk_indexing.isChecked()
        self.db_container.setEnabled(enabled)
        self.chk_tags.setEnabled(enabled)

    def pick(self, line):
        d = QFileDialog.getExistingDirectory(self, "Ordner wählen")
        if d:
            line.setText(d)

    def pick_file(self, line):
        f, _ = QFileDialog.getSaveFileName(self, "DB speichern unter",
                                          "profiler.db", "SQLite (*.db)")
        if f:
            line.setText(f)

    def get_result(self):
        """V3 IMPROVED: Apply database safety settings automatically."""
        source = self.source.text()

        db = self.db_path.text()
        if self.chk_indexing.isChecked() and not db and source:
            db = os.path.join(source, "profiler_index.db")

        autosync = {"enabled": False, "interval_minutes": 15}
        if self.existing and "autosync" in self.existing:
            autosync = self.existing["autosync"]

        conn_config = {
            "id": self.existing["id"] if self.existing else f"conn-{uuid.uuid4().hex[:6]}",
            "name": self.name.text(),
            "source": source,
            "target": self.target.text(),
            "mode": self.mode.currentText(),
            "conflict_policy": self.conflict.currentText(),
            "indexing": self.chk_indexing.isChecked(),
            "db_path": db,
            "structure": {"auto_tags": self.chk_tags.isChecked()},
            "autosync": autosync,
            "exclude_patterns": self.existing.get("exclude_patterns", []) if self.existing else []
        }

        # V3.1 NEW: Apply database safety settings automatically (for folders)
        conn_config["type"] = ConnectionType.FOLDER
        self._apply_safety_settings(conn_config, source)
        return conn_config

    def _apply_safety_settings(self, conn_config, source):
        """Wendet automatische Datenbank-Sicherheitseinstellungen an."""
        if not source or not os.path.exists(source):
            return

        databases = DatabaseSafetyManager.scan_directory_for_databases(source)
        conn_config, warnings, excluded_dbs, was_changed = \
            DatabaseSafetyManager.apply_safe_settings_folder(conn_config, databases)

        if was_changed and warnings:
            self._show_safety_message(warnings, excluded_dbs)

    def _show_safety_message(self, warnings, excluded_dbs):
        """Zeigt Informationsnachricht über angewendete Sicherheitseinstellungen."""
        msg = "🛡️ Datenbank-Sicherheitseinstellungen wurden automatisch angewendet:\n\n"
        msg += "\n".join(warnings)

        if excluded_dbs:
            msg += f"\n\n{len(excluded_dbs)} Datenbank(en) wurden ausgeschlossen:"
            for db in excluded_dbs[:3]:  # Show first 3
                msg += f"\n  • {db['name']} ({db['size_mb']:.1f} MB)"
            if len(excluded_dbs) > 3:
                msg += f"\n  ... und {len(excluded_dbs) - 3} weitere"
            msg += "\n\n💡 Tipp: Erstelle Datei-Verbindungen für einzelne Datenbank-Backups"

        QMessageBox.information(self, "Sicherheitseinstellungen angewendet", msg)

# ---------------- FILE CONNECTION DIALOG (V3.1 NEW) ----------------
class FileConnectionDialog(QDialog):
    """V3.1 NEW: Dialog for single-file synchronization."""

    def __init__(self, parent=None, existing=None, suggested_file=None):
        super().__init__(parent)
        self.setWindowTitle("Datei synchronisieren")
        self.existing = existing
        self.resize(500, 450)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        # Name
        self.name = QLineEdit(existing["name"] if existing else "")
        form.addRow("Name der Aufgabe", self.name)

        # Source File
        self.source_file = QLineEdit(existing.get("source_file", suggested_file or "") if existing else (suggested_file or ""))
        btn_src = QPushButton("📄")
        btn_src.clicked.connect(lambda: self.pick_file(self.source_file, "Quelldatei wählen"))
        h_src = QHBoxLayout()
        h_src.addWidget(self.source_file)
        h_src.addWidget(btn_src)
        form.addRow("Quelldatei", h_src)

        # Target File
        self.target_file = QLineEdit(existing.get("target_file", "") if existing else "")
        btn_tgt = QPushButton("📄")
        btn_tgt.clicked.connect(lambda: self.pick_file(self.target_file, "Zieldatei wählen"))
        h_tgt = QHBoxLayout()
        h_tgt.addWidget(self.target_file)
        h_tgt.addWidget(btn_tgt)
        form.addRow("Zieldatei", h_tgt)

        # Mode (for files, usually one-way)
        self.mode = QComboBox()
        self.mode.addItems(["one_way", "two_way"])
        if existing:
            self.mode.setCurrentText(existing.get("mode", "one_way"))
        form.addRow("Sync-Modus", self.mode)

        # Checkpoint option
        self.chk_checkpoint = QCheckBox("WAL-Checkpoint vor Sync (für SQLite)")
        if existing:
            self.chk_checkpoint.setChecked(existing.get("checkpoint_before_sync", False))
        form.addRow("", self.chk_checkpoint)

        lay.addLayout(form)

        # Safety info box
        safety_box = QWidget()
        safety_box.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 4px; padding: 8px;")
        safety_lay = QVBoxLayout(safety_box)

        lbl_safety = QLabel("<b>🛡️ Datei-Sicherheit (V3.1)</b>")
        safety_lay.addWidget(lbl_safety)

        self.safety_info = QTextEdit()
        self.safety_info.setReadOnly(True)
        self.safety_info.setMaximumHeight(120)
        self.safety_info.setPlaceholderText("Datei-Synchronisierung ist ideal für Datenbanken.\nWAL-Dateien werden automatisch übersprungen.")
        safety_lay.addWidget(self.safety_info)

        # Auto-analyze button
        btn_analyze = QPushButton("🔍 Datei analysieren")
        btn_analyze.clicked.connect(self.analyze_file)
        safety_lay.addWidget(btn_analyze)

        lay.addWidget(safety_box)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        # Auto-analyze if suggested file provided
        if suggested_file and os.path.exists(suggested_file):
            QTimer.singleShot(100, self.analyze_file)

    def pick_file(self, line, title):
        """Pick a file (not folder)."""
        f, _ = QFileDialog.getOpenFileName(self, title)
        if f:
            line.setText(f)
            # Auto-set target if source was picked
            if line == self.source_file and not self.target_file.text():
                # Suggest target path
                source_dir = os.path.dirname(f)
                filename = os.path.basename(f)
                # Could suggest network path here
                self.target_file.setText(f"[Ziel-Pfad für {filename}]")

    def analyze_file(self):
        """Analyze source file and show recommendations."""
        source_file = self.source_file.text().strip()
        if not source_file or not os.path.exists(source_file):
            self.safety_info.setText("⚠ Bitte gültige Quelldatei angeben!")
            return

        filename = os.path.basename(source_file)
        info_lines = [f"📄 Datei: {filename}\n"]

        # Check if database
        if DatabaseSafetyManager.is_database_file(source_file):
            db_type = "unbekannt"
            wal_mode = False
            size_mb = 0

            try:
                size_mb = os.path.getsize(source_file) / (1024 * 1024)
                info_lines.append(f"Größe: {size_mb:.1f} MB")
            except OSError:
                # File may not exist or is inaccessible
                pass

            # SQLite check
            if DatabaseSafetyManager.is_sqlite_database(source_file):
                db_type = "SQLite"
                wal_mode = DatabaseSafetyManager.check_wal_mode(source_file)

                if wal_mode:
                    info_lines.append(f"Typ: {db_type} (WAL-Modus ⚠)")
                    info_lines.append("\n🛡️ EMPFEHLUNGEN:")
                    info_lines.append("  • Modus: one_way")
                    info_lines.append("  • WAL-Checkpoint: AKTIVIERT")
                    info_lines.append("\n✓ WAL-Dateien werden automatisch übersprungen")

                    # Auto-apply settings
                    self.mode.setCurrentText("one_way")
                    self.chk_checkpoint.setChecked(True)
                else:
                    info_lines.append(f"Typ: {db_type} (Journal-Modus ✓)")
                    info_lines.append("\n✓ Sicher für Sync")

            elif source_file.endswith(('.mdb', '.accdb')):
                db_type = "MS Access"
                info_lines.append(f"Typ: {db_type}")
                info_lines.append("\n💡 Empfehlung: one_way Modus")
                self.mode.setCurrentText("one_way")

            else:
                info_lines.append("Typ: Datenbank (erkannt)")
        else:
            info_lines.append("Typ: Reguläre Datei")
            info_lines.append("\n✓ Kann two_way synchronisiert werden")

        self.safety_info.setText("\n".join(info_lines))

        # Auto-set name if empty
        if not self.name.text():
            base_name = os.path.splitext(filename)[0]
            self.name.setText(f"{base_name} - Backup")

    def get_result(self):
        """Return file connection configuration."""
        source_file = self.source_file.text()
        target_file = self.target_file.text()

        conn_config = {
            "id": self.existing["id"] if self.existing else f"conn-{uuid.uuid4().hex[:6]}",
            "type": ConnectionType.FILE,  # V3.1: Mark as FILE connection
            "name": self.name.text(),
            "source_file": source_file,
            "target_file": target_file,
            "mode": self.mode.currentText(),
            "checkpoint_before_sync": self.chk_checkpoint.isChecked(),
            "autosync": self.existing.get("autosync", {"enabled": False, "interval_minutes": 15}) if self.existing else {"enabled": False}
        }

        # V3.1: Apply file safety settings
        if source_file and os.path.exists(source_file):
            conn_config, warnings, was_changed = DatabaseSafetyManager.apply_safe_settings_file(conn_config)

            if was_changed and warnings:
                msg = "🛡️ Sicherheitseinstellungen wurden automatisch angewendet:\n\n"
                msg += "\n".join(warnings)
                QMessageBox.information(self, "Sicherheitseinstellungen", msg)

        return conn_config

class MainWindow(QMainWindow):
    # V3.2 NEW: Notification-Typen für Toast-System
    class NotificationType:
        INFO = QSystemTrayIcon.MessageIcon.Information
        SUCCESS = QSystemTrayIcon.MessageIcon.Information  # Windows hat kein Success
        WARNING = QSystemTrayIcon.MessageIcon.Warning
        ERROR = QSystemTrayIcon.MessageIcon.Critical
    
    def __init__(self, cfg):
        super().__init__()
        self.setWindowTitle("ProSync V3.2 - Sync & Index mit DB-Sicherheit")  # V3.2: Toast-Notifications
        self.resize(900, 600)
        self.cfg = cfg
        self.worker = None

        self.scheduler = ConnectionScheduler(cfg)
        self.scheduler.trigger_sync.connect(self.on_auto_sync_triggered)

        self.tray_icon = QSystemTrayIcon(self)
        self.setup_tray_icon()

        tray_menu = QMenu()
        act_show = tray_menu.addAction("Öffnen")
        act_show.triggered.connect(self.show_and_raise)

        if HAS_WINREG:
            act_autostart = QAction("Mit Windows starten", self)
            act_autostart.setCheckable(True)
            act_autostart.setChecked(AutostartManager.is_autostart_enabled())
            act_autostart.triggered.connect(self.toggle_autostart)
            tray_menu.addAction(act_autostart)

        tray_menu.addSeparator()
        act_quit = tray_menu.addAction("Beenden")
        act_quit.triggered.connect(self.force_quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_click)
        self.tray_icon.show()

        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)

        toolbar_lay = QHBoxLayout()

        # V3.1 NEW: Menu button for adding connections
        btn_add = QPushButton("➕ Neue Aufgabe")
        add_menu = QMenu(self)
        act_folder = add_menu.addAction("📁 Ordner synchronisieren")
        act_folder.triggered.connect(self.add_folder_connection)
        act_file = add_menu.addAction("📄 Datei synchronisieren")
        act_file.triggered.connect(self.add_file_connection)
        btn_add.setMenu(add_menu)

        # V3 NEW: Database audit button
        btn_audit = QPushButton("🛡️ Sicherheitsprüfung")
        btn_audit.setToolTip("Prüfe alle Verbindungen auf Datenbank-Sicherheit")
        btn_audit.clicked.connect(self.audit_all_connections)

        empty = QWidget()
        empty.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.btn_search = QPushButton("🔍 Datenbank durchsuchen")
        self.btn_search.clicked.connect(self.open_reader)

        toolbar_lay.addWidget(btn_add)
        toolbar_lay.addWidget(btn_audit)  # V3 NEW
        toolbar_lay.addWidget(empty)
        toolbar_lay.addWidget(self.btn_search)
        main_lay.addLayout(toolbar_lay)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.itemClicked.connect(self.on_item_select)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.open_context_menu)

        right_panel = QWidget()
        r_lay = QVBoxLayout(right_panel)
        self.lbl_info = QLabel("Wähle eine Aufgabe...")
        self.lbl_info.setStyleSheet("font-weight: bold; font-size: 14px;")

        ctrl_lay = QHBoxLayout()
        self.btn_run = QPushButton("▶ Start Sync")
        self.btn_run.clicked.connect(self.start_sync)
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)
        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.clicked.connect(self.stop_worker)
        self.btn_stop.setEnabled(False)
        ctrl_lay.addWidget(self.btn_run)
        ctrl_lay.addWidget(self.btn_pause)
        ctrl_lay.addWidget(self.btn_stop)

        self.progress = QProgressBar()
        self.lbl_status = QLabel("Bereit")
        self.lbl_status.setWordWrap(True)
        r_lay.addWidget(self.lbl_info)
        r_lay.addLayout(ctrl_lay)
        r_lay.addWidget(self.progress)
        r_lay.addWidget(self.lbl_status)
        r_lay.addStretch()

        splitter.addWidget(self.list)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 2)
        main_lay.addWidget(splitter)

        self.populate_list()
        self.scheduler.update_all()

    def setup_tray_icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ICO_TRAY.ico")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon)
            )
        self.tray_icon.setToolTip("ProSync V3.2 - Läuft im Hintergrund")

    # ============ V3.2 NEW: TOAST-NOTIFICATION SYSTEM ============
    def notify(self, title: str, message: str, 
               msg_type: QSystemTrayIcon.MessageIcon = None,
               duration_ms: int = 3000):
        """
        V3.2 NEW: Zentrale Toast-Notification Methode.
        
        Args:
            title: Titel der Benachrichtigung
            message: Nachrichtentext
            msg_type: Info/Warning/Critical (default: Info)
            duration_ms: Anzeigedauer in ms (default: 3000)
        """
        # Prüfe ob Notifications aktiviert sind
        app_settings = self.cfg.data.get("app", {})
        if not app_settings.get("notifications_enabled", True):
            return
        
        if msg_type is None:
            msg_type = self.NotificationType.INFO
        
        if self.tray_icon.isVisible():
            self.tray_icon.showMessage(title, message, msg_type, duration_ms)
    
    def notify_sync_started(self, conn_name: str):
        """V3.2: Benachrichtigung bei Sync-Start."""
        self.notify("ProSync", f"▶ Sync gestartet: {conn_name}", 
                   self.NotificationType.INFO, 2000)
    
    def notify_sync_finished(self, conn_name: str, success: bool = True):
        """V3.2: Benachrichtigung bei Sync-Ende."""
        if success:
            self.notify("ProSync", f"✓ Sync abgeschlossen: {conn_name}",
                       self.NotificationType.SUCCESS, 3000)
        else:
            self.notify("ProSync", f"⚠ Sync fehlgeschlagen: {conn_name}",
                       self.NotificationType.ERROR, 5000)
    
    def notify_error(self, message: str):
        """V3.2: Fehler-Benachrichtigung."""
        self.notify("ProSync - Fehler", message, 
                   self.NotificationType.ERROR, 5000)
    
    def notify_auto_sync(self, conn_name: str):
        """V3.2: Benachrichtigung bei Auto-Sync."""
        self.notify("ProSync [Auto]", f"⏰ Starte automatischen Sync: {conn_name}",
                   self.NotificationType.INFO, 2000)
    # ============ END TOAST-NOTIFICATION SYSTEM ============

    def toggle_autostart(self, checked):
        if AutostartManager.set_autostart(checked):
            self.lbl_status.setText(f"Autostart {'aktiviert' if checked else 'deaktiviert'}")
        else:
            QMessageBox.warning(self, "Fehler",
                              "Autostart konnte nicht geändert werden (Rechte?).")

    def populate_list(self):
        self.list.clear()
        for c in self.cfg.list_connections():
            auto_txt = " [Auto]" if c.get("autosync", {}).get("enabled") else ""

            # V3 NEW: Show safety status
            safety_txt = ""
            if c.get("_safety_analysis", {}).get("auto_configured"):
                safety_txt = " 🛡️"

            # V3.1 NEW: Show connection type icon
            conn_type = c.get("type", ConnectionType.FOLDER)
            type_icon = "📄" if conn_type == ConnectionType.FILE else "📁"

            item = QListWidgetItem(f"{type_icon} {c['name']}{auto_txt}{safety_txt}")

            # V3.1: Different tooltip for file vs folder
            if conn_type == ConnectionType.FILE:
                src = c.get("source_file", "?")
                tgt = c.get("target_file", "?")
                item.setToolTip(f"[FILE] {src} -> {tgt} ({c.get('mode', 'one_way')})")
            else:
                src = c.get("source", "?")
                tgt = c.get("target", "?")
                item.setToolTip(f"[FOLDER] {src} -> {tgt} ({c.get('mode', 'two_way')})")

            item.setData(Qt.ItemDataRole.UserRole, c)
            self.list.addItem(item)

    def add_folder_connection(self):
        """V3.1: Add folder connection."""
        dlg = ConnectionDialog(self)
        if dlg.exec():
            self.cfg.add_or_update_connection(dlg.get_result())
            self.scheduler.update_all()
            self.populate_list()

    def add_file_connection(self):
        """V3.1 NEW: Add file connection."""
        dlg = FileConnectionDialog(self)
        if dlg.exec():
            self.cfg.add_or_update_connection(dlg.get_result())
            self.scheduler.update_all()
            self.populate_list()

    def on_item_select(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        conn_type = data.get("type", ConnectionType.FOLDER)

        # V3.1: Different info display for FILE vs FOLDER
        if conn_type == ConnectionType.FILE:
            # File connection info
            checkpoint_txt = " [Checkpoint: AN]" if data.get("checkpoint_before_sync") else ""
            safety_info = ""

            if "_file_analysis" in data:
                fa = data["_file_analysis"]
                db_type = fa.get("type", "unknown")
                size_mb = fa.get("size_mb", 0)
                wal_mode = fa.get("wal_mode", False)
                wal_txt = " (WAL)" if wal_mode else ""
                safety_info = f"\n🛡️ Typ: {db_type}{wal_txt}, {size_mb:.1f} MB"

            self.lbl_info.setText(
                f"📄 {data['name']} [{data.get('mode', 'one_way').upper()}]{checkpoint_txt}{safety_info}\n"
                f"Src: {data.get('source_file', '?')}\n"
                f"Tgt: {data.get('target_file', '?')}"
            )
        else:
            # Folder connection info
            idx_txt = " [Index: AN]" if data.get("indexing", True) else " [Index: AUS]"

            # V3 NEW: Show safety info
            safety_info = ""
            if "_safety_analysis" in data:
                sa = data["_safety_analysis"]
                excluded = sa.get("excluded_databases", 0)
                if excluded > 0:
                    safety_info = f"\n🛡️ {excluded} DB(s) ausgeschlossen, {sa.get('databases_found', 0)} total"
                else:
                    safety_info = f"\n🛡️ {sa.get('databases_found', 0)} DB(s) gefunden"

            self.lbl_info.setText(
                f"📁 {data['name']} [{data.get('mode', 'two_way').upper()}]{idx_txt}{safety_info}\n"
                f"Src: {data.get('source', '?')}\n"
                f"Tgt: {data.get('target', '?')}"
            )

        is_running = bool(self.worker and self.worker.isRunning())
        is_this_task_running = is_running and (self.worker.conn_id == data['id'])
        self.btn_run.setEnabled(not is_running)
        self.btn_pause.setEnabled(is_this_task_running)
        self.btn_stop.setEnabled(is_this_task_running)
        if is_this_task_running and self.worker.is_paused:
            self.btn_pause.setText("▶ Fortsetzen")
        else:
            self.btn_pause.setText("⏸ Pause")

    def start_sync(self):
        item = self.list.currentItem()
        if not item:
            return
        self.run_sync_logic(item.data(Qt.ItemDataRole.UserRole))

    def run_sync_logic(self, conn_data):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "Beschäftigt",
                              "Es läuft bereits ein Synchronisationsvorgang.")
            return

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ Pause")
        
        # V3.2 NEW: Toast bei Sync-Start
        self.notify_sync_started(conn_data.get("name", "Unbekannt"))

        # V3.1 NEW: Select worker based on connection type
        conn_type = conn_data.get("type", ConnectionType.FOLDER)

        if conn_type == ConnectionType.FILE:
            # File sync worker (no database indexing)
            self.worker = FileSyncWorker(conn_data)
        else:
            # Folder sync worker (with optional database)
            db = None
            if conn_data.get("indexing") and conn_data.get("db_path"):
                try:
                    db = ConnectionDB(conn_data["db_path"])
                except Exception as e:
                    log_warning(f"Warning: Could not open indexing database: {e}")

            self.worker = FolderSyncWorker(conn_data, db)

        self.worker.progress.connect(self.progress.setValue)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.finished.connect(self.worker_finished)
        # V3.2 CHANGED: Error-Handler mit Notification
        self.worker.error.connect(self._handle_worker_error)
        self.worker.start()

    def _handle_worker_error(self, error_msg: str):
        """V3.2 NEW: Zentraler Error-Handler mit Notification."""
        QMessageBox.critical(self, "Fehler", error_msg)
        self.notify_error(error_msg[:100])  # Kürzen für Toast
        # Buttons zurücksetzen
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)

    def toggle_pause(self):
        if self.worker and self.worker.isRunning():
            if self.worker.is_paused:
                self.worker.resume()
                self.btn_pause.setText("⏸ Pause")
                self.lbl_status.setText(f"[{self.worker.cfg['name']}] Fahre fort...")
            else:
                self.worker.pause()
                self.btn_pause.setText("▶ Fortsetzen")
                self.lbl_status.setText(f"[{self.worker.cfg['name']}] Pausiert")

    def on_auto_sync_triggered(self, conn):
        if self.worker is not None and self.worker.isRunning():
            return
        self.lbl_status.setText(f"[Auto] Starte Sync für {conn['name']}...")
        # V3.2 NEW: Toast bei Auto-Sync
        self.notify_auto_sync(conn.get("name", "Unbekannt"))
        self.run_sync_logic(conn)

    def stop_worker(self):
        if self.worker:
            self.worker.kill()
            self.lbl_status.setText("Breche ab...")

    def worker_finished(self):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Pause")
        self.progress.setValue(100)
        self.lbl_status.setText("Fertig.")
        # V3.2 CHANGED: Verwende zentrale Notification-Methode
        conn_name = self.worker.cfg.get("name", "Sync") if self.worker else "Sync"
        self.notify_sync_finished(conn_name, success=True)
        self.worker = None

    def audit_all_connections(self):
        """V3 NEW: Audit all connections for database safety."""
        connections = self.cfg.list_connections()
        if not connections:
            QMessageBox.information(self, "Sicherheitsprüfung",
                                  "Keine Verbindungen konfiguriert.")
            return

        results = []
        fixed_count = 0

        for conn in connections:
            conn_type = conn.get("type", ConnectionType.FOLDER)

            if conn_type == ConnectionType.FILE:
                # File connections - check file safety
                updated_conn, warnings, was_changed = DatabaseSafetyManager.apply_safe_settings_file(
                    conn.copy()
                )

                if was_changed:
                    self.cfg.add_or_update_connection(updated_conn)
                    fixed_count += 1
                    results.append(f"✓ {conn['name']} [FILE]: {len(warnings)} Änderung(en)")
                    for w in warnings:
                        results.append(f"  - {w}")
                else:
                    results.append(f"✓ {conn['name']} [FILE]: Bereits sicher konfiguriert")

            else:
                # Folder connections - check for databases
                source = conn.get("source", "")
                if not source or not os.path.exists(source):
                    continue

                databases = DatabaseSafetyManager.scan_directory_for_databases(source)

                if databases:
                    # Apply safe settings
                    updated_conn, warnings, excluded_dbs, was_changed = DatabaseSafetyManager.apply_safe_settings_folder(
                        conn.copy(), databases
                    )

                    if was_changed:
                        # Update configuration
                        self.cfg.add_or_update_connection(updated_conn)
                        fixed_count += 1
                        results.append(f"✓ {conn['name']}: {len(warnings)} Änderung(en)")
                        for w in warnings:
                            results.append(f"  - {w}")
                    else:
                        results.append(f"✓ {conn['name']}: Bereits sicher konfiguriert")

        if results:
            msg = f"🛡️ Sicherheitsprüfung abgeschlossen\n\n"
            if fixed_count > 0:
                msg += f"{fixed_count} Verbindung(en) wurden aktualisiert:\n\n"
            msg += "\n".join(results)
            QMessageBox.information(self, "Sicherheitsprüfung", msg)

            # Refresh UI
            self.populate_list()
            self.scheduler.update_all()
        else:
            QMessageBox.information(self, "Sicherheitsprüfung",
                                  "Keine Datenbanken in konfigurierten Quellen gefunden.")

    def open_context_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return

        conn = item.data(Qt.ItemDataRole.UserRole)
        autosync = conn.get("autosync", {"enabled": False, "interval_minutes": 15})

        menu = QMenu()
        act_edit = menu.addAction("Bearbeiten")
        act_del = menu.addAction("Löschen")
        menu.addSeparator()

        act_auto = QAction("Automatisch ausführen", self)
        act_auto.setCheckable(True)
        act_auto.setChecked(autosync.get("enabled", False))
        menu.addAction(act_auto)

        interval_menu = menu.addMenu("Intervall")
        group = QActionGroup(self)
        current_int = autosync.get("interval_minutes", 15)
        for mins in [5, 15, 30, 60, 120]:
            act_int = QAction(f"Alle {mins} Minuten", self)
            act_int.setCheckable(True)
            act_int.setData(mins)
            if mins == current_int:
                act_int.setChecked(True)
            group.addAction(act_int)
            interval_menu.addAction(act_int)

        res = menu.exec(self.list.viewport().mapToGlobal(pos))

        if res == act_del:
            if self.worker and self.worker.isRunning() and self.worker.conn_id == conn['id']:
                return
            if QMessageBox.question(self, "Löschen", "Aufgabe löschen?") == QMessageBox.StandardButton.Yes:
                self.cfg.remove_connection(conn['id'])
                self.scheduler.update_all()
                self.populate_list()

        elif res == act_edit:
            dlg = ConnectionDialog(self, existing=conn)
            if dlg.exec():
                self.cfg.add_or_update_connection(dlg.get_result())
                self.scheduler.update_all()
                self.populate_list()

        elif res == act_auto:
            conn["autosync"] = conn.get("autosync", {})
            conn["autosync"]["enabled"] = act_auto.isChecked()
            self.cfg.add_or_update_connection(conn)
            self.scheduler.update_connection(conn)
            self.populate_list()

        elif res in group.actions():
            conn["autosync"] = conn.get("autosync", {})
            conn["autosync"]["interval_minutes"] = res.data()
            conn["autosync"]["enabled"] = True
            self.cfg.add_or_update_connection(conn)
            self.scheduler.update_connection(conn)
            self.populate_list()

    def open_reader(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        reader_path = os.path.join(script_dir, "ProSyncReader.py")
        if os.path.exists(reader_path):
            if sys.platform == "win32":
                subprocess.Popen([sys.executable, reader_path],
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen([sys.executable, reader_path])
        else:
            QMessageBox.warning(self, "Nicht gefunden",
                              "ProSyncReader.py nicht gefunden.")

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            # V3.2 CHANGED: Verwende zentrale Notification-Methode
            self.notify("ProSync", "Läuft im Hintergrund weiter. Doppelklick auf Tray-Icon zum Öffnen.",
                       self.NotificationType.INFO, 2500)
            event.ignore()
        else:
            event.accept()

    def show_and_raise(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_and_raise()

    def force_quit(self):
        self.scheduler.stop_all()
        QApplication.quit()

def main() -> None:
    """
    Haupteinstiegspunkt der ProSync-Anwendung.

    Initialisiert QApplication, ConfigManager und MainWindow.
    Verhindert mehrere Instanzen über QLockFile.
    """
    app = QApplication(sys.argv)
    lock_file = QLockFile(QDir.temp().filePath("prosync.lock"))
    if not lock_file.tryLock(100):
        sys.exit(0)

    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")

    cfg = ConfigManager(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ProSync_config.json")
    )

    win = MainWindow(cfg)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
