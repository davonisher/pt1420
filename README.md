# greek-printer

Print de dagelijkse Griekse les op de **Powertech PT-1420** (mini "cat printer")
via Bluetooth LE, hier op de Mac. De PT-1420 laadt alleen op via USB-C — printen
gaat uitsluitend over BLE (adverteert als `X6h-0000`).

## Gebruik

```bash
# Les van vandaag printen (32 kolommen, ~18px lettertype)
python3 greek_print.py

# Voorbeeld van een specifieke lesdag
python3 greek_print.py --day 1

# Kleiner/groter: meer kolommen = kleiner lettertype
python3 greek_print.py --cols 40

# Alleen de tekst zien, niet printen
python3 greek_print.py --dry-run
```

Willekeurige tekst printen (los van de les):

```bash
python3 pt1420.py "Γεια σου! Hallo!"
echo "regel" | python3 pt1420.py -
python3 pt1420.py --file brief.txt
```

## Hoe het werkt

- `greek_print.py` draait het aparte **greek-tutor** project
  (`~/greek-tutor/learn_greek.py --dry-run`, of `GREEK_TUTOR_DIR`) met een
  tijdelijke config die `line_width` naar 32 zet, en print de uitvoer via
  `pt1420.py`. greek-tutor is een persoonlijk project en zit niet in deze repo;
  `pt1420.py` werkt op zichzelf voor iedereen met zo'n printer.
- `pt1420.py` is de herbruikbare driver: rendert tekst naar een 384px-brede
  1-bit afbeelding (monospace, auto-passend lettertype) en stuurt die met het
  cat-printer protocol naar characteristic `AE01`.

## Aandachtspunten

- **Zet de printer aan** en zorg dat hij niet verbonden is met een telefoon-app
  (BLE laat maar één verbinding tegelijk toe).
- `--dry-run` betekent dat greek-tutor de voortgang (spaced-repetition "seen")
  **niet** opslaat. Draai het echte greek-tutor project als je dat wel wilt.
- Vereist: `pip install --user bleak pillow`.
- Omgevingsvariabelen (optioneel): `PT1420_ADDRESS` (forceer een BLE-adres),
  `PT1420_NAME` (advertentienaam, default `X6h`), `PT1420_FONT` (pad naar een
  monospace-font met Grieks), `GREEK_TUTOR_DIR` (pad naar greek-tutor).
```
