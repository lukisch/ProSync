"""
ProSync Utilities
Gemeinsame Hilfsfunktionen für ProSync-Komponenten
"""

import os
import sys
import subprocess


def open_file_cross_platform(path: str) -> None:
    """
    Öffnet eine Datei mit dem Standard-Programm des Betriebssystems.

    Args:
        path: Pfad zur zu öffnenden Datei

    Returns:
        None
    """
    if not os.path.exists(path):
        return

    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.call(['open', path])
    else:
        subprocess.call(['xdg-open', path])


def open_folder_cross_platform(path: str) -> None:
    """
    Öffnet den Ordner einer Datei im Datei-Explorer.

    Args:
        path: Pfad zur Datei (der Ordner wird geöffnet)

    Returns:
        None
    """
    folder = os.path.dirname(path)
    if not os.path.exists(folder):
        return

    if sys.platform == 'win32':
        os.startfile(folder)
    elif sys.platform == 'darwin':
        subprocess.call(['open', folder])
    else:
        subprocess.call(['xdg-open', folder])
