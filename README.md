# xerox-poster-generator

*Python-Skript zum Erstellen von Punk-Postern im Fotokopierstil (Xerox).*

---
## Was das Script macht

- Erstellt anhand von vorgegebenen Fotos einen Punk-Poster in einem Fotokopierstil
- Posters werden lokal als `.png` gespeichert
- Musiker-/Band-Name, Datum, Preis, Lokal und Ort werden randomisiert irgendwo auf dem Poster platziert (wobei gewisse Regeln vorhanden sind)
- Poster haben immer verschiedene Hauptfarben
- Die Texte auf den Postern haben zufällige Fonts
- Poster hat einen "Fotokopier"-Effekt drauf
- Beispiel-Daten für Musiker- / Band-Namen, Datum, Preis, Lokal und Ort werden von einer JSON-Datei zufällig herausgelesen

---
## Setup

- Fonts müssen im `fonts/` vorhanden sein, kann man auch mit anderen Fonts ergänzen
- MusikerInnen / Band Fotos müssen in `images/` liegen
- Eine `.json`-Datei im selben Ordner wie der Skript, der Beispiel-Daten für die Events vorgibt

Python Libraries `numpy`, `scipy` und `pillow` müssen installiert sein. Auf Linux/MacOS kann man das wie folgt machen (als Python venv installieren). Im Ordner, wo das Python-Script liegt:

```Sh
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install pillow numpy scipy
```

---
## Usage

Das Script kann wie folgt ausgeführt werden.

Alle Fotos in `images/` werden in `posters/` erstellt:
```
python3 poster.py
```

Explizite Folders nennen:
```
python poster.py images/ out/
```

3 verschiedene Poster-Varianten pro Foto:
```
python poster.py images/ --variants=3
```

Neuer Seed (neues zufälliges Layout und Farben):
```
python poster.py --reroll # new random layout/colours
```

Ein explizites Poster wird generiert:
```
python poster.py image.jpg # single poster
```

---
## index.html

`index.html` ist als Prototyp da, um die Posters auf einer Website zu displayen (wie was wieso warum wo wann).

Nutzung:
- `index.html` öffnen (am Besten als Server, bspw. mit dem Live-Server Plugin im VSCode)
- Je nachdem, werden die Posters direkt auf der Website geladen. Wenn nicht, dann muss man per Drag&Drop die Posters auf die Seite laden.

---
## KI-Nutzung

Python-Skript und `index.html` wurden mit KI erstellt.