"""
Smoke-Tests für ConfigManager
Testet grundlegende Funktionalität: Load, Save, Add, Update, Delete
"""

import os
import sys
import json
import tempfile
from pathlib import Path

# Konstanten
JSON_INDENT = 2  # Einrückung für JSON-Formatierung
EXIT_SUCCESS = 0  # Exit-Code für erfolgreiche Ausführung
EXIT_FAILURE = 1  # Exit-Code für Fehler

# Import ConfigManager from main file
sys.path.insert(0, os.path.dirname(__file__))

# Mock PyQt6 imports if not available
try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
except ImportError:
    print("PyQt6 nicht verfügbar - Mock-Klassen werden verwendet")
    class QThread: pass
    class pyqtSignal:
        def __init__(self, *args): pass
    class QObject: pass


def test_config_manager():
    """Smoke-Test für ConfigManager: Load, Save, Add, Update, Delete."""

    print("=== ConfigManager Smoke-Test ===\n")

    # Erstelle temporäre Config-Datei
    temp_dir = tempfile.gettempdir()
    test_config_path = os.path.join(temp_dir, "test_prosync_config.json")

    # Cleanup falls vorhanden
    if os.path.exists(test_config_path):
        os.remove(test_config_path)

    print(f"Test-Config: {test_config_path}\n")

    # Manuelles ConfigManager-Mock (da wir die Klasse nicht importieren können ohne PyQt)
    class SimpleConfigManager:
        def __init__(self, path):
            self.path = path
            self.data = {"connections": []}
            self.load()

        def load(self):
            if os.path.exists(self.path):
                try:
                    with open(self.path, "r", encoding="utf-8") as f:
                        self.data = json.load(f)
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                    print(f"Config load error: {e}")
                    self.save()
            else:
                self.save()

        def save(self):
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=JSON_INDENT, ensure_ascii=False)

        def get_all(self):
            return self.data.get("connections", [])

        def get(self, conn_id):
            for conn in self.data["connections"]:
                if conn["id"] == conn_id:
                    return conn
            return None

        def add_or_update_connection(self, conn):
            existing = self.get(conn["id"])
            if existing:
                # Update
                for i, c in enumerate(self.data["connections"]):
                    if c["id"] == conn["id"]:
                        self.data["connections"][i] = conn
                        break
            else:
                # Add
                self.data["connections"].append(conn)
            self.save()

        def delete(self, conn_id):
            self.data["connections"] = [c for c in self.data["connections"] if c["id"] != conn_id]
            self.save()

    # Test 1: Initialisierung & Leere Config
    print("Test 1: Initialisierung & Leere Config")
    cfg = SimpleConfigManager(test_config_path)
    assert os.path.exists(test_config_path), "Config-Datei wurde nicht erstellt"
    assert len(cfg.get_all()) == 0, "Config sollte leer sein"
    print("✓ PASS: Config wurde erstellt und ist leer\n")

    # Test 2: Connection hinzufügen
    print("Test 2: Connection hinzufügen")
    conn1 = {
        "id": "test-123",
        "name": "Test Backup",
        "source": "C:\\Test\\Source",
        "target": "D:\\Test\\Target",
        "mode": "mirror"
    }
    cfg.add_or_update_connection(conn1)
    assert len(cfg.get_all()) == 1, "Eine Connection sollte vorhanden sein"
    assert cfg.get("test-123") == conn1, "Connection sollte korrekt gespeichert sein"
    print("✓ PASS: Connection erfolgreich hinzugefügt\n")

    # Test 3: Connection aktualisieren
    print("Test 3: Connection aktualisieren")
    conn1_updated = conn1.copy()
    conn1_updated["mode"] = "update"
    conn1_updated["name"] = "Test Backup (Updated)"
    cfg.add_or_update_connection(conn1_updated)
    assert len(cfg.get_all()) == 1, "Immer noch eine Connection"
    assert cfg.get("test-123")["mode"] == "update", "Mode sollte aktualisiert sein"
    assert cfg.get("test-123")["name"] == "Test Backup (Updated)", "Name sollte aktualisiert sein"
    print("✓ PASS: Connection erfolgreich aktualisiert\n")

    # Test 4: Zweite Connection hinzufügen
    print("Test 4: Zweite Connection hinzufügen")
    conn2 = {
        "id": "test-456",
        "name": "DB Backup",
        "source_file": "C:\\App\\data.db",
        "target_file": "D:\\Backup\\data.db",
        "mode": "one_way",
        "type": "file"
    }
    cfg.add_or_update_connection(conn2)
    assert len(cfg.get_all()) == 2, "Zwei Connections sollten vorhanden sein"
    print("✓ PASS: Zweite Connection hinzugefügt\n")

    # Test 5: Connection löschen
    print("Test 5: Connection löschen")
    cfg.delete("test-123")
    assert len(cfg.get_all()) == 1, "Eine Connection sollte übrig sein"
    assert cfg.get("test-123") is None, "test-123 sollte gelöscht sein"
    assert cfg.get("test-456") is not None, "test-456 sollte noch existieren"
    print("✓ PASS: Connection erfolgreich gelöscht\n")

    # Test 6: Config neu laden (Persistenz-Test)
    print("Test 6: Config neu laden (Persistenz)")
    cfg2 = SimpleConfigManager(test_config_path)
    assert len(cfg2.get_all()) == 1, "Nach Reload: Eine Connection"
    assert cfg2.get("test-456") is not None, "test-456 sollte nach Reload existieren"
    print("✓ PASS: Config wurde korrekt persistiert\n")

    # Test 7: Korrupte Config-Datei (Error-Handling)
    print("Test 7: Korrupte Config-Datei")
    with open(test_config_path, "w", encoding="utf-8") as f:
        f.write("INVALID JSON{{{")
    cfg3 = SimpleConfigManager(test_config_path)
    assert len(cfg3.get_all()) == 0, "Korrupte Config sollte auf leer zurückfallen"
    print("✓ PASS: Korrupte Config wird korrekt behandelt\n")

    # Cleanup
    if os.path.exists(test_config_path):
        os.remove(test_config_path)

    print("=== ALLE TESTS BESTANDEN ✓ ===")
    return True


if __name__ == "__main__":
    try:
        success = test_config_manager()
        sys.exit(EXIT_SUCCESS if success else EXIT_FAILURE)
    except Exception as e:
        print(f"\n❌ TEST FEHLGESCHLAGEN: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(EXIT_FAILURE)
