# Nightly Report – 21./22.11.2026

Branch `feature/inference-strategies` (nicht auf `main` gepusht). Alle Läufe mit echtem Dream-1 (`dreamlabs/dream-1-beta`)
im MuJoCo-YAM-Simulator. Rohdaten, Pläne, Logs und Auswertungen liegen in [`measurements/2026-11-22/`](measurements/2026-11-22/),
die vollständigen Kampagnen (jede Zeile ein Trial mit allen Metriken) in `measurements/2026-11-22/campaigns/`.

## Kurzfassung

1. **Kamera-Pipeline ist korrekt.** Der neue Kamera-Check (Tab „Cameras“) vergleicht jedes an Dream-1 gesendete Bild
   mit dem gerenderten Wahrheitsbild. Auf echtem Dream-1: 8/8 eingebaute Fehler erkannt (vertauschte Handgelenke,
   doppelte Kamera, kopfüber, BGR, eingefroren, 600 ms Verzögerung, schwarz, Zoom), saubere Läufe ohne Fehlalarm
   (Lag-Median 0 ms, 5,0 fps). Dream-1 nutzt alle drei Kameras (Ausblenden ändert den Plan um 4,1 / 5,9 / 1,5 cm).
2. **Größte Verbesserung der Nacht: ein Messfehler im Simulator-Loop wurde gefunden und behoben** (künstliche Latenz,
   siehe Verbesserung V3). Der Dream-Client ersetzte die ersten ~11 Zeilen jedes neuen Chunks durch den alten Plan,
   weil er annimmt, der Roboter laufe während der Anfrage weiter – im Simulator pausiert aber die Physik.
3. **Chunk vs. Receding/Crossfade:** Über die ganze Nacht (42 gepaarte Szenen) erreicht `receding-24` deutlich mehr
   Fortschritt als der volle 48er-Chunk (Δ Fortschritt **+0,31 [+0,17; +0,43]**, 95 %-Bootstrap-KI), `crossfade-30`
   +0,28 [+0,16; +0,39]. Die Erfolgsquote ist höher (Apfel: chunk 22 %, receding-24 32 %, receding-30 40 %,
   crossfade-30 42 %), aber mit den bisherigen Trialzahlen **nicht signifikant** (McNemar p ≈ 0,45).
   Kurze Horizonte (8, 16) und das Ensemble sind schlechter oder gleich. Bestätigungsserie 6 siehe unten.
4. **Wichtigste methodische Erkenntnis:** Wiederholungen derselben Szene sind *nicht* identisch – Ursache ist
   GPU-Render-Rauschen (≈0,01 % der Pixel weichen um 1 Graustufe ab). Dream-1 selbst ist deterministisch (gleiche
   Anfrage → identischer Plan), reagiert aber auf dieses unsichtbare Rauschen mit bis zu 0,03 rad im ersten Plan; danach
   divergieren die Läufe chaotisch. Konsequenz: Eine einzelne Szene ist oft ein Münzwurf, deshalb nie anhand einzelner
   Trials optimieren (genau so wurde ausgewertet).
5. **Offene Hauptprobleme:** Banane und Orange werden in keiner Konfiguration abgelegt (0/74 gewertete Trials) – das Objekt rutscht
   aus dem geschlossenen Greifer („slipped“, nicht „released“). Bei langen Horizonten ist der dominante Fehler
   „neben den Behälter gelegt“, beim vollen Chunk „nicht gegriffen“.

## Was gebaut wurde (Features auf dem Branch)

