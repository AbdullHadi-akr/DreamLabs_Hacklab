# Testübersicht – Nacht vom 21. auf den 22.11.2026

Kurzfassung aller Tests mit echtem Dream-1 im Simulator. Details, Methodik und Rohdaten:
[NIGHTLY_REPORT.md](NIGHTLY_REPORT.md) und [`measurements/2026-11-22/`](measurements/2026-11-22/).

**Umfang:** 397 Durchläufe in 23 Kampagnen, dazu Kamera-Selbsttests, ein Determinismus-Test und X-Ray-Analysen.
Verglichen wurde immer **paarweise**: Jede Strategie lief auf exakt derselben Szene. Jeder Durchlauf hatte 40 s
Simulationszeit.

---

## 1. Die Strategien

| Strategie | Was sie macht |
|---|---|
| **chunk** | Dream-1 liefert 48 Schritte (2,4 s), alle werden ausgeführt, dann folgt die nächste Anfrage (bisheriger Standard) |
| **receding-N** | nur die ersten N Schritte ausführen, dann neu fragen |
| **crossfade-N** | alle N Schritte neu fragen und vom alten zum neuen Plan weich überblenden |
| **ensemble-N** | alle Pläne, die einen Zeitpunkt abdecken, gewichtet mitteln |

---

## 2. Hauptergebnis: chunk gegen die anderen

Alle Kampagnen der Nacht zusammen, nur Paare auf derselben Szene.

| Strategie | Paare | Erfolg chunk | Erfolg Strategie | nur chunk gewinnt | nur Strategie gewinnt | Fazit |
|---|---|---|---|---|---|---|
| **crossfade-30** | 55 | 9 % | **42 %** | 3 | **21** | ✅ **signifikant besser (p ≈ 0,0003)** |
| receding-24 | 62 | 16 % | 29 % | 8 | 16 | besser, nicht signifikant (p = 0,15) |
| crossfade-24 | 14 | 29 % | 36 % | 2 | 3 | etwas besser, zu wenige Paare |
| receding-30 | 28 | 18 % | 29 % | 3 | 6 | etwas besser |
| receding-16 | 33 | 18 % | 9 % | 6 | 3 | ❌ nicht besser |
| crossfade-16 | 16 | 12 % | 0 % | 2 | 0 | ❌ schlechter |
| ensemble-16 | 16 | 12 % | 0 % | 2 | 0 | ❌ schlechter |
| receding-8 | 14 | 29 % | 0 % | 4 | 0 | ❌ deutlich schlechter |

**Fortschritt** (0 = nichts erreicht, 1 = abgelegt): crossfade-30 kommt im Schnitt um **+0,35** weiter als chunk
(95 %-Konfidenzintervall +0,26 bis +0,44).

### Apfel in die Schüssel (alle Versuche)

| Strategie | Erfolge | Quote | häufigster Fehler |
|---|---|---|---|
| chunk | 12 / 68 | 18 % | **nicht gegriffen** (46×) |
| receding-24 | 16 / 46 | 35 % | neben die Schüssel gelegt (15×) |
| receding-30 | 8 / 20 | 40 % | gegriffen, verloren (7×) |
| **crossfade-30** | **20 / 40** | **50 %** | neben die Schüssel gelegt (11×) |

**Warum?** chunk fährt 2,4 s „blind“, und zwar genau in der Annäherung, in der eine Korrektur nötig wäre. Deshalb
greift es meistens daneben. crossfade-30 plant alle 1,5 s neu und blendet ohne Sprung über.

---

## 3. Bestätigung unter neuen Bedingungen (crossfade-30 gegen chunk)

| Bedingung | chunk | crossfade-30 |
|---|---|---|
| neue Szenen, Apfel 2 cm verschoben (12 Paare) | 0 / 12 | **6 / 12** |
| Licht um 50 % gedimmt | 1 / 8 | **4 / 8** |
| Schüssel 3 cm verschoben | 2 / 8 | **5 / 8** |
| Banane auf den Teller | 0 / 7 | **3 / 8** (die einzigen Bananen-Erfolge der Nacht) |

➡️ **crossfade-30 ist jetzt Standard im Dashboard.** Die 8er- und 16er-Varianten sind aus dem Menü genommen,
weil sie gemessen schlechter waren. Per Name lassen sie sich weiter nutzen.

---

## 4. Prompt-Varianten (Apfel, je 3 Versuche)

