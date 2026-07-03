# pt1420

Drive the **Powertech PT-1420** mini thermal printer from a laptop or desktop
over **Bluetooth LE**.

The PT-1420 is a rebranded "cat printer" module. Its USB-C port **only charges**
the battery — it never shows up as a USB device, so you cannot print over the
cable. All printing goes over Bluetooth LE, where it advertises as `X6h-...` and
speaks the classic cat-printer protocol (GATT service `AE30`, write
characteristic `AE01`). This repo is a small, dependency-light driver for it.

- 🖨️ Print **text** (any Unicode; auto-fitting monospace font) or **images**
  (scaled to 384px and dithered to 1-bit).
- 💻 Runs from the command line or as a Python library.
- 🍎🐧🪟 Pure BLE via [`bleak`](https://github.com/hbldh/bleak), so it works on
  macOS, Linux, and Windows.

## Install

```bash
pip install bleak pillow
git clone https://github.com/davonisher/pt1420.git
cd pt1420
```

Turn the printer **on** and make sure it isn't connected to a phone app (BLE
allows only one connection at a time). The driver discovers it by name.

## Command line

```bash
python3 pt1420.py "Hello, world!"       # print text
echo "hi there" | python3 pt1420.py -    # print from stdin
python3 pt1420.py --file notes.txt       # print a text file
python3 pt1420.py --image logo.png       # print an image (scaled + dithered)
```

## Library

```python
import asyncio
import pt1420

asyncio.run(pt1420.print_text("Hello!\nΓεια σου!"))
asyncio.run(pt1420.print_image(pt1420.image_from_file("photo.jpg")))
```

Key building blocks: `text_to_image(text)`, `image_from_file(path)`,
`image_to_stream(img)` (encode to the cat-printer wire format), and the async
`print_image(img)` / `print_text(text)`.

## Examples

Two runnable examples live in [`examples/`](examples/):

| Example | Shows |
| --- | --- |
| [`print_image.py`](examples/print_image.py) | Print a photo/logo/QR from a file, with an optional text caption stacked underneath. |
| [`greek_lesson.py`](examples/greek_lesson.py) | Generate text with an external program and print it — here, a daily Greek lesson from the author's separate `greek-tutor` project. |

```bash
python3 examples/print_image.py logo.png --caption "Printed from my laptop"
python3 examples/greek_lesson.py --dry-run
```

## How it works

Each print is rendered to a 384px-wide, 1-bit image, then encoded as a stream of
cat-printer command frames:

```
0x51 0x78 <cmd> 0x00 <len_lo> <len_hi> <payload...> <crc8> 0xFF
```

CRC8 uses polynomial `0x07` (init `0x00`) over the payload. The sequence is
`get-state → set-quality → image-mode → set-energy → lattice-start →
one 0xA2 draw command per pixel row (48 bytes, LSB-first) → lattice-end →
feed → get-state`. Rows are written to `AE01` (write-without-response) in ~120
byte chunks; status comes back on `AE02`.

## Configuration (environment variables)

| Variable | Purpose | Default |
| --- | --- | --- |
| `PT1420_ADDRESS` | Force a specific BLE address/UUID instead of discovering by name | *(discover by name)* |
| `PT1420_NAME` | Advertised-name prefix to match | `X6h` |
| `PT1420_FONT` | Path to a monospace `.ttf` with the glyphs you need | auto-detect |
| `GREEK_TUTOR_DIR` | Location of the `greek-tutor` checkout (Greek example only) | `~/greek-tutor` |

## Notes

- Darkness is set via `ENERGY` (default `0x3FFF`); raise it if prints look
  faint. A fuller battery also prints darker.
- If text ever prints garbled/mirrored, flip `MSB_FIRST` — bit order within a
  byte varies across cat-printer clones; `False` (LSB-first) is correct here.

## License

MIT — see [LICENSE](LICENSE).
