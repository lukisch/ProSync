"""
Smoke-Test für Sync-Worker und Utility-Funktionen
Testet Hilfsfunktionen die von FileSyncWorker und FolderSyncWorker verwendet werden
"""

import os
import sys
import tempfile
from pathlib import Path

# Import der zu testenden Funktionen
sys.path.insert(0, os.path.dirname(__file__))

# Mock PyQt6 falls nicht verfügbar
try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QCoreApplication
    HAS_PYQT = True
except ImportError:
    print("PyQt6 nicht verfügbar - limitierte Tests")
    HAS_PYQT = False

# Importiere Module
import importlib.util
spec = importlib.util.spec_from_file_location(
    "prosync",
    os.path.join(os.path.dirname(__file__), "ProSyncStart_V3.1.py")
)
prosync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prosync)

sha256_file = prosync.sha256_file


def main():
    print("=== Sync Worker Utility Functions Smoke-Test ===\n")

    try:
        # Temporäres Verzeichnis für Tests
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Test 1: sha256_file Funktion
            print("Test 1: sha256_file")
            test_file = test_dir / "test.txt"
            test_file.write_text("Hello World")

            hash1 = sha256_file(str(test_file))
            assert hash1 != "ERROR"
            assert len(hash1) == 64  # SHA256 hash ist 64 Zeichen lang
            print(f"✓ PASS: sha256_file funktioniert (Hash: {hash1[:16]}...)\n")

            # Test 2: sha256_file konsistent
            print("Test 2: sha256_file Konsistenz")
            hash2 = sha256_file(str(test_file))
            assert hash1 == hash2
            print("✓ PASS: Gleiche Datei produziert gleichen Hash\n")

            # Test 3: sha256_file unterschiedliche Dateien
            print("Test 3: sha256_file für unterschiedliche Dateien")
            test_file2 = test_dir / "test2.txt"
            test_file2.write_text("Different Content")

            hash3 = sha256_file(str(test_file2))
            assert hash3 != hash1
            print("✓ PASS: Unterschiedliche Dateien haben unterschiedliche Hashes\n")

            # Test 4: sha256_file für nicht-existente Datei
            print("Test 4: sha256_file für nicht-existente Datei")
            hash_error = sha256_file("nonexistent.txt")
            assert hash_error == "ERROR"
            print("✓ PASS: Nicht-existente Datei gibt ERROR zurück\n")

            # Test 5: sha256_file für große Datei (chunk-basiertes Lesen)
            print("Test 5: sha256_file für große Datei")
            large_file = test_dir / "large.bin"
            # Erstelle 5MB Datei
            with open(large_file, 'wb') as f:
                f.write(b'x' * (5 * 1024 * 1024))

            hash_large = sha256_file(str(large_file))
            assert hash_large != "ERROR"
            assert len(hash_large) == 64
            print("✓ PASS: Große Datei (5MB) wird korrekt gehasht\n")

            # Test 6: Worker-Klassen existieren
            print("Test 6: Worker-Klassen existieren")
            assert hasattr(prosync, 'FileSyncWorker')
            assert hasattr(prosync, 'FolderSyncWorker')
            print("✓ PASS: FileSyncWorker und FolderSyncWorker sind definiert\n")

            # Test 7: Worker-Initialisierung (nur wenn PyQt6 verfügbar)
            if HAS_PYQT:
                print("Test 7: Worker-Initialisierung")
                # QCoreApplication benötigt für QThread
                app = QCoreApplication.instance()
                if app is None:
                    app = QCoreApplication(sys.argv)

                cfg = {
                    "id": "test-001",
                    "name": "Test Connection",
                    "source_file": str(test_file),
                    "target_file": str(test_dir / "target.txt"),
                    "checkpoint_before_sync": False
                }

                worker = prosync.FileSyncWorker(cfg)
                assert worker is not None
                assert worker.conn_id == "test-001"
                assert worker.is_killed == False
                print("✓ PASS: FileSyncWorker kann initialisiert werden\n")
            else:
                print("Test 7: ÜBERSPRUNGEN (PyQt6 nicht verfügbar)\n")

            # Test 8: ConfigManager Integration
            print("Test 8: ConfigManager existiert")
            assert hasattr(prosync, 'ConfigManager')
            print("✓ PASS: ConfigManager ist definiert\n")

        print("=== ALLE TESTS BESTANDEN ✓ ===")
        return 0

    except AssertionError as e:
        print(f"\n❌ TEST FEHLGESCHLAGEN: {e}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ UNERWARTETER FEHLER: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
