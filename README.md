# gamelist-ai-enricher

A command-line tool that automatically enriches EmulationStation / Batocera `gamelist.xml` files using a local LLM via **Ollama**.

For each game missing metadata, the script:
1. Searches for relevant information in a folder of retrogaming PDF magazines (optional)
2. Sends the context to a local LLM (Mistral by default)
3. Injects the generated metadata (`desc`, `genre`, `releasedate`, `developer`, `publisher`, `players`) into the XML

The source file is **never modified** — results are always written to `gamelist_updated.xml`.

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Ollama Setup](#ollama-setup)
- [File Structure](#file-structure)
- [Usage](#usage)
- [JSON Prompt System](#json-prompt-system)
- [How It Works](#how-it-works)
- [FAQ / Troubleshooting](#faq--troubleshooting)

---

## Requirements

- Python **3.10** or higher
- [Ollama](https://ollama.com) installed and running
- A LLM model downloaded in Ollama (e.g. `mistral`)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/gamelist-ai-enricher.git
cd gamelist-ai-enricher
```

### 2. Install Python dependencies

```bash
pip install requests pymupdf
```

| Package | Purpose |
|---|---|
| `requests` | HTTP calls to the Ollama API |
| `pymupdf` (`fitz`) | Reading and extracting text from PDF files |

All other modules used (`os`, `re`, `json`, `xml.etree.ElementTree`, `argparse`) are part of the Python standard library — no additional installation needed.

---

## Ollama Setup

### Install Ollama

Go to [https://ollama.com](https://ollama.com) and follow the instructions for your operating system (macOS, Linux, Windows).

### Download a model

```bash
ollama pull mistral
```

Other models also work well for this task:

```bash
ollama pull llama3
ollama pull gemma2
ollama pull phi3
```

> **Recommendation**: `mistral` and `llama3` give the best results for respecting language constraints and structured JSON output. Smaller models (Phi-3, Gemma 2B) may struggle to follow all instructions reliably.

### Verify Ollama is running

```bash
ollama serve
```

By default, Ollama listens on `http://localhost:11434`. If you use a different address or model, edit the constants at the top of the script:

```python
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "mistral"  # Change this to use a different model
```

---

## File Structure

```
gamelist-ai-enricher/
│
├── gamelist_updater.py       # Main script
├── gamelist.xml              # Your source gamelist (you provide this)
│
├── prompts/
│   ├── prompt_default.json   # Default prompt (French, epic journalistic tone)
│   └── prompt_english.json   # Alternative prompt example (English, factual tone)
│
└── magazines/                # (Optional) Retrogaming PDF magazines
    ├── joystick_123.pdf
    ├── playstation_magazine_45.pdf
    └── ...
```

### The `magazines/` folder (optional)

Place retrogaming PDF magazines here (Joystick, PlayStation Magazine, Edge, etc.). Before calling the LLM, the script will search these files for articles matching the game being processed, providing richer context to the model.

If the folder is absent or no relevant article is found, the LLM falls back to its own training knowledge.

---

## Usage

### General syntax

```bash
python gamelist_updater.py [OPTIONS]
```

### Available options

| Option | Description |
|---|---|
| *(none)* | Process all games in the gamelist that have no description |
| `-add "Game Name"` | Add a new game or notify that it already exists |
| `-rom "term"` | Find games whose name contains the term and enrich them |
| `-f` / `--force` | Force overwrite of existing metadata |
| `-prompt path.json` | Use a custom prompt file |

---

### Detailed examples

#### Process the entire gamelist

Enriches only games **without a description**. Games that already have metadata are skipped.

```bash
python gamelist_updater.py
```

Typical output:
```
  [Prompt] 'Default Prompt - Retrogaming FR' loaded from './prompts/prompt_default.json'

[1/42] Processing: 'ICO'
  -> Searching in magazines...
  -> 3 occurrence(s) of 'ICO' in 'playstation_mag_12.pdf' p.47 -- page kept.
  -> Article found! Sending to AI...
  -> Done successfully.

[2/42] Processing: 'God of War'
  -> Searching in magazines...
  -> No article found. AI will use its own knowledge.
  -> Done successfully.

[3/42] Processing: 'Shadow of the Colossus'
  -> Description already present. Skipped (use -f to force).
...
Done! 35 game(s) updated -> 'gamelist_updated.xml'.
```

---

#### Force update the entire gamelist

Overwrites all existing metadata, including descriptions already present.

```bash
python gamelist_updater.py -f
```

---

#### Add a game that doesn't exist in the gamelist

Creates a new `<game>` entry with an auto-generated `<path>`, then enriches it.

```bash
python gamelist_updater.py -add "ICO"
```

Output:
```
  [Prompt] 'Default Prompt - Retrogaming FR' loaded from './prompts/prompt_default.json'
Game 'ICO' not found. Creating new entry...

[1/1] Processing: 'ICO'
  -> Searching in magazines...
  -> No article found. AI will use its own knowledge.
  -> Done successfully.

File 'gamelist_updated.xml' updated.
```

Result in `gamelist_updated.xml`:
```xml
<game>
    <path>./ICO.iso</path>
    <name>ICO</name>
    <desc>Perched atop a mysterious castle, ICO must guide Yorda, a fragile prisoner, toward freedom. Solving environmental puzzles and shielding your companion from shadow creatures, you will experience an adventure of rare poetry. A contemplative masterpiece on PlayStation 2 that redefines the notion of emotional bond in video games.</desc>
    <genre>Adventure / Puzzle</genre>
    <releasedate>20011122T000000</releasedate>
    <developer>Team Ico</developer>
    <publisher>Sony Computer Entertainment</publisher>
    <players>1</players>
</game>
```

---

#### Update a game that already exists

If the game is already in the gamelist, `-add` alone will display a warning. Add `-f` to force the update.

```bash
python gamelist_updater.py -add "ICO" -f
```

Output:
```
Game 'ICO' already exists in 'gamelist_updated.xml'.
Force mode active: updating...

[1/1] Processing: 'ICO'
  -> Searching in magazines...
  -> Done successfully.

File 'gamelist_updated.xml' updated.
```

---

#### Search and enrich games by keyword

Filters all games whose `<name>` contains the search term, and enriches those without a description.

```bash
python gamelist_updater.py -rom "God of War"
```

Multiple matches:
```
[1/3] Processing: 'God of War'
  -> Done successfully.

[2/3] Processing: 'God of War II'
  -> Description already present. Skipped (use -f to force).

[3/3] Processing: 'God of War III'
  -> Done successfully.
```

Force update all matches:

```bash
python gamelist_updater.py -rom "God of War" -f
```

---

#### Use a custom prompt

```bash
python gamelist_updater.py -prompt ./prompts/prompt_english.json
```

Combined with other options:

```bash
# Custom prompt + add a specific game
python gamelist_updater.py -prompt ./prompts/prompt_english.json -add "ICO"

# Custom prompt + search and force update
python gamelist_updater.py -prompt ./prompts/prompt_english.json -rom "Zelda" -f

# Custom short prompt + full gamelist
python gamelist_updater.py -prompt ./prompts/prompt_short.json
```

---

## JSON Prompt System

The LLM's behavior is entirely driven by `.json` files in the `prompts/` folder. This lets you create multiple profiles — different languages, tones, or description lengths — without touching the code.

### Full structure of a prompt file

```json
{
    "name": "Name displayed when the script starts",
    "description": "Internal note describing this prompt (not sent to the LLM)",

    "role": "Who the LLM is — its identity and area of expertise.",

    "goal": "What it must produce — the final objective in one sentence.",

    "steps": [
        "Step 1: verify the game exists.",
        "Step 2: validate the provided context.",
        "Step 3: write the description.",
        "Step 4: fill in the remaining metadata fields."
    ],

    "tone": "Desired writing style (optional).",

    "language": "Language constraint for the description field (optional).",

    "constraints": [
        "Absolute rule #1.",
        "Absolute rule #2."
    ],

    "input_variables": {
        "nom_brut": "{nom_brut}",
        "contexte_pdf": "{contexte_pdf}"
    },

    "output_example": {
        "is_real_game": true,
        "real_name": "Exact game name",
        "desc": "Generated description.",
        "genre": "Genre",
        "releasedate": "YYYYMMDDTHHMMSS",
        "developer": "Studio",
        "publisher": "Publisher",
        "players": "1"
    }
}
```

### Key reference

| Key | Required | Description |
|---|---|---|
| `name` | ✅ | Name displayed in the terminal when the prompt loads |
| `description` | ❌ | Internal note, not transmitted to the LLM |
| `role` | ✅ | Defines the LLM's identity (e.g. journalist, database expert) |
| `goal` | ✅ | The overall objective of the task |
| `steps` | ✅ | Ordered list of instructions. Supports the `{nom_brut}` variable |
| `tone` | ❌ | Stylistic guidance (epic, factual, concise…) |
| `language` | ❌ | Language constraint for the description field |
| `constraints` | ❌ | Hard rules passed as-is to the LLM |
| `input_variables` | ❌ | Documents the injected variables (informational only, not processed) |
| `output_example` | ✅ | JSON object shown to the LLM as a format reference |

### The `{nom_brut}` variable in steps

In the `steps` array, you can use `{nom_brut}` to reference the name of the game currently being processed. The script replaces it automatically before sending the prompt.

```json
"steps": [
    "If '{nom_brut}' is not a real known video game, return {\"is_real_game\": false}.",
    "Check that the context is specifically about '{nom_brut}' and not another game."
]
```

> ⚠️ **Important**: if your step text contains literal JSON curly braces (e.g. `{"is_real_game": false}`), they must be escaped as standard JSON strings: `{\"is_real_game\": false}`. This is standard JSON escaping — your editor or validator will confirm it.

### The `output_example` field

This is a standard JSON object (not a string). It is serialized and injected at the end of the prompt as a format reference. Showing the LLM a concrete example of the expected output is the most reliable way to get consistent, well-structured responses.

```json
"output_example": {
    "is_real_game": true,
    "real_name": "ICO",
    "desc": "Three epic sentences in French...",
    "genre": "Adventure / Puzzle",
    "releasedate": "20011122T000000",
    "developer": "Team Ico",
    "publisher": "Sony Computer Entertainment",
    "players": "1"
}
```

The `releasedate` field follows the EmulationStation format: `YYYYMMDDTHHMMSS` (e.g. `20010922T000000`).

---

### Custom prompt examples

#### Short, factual French prompt

```json
{
    "name": "Short prompt - FR factual",
    "description": "One-sentence description, factual data only.",
    "role": "Video game database, specialized in retrogaming.",
    "goal": "Generate a short and accurate metadata entry in JSON format.",
    "steps": [
        "If '{nom_brut}' is not a real game, return {\"is_real_game\": false}.",
        "Write 'desc' as a SINGLE factual sentence describing the game and its gameplay.",
        "Fill all other fields with verified data."
    ],
    "tone": "Factual, neutral, encyclopedic.",
    "language": "French.",
    "constraints": [
        "Respond only with the JSON object. No surrounding text.",
        "The description must be exactly one sentence.",
        "Do not invent data."
    ],
    "output_example": {
        "is_real_game": true,
        "real_name": "ICO",
        "desc": "Jeu d'aventure et de réflexion sur PS2 dans lequel le joueur guide une jeune fille à travers un château en résolvant des énigmes.",
        "genre": "Aventure / Puzzle",
        "releasedate": "20011122T000000",
        "developer": "Team Ico",
        "publisher": "Sony Computer Entertainment",
        "players": "1"
    }
}
```

#### English prompt

```json
{
    "name": "English prompt - Retrogaming EN",
    "description": "2-sentence English description, factual tone.",
    "role": "Video game database expert and retrogaming journalist for an international audience.",
    "goal": "Generate complete video game metadata in strict JSON format, in English.",
    "steps": [
        "If '{nom_brut}' is not a real known video game, return {\"is_real_game\": false}.",
        "CONTEXT VALIDATION: Only use the magazine context if it explicitly and primarily discusses '{nom_brut}'. If the context is about a different game or topic, ignore it entirely and rely on your own knowledge.",
        "Write 'desc' in exactly 2 sentences: (1) game universe and setting, (2) core gameplay mechanic.",
        "Fill all metadata fields accurately."
    ],
    "tone": "Clear, engaging, informative.",
    "language": "English for all fields.",
    "constraints": [
        "Respond ONLY with the JSON object. No text before or after.",
        "'desc' must be exactly 2 sentences, no more, no less.",
        "Do not invent data: omit unknown fields rather than guessing."
    ],
    "output_example": {
        "is_real_game": true,
        "real_name": "ICO",
        "desc": "ICO is a haunting puzzle-adventure set in a crumbling castle where a horned boy must guide a mysterious girl to freedom. Players escort Yorda through environmental puzzles while fending off shadow creatures that seek to reclaim her.",
        "genre": "Adventure / Puzzle",
        "releasedate": "20011122T000000",
        "developer": "Team Ico",
        "publisher": "Sony Computer Entertainment",
        "players": "1"
    }
}
```

#### Arcade prompt (short descriptions, focus on controls)

```json
{
    "name": "Arcade prompt - EN",
    "description": "Focused on arcade games: controls, coins, high score culture.",
    "role": "Arcade game historian and retrogaming enthusiast.",
    "goal": "Generate metadata for classic arcade games with a focus on their cabinet and gameplay experience.",
    "steps": [
        "If '{nom_brut}' is not a real arcade game, return {\"is_real_game\": false}.",
        "Write 'desc' in exactly 2 sentences: (1) the arcade cabinet experience and theme, (2) controls and objective.",
        "Fill all metadata fields. For arcade games, 'players' can be '1-2'."
    ],
    "tone": "Nostalgic, energetic, arcade culture.",
    "language": "English.",
    "constraints": [
        "Respond only with the JSON. No preamble.",
        "Exactly 2 sentences for 'desc'.",
        "Set 'publisher' to the arcade manufacturer (Namco, Capcom, Konami, etc.)."
    ],
    "output_example": {
        "is_real_game": true,
        "real_name": "Pac-Man",
        "desc": "Pac-Man defined an era with its iconic yellow protagonist navigating mazes through neon-lit arcades around the world. Guide Pac-Man through the maze eating dots and power pellets while avoiding four relentless ghosts.",
        "genre": "Maze / Action",
        "releasedate": "19800722T000000",
        "developer": "Namco",
        "publisher": "Namco",
        "players": "1-2"
    }
}
```

---

## How It Works

### Processing pipeline

```
gamelist.xml
     │
     ▼
Load XML
     │
     ▼
For each <game> without a description
     │
     ├──► Search PDFs in ./magazines/
     │         │
     │         ├── Whole-word regex (\b) on the game title
     │         └── Relevance filter: at least 2 occurrences per page
     │                   (avoids false positives)
     │
     ├──► Build prompt text from the JSON file
     │         │
     │         └── Inject {nom_brut} and the PDF context
     │
     ├──► Call Ollama (POST /api/generate)
     │
     ├──► Parse the JSON response
     │
     └──► Inject metadata into the XML element
               │
               ▼
        gamelist_updated.xml
```

### False positive protection in PDF search

The script uses two mechanisms to avoid pulling irrelevant context from magazines:

1. **Whole-word regex** (`\bico\b`): the word `ICO` will not match `músico`, `erico`, `xico`, etc. Game titles with parenthetical suffixes like `ICO (USA)` are automatically cleaned before the search.

2. **Occurrence filter**: a page is only kept if the game title appears **at least twice** on it. A single mention is treated as a passing reference (release list, advertisement) and ignored, with a log message explaining why.

Additionally, the prompt explicitly instructs the LLM to **validate the context** before using it, and to ignore it entirely if the content does not clearly relate to the requested game.

### Save logic

| Situation | File read | File written |
|---|---|---|
| No argument | `gamelist.xml` | `gamelist_updated.xml` |
| `-add` or `-rom` | `gamelist_updated.xml` if it exists, otherwise `gamelist.xml` | `gamelist_updated.xml` |

The source file `gamelist.xml` is **never modified**.

---

## FAQ / Troubleshooting

**The script cannot connect to Ollama**

Make sure Ollama is running:
```bash
ollama serve
curl http://localhost:11434/api/tags
```

**The model responds in English despite a French prompt**

Smaller models (Phi-3, Gemma 2B) sometimes struggle to respect language constraints. Switch to `mistral` or `llama3` for better instruction-following:
```bash
ollama pull mistral
```
Then update `MODEL_NAME = "mistral"` at the top of the script.

**`KeyError` when building the prompt**

If your `steps` text contains literal JSON curly braces like `{"key": "value"}`, they must be escaped in the JSON file: `{\"key\": \"value\"}`. This is standard JSON — any JSON validator will catch the issue.

**Too many false positives from magazines**

If a short game title (e.g. `Out`, `War`, `Run`) generates too many irrelevant matches, you can raise the occurrence threshold in the script:
```python
if occurrences < 2:  # Increase this value to 3 or 4 for stricter filtering
```

**The output XML is not indented**

Automatic indentation requires Python 3.9+. On Python 3.8, the output file will be valid XML but unindented.

**A game is marked as not real by the LLM**

Some obscure or region-specific titles may not be recognized by the model. Try adding more context in the game name (e.g. `"ICO (PS2)"` instead of `"ICO"`), or switch to a larger model.