| Feature | Dateien | Zweck |
|---|---|---|
| Inferenz-Strategien | `dreamtool/inference.py`, Runner, Dashboard „Execution“ | chunk, receding-N, ensemble-N (ACT-Gewichte), crossfade-N; Greifer immer aus dem neuesten Plan |
| Strategy A/B | `dashboard/extensions/robustness/compare.py` | gepaarter Vergleich auf identischen Szenen: McNemar exakt, Bootstrap-KI, Jitter-Anteil, Seam-Ratio |
| Drop-Analyse | `robustness/monitor.py` | unterscheidet „losgelassen“ (Greifer öffnet) von „rausgerutscht“ |
| Model X-Ray | `dreamtool/xray.py`, Tab „X-Ray“ | geplante Bahnen (FK), Intent-Text, RISE-Heatmaps mit Zufallsniveau, Sprach-Probe |
| Kamera-Check | `dreamtool/camcheck.py`, Tab „Cameras“ | Live-Prüfung jedes gesendeten Bildes, Selbsttest mit 8 Fehlern, „Nutzt Dream-1 die Kamera?“ |
| Retry bei Kapazität | `dreamtool/runner.py` | DA-2000 `pool_full` wird bis 180 s abgewartet statt den Lauf abzubrechen |
| Latenz-Fix | `dreamtool/runner.py` (`latency="paused"`) | siehe V3 |
| Messwerkzeuge | `measurements/analyze.py`, `measurements/pool.py` | Tabellen pro Kampagne / über alle Kampagnen |

Tests: 158 bestanden (`python -m pytest`).

## Methodik

- **Metriken pro Trial:** Erfolg (Simulator-Check), Fortschritt 0–1 (erreicht 0,25 / gegriffen 0,5 / getragen 0,75 /
  abgelegt 1), nächste Annäherung, Endabstand Objekt–Behälter, Zeit bis Erfolg (Simulationszeit), Anzahl Anfragen,
  RTT, Sim- und Wandzeit, Gelenkgeschwindigkeit, Jitter-Anteil (Residuum nach 9-Schritt-Mittel), Seam-Ratio
  (Sprung an Chunk-Grenzen / typischer Schritt), Drops, Ergebnisklasse.
- **Budget:** 40 s Simulationszeit pro Trial (800 Steuerschritte à 50 ms), unabhängig von der Netzwerkzeit.
- **Paarung:** Im Compare-Modus läuft jede Strategie auf exakt derselben Szene (gleicher Seed/gleiche Störung).
  Statistik: McNemar exakt für Erfolg, Bootstrap-KI für Δ Fortschritt, Wilson-KI für Raten.
- **Datenprüfung nach jeder Serie:** `analyze.py` meldet Fehlertrials (z. B. pool_full), unvollständige Paare,
  unplausible Werte. Fehlertrials werden nie als Modellfehler gezählt.
- **Sequenziell:** Nach den `pool_full`-Abbrüchen der ersten Stunde laufen alle Messungen nacheinander in einer Session.

## Experimente und Ergebnisse

### Kamera-Pipeline (Anforderung 4)

| Test | Ergebnis |
|---|---|
| Selbsttest auf echtem Dream-1 (8 Fehler) | 8/8 erkannt, Kamera und Fehlerart korrekt benannt; Verzögerung als 525 ms bzw. 600 ms gemessen |
| Sauberer Lauf | alle drei Kameras „ok“, Match ≥ 0,998, Lag-Median 0 ms, 5,0 fps |
| camera_tilt 0/4/8°, light_dim 0/50/75 %, image_noise 0/10/20 σ, camera_shift 0/4 cm | Pipeline korrekt unter allen Bedingungen (Match ≥ 0,998, Lag 0). Einziger Fehlalarm: „eingefroren“ bei 75 % Dimmung → behoben (V1), Wiederholung 2×0 % und 2×75 %: alles ok |
| Unter Strategien chunk / receding-8 / crossfade-8 | keine Auffälligkeit |
| „Nutzt Dream-1 die Kameras?“ (Apfel) | Ausblenden top 4,13 cm, links 5,87 cm, rechts 1,46 cm, Handgelenke tauschen 2,81 cm – alle über der Schwelle, alle Kameras werden genutzt |

Robustheit des *Modells* gegenüber den Störungen (je 1–2 Trials, nur Hinweise): Kippen der Kamera um 8° und
Verschieben um 4 cm brechen den Apfel-Task, Dimmen und Bildrauschen bis 20 σ nicht eindeutig.

### Serie 1 – Baseline (ohne Latenz-Fix), 3 Prompts × 4 Strategien × 6 Paare

[`series1_baseline_n16.md`](measurements/2026-11-22/series1_baseline_n16.md)

