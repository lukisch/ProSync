"""
Smoke-Test für DatabaseSafetyManager
Testet die grundlegende Funktionalität der Datenbank-Sicherheitsfeatures
"""

import os
import sys
import tempfile
import sqlite3
from pathlib import Path

# Import der zu testenden Klasse
sys.path.insert(0, os.path.dirname(__file__))

# Mock PyQt6 falls nicht verfügbar
try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    print("PyQt6 nicht verfügbar - Mock-Klassen werden verwendet")
    class QApplication:
        pass

# Importiere DatabaseSafetyManager
# Note: Import von .py Dateien mit Punkten im Namen erfordert importlib
import importlib.util
spec = importlib.util.spec_from_file_location(
    "prosync",
    os.path.join(os.path.dirname(__file__), "ProSyncStart_V3.1.py")
)
prosync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prosync)
DatabaseSafetyManager = prosync.DatabaseSafetyManager


def create_test_sqlite_db(path: str, wal_mode: bool = False):
    """Erstellt eine Test-SQLite-Datenbank."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO test (data) VALUES ('test')")

    if wal_mode:
        conn.execute("PRAGMA journal_mode=WAL")

    conn.commit()
    conn.close()


def main():
    print("=== DatabaseSafetyManager Smoke-Test ===\n")

    try:
        # Temporäres Verzeichnis für Tests
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir)

            # Test 1: is_database_file
            print("Test 1: is_database_file")
            assert DatabaseSafetyManager.is_database_file("test.db") == True
            assert DatabaseSafetyManager.is_database_file("test.sqlite") == True
            assert DatabaseSafetyManager.is_database_file("test.txt") == False
            print("✓ PASS: Datenbankdatei-Erkennung funktioniert\n")

            # Test 2: is_access_lock_file
            print("Test 2: is_access_lock_file")
            assert DatabaseSafetyManager.is_access_lock_file("test.ldb") == True
            assert DatabaseSafetyManager.is_access_lock_file("test.laccdb") == True
            assert DatabaseSafetyManager.is_access_lock_file("test.db") == False
            print("✓ PASS: MS Access Lock-Datei-Erkennung funktioniert\n")

            # Test 3: is_sqlite_database (echte DB-Datei)
            print("Test 3: is_sqlite_database")
            db_path = test_dir / "test.db"
            create_test_sqlite_db(str(db_path))

            assert DatabaseSafetyManager.is_sqlite_database(str(db_path)) == True
            assert DatabaseSafetyManager.is_sqlite_database("nonexistent.db") == False
            print("✓ PASS: SQLite-Datenbank-Erkennung (Header-Check) funktioniert\n")

            # Test 4: check_wal_mode
            print("Test 4: check_wal_mode")
            db_wal = test_dir / "test_wal.db"
            db_normal = test_dir / "test_normal.db"

            create_test_sqlite_db(str(db_wal), wal_mode=True)
            create_test_sqlite_db(str(db_normal), wal_mode=False)

            assert DatabaseSafetyManager.check_wal_mode(str(db_wal)) == True
            assert DatabaseSafetyManager.check_wal_mode(str(db_normal)) == False
            assert DatabaseSafetyManager.check_wal_mode("nonexistent.db") == False
            print("✓ PASS: WAL-Modus-Erkennung funktioniert\n")

            # Test 5: scan_directory_for_databases
            print("Test 5: scan_directory_for_databases")
            # Erstelle mehrere Test-DBs
            (test_dir / "db1.db").write_text("fake db")
            create_test_sqlite_db(str(test_dir / "db2.sqlite"))
            (test_dir / "db3.mdb").write_text("fake access")

            databases = DatabaseSafetyManager.scan_directory_for_databases(str(test_dir))

            # Mindestens 3 Datenbanken sollten gefunden werden
            assert len(databases) >= 3
            # Prüfe ob Metadaten vorhanden sind
            assert all("path" in db for db in databases)
            assert all("type" in db for db in databases)
            print(f"✓ PASS: {len(databases)} Datenbanken gefunden und analysiert\n")

            # Test 6: apply_safe_settings_folder
            print("Test 6: apply_safe_settings_folder")
            db_critical = test_dir / "critical.db"
            create_test_sqlite_db(str(db_critical), wal_mode=True)

            # Scanne das Verzeichnis
            dbs = DatabaseSafetyManager.scan_directory_for_databases(str(test_dir))

            # Wende Safe Settings an
            conn_config = {
                "type": "folder",
                "source": str(test_dir),
                "mode": "two_way"
            }

            modified_config, warnings, excluded_dbs, was_changed = \
                DatabaseSafetyManager.apply_safe_settings_folder(conn_config, dbs)

            # Config sollte geändert worden sein
            assert was_changed == True
            # exclude_patterns sollten hinzugefügt worden sein
            assert "exclude_patterns" in modified_config
            assert len(modified_config["exclude_patterns"]) > 0
            print("✓ PASS: Safe Settings für Folder-Connection angewendet\n")

            # Test 7: apply_safe_settings_file
            print("Test 7: apply_safe_settings_file")
            file_db = test_dir / "file.db"
            create_test_sqlite_db(str(file_db), wal_mode=True)

            file_config = {
                "type": "file",
                "source_file": str(file_db),
                "mode": "two_way"
            }

            modified_file_config, file_warnings, file_was_changed = \
                DatabaseSafetyManager.apply_safe_settings_file(file_config)

            # Modus sollte auf one_way gesetzt worden sein
            assert modified_file_config["mode"] == "one_way"
            # Checkpoint sollte aktiviert worden sein
            assert modified_file_config.get("checkpoint_before_sync") == True
            print("✓ PASS: Safe Settings für File-Connection angewendet\n")

            # Test 8: checkpoint_sqlite_database
            print("Test 8: checkpoint_sqlite_database")
            checkpoint_db = test_dir / "checkpoint.db"
            create_test_sqlite_db(str(checkpoint_db), wal_mode=True)

            # Checkpoint sollte erfolgreich sein
            result = DatabaseSafetyManager.checkpoint_sqlite_database(str(checkpoint_db))
            assert result == True

            # Nicht-existente DB sollte False zurückgeben
            result = DatabaseSafetyManager.checkpoint_sqlite_database("nonexistent.db")
            assert result == False
            print("✓ PASS: SQLite WAL-Checkpoint funktioniert\n")

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
