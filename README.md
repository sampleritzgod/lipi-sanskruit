# Lipi-Sanskruit

Reads old handwritten Nagari manuscripts into modern Devanagari and explains them in Hindi and Sanskrit. See [PLAN.md](PLAN.md) for goals and phases.

## Layout

| Path | What goes there |
|---|---|
| `data/raw/book/` | Lipi-reading book pages (glyph tables) |
| `data/raw/manuscripts/` | Manuscript scans: photos or PDFs, any subfolders |
| `data/raw/refs/` | Reference PDFs: dictionaries, grammars |
| `data/processed/<file_id>/` | Generated: every book/manuscript page as `page-NNN.jpg` |
| `data/lines/<file_id>/page-NNN/` | Generated: one image per text line, plus `overlay.jpg` |
| `data/inventory.csv` | Generated + hand-edited list of every file |
| `data/gold/` | Expert-verified transcriptions (the test set) |
| `ml/` | Python pipeline: inventory, reading, training, evaluation |
| `services/` | API (Phase 6) |
| `apps/` | Web app (Phase 6) |

## Adding data

1. Copy files into `data/raw/manuscripts/` (or `book/`, `refs/`).
2. Run:
   ```sh
   cd ml
   uv run lipi-inventory
   ```
3. Open `data/inventory.csv` and fill in the hand columns for each file:
   - `script`: e.g. jain-nagari, devanagari
   - `language`: sanskrit, prakrit, hindi, braj, old-gujarati
   - `era`: century if known, e.g. 17c
   - `condition`: `clear`, `average` or `damaged`
   - `rotation`: `0`, `90`, `180` or `270` (clockwise, to make text upright)
   - `notes`

   Re-running the inventory keeps these columns, even if files are renamed or moved.

## Building the gold set (Phase 1)

1. Cut manuscript pages into lines (writes `data/lines/`; check each page's `overlay.jpg`):
   ```sh
   cd ml
   uv run lipi-segment
   ```
2. Read [data/gold/CONVENTIONS.md](data/gold/CONVENTIONS.md), then start the transcription tool:
   ```sh
   uv run lipi-transcribe --name <your-name>
   ```
   It opens http://127.0.0.1:8765. Type each line and press Enter. Every line is saved at once to `data/gold/<file_id>/page-NNN.json`.

## Measuring accuracy

Compare a website reading (job id from the URL, `#job=<id>`) with the typed gold page:

```sh
cd ml
uv run lipi-eval <job_id> <file_id>/page-001
```

## Tests

```sh
cd ml && uv run pytest
```