| Prompt | chunk | receding-16 | ensemble-16 | crossfade-16 |
|---|---|---|---|---|
| Apfel → Schüssel | 2/6 | 2/6 | 0/6 | 0/6 |
| Banane → Teller | 0/6 | 0/6 | 0/6 | 0/6 |
| Orange → Teller | 0/5 | 0/5 | 0/4 | 0/4 (Abbruch durch pool_full, Trial nicht gezählt) |

Banane/Orange scheitern fast nur an `carry_failed` (Objekt gehoben, verloren). Crossfade-16 hat den geringsten
Jitter (24–25 % vs. 40–47 %) und die kleinsten Seams, aber keinen Erfolgsvorteil.

### Serie 2 – Chunk-Größen (Apfel, 6 Paare)

[`series2_chunk_sizes.md`](measurements/2026-11-22/series2_chunk_sizes.md): chunk 1/6, receding-8 0/6, receding-24 4/6,
crossfade-8 0/6, crossfade-24 3/6. Δ Fortschritt der 24er-Varianten +0,5 (KI ohne 0). Alle Drops „slipped“.
Befund: receding-8 führte nie einen neuen Plan aus (8 Zeilen < ~11 vom Client ersetzte Zeilen) → führte zu V3.

### Serie 3 – Horizonte 24/30 (8 Paare)

- Apfel ([`series3a`](measurements/2026-11-22/series3a_horizons_apple.md)): chunk 1/8 (7× nicht gegriffen),
  receding-24 2/8, receding-30 3/8, crossfade-30 3/8; Δ Fortschritt +0,375 [+0,12; +0,62] bzw. +0,406 [+0,25; +0,56].
- Orange ([`series3b`](measurements/2026-11-22/series3b_horizons_orange.md)): alle 0/8; Fortschritt chunk 0,38,
  receding-24 0,50 (KI +0,03…+0,25), crossfade-30 0,47, receding-30 0,28.

### Serie 4 – Prompt-Varianten (Apfel, 3 Trials je Variante, ohne Latenz-Fix)

[`series4_prompts.md`](measurements/2026-11-22/series4_prompts.md)

| Prompt | chunk | receding-24 |
|---|---|---|
| put the apple into the bowl | 0/3 | 2/3 |
| place the apple in the bowl | 3/3 | 1/3 |
| could you please pick up the apple and put it into the bowl? | 1/3 | 0/3 |
| apple -> bowl | 0/3 | 0/3 |
| put the red fruit into the bowl | 0/3 | 1/3 |

Keine Variante ist über beide Strategien konsistent besser; „place the apple in the bowl“ 3/3 mit chunk wird in
Serie 6b auf neuen Szenen gegengeprüft. Fortschritt bei receding-24 für alle Prompts ≥ 0,5 (chunk teils 0,25).

### Serie 5 – nach dem Latenz-Fix

- **5a Determinismus** (keine Störung, 4 Wiederholungen derselben Szene, [`series5a`](measurements/2026-11-22/series5a_paused_determinism.md)):
  chunk 1/4, receding-24 1/4, receding-30 2/4, crossfade-30 2/4 – Wiederholungen sind *nicht* identisch. Ursache
  isoliert mit [`determinism.py`](measurements/2026-11-22/determinism.py): gleiche Startpose, gleicher Gelenkzustand,
  aber unterschiedliche Bilder schon bei Anfrage 0 → erster Plan weicht um bis zu 0,029 rad ab, danach bis 0,13 rad
  ([`determinism_render_noise.json`](measurements/2026-11-22/determinism_render_noise.json)). Zwei Renderings desselben
  Zustands unterscheiden sich in 0,001–0,02 % der Pixel um genau 1 Graustufe (GPU-Rasterisierung).
