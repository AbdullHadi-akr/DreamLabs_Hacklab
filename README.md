# dream-tool – Dream Labs Track

Grundgerüst für den Track **„Build a Tool for Dream-1 Users“**: ein Tool, das echte Dream-1-Nutzer verwenden
würden, gebaut auf [dreamlabs-co/dreamlabs](https://github.com/dreamlabs-co/dreamlabs) und getestet im Simulator.

**Bewertung (100 Punkte):** Real-user value 25 · Robustness 25 · Technical difficulty 20 · Demo quality 20 ·
Presentation 10. Sonntag: 3 Minuten Live-Demo + 2 Minuten Fragen.

## Ordnerstruktur

```
Hacklab/
├── .venv/              Python 3.12 mit dreamlabs + dreamlabs-client (aus dem Klon installiert)
├── dreamlabs/          Klon des offiziellen Repos (nicht ändern, nur lesen)
│   └── dream_library/examples/yam_mujoco/   ← der Simulator (2 YAM-Arme, 3 Kameras, Obst, Schüssel, Teller)
└── dream-tool/         ← DEIN Projekt (dieses Repo)
    ├── dashboard/        ← lokale Web-App (FastAPI + Plain-JS), Sim in der Mitte
    │   ├── app.py          HTTP-API, MJPEG-Streams, WebSocket-Events
    │   ├── simulation.py   Sim-Thread: besitzt Physik + Rendering, führt Läufe aus
    │   ├── extension.py    Extension-Basisklasse + Loader + 3D-Overlay-Helfer
    │   ├── extensions/     ← HIER kommen neue Features rein (je ein Ordner)
    │   │   ├── scene_inspector/   Objekt-Positionen, Erfolgszonen, Debug-Platzieren
    │   │   ├── robustness/        Störungs-Sweeps (Objekt/Kamera/Licht), Erfolgsquote pro Stärke
    │   │   └── _template/         Vorlage zum Kopieren
    │   ├── static/         Core-UI (index.html, app.js, style.css, lib/api.js)
    │   └── EXTENSIONS.md   Anleitung: eigene Extension schreiben
    ├── start.py          startet das Dashboard
    ├── dreamtool/
    │   ├── sim.py        findet den Simulator, re-exportiert YamEnv + Request-Helfer
    │   ├── runner.py     Kontrollschleife Dream-1 ↔ Sim, mit Hooks für dein Tool
    │   ├── scene.py      Objekt-Positionen + einfache Erfolgserkennung („apple in bowl“)
    │   └── recorder.py   MP4-Aufnahme der 3 Kameras (für die Demo)
    ├── run.py            CLI: Task ausführen, optional aufnehmen
    ├── check_setup.py    prüft, ob alles läuft
    ├── tests/            Offline-Tests (kein API-Key nötig)
    └── setup.ps1         Setup für Teammitglieder
```

## Setup

Auf diesem Rechner ist alles schon installiert. Für Teammitglieder (Windows, Python 3.12 + git):

```powershell
git clone <euer-repo> Hacklab\dream-tool
cd Hacklab\dream-tool
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Aktivieren (jede neue Shell):

```powershell
..\.venv\Scripts\Activate.ps1
```

### API-Key

Key erstellen auf [platform.dreamlabs.ai/api-keys](https://platform.dreamlabs.ai/api-keys) (wird nur einmal
angezeigt). Dann **eins** davon:

- `$env:DREAM_API_KEY = "dl_live_..."` (nur aktuelle Shell)
- Datei `%USERPROFILE%\.dreamlabs\credentials` mit diesen vier Zeilen:

```
DREAM_GATEWAY_URL=https://api.dreamlabs.ai
DREAM_API_URL=https://platform.dreamlabs.ai
DREAM_DATA_URL=https://data.dreamlabs.ai
DREAM_API_KEY=dl_live_...
```

Jeder Task-Lauf verbraucht Credits auf dem Account.

## Dashboard

```powershell
python start.py                      # oder: python -m dashboard   → öffnet http://localhost:8000
```

- **Mitte:** 3D-Ansicht der Sim (ziehen = drehen, rechts/Shift = verschieben, Rad = zoomen, Doppelklick = zurück),
  darunter Taskleiste und die drei Roboter-Kameras.
- **Links:** Extension-Tabs (Szene, Robustness, …). **Rechts:** aktueller Lauf, RTT-Verlauf, Log.
- **Offline-Demo**, **Home**, **Reset** und der **Trockenlauf** im Robustness-Tab kosten keine Credits.
  **Start** und Sweeps ohne Trockenlauf rufen Dream-1 auf.
- Der Server läuft nur lokal (127.0.0.1). Strg+C beendet ihn.

**Neues Feature bauen:** `dashboard/extensions/_template` kopieren → Anleitung in
[dashboard/EXTENSIONS.md](dashboard/EXTENSIONS.md).

## Loslegen (CLI)

```powershell
python check_setup.py --online       # alles grün? (--online prüft den Key gegen die API)
python -m pytest -q                  # Offline-Tests
python run.py --offline --record out/offline.mp4   # Sim ohne API, Video als Beweis
python run.py "put apple into the bowl"            # Dream-1 steuert die Arme, 3D-Viewer geht auf
python run.py "put banana on the plate" --headless --record out/banana.mp4 --seconds 90
```

Der offizielle interaktive Simulator (mit Task-Terminal, `/reset`, `/model` …):

```powershell
cd ..\dreamlabs\dream_library\examples\yam_mujoco
python yam_mujoco.py
```

> **Windows-Hinweise:** `dreamcli` läuft unter Windows nicht (nutzt `fcntl`) – braucht man für den Sim aber nicht.
> `yam_mujoco.py` braucht eine echte Konsole (PowerShell / Windows Terminal), nicht Git Bash.

## Dein Tool einhängen

Die ganze Logik kommt über **Hooks** in die Schleife – du musst die Kontrollschleife nicht anfassen:

```python
from dreamtool import Hooks, run_task, scene

class MeinTool(Hooks):
    def on_start(self, env, task, model): ...           # vor dem ersten Request
    def on_reply(self, env, reply, rtt_s): ...          # jeder Action-Chunk: reply["q_l_chunk"], ["q_r_chunk"] je [H,7]
    def on_step(self, env, step, images): ...           # alle 50 ms: env.state(), images["top"|"left"|"right"]
    def should_stop(self, env): return None             # "Grund" zurückgeben → Lauf stoppt
    def on_end(self, env, result): ...                  # RunResult: success, stop_reason, rtts_s, steps …

result = run_task("put apple into the bowl", hooks=[MeinTool()], viewer=False, seconds=60)
```

Nützlich: `scene.positions(env)`, `scene.is_in(env, "apple", "bowl")`, `env.state()` (Gelenke in rad +
Greifer 0–1), `env.reset()`, `sim.home_path(env.state())`. Offline testen ohne Credits: `run_scripted(env, targets, hooks)`.

**Fakten zum Modell:** `dreamlabs/dream-1-beta`, 20 Hz Steuerung, bis 48 Aktionen pro Antwort, Input = je 9 Frames
(320×176 JPEG, 0,2 s Abstand) von 3 Kameras + Gelenkzustände + Text-Prompt. Der Simulator erkennt **keinen
Aufgaben-Erfolg** von sich aus. Laut Doku: Apfel/Orange → Schüssel klappt manchmal, Banane → Teller ist unzuverlässig.

## Ideen (passend zu den Kriterien)

1. **Eval-/Benchmark-Runner** – N Durchläufe pro Prompt, automatische Erfolgserkennung (`scene.py` ausbauen),
   Erfolgsquote, Latenz-Statistik, Video pro Trial → HTML-Report. Beantwortet die Frage jedes Nutzers: *„Welcher
   Prompt / welches Modell / welcher Fine-Tune funktioniert wirklich?“* (Real-user value + Robustness)
2. **Safety-Guard** – jeden Action-Chunk vor der Ausführung in einer Kopie der Physik vorsimulieren; bei Kollision,
   Arm-Kreuzung oder Verlassen des Arbeitsbereichs stoppen/abbremsen. Auf echte Roboter übertragbar.
3. **Run-Debugger** – geplante vs. ausgeführte Trajektorien, RTT-Timeline, Seam-Sprünge zwischen Chunks visualisieren.
4. **Prompt-Optimizer** – Varianten eines Tasks automatisch durchprobieren und die beste Formulierung finden.
5. **Datensatz-Recorder** – erfolgreiche Sim-Läufe als Fine-Tuning-Datensatz exportieren (`client.validate_dataset`).

Tipp für die Demo: Läufe vorher mit `--record` aufnehmen als Backup, falls API/WLAN live hakt.

## Links

- Doku: <https://platform.dreamlabs.ai/api-documentation>
- Client-Referenz: `../dreamlabs/dream_library/dream_client/README.md`
- Simulator: `../dreamlabs/dream_library/examples/yam_mujoco/README.md`
- Discord: <https://discord.gg/UAPxxH6tTg>
