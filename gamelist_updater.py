import os
import re
import zipfile
import logging
import requests
import json
import xml.etree.ElementTree as ET
import argparse
import fitz  # PyMuPDF

try:
    from PIL import Image
    import pytesseract
    CBZ_SUPPORT = True
except ImportError:
    CBZ_SUPPORT = False

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

OLLAMA_URL        = "http://localhost:11434/api/generate"
MODEL_NAME        = "mistral"
MAGAZINES_DIR     = "./magazines/"
SOURCE_FILE       = "gamelist.xml"
OUTPUT_FILE       = "gamelist_updated.xml"
DEFAULT_PROMPT    = "./prompts/prompt_default.json"
LOG_FILE          = "gamelist_updater.log"


# ─────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────
# All messages go to the log file.
# Only high-level progress messages are printed to the terminal.

logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def log(msg, level="info"):
    """Write a message to the log file only."""
    getattr(logging, level)(msg)

def out(msg, level="info"):
    """Print a message to the terminal AND write it to the log file."""
    print(msg)
    getattr(logging, level)(msg)


# ─────────────────────────────────────────────
# Prompt loading
# ─────────────────────────────────────────────

def load_prompt(json_path):
    """
    Load a structured prompt from a JSON file with named keys:
    {
        "name":           "Human-readable name",
        "role":           "LLM identity and expertise",
        "goal":           "What the LLM must produce",
        "steps":          ["Step 1", "Step 2", ...],
        "tone":           "Writing style (optional)",
        "language":       "Language constraint (optional)",
        "constraints":    ["Hard rule 1", ...] (optional),
        "output_example": { ... }  (JSON object used as format reference)
    }
    Raises FileNotFoundError or ValueError on invalid input.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(
            f"Prompt file not found: '{json_path}'\n"
            f"Create a JSON file in ./prompts/ or specify -prompt <path>."
        )
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for key in ("name", "role", "goal", "steps", "output_example"):
        if key not in data:
            raise ValueError(
                f"Prompt file '{json_path}' is missing required key: '{key}'."
            )
    out(f"  [Prompt] '{data['name']}' loaded from '{json_path}'")
    log(f"Prompt loaded: {json_path}")
    return data


def build_prompt_text(prompt_data, game_name, pdf_context):
    """
    Reconstruct the full prompt string from the structured JSON keys.
    Injects game_name and pdf_context at the appropriate locations.
    Uses str.replace() instead of str.format() to avoid conflicts
    with literal curly braces in step descriptions (e.g. JSON examples).
    """
    lines = []
    lines.append(f"ROLE: {prompt_data['role']}\n")
    lines.append(f"GOAL: {prompt_data['goal']}\n")
    lines.append("STEPS:")
    for i, step in enumerate(prompt_data["steps"], 1):
        lines.append(f"  {i}. {step.replace('{nom_brut}', game_name)}")
    lines.append("")
    if prompt_data.get("tone"):
        lines.append(f"TONE: {prompt_data['tone']}\n")
    if prompt_data.get("language"):
        lines.append(f"LANGUAGE: {prompt_data['language']}\n")
    if prompt_data.get("constraints"):
        lines.append("CONSTRAINTS:")
        for c in prompt_data["constraints"]:
            lines.append(f"  - {c}")
        lines.append("")
    lines.append("INPUT DATA:")
    lines.append(f"  Game name: {game_name}")
    lines.append(f"  Magazine context:\n{pdf_context}\n")
    lines.append("EXPECTED OUTPUT FORMAT (example):")
    lines.append(json.dumps(prompt_data["output_example"], ensure_ascii=False, indent=2))
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────

def clean_json_response(text):
    """Strip markdown code fences that some LLMs add around JSON output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def build_search_pattern(game_name):
    """
    Build a whole-word regex pattern for the game title.
    - Strips parenthetical/bracket suffixes: "ICO (USA)" -> "ICO"
    - Uses word boundaries (\b) to avoid partial matches:
      "ICO" will not match "musico" or "erico"
    """
    title         = game_name.split('(')[0].split('[')[0].strip()
    title_escaped = re.escape(title)
    return re.compile(r'\b' + title_escaped + r'\b', re.IGNORECASE)


# ─────────────────────────────────────────────
# Magazine search — PDF
# ─────────────────────────────────────────────

