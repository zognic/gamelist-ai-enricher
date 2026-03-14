import os
import re
import requests
import json
import xml.etree.ElementTree as ET
import argparse
import fitz  # PyMuPDF

OLLAMA_URL        = "http://localhost:11434/api/generate"
MODEL_NAME        = "mistral"
DOSSIER_MAGAZINES = "./magazines/"
FICHIER_SOURCE    = "gamelist.xml"
FICHIER_FINAL     = "gamelist_updated.xml"
PROMPT_DEFAUT     = "./prompts/prompt_default.json"


# ---------------------------------------------
# Chargement du prompt externe
# ---------------------------------------------

def charger_prompt(chemin_json):
    """
    Charge un fichier prompt .json structure avec des cles nommees :
    {
        "name":           "Nom lisible",
        "role":           "...",
        "goal":           "...",
        "steps":          ["...", "..."],
        "tone":           "...",          (facultatif)
        "language":       "...",          (facultatif)
        "constraints":    ["...", "..."], (facultatif)
        "output_example": { ... }
    }
    """
    if not os.path.exists(chemin_json):
        raise FileNotFoundError(
            f"Fichier prompt introuvable : '{chemin_json}'\n"
            f"Creez un fichier JSON dans ./prompts/ ou specifiez -prompt <chemin>."
        )
    with open(chemin_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    for cle in ("name", "role", "goal", "steps", "output_example"):
        if cle not in data:
            raise ValueError(
                f"Le fichier prompt '{chemin_json}' doit contenir la cle '{cle}'."
            )
    print(f"  [Prompt] '{data['name']}' charge depuis '{chemin_json}'")
    return data


def construire_prompt_texte(prompt_data, nom_brut, contexte_pdf):
    """
    Reconstruit le texte du prompt envoye au LLM a partir des cles structurees du JSON.
    """
    lignes = []
    lignes.append(f"ROLE : {prompt_data['role']}\n")
    lignes.append(f"OBJECTIF : {prompt_data['goal']}\n")
    lignes.append("ETAPES :")
    for i, etape in enumerate(prompt_data["steps"], 1):
        lignes.append(f"  {i}. {etape.replace("{nom_brut}", nom_brut)}")
    lignes.append("")
    if prompt_data.get("tone"):
        lignes.append(f"TON : {prompt_data['tone']}\n")
    if prompt_data.get("language"):
        lignes.append(f"LANGUE : {prompt_data['language']}\n")
    if prompt_data.get("constraints"):
        lignes.append("CONTRAINTES :")
        for c in prompt_data["constraints"]:
            lignes.append(f"  - {c}")
        lignes.append("")
    lignes.append("DONNEES D'ENTREE :")
    lignes.append(f"  Nom du jeu : {nom_brut}")
    lignes.append(f"  Archives magazines :\n{contexte_pdf}\n")
    lignes.append("FORMAT DE SORTIE ATTENDU (exemple) :")
    lignes.append(json.dumps(prompt_data["output_example"], ensure_ascii=False, indent=2))
    return "\n".join(lignes)


# ---------------------------------------------
# Helpers
# ---------------------------------------------

def nettoyer_reponse_json(texte):
    texte = texte.strip()
    if texte.startswith("```json"):
        texte = texte[7:]
    if texte.startswith("```"):
        texte = texte[3:]
    if texte.endswith("```"):
        texte = texte[:-3]
    return texte.strip()


def construire_pattern_recherche(nom_jeu):
    """
    Regex mot entier pour eviter les faux positifs :
    "ico" ne matche pas "musico" ou "erico".
    Supprime les suffixes entre parentheses/crochets : "ICO (USA)" -> "ICO"
    """
    titre         = nom_jeu.split('(')[0].split('[')[0].strip()
    titre_escaped = re.escape(titre)
    return re.compile(r'\b' + titre_escaped + r'\b', re.IGNORECASE)


def chercher_dans_dossier_pdf(nom_jeu, dossier_magazines=DOSSIER_MAGAZINES):
    if not os.path.exists(dossier_magazines):
        return "Aucun dossier ./magazines/ trouve. L'IA utilisera ses propres connaissances."

    pattern      = construire_pattern_recherche(nom_jeu)
    titre_propre = nom_jeu.split('(')[0].split('[')[0].strip()
    contexte_total = ""

    for fichier in os.listdir(dossier_magazines):
        if not fichier.lower().endswith('.pdf'):
            continue
        chemin_pdf = os.path.join(dossier_magazines, fichier)
        try:
            doc = fitz.open(chemin_pdf)
            for page_num in range(len(doc)):
                page       = doc.load_page(page_num)
                texte_page = page.get_text("text")

                if not pattern.search(texte_page):
                    continue

                # Filtre de pertinence : au moins 2 occurrences sur la page
                occurrences = len(pattern.findall(texte_page))
                if occurrences < 2:
                    print(f"  -> Mention unique de '{titre_propre}' dans '{fichier}' "
                          f"p.{page_num+1} -- ignoree (probablement hors-sujet).")
                    continue

                print(f"  -> {occurrences} occurrence(s) de '{titre_propre}' "
                      f"dans '{fichier}' p.{page_num+1} -- page retenue.")
                contexte_total += (
                    f"\n--- Extrait du magazine '{fichier}' (Page {page_num + 1}) ---\n"
                    + texte_page
                )

                if len(contexte_total) > 4000:
                    doc.close()
                    return contexte_total
            doc.close()
        except Exception as e:
            print(f"  -> Impossible de lire le fichier {fichier} : {e}")

    if not contexte_total:
        return "Aucune information trouvee dans les magazines pour ce jeu."
    return contexte_total


def interroger_llm_pour_metadonnees(nom_brut, contexte_pdf, prompt_data):
    """
    Reconstruit le prompt depuis les cles structurees du JSON, puis interroge Ollama.
    """
    prompt = construire_prompt_texte(prompt_data, nom_brut, contexte_pdf)

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
        return json.loads(nettoyer_reponse_json(data["response"]))
    except Exception as e:
        print(f"  -> Erreur avec Ollama : {e}")
        return None


# ---------------------------------------------
# Sauvegarde
# ---------------------------------------------

def sauvegarder(tree, fichier_sortie):
    if hasattr(ET, "indent"):
        ET.indent(tree, space="\t", level=0)
    tree.write(fichier_sortie, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------
# Traitement d'un jeu individuel
# ---------------------------------------------

def enrichir_jeu(game, prompt_data, force=False):
    """
    Interroge le LLM et injecte les metadonnees dans l'element <game>.
    Retourne True si des donnees ont ete modifiees.
    """
    nom_element  = game.find('name')
    desc_element = game.find('desc')
    nom_brut     = nom_element.text if nom_element is not None else "Jeu Inconnu"

    if not force and desc_element is not None and desc_element.text and desc_element.text.strip():
        print("  -> Description deja presente. Ignore (utilisez -f pour forcer).")
        return False

    print("  -> Recherche dans les magazines...")
    contexte = chercher_dans_dossier_pdf(nom_brut)

    if "Aucune information trouvee" not in contexte and "Aucun dossier" not in contexte:
        print("  -> Article trouve ! Envoi a l'IA...")
    else:
        print("  -> Pas d'article. L'IA utilisera ses propres connaissances.")

    metadonnees = interroger_llm_pour_metadonnees(nom_brut, contexte, prompt_data)

    if not metadonnees or not metadonnees.get("is_real_game", False):
        print("  -> Jeu non reconnu ou erreur LLM. Ignore.")
        return False

    if force and nom_element is not None and metadonnees.get("real_name"):
        nom_element.text = str(metadonnees["real_name"])

    champs = ["desc", "genre", "releasedate", "developer", "publisher", "players"]
    for champ in champs:
        if not metadonnees.get(champ):
            continue
        existant = game.find(champ)
        if existant is not None:
            if force:
                existant.text = str(metadonnees[champ])
        else:
            nouveau = ET.SubElement(game, champ)
            nouveau.text = str(metadonnees[champ])

    print("  -> Termine avec succes.")
    return True


# ---------------------------------------------
# Modes principaux
# ---------------------------------------------

def charger_xml(fichier):
    try:
        tree = ET.parse(fichier)
        root = tree.getroot()
    except FileNotFoundError:
        print(f"Fichier '{fichier}' introuvable. Creation d'un nouveau gameList vide.")
        root = ET.Element("gameList")
        tree = ET.ElementTree(root)
    return tree, root


def mode_tout_traiter(prompt_data, force=False):
    tree, root = charger_xml(FICHIER_SOURCE)
    jeux = root.findall('game')

    if not jeux:
        print("Aucun jeu trouve dans la gamelist.")
        return

    modifications = 0
    for index, game in enumerate(jeux):
        nom = game.find('name').text if game.find('name') is not None else "???"
        print(f"\n[{index + 1}/{len(jeux)}] Traitement de : '{nom}'")
        if enrichir_jeu(game, prompt_data, force=force):
            modifications += 1

    if modifications > 0:
        sauvegarder(tree, FICHIER_FINAL)
        print(f"\nTermine ! {modifications} jeu(x) mis a jour -> '{FICHIER_FINAL}'.")
    else:
        print("\nAucune modification apportee.")


def mode_ajouter_ou_mettre_a_jour(nom_jeu, prompt_data, force=False):
    fichier_cible = FICHIER_FINAL if os.path.exists(FICHIER_FINAL) else FICHIER_SOURCE
    tree, root    = charger_xml(fichier_cible)
    jeux          = root.findall('game')

    jeu_cible = None
    for g in jeux:
        nom_elem = g.find('name')
        if nom_elem is not None and nom_jeu.lower() == nom_elem.text.lower():
            jeu_cible = g
            break

    if jeu_cible is not None:
        print(f"Le jeu '{nom_jeu}' existe deja dans '{fichier_cible}'.")
        if not force:
            print("Utilisez -f pour forcer la mise a jour.")
            return
        print("Mode force active : mise a jour en cours...")
    else:
        print(f"Jeu '{nom_jeu}' non trouve. Creation d'une nouvelle entree...")
        jeu_cible = ET.SubElement(root, 'game')
        ET.SubElement(jeu_cible, 'path').text = f"./{nom_jeu}.iso"
        ET.SubElement(jeu_cible, 'name').text = nom_jeu
        force = True  # nouveau jeu => toujours enrichir

    print(f"\n[1/1] Traitement de : '{nom_jeu}'")
    if enrichir_jeu(jeu_cible, prompt_data, force=force):
        sauvegarder(tree, FICHIER_FINAL)
        print(f"\nFichier '{FICHIER_FINAL}' mis a jour.")
    else:
        print("\nAucune modification apportee.")


def mode_rechercher(recherche, prompt_data, force=False):
    fichier_cible = FICHIER_FINAL if os.path.exists(FICHIER_FINAL) else FICHIER_SOURCE
    tree, root    = charger_xml(fichier_cible)
    jeux          = root.findall('game')

    correspondances = [
        g for g in jeux
        if g.find('name') is not None
        and recherche.lower() in g.find('name').text.lower()
    ]

    if not correspondances:
        print(f"Aucun jeu trouve pour '{recherche}'. Utilisez -add pour le creer.")
        return

    modifications = 0
    for index, game in enumerate(correspondances):
        nom = game.find('name').text
        print(f"\n[{index + 1}/{len(correspondances)}] Traitement de : '{nom}'")
        if enrichir_jeu(game, prompt_data, force=force):
            modifications += 1

    if modifications > 0:
        sauvegarder(tree, FICHIER_FINAL)
        print(f"\n{modifications} jeu(x) mis a jour -> '{FICHIER_FINAL}'.")
    else:
        print("\nAucune modification apportee.")


# ---------------------------------------------
# Point d'entree
# ---------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Complete les metadonnees d'un gamelist.xml via une IA locale (Ollama).",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=f"""
Exemples d'utilisation :
  python gamelist_updater.py                                   Traite toute la gamelist (jeux sans description)
  python gamelist_updater.py -f                                Traite toute la gamelist et ecrase les donnees existantes
  python gamelist_updater.py -rom "God of War"                 Cherche et enrichit le(s) jeu(x) correspondant(s)
  python gamelist_updater.py -add "Ico"                        Ajoute 'Ico' s'il n'existe pas, sinon signale l'existence
  python gamelist_updater.py -add "Ico" -f                     Ajoute ou met a jour 'Ico' en forcant l'ecrasement
  python gamelist_updater.py -prompt ./prompts/prompt_en.json  Utilise un prompt personnalise
  python gamelist_updater.py -prompt ./prompts/prompt_en.json -add "Ico"  Combine prompt custom + ajout
"""
    )
    parser.add_argument("-rom",    type=str, default=None,
                        help="Recherche et enrichit les jeux dont le nom contient ce terme.")
    parser.add_argument("-add",    type=str, default=None,
                        help="Ajoute un jeu ou le met a jour (requiert -f pour ecraser).")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Force l'ecrasement des donnees existantes.")
    parser.add_argument("-prompt", type=str, default=PROMPT_DEFAUT,
                        help=f"Chemin vers le fichier prompt .json (defaut : {PROMPT_DEFAUT}).")
    args = parser.parse_args()

    # Chargement du prompt — echec rapide si fichier absent ou invalide
    try:
        prompt_data = charger_prompt(args.prompt)
    except (FileNotFoundError, ValueError) as e:
        print(f"\nERREUR : {e}")
        exit(1)

    if args.add:
        mode_ajouter_ou_mettre_a_jour(args.add, prompt_data, force=args.force)
    elif args.rom:
        mode_rechercher(args.rom, prompt_data, force=args.force)
    else:
        mode_tout_traiter(prompt_data, force=args.force)
