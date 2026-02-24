# Entwicklungsplan: Scheduled Sync (Zeitsteuerung)

**Status:** Teilweise implementiert  
**Erstellt:** 2026-01-26

---

## Aktueller Stand

### ✅ Bereits vorhanden
- `ConnectionScheduler` Klasse (L846-876)
- Intervall-basiertes Auto-Sync (alle X Minuten)
- UI: Kontextmenü "Automatisch ausführen" (Checkbox)
- Timer-System mit QTimer

### ❌ Noch fehlend
1. **Feste Uhrzeiten** - "täglich um 18:00"
2. **Wochentage-Auswahl** - "nur Mo-Fr"
3. **Erweiterte UI** - Konfigurationsdialog für Schedule

---

## Implementierungsplan

### Phase 1: Datenstruktur erweitern (~3 Min)
```python
"autosync": {
    "enabled": True,
    "mode": "interval",  # NEU: "interval" | "scheduled"
    "interval_minutes": 15,
    # NEU:
    "schedule": {
        "time": "18:00",  # Uhrzeit
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri"]  # Wochentage
    }
}
```

### Phase 2: Scheduler erweitern (~5 Min)
- `ConnectionScheduler.update_connection()` anpassen
- Neue Methode `_calculate_next_run()` für feste Zeiten
- QTimer auf nächsten Zeitpunkt setzen

### Phase 3: UI erweitern (~8 Min)
- Neuer Dialog `ScheduleDialog` oder Erweiterung von `ConnectionDialog`
- Zeitauswahl (QTimeEdit)
- Wochentage-Checkboxen
- Modus-Auswahl (Intervall vs. Zeitplan)

### Phase 4: Test & Dokumentation (~5 Min)
- Manueller Test
- README aktualisieren

---

## Geschätzter Gesamtaufwand: ~20-25 Min

---

## Nächste Schritte
1. [ ] Phase 1: Datenstruktur in ProSync_config.json definieren
2. [ ] Phase 2: ConnectionScheduler erweitern
3. [ ] Phase 3: UI-Dialog erstellen
4. [ ] Phase 4: Test durchführen

---
*Erstellt von Claude BATCH Session*
