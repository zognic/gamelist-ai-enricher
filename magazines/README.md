# magazines/

Place your retrogaming magazine files in this folder. The script will search them automatically for articles matching each game before querying the LLM, providing richer and more accurate metadata.

---

## Supported formats

| Format | How text is extracted | Notes |
|---|---|---|
| `.pdf` | Direct text extraction via **PyMuPDF** | Fast, no extra setup required |
| `.cbz` | OCR on each page image via **pytesseract** | Slower, requires additional setup (see below) |

### PDF — strongly recommended

PDF files with an embedded text layer (i.e. **OCR-processed PDFs**) give the best results. The script can extract text instantly without any image processing.

> ⚠️ **Scanned PDFs without OCR** (pure image scans) will appear empty to the script — no text will be found even if the magazine mentions the game. Always prefer OCR'd PDFs when available.

To check whether a PDF has a text layer, try selecting text in your PDF viewer. If you cannot select any text, the file is a raw image scan and needs OCR processing before use.

### CBZ — supported with additional setup

CBZ files (comic/magazine archives) contain page images with no embedded text. The script processes them using **Tesseract OCR** on each page image. This is significantly slower than PDF extraction but allows you to use CBZ files from sources that don't offer PDF downloads.

CBZ support requires two additional dependencies — see the [CBZ Setup](#cbz-setup) section below.

---

## CBZ Setup

### 1. Install Python dependencies

```bash
pip install pillow pytesseract
```

### 2. Install Tesseract on your system

Tesseract is an external binary that must be installed separately.

**macOS (Homebrew):**
```bash
brew install tesseract
brew install tesseract-lang  # includes French and other language packs
```

**Ubuntu / Debian:**
```bash
sudo apt install tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng
```

**Windows:**
Download the installer from the official repository:
[https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)

Then add the Tesseract install path to your system `PATH`, or set it manually in the script:
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

### 3. Verify Tesseract is working

```bash
tesseract --version
tesseract --list-langs  # should include 'eng' and 'fra'
```

> **Note on CBZ performance**: OCR runs on every page image. A 100-page magazine may take 1–3 minutes to scan depending on your machine. PDF files with a text layer are processed in under a second for the same content.

---

## How the search works

The script scans every file in this folder for the game title being processed. To avoid false positives, two filters are applied:

1. **Whole-word matching**: the title is searched as a complete word using a regex boundary (`\b`). For example, searching for `ICO` will not match `músico` or `erico`. Parenthetical suffixes like `ICO (USA)` are stripped before the search.

2. **Occurrence threshold**: a page is only kept if the game title appears **at least twice** on it. A single mention is treated as a passing reference (release schedule, advertisement) and ignored.

If a relevant page is found, its text is sent to the LLM as context. If nothing is found, the LLM falls back to its own training knowledge.

---

## Where to find retrogaming magazines

Below are known sources for retrogaming magazines in PDF or CBZ format. Always verify the legal status in your country before downloading.

### English-language magazines

| Source | URL | Formats | Notes |
|---|---|---|---|
| **Retromags** | [retromags.com](https://www.retromags.com) | CBZ, PDF | Community scans, good quality. Includes EGM, GameFan, GamePro, Nintendo Power, Edge and more |
| **Internet Archive** | [archive.org/details/gamemagazines](https://archive.org/details/gamemagazines) | PDF, CBZ | Large collection, OCR available on many titles. Free to access |

### French-language magazines

| Source | URL | Formats | Notes |
|---|---|---|---|
| **Abandonware Magazines** | [abandonware-magazines.org](https://www.abandonware-magazines.org) | PDF, CBZ | Dedicated to French retrogaming press. Covers Joystick, Tilt, Gen4, Consoles+, Player One and more. OCR present on some issues |
| **Internet Archive** | [archive.org](https://archive.org) | PDF | French titles available, variable OCR quality |

### Recommended titles by platform

| Platform | Useful magazines |
|---|---|
| PlayStation / PS2 | PlayStation Magazine (FR/EN), PSM, Official PlayStation Magazine |
| Nintendo / SNES / N64 | Nintendo Power, Super Play, Joypad |
| Sega / Mega Drive | Mean Machines Sega, Joystick, Consoles+ |
| Arcade / general | Joystick, Tilt, GamePro, GameFan |
| PC / DOS | Gen4, PC Games, PC Gamer |

---

## Tips for best results

- **Prefer OCR'd PDFs** over CBZ whenever both formats are available for the same issue.
- **Name your files clearly**: the filename is shown in the script output, so something like `joystick_042_1993.pdf` is easier to trace than `scan001.pdf`.
- **More issues = better coverage**: the more magazine issues you add, the higher the chance of finding a relevant article for a given game.
- **Language match**: if you use a French-language prompt, French magazines will produce better context. Same logic applies for English prompts and English magazines.
