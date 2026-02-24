import sys
import os
import json
import sqlite3
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QFileDialog, QDialog, QDialogButtonBox,
    QHBoxLayout, QTextEdit, QLabel, QSplitter, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from prosync_utils import open_file_cross_platform, open_folder_cross_platform
from logger import log_error

# Optional libraries for preview
try:
    import PyPDF2
    HAS_PDF = True
except ImportError:
    HAS_PDF = False

try:
    import docx
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

CONFIG_PATH = "search_config.json"
SEARCH_RESULT_LIMIT = 500  # Maximum number of search results

# ---------------- CONFIG & DB ----------------
class DBManager:
    """
    Verwaltet die Liste der zu durchsuchenden ProSync-Indexdatenbanken.

    Speichert die Pfade zu profiler_index.db Dateien in einer JSON-Konfiguration
    (search_config.json). Ermöglicht das Hinzufügen/Entfernen von Datenbanken.
    """

    def __init__(self):
        self.dbs = []
        self.load()

    def load(self):
        """
        Lädt die Datenbank-Liste aus search_config.json.

        Bei Fehler oder fehlender Datei wird eine neue Config erstellt.
        """
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.dbs = json.load(f).get("databases", [])
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                log_error(f"Config load error: {e}")
                self.save()
        else:
            self.save()

    def save(self):
        """
        Speichert die aktuelle Datenbank-Liste in search_config.json.

        Schreibt JSON mit indent=2 für bessere Lesbarkeit.
        """
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"databases": self.dbs}, f, indent=2)

    def add_db(self, path):
        """
        Fügt einen Datenbank-Pfad zur Suchliste hinzu (falls noch nicht vorhanden).

        Args:
            path: Absoluter Pfad zur profiler_index.db Datei
        """
        if path not in self.dbs:
            self.dbs.append(path)
            self.save()

    def remove_db(self, path):
        """
        Entfernt einen Datenbank-Pfad aus der Suchliste.

        Args:
            path: Pfad zur zu entfernenden Datenbank
        """
        self.dbs = [d for d in self.dbs if d != path]
        self.save()

# ---------------- WORKER THREADS ----------------
class SearchWorker(QThread):
    """
    Background-Thread für die Suche in ProSync-Indexdatenbanken.

    Durchsucht alle in DBManager konfigurierten profiler_index.db Dateien
    nach dem Suchbegriff (in Dateinamen, Pfaden und Tags). Emittiert
    results_found Signal mit gefundenen Dateien.
    """

    results_found = pyqtSignal(list) # List of dicts
    finished = pyqtSignal()

    def __init__(self, manager, term):
        """
        Initialisiert den Search-Worker.

        Args:
            manager: DBManager-Instanz mit den zu durchsuchenden Datenbanken
            term: Suchbegriff (wird zu lowercase konvertiert)
        """
        super().__init__()
        self.manager = manager
        self.term = term.lower()

    def run(self):
        """
        Führt die Suche in allen konfigurierten Datenbanken aus.

        Sendet results_found Signal mit Suchergebnissen (max. SEARCH_RESULT_LIMIT).
        Sendet finished Signal nach Abschluss.
        """
        results = []

        for db_path in self.manager.dbs:
            if not os.path.exists(db_path): continue
            try:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                
                # Search Logic
                query = """
                    SELECT DISTINCT v.name, v.path, v.mtime, 'file' as match_type
                    FROM versions v
                    JOIN files f ON f.id = v.file_id
                    WHERE lower(v.name) LIKE ? OR lower(v.path) LIKE ?
                    UNION
                    SELECT DISTINCT v.name, v.path, v.mtime, 'tag' as match_type
                    FROM versions v
                    JOIN files f ON f.id = v.file_id
                    JOIN tags t ON t.file_id = f.id
                    WHERE lower(t.tag) LIKE ?
                """
                wildcard = f"%{self.term}%"
                cur.execute(query, (wildcard, wildcard, wildcard))
                
                rows = cur.fetchmany(SEARCH_RESULT_LIMIT)
                for row in rows:
                    results.append({
                        "name": row["name"],
                        "path": row["path"],
                        "mtime": row["mtime"],
                        "type": row["match_type"]
                    })
                conn.close()
            except Exception as e:
                print(f"DB Error {db_path}: {e}")
                
            if len(results) >= SEARCH_RESULT_LIMIT: break
            
        self.results_found.emit(results)
        self.finished.emit()

class PreviewWorker(QThread):
    preview_ready = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        if not os.path.exists(self.path):
            self.preview_ready.emit("Datei nicht gefunden.")
            return

        text = ""
        ext = os.path.splitext(self.path)[1].lower()

        try:
            if ext in [".txt", ".md", ".py", ".json", ".xml", ".log", ".csv"]:
                with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read(3000) 
            
            elif ext == ".pdf" and HAS_PDF:
                with open(self.path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    if len(reader.pages) > 0:
                        extracted = reader.pages[0].extract_text()
                        text = extracted if extracted else "[Kein Text extrahierbar]"
                        text = text[:3000]
            
            elif ext == ".docx" and HAS_DOCX:
                doc = docx.Document(self.path)
                full_text = []
                for para in doc.paragraphs[:25]:
                    full_text.append(para.text)
                text = "\n".join(full_text)
            
            elif ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]:
                text = "[Bilddatei - Vorschau nicht implementiert]"
            
            else:
                text = f"Keine Vorschau für {ext} verfügbar."

            if not text.strip(): text = "[Datei ist leer oder Inhalt nicht lesbar]"

        except Exception as e:
            text = f"Fehler beim Lesen: {str(e)}"

        self.preview_ready.emit(text)

