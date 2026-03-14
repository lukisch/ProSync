# ProSync – User Guide

Version 3.1 | Stand: 2026-03-14

---

## Inhalt

1. [Einrichtung (Setup)](#einrichtung)
2. [Verbindung erstellen](#verbindung-erstellen)
3. [Synchronisation starten](#synchronisation-starten)
4. [Automatische Backups planen](#automatische-backups-planen)
5. [Troubleshooting](#troubleshooting)
6. [FAQ](#faq)

---

## 1. Einrichtung (Setup) {#einrichtung}

### Voraussetzungen

- Python 3.9+ **oder** die mitgelieferte `.exe`
- Windows 10/11

### Installation (Python-Version)

```bash
pip install -r requirements.txt
python ProSyncStart_V3.1.py
```

### Installation (Batch-Datei)

Doppelklick auf `START.bat` – startet direkt im System-Tray.

### Erster Start

Nach dem Start erscheint ProSync als Icon im System-Tray (Taskleiste rechts unten).
Rechtsklick auf das Icon → **"Öffnen"** zum Aufrufen des Hauptfensters.

---

## 2. Verbindung erstellen {#verbindung-erstellen}

Eine **Verbindung** definiert Quelle, Ziel und Synchronisationsmodus.

### Ordner-Verbindung

1. Klicke auf **"Neue Verbindung"** → **"Ordner"**
2. Wähle **Quellordner** (z. B. `C:\Projekte\MeinProjekt`)
3. Wähle **Zielordner** (z. B. `D:\Backups\MeinProjekt`)
4. Wähle einen **Modus** (siehe Tabelle unten)
5. Optional: Ausschlussmuster eingeben (z. B. `*.tmp`, `.git`)
6. Klicke **"Speichern"**

### Datei-Verbindung (für einzelne Dateien / Datenbanken)

1. Klicke auf **"Neue Verbindung"** → **"Datei"**
2. Wähle **Quelldatei** (z. B. `C:\App\data.db`)
3. Wähle **Zieldatei** (z. B. `D:\Backups\data.db`)
4. Optional: **WAL Checkpoint** aktivieren (empfohlen für SQLite-Datenbanken)
5. Klicke **"Speichern"**

### Synchronisationsmodi

| Modus        | Beschreibung                                    | Anwendungsfall             |
|-------------|------------------------------------------------|---------------------------|
| `mirror`    | Ziel = exakte Kopie der Quelle (löscht auch)   | Vollständiges Backup       |
| `update`    | Nur neuere Dateien übertragen                  | Inkrementelles Backup      |
| `two_way`   | Bidirektionale Synchronisation                  | Sync zwischen zwei Rechnern |
| `one_way`   | Quelle → Ziel, keine Löschungen               | Sichere Archivierung       |
| `index_only`| Nur Indexierung, kein Kopieren                 | Dateiverwaltung ohne Sync  |

---

## 3. Synchronisation starten {#synchronisation-starten}

### Manueller Sync

1. Verbindung in der Liste auswählen
2. Klicke **"Sync starten"**
3. Fortschritt wird in der Statusleiste angezeigt
4. Nach Abschluss erscheint ein Sync-Report (Dateien kopiert/gelöscht/übersprungen)

### Sync-Report

Nach jedem Sync wird ein JSON-Log gespeichert unter:
```
%APPDATA%\ProSync\reports\sync_log.json
```
Die letzten 100 Einträge werden aufbewahrt.

---

## 4. Automatische Backups planen {#automatische-backups-planen}

1. Verbindung auswählen → **"Zeitplan bearbeiten"**
2. Intervall wählen (z. B. alle 30 Minuten, täglich um 18:00 Uhr)
3. **"Aktivieren"** und **"Speichern"**

ProSync muss dazu im Hintergrund laufen (System-Tray-Icon sichtbar).

**Tipp:** Aktiviere unter **Einstellungen → "Autostart"**, damit ProSync
automatisch mit Windows startet.

---

## 5. Troubleshooting {#troubleshooting}

### Sync startet nicht / Fehler beim Verbinden

- **Ursache:** Quell- oder Zielordner existiert nicht oder ist nicht erreichbar
  (z. B. Netzlaufwerk nicht verbunden).
- **Lösung:** Pfad in der Verbindung prüfen → rechte Maustaste → "Bearbeiten".

### SQLite-Datenbank wird nicht korrekt gesichert

- **Ursache:** Datenbank ist noch geöffnet / WAL-Modus aktiv ohne Checkpoint.
- **Lösung:** Verbindungstyp auf **"Datei"** setzen und **"WAL Checkpoint"** aktivieren.
  Dadurch führt ProSync einen `PRAGMA wal_checkpoint(TRUNCATE)` durch, bevor die Datei kopiert wird.

### Datei-Duplikate am Ziel

- **Ursache:** Modus `one_way` löscht nichts am Ziel.
- **Lösung:** Modus auf `mirror` umstellen (löscht Dateien am Ziel, die an der Quelle fehlen).

### ProSync erscheint nicht im System-Tray

- Aufgaben-Manager prüfen: Läuft `python.exe` oder `ProSync.exe`?
- Neustart via `START.bat`

### Log-Datei lesen

Logs befinden sich unter:
```
%APPDATA%\ProSync\prosync.log
```

---

## 6. FAQ {#faq}

**F: Kann ich mehrere Verbindungen gleichzeitig synchronisieren?**
A: Ja. Alle aktiven Verbindungen können gleichzeitig gestartet werden. Jede läuft in einem eigenen Thread.

**F: Was passiert, wenn das Ziel voll ist?**
A: Der Sync schlägt mit einer OSError fehl und wird im Log protokolliert. Es werden keine Dateien gelöscht.

**F: Werden Unterordner ebenfalls synchronisiert?**
A: Ja, standardmäßig rekursiv. Ausschlussmuster können Unterordner ausschließen (z. B. `temp/**`).

**F: Wie schütze ich Datenbanken vor Korruption beim Backup?**
A: Nutze den Verbindungstyp "Datei" mit aktiviertem WAL Checkpoint. ProSync führt einen Checkpoint durch, bevor die Datei kopiert wird, sodass das Backup immer konsistent ist.

**F: Kann ich ProSync auf einem NAS/Netzlaufwerk als Ziel nutzen?**
A: Ja, solange das Laufwerk als Netzlaufwerk eingebunden ist (Laufwerksbuchstabe oder UNC-Pfad `\server\share`).

**F: Wo werden die Einstellungen gespeichert?**
A: In `ProSync_config.json` im Programmordner.

**F: Wie deinstalliere ich ProSync?**
A: Autostart deaktivieren (Einstellungen → Autostart ausschalten), dann den Programmordner löschen.
