# ProSync

Intelligente Backup-Synchronisation mit Datenbank-Sicherheit.

## Features

- **Ordner-Synchronisation** (Ein-Weg / Zwei-Wege)
- **Datei-Synchronisation** für einzelne Dateien
- **Automatische Datenbank-Erkennung** und -Schutz
- **WAL-Checkpoint** für SQLite-Dateien vor dem Kopieren
- **System-Tray Integration** für Hintergrund-Betrieb
- **Zeitgesteuerte Backups** mit konfigurierbaren Intervallen
- **Datenbank-Indexierung** für Suche und Versionierung (optional)

## Installation

```bash
pip install -r requirements.txt
```

### Benötigte Pakete

- PyQt6
- (Optional) PyPDF2 für PDF-Vorschau im Reader
- (Optional) python-docx für Word-Vorschau im Reader

## Verwendung

### Über Python

```bash
python ProSyncStart_V3.1.py
```

### Über Batch-Datei

```bash
START.bat
```

Die Anwendung startet im System-Tray. Rechtsklick auf das Icon für Optionen.

## Synchronisationsmodi

| Modus | Beschreibung | Anwendungsfall |
|-------|-------------|----------------|
| **mirror** | Ziel = exakte Kopie der Quelle | Vollständiges Backup |
| **update** | Nur neuere Dateien übertragen | Inkrementelles Backup |
| **two_way** | Bidirektionale Synchronisation | Sync zwischen zwei Arbeitsplätzen |
| **one_way** | Nur Quelle → Ziel, keine Löschungen | Sichere Archivierung |
| **index_only** | Nur Indexierung, kein Kopieren | Dateiverwaltung ohne Sync |

## Beispiel-Szenarien

### 1. Backup eines Projektordners

**Aufgabe:** Tägliches Backup eines Entwicklungsprojekts

**Konfiguration:**
- **Quelle:** `C:\Projekte\MeinProjekt`
- **Ziel:** `D:\Backups\MeinProjekt`
- **Modus:** `mirror`
- **Zeitgesteuert:** Täglich um 18:00 Uhr
- **Indexierung:** Aktiviert (für Suche)

**Ergebnis:** Vollständiges Backup mit Dateiversionierung und Suchfunktion

### 2. Synchronisation zwischen Laptop und Desktop

**Aufgabe:** Dateien zwischen zwei PCs synchronisieren

**Konfiguration:**
- **Quelle:** `C:\Dokumente`
- **Ziel:** `\\Desktop-PC\Dokumente`
- **Modus:** `two_way`
- **Zeitgesteuert:** Alle 30 Minuten
- **Konfliktauflösung:** `newest` (neueste Datei gewinnt)

**Ergebnis:** Bidirektionale Sync, beide PCs haben immer die neuesten Dateien

### 3. Datenbank-Backup (SQLite mit WAL-Modus)

**Aufgabe:** Sichere Sicherung einer SQLite-Datenbank

**Konfiguration:**
- **Typ:** Datei-Verbindung (nicht Ordner!)
- **Quelle:** `C:\App\data.db`
- **Ziel:** `D:\Backups\data.db`
- **Modus:** `one_way`
- **WAL-Checkpoint:** Aktiviert
- **Zeitgesteuert:** Alle 4 Stunden

**Ergebnis:** Konsistente DB-Backups ohne Korruption

## Datenbank-Schutz (V3.1)

ProSync erkennt automatisch kritische Datenbanken und wendet sichere Einstellungen an:

### Unterstützte Datenbanktypen

- **SQLite** (.sqlite, .sqlite3, .db, .db3)
- **MS Access** (.mdb, .accdb)

### Automatische Schutzmaßnahmen

#### Für Ordner-Verbindungen:
- Kritische DBs (im WAL-Modus) werden **automatisch ausgeschlossen**
- WAL-Dateien (.db-wal, .db-shm, .db-journal) werden **nie kopiert**
- Empfehlung: Erstelle **Datei-Verbindungen** für einzelne DBs