- **5b Horizonte, target_shift 2 cm** (8 Paare, [`series5b`](measurements/2026-11-22/series5b_paused_target_shift.md)):

  | Strategie | Erfolg | Fortschritt | Anfragen | Jitter | Seam/Schritt | häufigster Fehler |
  |---|---|---|---|---|---|---|
  | chunk | 3/8 | 0,50 | 14 | 40 % | 2,70 | nicht gegriffen (4) |
  | receding-8 | 0/8 | 0,31 | 100 | 51 % | 3,28 | geschoben (6) |
  | receding-16 | 0/8 | 0,41 | 50 | 36 % | 2,13 | nicht gegriffen (4) |
  | receding-24 | 2/8 | 0,78 | 31 | 38 % | 1,68 | daneben gelegt (5) |
  | receding-30 | 3/8 | 0,66 | 24 | 40 % | 2,69 | getragen, verloren (2) |
  | crossfade-24 | 2/8 | 0,72 | 31 | 38 % | 1,42 | daneben gelegt (4) |

- **5c gleiche Szenen mit alter Client-Latenz** ([`series5c`](measurements/2026-11-22/series5c_client_target_shift.md)):
  chunk 1/8, receding-16 1/8, receding-24 2/8. Pro Szene gepaart gegen 5b streuen die Ergebnisse in beide Richtungen –
  bei diesem N ist kein Erfolgseffekt des Fixes messbar; der Fix ist trotzdem korrekt, weil er eine nachweislich
  falsche Annahme entfernt (siehe V3) und receding-8/16 erst damit wirklich neue Pläne ausführen.

### Über die ganze Nacht gepoolt

[`pooled_all_night.md`](measurements/2026-11-22/pooled_all_night.md) (alle Compare-Kampagnen, gepaart nur gleiche
Szene/gleicher Prompt):

| Strategie | Paare | Erfolg chunk | Erfolg Strategie | nur chunk | nur Strategie | McNemar p | Δ Fortschritt (95 %-KI) |
|---|---|---|---|---|---|---|---|
| receding-24 | 42 | 17 % | 26 % | 6 | 10 | 0,45 | **+0,31 [+0,17; +0,43]** |
| crossfade-30 | 20 | 10 % | 25 % | 0 | 3 | 0,25 | **+0,28 [+0,16; +0,39]** |
| crossfade-24 | 14 | 29 % | 36 % | 2 | 3 | 1,00 | **+0,34 [+0,16; +0,52]** |
| receding-30 | 28 | 18 % | 29 % | 3 | 6 | 0,51 | **+0,18 [+0,03; +0,33]** |
| receding-16 | 33 | 18 % | 9 % | 6 | 3 | 0,51 | +0,02 [−0,12; +0,15] |
| ensemble-16 | 16 | 12 % | 0 % | 2 | 0 | 0,50 | −0,09 [−0,20; 0,00] |
| crossfade-16 | 16 | 12 % | 0 % | 2 | 0 | 0,50 | −0,05 [−0,20; +0,09] |
| receding-8 | 14 | 29 % | 0 % | 4 | 0 | 0,13 | −0,20 [−0,41; 0,00] |

Apfel ungepaart: chunk 9/40 (22 %, davon 27× nicht gegriffen), receding-24 11/34 (32 %), receding-30 8/20 (40 %),
crossfade-30 5/12 (42 %), crossfade-24 5/14 (36 %).

<!-- SERIES6 -->

### Model X-Ray auf echtem Dream-1

[`xray_real/`](measurements/2026-11-22/xray_real/), Moment bei 78 s (Apfel):

- Dream-1 ist deterministisch: drei identische Anfragen → 0,0 cm Streuung, Ziel immer „apple“.
- Der neu erfragte Plan weicht 2,31 cm vom aufgezeichneten ab (Seam-Glättung des Clients).
- Sprach-Probe: folgt dem Objektwort in 1 von 4 Fällen – der Moment war aber zu spät (Arm schon am Apfel), daher
  V4. Mit dem Kunstwort „blicket“ geht es trotzdem zum Apfel.
- RISE (60 Masken): nur die Overhead-Kamera knapp über Zufallsniveau (0,57 vs. 0,56 cm) → 60 Masken reichen nicht.
- Ganze Kamera ausblenden: top 5,04, links 4,47, rechts 2,81 cm Planänderung.

<!-- XRAY2 -->

## Verbesserungen (jeweils durch eine Messung begründet und erneut gemessen)