| Prompt | chunk | receding-24 |
|---|---|---|
| put the apple into the bowl | 0 / 3 | 2 / 3 |
| place the apple in the bowl | 3 / 3 | 1 / 3 |
| could you please pick up the apple and put it into the bowl? | 1 / 3 | 0 / 3 |
| apple -> bowl | 0 / 3 | 0 / 3 |
| put the red fruit into the bowl | 0 / 3 | 1 / 3 |

Gegenprobe auf neuen Szenen: „place the apple in the bowl“ mit chunk nur **3 / 8**. Keine Formulierung ist dauerhaft
besser; die 3/3 waren Zufall einer einzelnen Szene.

---

## 5. Andere Früchte

| Aufgabe | Ergebnis | Ursache |
|---|---|---|
| Orange auf den Teller | **0 / 50** in allen Strategien | rutscht aus dem geschlossenen Greifer |
| Banane auf den Teller | 0 / 31 ohne crossfade-30, **3 / 8 mit crossfade-30** | meist ebenfalls rausgerutscht |

Das ist ein Physik- bzw. Greifproblem, kein reines Strategieproblem.

---

## 6. Kamera-Pipeline

| Test | Ergebnis |
|---|---|
| 8 absichtlich eingebaute Fehler (Kameras vertauscht, kopfüber, Farben vertauscht, eingefroren, 600 ms Verzögerung, schwarz, Zoom, doppelt) | ✅ **8 / 8 erkannt**, mit richtiger Kamera und Fehlerart |
| saubere Läufe | ✅ kein Fehlalarm, Verzögerung 0 ms, 5 Bilder/s |
| Kamera gekippt, Licht gedimmt, Bildrauschen, Kamera verschoben | ✅ Bilder kommen korrekt beim Modell an |
| Nutzt Dream-1 die Kameras? | ✅ ja: Ausblenden ändert den Plan um bis zu 9,5 cm (oben) bzw. 5,9 cm (Handgelenke) |

---

## 7. Model X-Ray (warum Dream-1 so handelt)

| Analyse | Ergebnis |
|---|---|
| Gleiche Anfrage mehrmals | Dream-1 ist exakt deterministisch (0,0 cm Abweichung) |
| Heatmap „Wo schaut es hin?“ | 78 s, Greifer am Apfel: die **Schüssel** und die Greiferspitze sind markiert, erstmals über dem Zufallsniveau. Beim zweiten Moment (4,5 s) liegt die Heatmap noch auf Zufallsniveau |
| Folgt es dem Wort im Prompt? | kurz vor und während des Griffs **nein** (0 von 3): Es bleibt beim Apfel, egal ob „banana“, „orange“ oder „bottle“ im Prompt steht |

---

## 8. Wichtige Erkenntnisse und behobene Messfehler

1. **Gleiche Szene heißt nicht gleiches Ergebnis.** Die Grafikkarte rendert minimal unterschiedlich (etwa 0,01 % der
   Pixel um eine Graustufe), und Dream-1 reagiert darauf. Ein einzelner Versuch sagt deshalb wenig, also wurden immer
   viele Paare gemessen.
2. **Künstliche Verzögerung behoben:** Der Dream-Client ersetzte die ersten ~11 Schritte jedes neuen Plans durch den
   alten, obwohl die Physik während der Anfrage pausiert.
3. **Hängender Versuch wird nicht mehr gezählt:** Ein Versuch hing im Standby rund 14 Minuten und wurde fälschlich als
   Fehlschlag gewertet. Solche Versuche werden jetzt aussortiert; betroffen war nur dieser eine.
4. **Kapazitätsfehler:** Bei „Dream-1 ist voll“ wartet das Tool jetzt, statt den Lauf abzubrechen.
5. **Kamera-Check:** Der falsche Alarm „eingefroren“ bei dunklem Licht ist behoben.

---

## 9. Offene Punkte

- **Orange** klappt nie, die **Banane** nur mit crossfade-30. Vermutlich liegt es an Reibung oder Greifposition.
- **„Neben die Schüssel gelegt“** ist der häufigste Restfehler mit crossfade-30.
- **receding-24 gegen crossfade-30** direkt ist kaum gemessen (5/12 gegen 6/12). Beide sind klar besser als chunk.
- Ob Dream-1 das Objektwort **früh in der Annäherung** nutzt, ist noch offen.
- Den **Dream Input-Check** muss eine Person selbst ausführen (nicht ein Agent):
  `python -m dream.input_check 4932209e541e`
