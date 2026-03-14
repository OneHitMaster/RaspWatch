# RPiMonitor

Modernes Echtzeit-Monitoring für **Raspberry Pi 5** (und andere Linux-Systeme) – inspiriert von [XavierBerger/RPi-Monitor](https://github.com/XavierBerger/RPi-Monitor), auf aktuellem Stand.

**© 2026 TheD3vil**

## Features

- **Dashboard**: CPU, RAM, Swap, Disk, Disk I/O, Temperatur (CPU/PMIC/RP1), Laufzeit, Netzwerk (inkl. pro Interface), Spannung (RPi), Top-Prozesse, System-Infos (OS, CPU-Modell, Kernel)
- **Logs**: System-Logs per journalctl oder optionale Log-Datei, Zeilenanzahl wählbar, Auto-Refresh
- **Einstellungen**: Aktualisierungsintervall, Design (Dark/Light), Log-Zeilen; Speicherung lokal (Browser) oder auf dem Server (`backend/settings.json`)
- **API**: `dynamic.json`, `static.json`, `/api/status`, `/api/info`, `/api/logs`, `/api/settings` (GET/POST), `/health`, `/docs`

## Schnellstart (lokal testen)

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Dashboard: **http://localhost:9090**  
API-Docs: **http://localhost:9090/docs**

## Installation auf dem Raspberry Pi 5

### 1. Projekt auf den Pi kopieren

```bash
scp -r RPIMonitor pi@raspberrypi.local:~/
```

### 2. Python-Umgebung

```bash
ssh pi@raspberrypi.local
cd ~/RPIMonitor/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Start

```bash
python main.py
```

Im Browser: **http://raspberrypi.local:9090** (oder die IP des Pi).

### 4. Optional: Log-Datei

Für die Log-Ansicht „Log-Datei“ eine Datei angeben (z. B. syslog):

```bash
export RPIMONITOR_LOG_FILE=/var/log/syslog
python main.py
```

(Oft braucht der Prozess dafür Root oder Gruppenmitgliedschaft z. B. in `adm`.)

### 5. Optional: als Systemdienst (systemd)

Datei anlegen: `/etc/systemd/system/rpimonitor.service`

```ini
[Unit]
Description=RPiMonitor Web Dashboard
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/RPIMonitor/backend
ExecStart=/home/pi/RPIMonitor/backend/venv/bin/python main.py
Restart=on-failure
Environment=PORT=9090

[Install]
WantedBy=multi-user.target
```

Aktivieren und starten:

```bash
sudo systemctl daemon-reload
sudo systemctl enable rpimonitor
sudo systemctl start rpimonitor
sudo systemctl status rpimonitor
```

## API

| Endpunkt | Beschreibung |
|----------|--------------|
| `GET /` | Web-Dashboard (Dashboard, Logs, Einstellungen) |
| `GET /dynamic.json` | Live-Metriken (CPU, RAM, Swap, Disk, I/O, Temp, Netz, Prozesse, …) |
| `GET /static.json` | Host-Infos (Hostname, Modell, OS, CPU-Modell, Kernel) |
| `GET /api/status` | Wie dynamic.json |
| `GET /api/info` | Wie static.json |
| `GET /api/logs?source=journal|file&lines=200` | System-Logs |
| `GET /api/settings` | Server-Einstellungen (Defaults + settings.json) |
| `POST /api/settings` | Einstellungen speichern (JSON-Body) |
| `GET /health` | Health-Check |
| `GET /docs` | OpenAPI-Dokumentation |

## Technik

- **Backend**: Python 3.9+, FastAPI, Uvicorn; Metriken aus `/proc`, `/sys`, optional `vcgencmd` (Raspberry Pi)
- **Frontend**: HTML/CSS/JS, kein Build; Dark/Light-Theme, Navigation (Dashboard, Logs, Einstellungen)
- **Einstellungen**: Browser localStorage und optional `backend/settings.json`

## Lizenz

MIT (Projekt) · RPi-Monitor von XavierBerger ist GPL-3.0.