| # | Schwachpunkt (Messung) | Änderung | Nachmessung |
|---|---|---|---|
| V1 | Kamera-Check meldete „eingefroren“ bei 75 % Dimmung, fps falsch | Graustufen-Änderung beider Seiten vergleichen; fps aus benachbarten Frames | 2×0 % + 2×75 % ohne Fehlalarm; Selbsttest erkennt eingefroren/Verzögerung/schwarz weiterhin; Regressionstest `test_dark_slow_scene_is_not_called_frozen` |
| V2 | Parallel laufende Messungen brachen mit DA-2000 `pool_full` ab (Serie 1 Orange bei 18/24) | Runner wartet retrybare Ablehnungen bis 180 s ab; X-Ray/Kamera-Tests mit einer Session; Messungen sequenziell | danach keine Fehlertrials mehr (ein Orange-Start um 01:20 brach vor dem Fix nach 1 Trial ab und wurde als `20261122-014508-compare` wiederholt) |
| V3 | receding-8 führte nie einen neuen Plan aus; Trial-Varianz hing von der RTT ab | `latency="paused"`: der Client bekommt `action_hz = 1e-3`, damit `round(rtt · hz) = 0` Zeilen ersetzt werden – im pausierenden Simulator die Wahrheit. `"client"` bleibt für alte Läufe/Vergleich wählbar | Serie 5b/5c; Unit-Test mit `dream.smoothing.old_motion`; alte Ergebnisse tragen im Report „· client latency“ |
| V4 | Sprach-Probe auf einem zu späten Moment | X-Ray behält die ersten 6 Momente eines Laufs (`FIRST_MOMENTS`) statt nur der letzten | siehe X-Ray-Wiederholung |
| V5 | Greifer-Blend > 1 und Blend des Greifers verzögert das Schließen | Greifer immer aus dem neuesten Plan, nur Armgelenke werden geblendet | Unit-Tests |
| V6 | Jerk-Index bevorzugte langsame Strategien | Jitter-Anteil (Residuum nach gleitendem Mittel) statt Jerk für „smoothest“ | Serie 1 ff. |

<!-- DEFAULT -->

## Offene Probleme

1. **Banane/Orange 0/74:** Objekt rutscht aus dem geschlossenen Greifer (Drop-Analyse: „slipped“, Greifer bleibt zu).
   Vermutlich Kontakt-/Reibungsparameter der Objekte oder Greifposition – kein Inferenzproblem, keine Strategie hilft.
2. **„Daneben gelegt“** ist bei langen Horizonten der häufigste Fehler (Apfel receding-24: 14/34).
3. **Signifikanz der Erfolgsquote:** Bei p_chunk ≈ 0,2 und p ≈ 0,35 braucht ein McNemar-Test grob 80–100 Paare.
   Der Fortschritts-Score ist das deutlich empfindlichere Maß und bereits signifikant.
4. **Render-Rauschen:** Für exakt reproduzierbare Wiederholungen müsste das Rendering deterministisch gemacht werden
   (CPU-Renderer/OSMesa oder Rundung vor dem JPEG). Bewusst nicht umgesetzt: das Rauschen wirkt wie echtes
   Sensorrauschen und macht Wiederholungen zu echten Stichproben.
5. **RISE** braucht mehr Masken (≥ 200) für belastbare Heatmaps; kostet entsprechend viele API-Aufrufe.
6. **Dream Input-Check:** Der Client warnt „no one has checked what the model sees …“. Die Aufzeichnung per
   `python -m dream.input_check` ist laut Dream einer Person vorbehalten („never an agent“) – bitte selbst ausführen.
   Der Kamera-Check liefert dafür die Belege.
7. Moritz’ Node-Test im Test-Suite-Bereich schlägt weiterhin fehl (bestand schon vor dieser Nacht).

## Reproduzieren

```
python measurements/analyze.py <out.md> <campaign id> ...
python measurements/pool.py <out.md> <campaign id> ...
python measurements/2026-11-22/drive.py 8001 measurements/2026-11-22/plan6.json log.jsonl   # Dashboard auf Port 8001
```

Kampagnen-IDs stehen in den `log*.jsonl` und in jeder Tabelle.