# ---------------- GUI ----------------
class SettingsDialog(QDialog):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Datenbanken verwalten")
        self.manager = manager
        self.resize(400, 300)
        lay = QVBoxLayout(self)
        
        self.list = QListWidget()
        self.refresh_list()
        lay.addWidget(QLabel("Verbundene Datenbanken:"))
        lay.addWidget(self.list)
        
        btn_lay = QHBoxLayout()
        btn_add = QPushButton("Hinzufügen")
        btn_remove = QPushButton("Entfernen")
        btn_lay.addWidget(btn_add); btn_lay.addWidget(btn_remove)
        lay.addLayout(btn_lay)
        
        btn_add.clicked.connect(self.add_db)
        btn_remove.clicked.connect(self.remove_db)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)

    def refresh_list(self):
        self.list.clear()
        for d in self.manager.dbs:
            item = QListWidgetItem(d)
            if not os.path.exists(d): item.setForeground(Qt.GlobalColor.red)
            self.list.addItem(item)

    def add_db(self):
        f, _ = QFileDialog.getOpenFileName(self, "DB wählen", "", "SQLite (*.db)")
        if f: 
            self.manager.add_db(f)
            self.refresh_list()

    def remove_db(self):
        item = self.list.currentItem()
        if item:
            self.manager.remove_db(item.text())
            self.refresh_list()

class SearchWindow(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.setWindowTitle("ProFiler Search")
        self.resize(900, 600)
        self.manager = manager
        self.search_worker = None
        self.preview_worker = None
        
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.interval = 400 
        self.search_timer.timeout.connect(self.execute_search)

        central = QWidget(); self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)

        # Top Bar
        top_lay = QHBoxLayout()
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Suchbegriff eingeben...")
        self.search_field.textChanged.connect(self.on_text_changed)
        self.search_field.setClearButtonEnabled(True)
        
        btn_settings = QPushButton("⚙")
        btn_settings.setFixedSize(30, 30)
        btn_settings.clicked.connect(self.open_settings)
        
        top_lay.addWidget(self.search_field)
        top_lay.addWidget(btn_settings)
        main_lay.addLayout(top_lay)

        # Splitter (List vs Preview)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.on_item_clicked)
        self.results_list.itemDoubleClicked.connect(self.open_file)
        self.results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self.open_context_menu)
        
        preview_container = QWidget()
        preview_lay = QVBoxLayout(preview_container)
        preview_lay.setContentsMargins(0,0,0,0)
        self.lbl_path = QLabel("Keine Auswahl")
        self.lbl_path.setStyleSheet("color: gray; font-size: 10px;")
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        
        preview_lay.addWidget(QLabel("<b>Vorschau</b>"))
        preview_lay.addWidget(self.lbl_path)
        preview_lay.addWidget(self.preview_text)

        splitter.addWidget(self.results_list)
        splitter.addWidget(preview_container)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        main_lay.addWidget(splitter)
        self.status_bar = self.statusBar()

    def on_text_changed(self):
        self.search_timer.start(400) 

    def execute_search(self):
        term = self.search_field.text().strip()
        if not term: 
            self.results_list.clear()
            return
            
        self.status_bar.showMessage("Suche läuft...")
        self.results_list.clear()
        
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.terminate()
            
        self.search_worker = SearchWorker(self.manager, term)
        self.search_worker.results_found.connect(self.update_results)
        self.search_worker.finished.connect(lambda: self.status_bar.showMessage("Bereit"))
        self.search_worker.start()

    def update_results(self, results):
        if not results:
            self.results_list.addItem("Keine Treffer.")
            return

        for r in results:
            name = r['name']
            path = r['path']
            display_text = f"{name}"
            
            item = QListWidgetItem(display_text)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, r)
            
            if r['type'] == 'tag':
                item.setText(f"🏷 {display_text} (Tag)")
            else:
                item.setText(f"📄 {display_text}")
                
            self.results_list.addItem(item)
        
        self.status_bar.showMessage(f"{len(results)} Treffer gefunden.")

    def on_item_clicked(self, item):
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data: return
        
        path = data['path']
        self.lbl_path.setText(path)
        self.preview_text.setText("Lade Vorschau...")
        
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_worker.terminate()

        self.preview_worker = PreviewWorker(path)
        self.preview_worker.preview_ready.connect(self.preview_text.setText)
        self.preview_worker.start()

    def open_file(self, item=None):
        if not item: item = self.results_list.currentItem()
        if not item: return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and os.path.exists(data['path']):
            open_file_cross_platform(data['path'])

    def open_context_menu(self, pos):
        item = self.results_list.itemAt(pos)
        if not item: return
        
        data = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu()
        
        act_open = menu.addAction("Öffnen")
        act_folder = menu.addAction("Ordner öffnen")
        
        action = menu.exec(self.results_list.viewport().mapToGlobal(pos))
        
        if action == act_open:
            self.open_file(item)
        elif action == act_folder:
            if data:
                open_folder_cross_platform(data['path'])

    def open_settings(self):
        SettingsDialog(self.manager, self).exec()

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    missing = []
    if not HAS_PDF: missing.append("PyPDF2")
    if not HAS_DOCX: missing.append("python-docx")
    
    if missing:
        print(f"Hinweis: Fehlende Libs für Vorschau: {', '.join(missing)}")

    manager = DBManager()
    win = SearchWindow(manager)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()