def extract_from_pdf(path, pattern, clean_title, context):
    """
    Scan a PDF file for pages relevant to the game being searched.
    Only keeps pages where the title appears at least twice
    (single mentions are likely off-topic references).
    Returns (updated_context, limit_reached).
    """
    filename = os.path.basename(path)
    try:
        doc = fitz.open(path)
    except Exception as e:
        log(f"Cannot open PDF '{filename}': {e}", "warning")
        return context, False

    for page_num in range(len(doc)):
        page      = doc.load_page(page_num)
        page_text = page.get_text("text")

        if not pattern.search(page_text):
            continue

        occurrences = len(pattern.findall(page_text))
        if occurrences < 2:
            log(f"Single mention of '{clean_title}' in '{filename}' p.{page_num+1} — skipped.")
            continue

        out(f"  -> {occurrences} match(es) in '{filename}' p.{page_num+1} — kept.")
        log(f"PDF match: '{clean_title}' x{occurrences} in '{filename}' p.{page_num+1}")
        context += f"\n--- Extract from '{filename}' (Page {page_num + 1}) ---\n" + page_text

        if len(context) > 4000:
            doc.close()
            return context, True  # context size limit reached

    doc.close()
    return context, False


# ─────────────────────────────────────────────
# Magazine search — CBZ
# ─────────────────────────────────────────────

def extract_from_cbz(path, pattern, clean_title, context):
    """
    Scan a CBZ file for pages relevant to the game being searched.
    Each image inside the ZIP archive is treated as one magazine page.
    Text is extracted via Tesseract OCR — significantly slower than PDF.
    OCR errors are silently logged and never shown in the terminal output.
    Returns (updated_context, limit_reached).
    """
    if not CBZ_SUPPORT:
        out("  -> CBZ support not available. Install: pip install pillow pytesseract (+ Tesseract)")
        log("CBZ support unavailable — pillow/pytesseract not installed.", "warning")
        return context, False

    filename = os.path.basename(path)

    try:
        with zipfile.ZipFile(path, 'r') as cbz:
            # Sort image entries to preserve reading order
            images = sorted([
                f for f in cbz.namelist()
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ])

            for page_num, image_name in enumerate(images):
                try:
                    with cbz.open(image_name) as img_file:
                        image     = Image.open(img_file).convert("RGB")
                        page_text = pytesseract.image_to_string(image, lang="fra+eng")
                except Exception as e:
                    # OCR errors are logged silently — never printed to terminal
                    log(f"OCR error on '{filename}' p.{page_num+1} ({image_name}): {e}", "warning")
                    continue

                if not pattern.search(page_text):
                    continue

                occurrences = len(pattern.findall(page_text))
                if occurrences < 2:
                    log(f"Single mention of '{clean_title}' in '{filename}' p.{page_num+1} (CBZ) — skipped.")
                    continue

                out(f"  -> {occurrences} match(es) in '{filename}' p.{page_num+1} (CBZ/OCR) — kept.")
                log(f"CBZ match: '{clean_title}' x{occurrences} in '{filename}' p.{page_num+1}")
                context += (
                    f"\n--- Extract from '{filename}' (Page {page_num + 1}, OCR) ---\n"
                    + page_text
                )

                if len(context) > 4000:
                    return context, True

    except zipfile.BadZipFile as e:
        log(f"Cannot open CBZ '{filename}': {e}", "error")

    return context, False


# ─────────────────────────────────────────────
# Magazine search — dispatcher
# ─────────────────────────────────────────────

def search_magazines(game_name, magazines_dir=MAGAZINES_DIR):
    """
    Search all PDF and CBZ files in the magazines folder for content
    relevant to the given game name.
    Returns a text context string to be injected into the LLM prompt.
    """
    if not os.path.exists(magazines_dir):
        log(f"Magazines folder not found: '{magazines_dir}'")
        return "No magazines folder found. AI will use its own knowledge."

    pattern     = build_search_pattern(game_name)
    clean_title = game_name.split('(')[0].split('[')[0].strip()
    context     = ""

    for filename in sorted(os.listdir(magazines_dir)):
        name_lower = filename.lower()
        filepath   = os.path.join(magazines_dir, filename)

        if name_lower.endswith('.pdf'):
            context, limit = extract_from_pdf(filepath, pattern, clean_title, context)
        elif name_lower.endswith('.cbz'):
            context, limit = extract_from_cbz(filepath, pattern, clean_title, context)
        else:
            continue

        if limit:
            log(f"Context size limit reached while processing '{filename}'.")
            return context

    if not context:
        log(f"No magazine content found for '{game_name}'.")
        return "No information found in magazines for this game."

    return context