#### Für Datei-Verbindungen:
- **WAL-Checkpoint** wird automatisch aktiviert
- **One-Way Modus** wird empfohlen
- Checkpoint vor jedem Kopiervorgang

### Was ist WAL-Checkpoint?

WAL (Write-Ahead Logging) speichert SQLite-Änderungen in einer separaten `-wal` Datei.
Ein Checkpoint merged diese Änderungen zurück in die Haupt-DB-Datei.

**Ohne Checkpoint:** Inkonsistente Backups möglich!
**Mit Checkpoint:** Garantiert konsistente DB-Kopie.

## Konfigurationsdatei

`ProSync_config.json` - Wird automatisch erstellt und verwaltet.

### Beispiel (Ordner-Verbindung):

```json
{
  "connections": [
    {
      "id": "conn-abc123",
      "name": "Projekt Backup",
      "type": "folder",
      "source": "C:\\Projekte\\MeinProjekt",
      "target": "D:\\Backups\\MeinProjekt",
      "mode": "mirror",
      "conflict_policy": "source",
      "indexing": true,
      "db_path": "C:\\Projekte\\MeinProjekt\\profiler_index.db",
      "exclude_patterns": ["*.tmp", "*.lock", "__pycache__"],
      "autosync": {
        "enabled": true,
        "interval_minutes": 60
      }
    }
  ]
}
```

### Beispiel (Datei-Verbindung):

```json
{
  "connections": [
    {
      "id": "conn-def456",
      "name": "Datenbank Backup",
      "type": "file",
      "source_file": "C:\\App\\data.db",
      "target_file": "D:\\Backups\\data.db",
      "mode": "one_way",
      "checkpoint_before_sync": true,
      "autosync": {
        "enabled": true,
        "interval_minutes": 240
      }
    }
  ]
}
```

## ProSyncReader

Separates Tool zum Durchsuchen der Sync-Datenbanken.

```bash
python ProSyncReader.py
```

**Features:**
- Volltext-Suche in synchronisierten Dateien
- Tag-basierte Suche
- Datei-Vorschau (PDF, DOCX)
- Direktes Öffnen von Dateien/Ordnern

## Tipps & Best Practices

### ✅ DO:
- Nutze **Datei-Verbindungen** für einzelne Datenbanken
- Aktiviere **WAL-Checkpoint** für SQLite-DBs
- Teste neue Verbindungen mit einem **manuellen Sync** zuerst
- Nutze **exclude_patterns** für temporäre Dateien

### ❌ DON'T:
- Verwende **kein two_way** für kritische Datenbanken
- Synchronisiere **keine laufenden** Anwendungen
- Kopiere **keine .db-wal** Dateien manuell
- Nutze **kein mirror** wenn du keine Löschungen willst

## Troubleshooting

### "Checkpoint fehlgeschlagen"
➡️ Datenbank ist gerade geöffnet/gelockt. Schließe die Anwendung oder erhöhe den Timeout.

### "Sync bleibt hängen"
➡️ Große Dateien oder langsame Netzwerkverbindung. Nutze `update` statt `mirror` für schnellere Syncs.

### "Datei wurde ausgeschlossen"
➡️ Prüfe `exclude_patterns` in der Config. Kritische DBs werden automatisch ausgeschlossen (bei Ordner-Verbindungen).

## System-Tray Befehle

- **Linksklick:** Hauptfenster öffnen
- **Rechtsklick → Ausführen:** Verbindung manuell starten
- **Rechtsklick → Automatisch ausführen:** Zeitgesteuerte Sync aktivieren
- **Rechtsklick → Beenden:** ProSync beenden

## Lizenz

GPL v3 - Siehe [LICENSE](LICENSE)

Dieses Projekt verwendet PyQt6 (GPL).

---

**Version:** 3.1
**Autor:** Lukas Geiger
**Letzte Aktualisierung:** Februar 2026
