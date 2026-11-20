# RoK Combat Trades – stabiler 8-Stunden-Checker

Diese Lösung umgeht die DNS-Beschränkung **der ChatGPT-Abrufumgebung**, indem GitHub Actions das API-JSON abfragt und einen regelmäßig aktualisierten Report im Repository ablegt. Der GitHub-Runner muss den Host selbst erreichen können; der Abruf wurde am 20.11.2026 bei vier Paarungen erfolgreich bestätigt.

## Installation auf GitHub

1. Ein eigenes GitHub-Repository erstellen (z. B. `RoK-Combat-Trades`) oder ein geeignetes vorhandenes verwenden.
2. Den Inhalt dieses ZIPs (einschließlich `.github/workflows/monitor.yml`) in das Stammverzeichnis des Repositorys hochladen.
3. Unter **Settings > Actions > General > Workflow permissions** Schreibrechte für `GITHUB_TOKEN` zulassen (Read and write permissions), falls noch nicht aktiv.
4. Unter **Actions > RoK Combat Trades > Run workflow** die erste Ausführung manuell starten.
5. Danach werden `REPORT.md` und `data/trades.json` bei jedem Lauf erzeugt bzw. aktualisiert. Auch bei fehlgeschlagenem Zugriff wird ein neuer Fehlerbericht erstellt.

## Zeitplan

`01:00 / 09:00 / 17:00 UTC` täglich (8 Stunden Abstand). Das entspricht in der deutschen Winterzeit 02 / 10 / 18 Uhr und in der Sommerzeit 03 / 11 / 19 Uhr. GitHub Actions kann geplante Jobs verzögert starten. Die zeitgesteuerte Ausführung erfolgt nur vom Standardbranch aus.

## ChatGPT-Integration

Wenn das Repository angebunden ist, kann die ChatGPT-Überwachung **GitHub `REPORT.md` bzw. `data/trades.json`** über den verbundenen GitHub-Zugriff auswerten, ohne rokbattles.com selbst abrufen zu müssen. Dazu muss der Monitor-Task anschließend um Repositoryname und Pfade ergänzt werden. Der ChatGPT-Task kann unabhängig alle 8 Stunden weiterhin seine Berichte schicken; zeitliche Verschiebungen der beiden Jobs sind möglich.

## Hinweise

- Es werden genau vier Kombinationen abgefragt (621/545, 621/596, 621/185, 595/621).
- API-JSON: `/proxy/v2/global/combat-lab?primary=...&secondary=...`
- Verglichen wird die **Standardansicht: 1 Jahr / Open field** (`summaries`-Tupel [0,1], 0=1 Jahr, 1=Open field). Das entspricht den Standardfiltern der vier Combat-Lab-Links. Wer manuell andere Filter wählt, bekommt andere Statistiken.
- Echte neue Daten werden nur akzeptiert, wenn die IDs exakt stimmen und Datenformate valide sind.
- Änderungswerte beziehen sich auf den vorherigen erfolgreichen API-Snapshot; bei Abfragefehlern gibt es **keine erfundenen Veränderungen**.
- Der erste Workflow nutzte versehentlich `1 Jahr / All` ([0,0]). Diese nicht vergleichbaren Snapshots wurden in `data/trades-all-archived.json` gesichert. Nach der Korrektur beginnt die Open-field-Zeitreihe neu; Änderungswerte erscheinen erst nach zwei vergleichbaren Datensätzen.
- Falls auch GitHub Actions blockiert wird, muss man einen alternativen, erreichbaren Runner/Server verwenden (z. B. PC mit Aufgabenplanung).

## Lokale Prüfung unter Windows

Python 3.10+ installieren und im Ordner `python monitor.py` ausführen. Der Script nutzt nur Python-Standardbibliothek und schreibt `REPORT.md` + `data/trades.json`.

**Keine Zugangsdaten oder Cookies erforderlich**, soweit der öffentliche JSON-Endpunkt erreichbar ist.