# ─────────────────────────────────────────────
# LLM query
# ─────────────────────────────────────────────

def query_llm(game_name, pdf_context, prompt_data):
    """
    Build the prompt from the structured JSON and send it to Ollama.
    Returns the parsed metadata dict, or None on failure.
    """
    prompt = build_prompt_text(prompt_data, game_name, pdf_context)
    log(f"Sending prompt to Ollama for: '{game_name}'")

    payload = {
        "model":       MODEL_NAME,
        "prompt":      prompt,
        "format":      "json",
        "stream":      False,
        "temperature": 0.1,
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        result = json.loads(clean_json_response(data["response"]))
        log(f"LLM response received for '{game_name}': is_real_game={result.get('is_real_game')}")
        return result
    except Exception as e:
        out(f"  -> Ollama error: {e}", "error")
        log(f"Ollama request failed for '{game_name}': {e}", "error")
        return None


# ─────────────────────────────────────────────
# XML save
# ─────────────────────────────────────────────

def save_xml(tree, output_path):
    """Write the XML tree to disk with indentation (requires Python 3.9+)."""
    if hasattr(ET, "indent"):
        ET.indent(tree, space="\t", level=0)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    log(f"XML saved to '{output_path}'")


# ─────────────────────────────────────────────
# Game enrichment
# ─────────────────────────────────────────────

def enrich_game(game, prompt_data, force=False):
    """
    Query the LLM and inject the returned metadata into a <game> XML element.
    Skips games that already have a description unless force=True.
    Returns True if the game was successfully updated.
    """
    name_el = game.find('name')
    desc_el = game.find('desc')
    name    = name_el.text if name_el is not None else "Unknown Game"

    # Skip if description already exists and force mode is off
    if not force and desc_el is not None and desc_el.text and desc_el.text.strip():
        out("  -> Description already present. Skipped (use -f to force).")
        log(f"Skipped '{name}': description already present.")
        return False

    out("  -> Searching magazines...")
    context = search_magazines(name)

    if "No information found" not in context and "No magazines folder" not in context:
        out("  -> Article found! Sending to AI...")
    else:
        out("  -> No article found. AI will use its own knowledge.")

    metadata = query_llm(name, context, prompt_data)

    if not metadata or not metadata.get("is_real_game", False):
        out("  -> Game not recognized or LLM error. Skipped.")
        log(f"Skipped '{name}': not recognized or LLM error.")
        return False

    # Update the name field if force mode is on and LLM suggests a correction
    if force and name_el is not None and metadata.get("real_name"):
        name_el.text = str(metadata["real_name"])

    fields = ["desc", "genre", "releasedate", "developer", "publisher", "players"]
    for field in fields:
        if not metadata.get(field):
            continue
        existing = game.find(field)
        if existing is not None:
            if force:
                existing.text = str(metadata[field])
        else:
            new_node      = ET.SubElement(game, field)
            new_node.text = str(metadata[field])

    out("  -> Done.")
    log(f"Successfully enriched '{name}'.")
    return True


# ─────────────────────────────────────────────
# XML loading
# ─────────────────────────────────────────────

def load_xml(filepath):
    """Load a gamelist XML file, or create an empty one if not found."""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        log(f"Loaded XML: '{filepath}' ({len(root.findall('game'))} games)")
    except FileNotFoundError:
        out(f"File '{filepath}' not found. Creating empty gameList.")
        log(f"XML not found, created empty gameList: '{filepath}'", "warning")
        root = ET.Element("gameList")
        tree = ET.ElementTree(root)
    return tree, root


# ─────────────────────────────────────────────
# Modes
# ─────────────────────────────────────────────

def mode_process_all(prompt_data, force=False):
    """
    Default mode (no arguments): process the entire gamelist.
    Only enriches games without a description unless force=True.
    Source file is never modified — output goes to OUTPUT_FILE.
    """
    tree, root = load_xml(SOURCE_FILE)
    games      = root.findall('game')

    if not games:
        out("No games found in the gamelist.")
        return

    updates = 0
    for index, game in enumerate(games):
        name = game.find('name').text if game.find('name') is not None else "???"
        out(f"\n[{index + 1}/{len(games)}] Processing: '{name}'")
        if enrich_game(game, prompt_data, force=force):
            updates += 1

    if updates > 0:
        save_xml(tree, OUTPUT_FILE)
        out(f"\nDone! {updates} game(s) updated -> '{OUTPUT_FILE}'.")
    else:
        out("\nNo changes made.")


def mode_add(game_name, prompt_data, force=False):
    """
    -add mode: add a new game entry or update an existing one.
    Reads OUTPUT_FILE if it exists, otherwise SOURCE_FILE.
    Always writes to OUTPUT_FILE.
    """
    target = OUTPUT_FILE if os.path.exists(OUTPUT_FILE) else SOURCE_FILE
    tree, root = load_xml(target)
    games      = root.findall('game')

    # Search for an existing entry (case-insensitive)
    match = None
    for g in games:
        name_el = g.find('name')
        if name_el is not None and game_name.lower() == name_el.text.lower():
            match = g
            break

    if match is not None:
        out(f"Game '{game_name}' already exists in '{target}'.")
        log(f"Add mode: '{game_name}' already exists in '{target}'.")
        if not force:
            out("Use -f to force update.")
            return
        out("Force mode active: updating...")
    else:
        out(f"Game '{game_name}' not found. Creating new entry...")
        log(f"Add mode: creating new entry for '{game_name}'.")
        match = ET.SubElement(root, 'game')
        ET.SubElement(match, 'path').text = f"./{game_name}.iso"
        ET.SubElement(match, 'name').text = game_name
        force = True  # new entry is always enriched

    out(f"\n[1/1] Processing: '{game_name}'")
    if enrich_game(match, prompt_data, force=force):
        save_xml(tree, OUTPUT_FILE)
        out(f"\nFile '{OUTPUT_FILE}' updated.")
    else:
        out("\nNo changes made.")


def mode_search(search_term, prompt_data, force=False):
    """
    -rom mode: filter games by name and enrich matching entries.
    Reads OUTPUT_FILE if it exists, otherwise SOURCE_FILE.
    Always writes to OUTPUT_FILE.
    """
    target = OUTPUT_FILE if os.path.exists(OUTPUT_FILE) else SOURCE_FILE
    tree, root = load_xml(target)
    games      = root.findall('game')

    matches = [
        g for g in games
        if g.find('name') is not None
        and search_term.lower() in g.find('name').text.lower()
    ]

    if not matches:
        out(f"No game found matching '{search_term}'. Use -add to create it.")
        log(f"Search mode: no match for '{search_term}'.", "warning")
        return

    updates = 0
    for index, game in enumerate(matches):
        name = game.find('name').text
        out(f"\n[{index + 1}/{len(matches)}] Processing: '{name}'")
        if enrich_game(game, prompt_data, force=force):
            updates += 1

    if updates > 0:
        save_xml(tree, OUTPUT_FILE)
        out(f"\n{updates} game(s) updated -> '{OUTPUT_FILE}'.")
    else:
        out("\nNo changes made.")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrich a gamelist.xml with AI-generated metadata via a local Ollama instance.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  python gamelist_updater.py                                   Process all games (missing descriptions only)
  python gamelist_updater.py -f                                Process all games and overwrite existing data
  python gamelist_updater.py -rom "God of War"                 Find and enrich matching game(s)
  python gamelist_updater.py -add "ICO"                        Add 'ICO' if not found, or warn if it exists
  python gamelist_updater.py -add "ICO" -f                     Add or force-update 'ICO'
  python gamelist_updater.py -prompt ./prompts/prompt_en.json  Use a custom prompt file
  python gamelist_updater.py -prompt ./prompts/prompt_en.json -add "ICO"
"""
    )
    parser.add_argument("-rom",    type=str, default=None,
                        help="Find and enrich games whose name contains this term.")
    parser.add_argument("-add",    type=str, default=None,
                        help="Add a game or update an existing one (requires -f to overwrite).")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Force overwrite of existing metadata.")
    parser.add_argument("-prompt", type=str, default=DEFAULT_PROMPT,
                        help=f"Path to the prompt JSON file (default: {DEFAULT_PROMPT}).")
    args = parser.parse_args()

    log("=" * 60)
    log(f"Session started — args: {vars(args)}")

    # Load prompt — fail fast if file is missing or malformed
    try:
        prompt_data = load_prompt(args.prompt)
    except (FileNotFoundError, ValueError) as e:
        out(f"\nERROR: {e}", "error")
        exit(1)

    if args.add:
        mode_add(args.add, prompt_data, force=args.force)
    elif args.rom:
        mode_search(args.rom, prompt_data, force=args.force)
    else:
        mode_process_all(prompt_data, force=args.force)

    log("Session ended.")
