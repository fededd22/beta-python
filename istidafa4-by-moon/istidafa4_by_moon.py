import subprocess
import os
import sys
import asyncio
import importlib
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command

# Keep-alive automatique + serveur web (même principe que le projet précédent)
from keepalive import DATA_DIR, start_web_server, keep_alive_task, get_status

# ==================== CONFIGURATION DU BOT ====================
# Le token peut (et devrait) être fourni via la variable d'environnement
# TELEGRAM_BOT_TOKEN. La valeur ci-dessous n'est qu'un repli.
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "7133630316:AAEPJccijGCjwyCPRcZtBeDBW0Nsc4aw0JI"
# Les scripts des utilisateurs sont stockés dans DATA_DIR (volume persistant).
BASE_DIR = os.path.join(DATA_DIR, "scripts")
processes = {}
user_states = {}
banned_users = set()
# IDs des administrateurs (variable ADMIN_IDS="id1,id2" ou valeur par défaut)
ADMINS = [int(x) for x in os.environ.get("ADMIN_IDS", "1726923679").replace(" ", "").split(",") if x]
BOT_MODE = "public"  # Peut être "public" ou "private"

# 📂 Créer le dossier des scripts s'il n'existe pas
os.makedirs(BASE_DIR, exist_ok=True)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ==================== INTERFACE UTILISATEUR ====================
# 🎛️ Clavier principal pour les utilisateurs normaux
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Ajouter un script")],
        [KeyboardButton(text="▶️ Exécuter un script")],
        [KeyboardButton(text="📜 Liste des scripts")],
        [KeyboardButton(text="❌ Arrêter et supprimer un script")],
    ],
    resize_keyboard=True
)

# 🎛️ Clavier principal pour les admins
admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Ajouter un script")],
        [KeyboardButton(text="▶️ Exécuter un script")],
        [KeyboardButton(text="📜 Liste des scripts")],
        [KeyboardButton(text="❌ Arrêter et supprimer un script")],
        [KeyboardButton(text="👑 Panel admin")],
    ],
    resize_keyboard=True
)

# 🎛️ Panel admin
admin_panel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔒 Bannir un utilisateur"), KeyboardButton(text="🔓 Débannir un utilisateur")],
        [KeyboardButton(text="💾 Sauvegarder scripts utilisateur"), KeyboardButton(text="📋 Liste de tous les scripts")],
        [KeyboardButton(text="🛑 Arrêter/supprimer script utilisateur")],
        [KeyboardButton(text="🔐 Mode privé"), KeyboardButton(text="🌍 Mode public")],
        [KeyboardButton(text="💻 Envoyer commande terminal")],
        [KeyboardButton(text="🔄 État Keep-Alive")],
        [KeyboardButton(text="⬅️ Retour au menu principal")],
    ],
    resize_keyboard=True
)

# 🎛️ Clavier pour la saisie manuelle des commandes
command_input_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="saisir la commande manuellement")],
        [KeyboardButton(text="⬅️ Annuler")],
    ],
    resize_keyboard=True
)

# ==================== COMMANDES DU BOT ====================
@dp.message(Command("start"))
async def start(message: types.Message):
    if BOT_MODE == "private" and message.from_user.id not in ADMINS:
        await message.reply("🚫 Le bot est en mode privé, seuls les admins peuvent l'utiliser.")
        return
    
    if message.from_user.id in banned_users:
        await message.reply("🚫 Vous êtes banni de ce bot.")
        return
    
    keyboard = admin_keyboard if message.from_user.id in ADMINS else main_keyboard
    await message.reply("👋 Bonjour ! Choisissez une action :", reply_markup=keyboard)

# ==================== COMMANDES ADMIN ====================
@dp.message(lambda message: message.text == "👑 Panel admin" and message.from_user.id in ADMINS)
async def admin_panel(message: types.Message):
    await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)

# ==================== ÉTAT KEEP-ALIVE (lecture seule) ====================
# Le keep-alive est entièrement automatique (voir keepalive.py) : plus de
# configuration manuelle, seulement un affichage de l'état.
@dp.message(lambda message: message.text == "🔄 État Keep-Alive" and message.from_user.id in ADMINS)
async def keep_alive_status(message: types.Message):
    st = get_status()
    lp = st["last_ping"]
    if lp["at"] is None:
        last = "aucun ping pour l'instant"
    elif lp["ok"]:
        last = f"✅ HTTP {lp['status']} ({lp['ms']} ms)"
    else:
        last = f"❌ {lp['status'] or lp['error']}"
    await message.reply(
        f"📊 Keep-Alive automatique:\n"
        f"Domaine détecté: {st['domain'] or 'pas encore détecté'}\n"
        f"Intervalle: {st['interval_s']} secondes\n"
        f"Port: {st['port']}\n"
        f"Dernier ping: {last}",
        reply_markup=admin_panel_keyboard
    )

# ==================== AUTRES COMMANDES ADMIN ====================
@dp.message(lambda message: message.text == "💻 Envoyer commande terminal" and message.from_user.id in ADMINS)
async def send_terminal_command(message: types.Message):
    user_states[message.from_user.id] = "terminal_command"
    await message.reply("📝 Entrez la commande à exécuter dans le terminal:", reply_markup=command_input_keyboard)

# Gestion des commandes terminal
@dp.message(lambda message: user_states.get(message.from_user.id) == "terminal_command" and message.from_user.id in ADMINS)
async def handle_terminal_command(message: types.Message):
    if message.text == "⬅️ Annuler":
        user_states.pop(message.from_user.id, None)
        await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)
        return
    
    if message.text == "saisir la commande manuellement":
        user_states[message.from_user.id] = "manual_command_input"
        await message.reply("📝 Entrez maintenant la commande à exécuter:")
        return
    
    command = message.text
    await message.reply(f"⚙️ Exécution de la commande: `{command}`", parse_mode="Markdown")
    
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if stdout:
            output = stdout.decode()
            if len(output) > 4000:
                output = output[:4000] + "\n... (sortie tronquée)"
            await message.reply(f"📤 Sortie:\n```\n{output}\n```", parse_mode="Markdown")
        
        if stderr:
            error = stderr.decode()
            if len(error) > 4000:
                error = error[:4000] + "\n... (erreur tronquée)"
            await message.reply(f"⚠️ Erreur:\n```\n{error}\n```", parse_mode="Markdown")
        
        if process.returncode == 0:
            await message.reply("✅ Commande exécutée avec succès!")
        else:
            await message.reply(f"❌ Commande terminée avec le code de sortie: {process.returncode}")
    
    except Exception as e:
        await message.reply(f"⚠️ Erreur lors de l'exécution de la commande: {str(e)}")
    
    user_states.pop(message.from_user.id, None)
    await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)

@dp.message(lambda message: message.text == "🔐 Mode privé" and message.from_user.id in ADMINS)
async def set_private_mode(message: types.Message):
    global BOT_MODE
    BOT_MODE = "private"
    await message.reply("✅ Le bot est maintenant en mode privé (admins seulement)")
    await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)

@dp.message(lambda message: message.text == "🌍 Mode public" and message.from_user.id in ADMINS)
async def set_public_mode(message: types.Message):
    global BOT_MODE
    BOT_MODE = "public"
    await message.reply("✅ Le bot est maintenant en mode public (tout le monde)")
    await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)

@dp.message(lambda message: message.text == "📋 Liste de tous les scripts" and message.from_user.id in ADMINS)
async def list_all_scripts(message: types.Message):
    MAX_MESSAGE_LENGTH = 4000
    
    text = "📜 Liste des scripts de tous les utilisateurs:\n"
    messages = [text]
    current_length = len(text)
    
    for user_id in os.listdir(BASE_DIR):
        user_folder = os.path.join(BASE_DIR, str(user_id))
        if os.path.isdir(user_folder):
            scripts = os.listdir(user_folder)
            user_text = f"\n👤 {user_id}:\n"
            
            for script in scripts:
                status = "🟢 Actif" if (int(user_id), script) in processes and processes[(int(user_id), script)].returncode is None else "🔴 Arrêté"
                script_line = f" - {script}: {status}\n"
                
                if current_length + len(user_text) + len(script_line) > MAX_MESSAGE_LENGTH:
                    messages.append("📜 Liste des scripts (suite):\n")
                    current_length = len(messages[-1])
                
                messages[-1] += user_text + script_line
                current_length += len(user_text) + len(script_line)
                user_text = ""
    
    for msg in messages:
        await message.reply(msg)
    
    await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)

@dp.message(lambda message: message.text == "🔒 Bannir un utilisateur" and message.from_user.id in ADMINS)
async def ban_user_prompt(message: types.Message):
    user_states[message.from_user.id] = "ban_user"
    await message.reply("📝 Envoyez l'ID de l'utilisateur à bannir:")

@dp.message(lambda message: message.text == "🔓 Débannir un utilisateur" and message.from_user.id in ADMINS)
async def unban_user_prompt(message: types.Message):
    user_states[message.from_user.id] = "unban_user"
    await message.reply("📝 Envoyez l'ID de l'utilisateur à débannir:")

@dp.message(lambda message: message.text == "💾 Sauvegarder scripts utilisateur" and message.from_user.id in ADMINS)
async def save_user_prompt(message: types.Message):
    user_states[message.from_user.id] = "save_user"
    await message.reply("📝 Envoyez l'ID de l'utilisateur dont vous voulez sauvegarder les scripts:")

@dp.message(lambda message: message.text == "🛑 Arrêter/supprimer script utilisateur" and message.from_user.id in ADMINS)
async def admin_stop_script_prompt(message: types.Message):
    user_states[message.from_user.id] = "admin_stop_script_user"
    await message.reply("📝 Envoyez l'ID de l'utilisateur dont vous voulez arrêter/supprimer les scripts:")

# ==================== COMMANDES UTILISATEUR ====================
@dp.message(lambda message: message.text == "➕ Ajouter un script")
async def prompt_add_script(message: types.Message):
    if BOT_MODE == "private" and message.from_user.id not in ADMINS:
        await message.reply("🚫 Le bot est en mode privé, seuls les admins peuvent l'utiliser.")
        return
    
    if message.from_user.id in banned_users:
        await message.reply("🚫 Vous êtes banni de ce bot.")
        return
    
    user_states[message.from_user.id] = "ajout_script"
    await message.reply("📤 Envoyez-moi un fichier **.py** à ajouter.")

@dp.message(lambda message: message.document and user_states.get(message.from_user.id) == "ajout_script")
async def handle_script_upload(message: types.Message):
    user_id = message.from_user.id

    if user_id in banned_users:
        await message.reply("🚫 Vous êtes banni de ce bot.")
        return

    document = message.document
    if not document.file_name.endswith(".py"):
        await message.reply("⚠️ Seuls les fichiers `.py` sont acceptés.")
        return

    user_folder = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    if user_id not in ADMINS:
        existing_files = os.listdir(user_folder)
        if len(existing_files) >= 4:
            await message.reply("⚠️ Vous ne pouvez pas avoir plus de 4 scripts. Supprimez-en un d'abord.")
            return

    file_path = os.path.join(user_folder, document.file_name)
    file = await bot.get_file(document.file_id)
    await bot.download_file(file.file_path, file_path)

    await message.reply(f"✅ Le script **{document.file_name}** a été ajouté avec succès!")
    user_states.pop(user_id, None)

# Fonction pour vérifier et installer les bibliothèques
def check_and_install_libraries(file_path):
    with open(file_path, 'r') as file:
        script_content = file.read()

    imports = [line for line in script_content.splitlines() if line.startswith("import") or line.startswith("from")]
    missing_libraries = []

    for imp in imports:
        try:
            if imp.startswith("import"):
                module = imp.split()[1]
                importlib.import_module(module)
            elif imp.startswith("from"):
                module = imp.split()[1]
                importlib.import_module(module)
        except ImportError:
            module = imp.split()[1]
            missing_libraries.append(module)

    if missing_libraries:
        for lib in missing_libraries:
            subprocess.run([sys.executable, "-m", "pip", "install", lib])

    return missing_libraries

@dp.message(lambda message: message.text == "❌ Arrêter et supprimer un script")
async def stop_and_delete_script(message: types.Message):
    if BOT_MODE == "private" and message.from_user.id not in ADMINS:
        await message.reply("🚫 Le bot est en mode privé, seuls les admins peuvent l'utiliser.")
        return
    
    user_id = message.from_user.id
    user_states[user_id] = "suppression"

    user_folder = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    files = os.listdir(user_folder)
    if not files:
        await message.reply("🚫 Aucun script trouvé à supprimer.")
        return

    buttons = [KeyboardButton(text=file) for file in files]
    keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    keyboard_layout.append([KeyboardButton(text="⬅️ Retour au menu principal")])

    keyboard = ReplyKeyboardMarkup(keyboard=keyboard_layout, resize_keyboard=True)
    await message.reply("🔍 Choisissez un script à arrêter et supprimer:", reply_markup=keyboard)

@dp.message(lambda message: message.text == "📜 Liste des scripts")
async def list_codes(message: types.Message):
    if BOT_MODE == "private" and message.from_user.id not in ADMINS:
        await message.reply("🚫 Le bot est en mode privé, seuls les admins peuvent l'utiliser.")
        return
    
    user_id = message.from_user.id
    user_folder = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    files = os.listdir(user_folder)
    if not files:
        await message.reply("🚫 Aucun script trouvé.")
        return

    status = {file: "🟢 Actif" if (user_id, file) in processes and processes[(user_id, file)].returncode is None else "🔴 Arrêté" for file in files}
    response = "\n".join([f"{file}: {state}" for file, state in status.items()])
    await message.reply(f"📂 Vos scripts:\n{response}")

@dp.message(lambda message: message.text == "▶️ Exécuter un script")
async def list_files_for_running(message: types.Message):
    if BOT_MODE == "private" and message.from_user.id not in ADMINS:
        await message.reply("🚫 Le bot est en mode privé, seuls les admins peuvent l'utiliser.")
        return
    
    user_id = message.from_user.id
    user_states[user_id] = "execution"

    user_folder = os.path.join(BASE_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)

    files = os.listdir(user_folder)
    if not files:
        await message.reply("🚫 Aucun script trouvé.")
        return

    buttons = [KeyboardButton(text=file) for file in files]
    keyboard_layout = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    keyboard_layout.append([KeyboardButton(text="⬅️ Retour au menu principal")])

    keyboard = ReplyKeyboardMarkup(keyboard=keyboard_layout, resize_keyboard=True)
    await message.reply("🔍 Choisissez un script à exécuter:", reply_markup=keyboard)

@dp.message(lambda message: message.text == "⬅️ Retour au menu principal")
async def return_to_main_menu(message: types.Message):
    user_id = message.from_user.id
    user_states.pop(user_id, None)
    keyboard = admin_keyboard if user_id in ADMINS else main_keyboard
    await message.reply("🏠 Retour au menu principal.", reply_markup=keyboard)

@dp.message(lambda message: message.text == "⬅️ Retour au panel admin" and message.from_user.id in ADMINS)
async def return_to_admin_panel(message: types.Message):
    await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)

# ==================== GESTION DES ACTIONS UTILISATEUR ====================
@dp.message()
async def handle_user_action(message: types.Message):
    # Vérifier d'abord le mode du bot
    if BOT_MODE == "private" and message.from_user.id not in ADMINS:
        await message.reply("🚫 Le bot est en mode privé, seuls les admins peuvent l'utiliser.")
        return
    
    if message.from_user.id in banned_users:
        await message.reply("🚫 Vous êtes banni de ce bot.")
        return

    # Traiter d'abord les commandes admin
    if message.from_user.id in ADMINS:
        if user_states.get(message.from_user.id) == "ban_user":
            try:
                banned_user_id = int(message.text)
                banned_users.add(banned_user_id)
                await message.reply(f"✅ L'utilisateur {banned_user_id} a été banni avec succès.")
            except ValueError:
                await message.reply("⚠️ Veuillez entrer un ID utilisateur valide (chiffres seulement)")
            user_states.pop(message.from_user.id, None)
            await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)
            return

        elif user_states.get(message.from_user.id) == "unban_user":
            try:
                unbanned_user_id = int(message.text)
                banned_users.discard(unbanned_user_id)
                await message.reply(f"✅ L'utilisateur {unbanned_user_id} a été débanni avec succès.")
            except ValueError:
                await message.reply("⚠️ Veuillez entrer un ID utilisateur valide (chiffres seulement)")
            user_states.pop(message.from_user.id, None)
            await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)
            return

        elif user_states.get(message.from_user.id) == "save_user":
            try:
                target_user_id = int(message.text)
                user_folder = os.path.join(BASE_DIR, str(target_user_id))
                
                if not os.path.exists(user_folder):
                    await message.reply("🚫 Aucun script trouvé pour cet utilisateur.")
                    user_states.pop(message.from_user.id, None)
                    return
                
                files = os.listdir(user_folder)
                if not files:
                    await message.reply("🚫 Cet utilisateur n'a aucun script.")
                    user_states.pop(message.from_user.id, None)
                    return
                
                for file in files:
                    try:
                        await message.answer_document(
                            types.FSInputFile(os.path.join(user_folder, file)),
                            caption=f"Script {file} de l'utilisateur {target_user_id}"
                        )
                        await asyncio.sleep(1)
                    except Exception as e:
                        await message.reply(f"⚠️ Erreur lors de l'envoi du fichier {file}: {str(e)}")
                
                await message.reply("✅ Tous les scripts ont été envoyés avec succès.")
            except ValueError:
                await message.reply("⚠️ Veuillez entrer un ID utilisateur valide (chiffres seulement)")
            except Exception as e:
                await message.reply(f"⚠️ Une erreur inattendue est survenue: {str(e)}")
            
            user_states.pop(message.from_user.id, None)
            await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)
            return

        elif user_states.get(message.from_user.id) == "admin_stop_script_user":
            try:
                target_user_id = int(message.text)
                user_folder = os.path.join(BASE_DIR, str(target_user_id))
                if not os.path.exists(user_folder):
                    await message.reply("🚫 Aucun script trouvé pour cet utilisateur.")
                    user_states.pop(message.from_user.id, None)
                    return
                
                files = os.listdir(user_folder)
                if not files:
                    await message.reply("🚫 Aucun script trouvé pour cet utilisateur.")
                    user_states.pop(message.from_user.id, None)
                    return
                
                user_states[message.from_user.id] = ("admin_stop_script_select", target_user_id)
                
                buttons = [KeyboardButton(text=file) for file in files]
                keyboard_layout = [buttons[i:i+2] for i in range(0, len(files), 2)]
                keyboard_layout.append([KeyboardButton(text="⬅️ Retour au menu principal")])

                keyboard = ReplyKeyboardMarkup(keyboard=keyboard_layout, resize_keyboard=True)
                await message.reply(f"🔍 Choisissez un script de l'utilisateur {target_user_id} à arrêter/supprimer:", reply_markup=keyboard)
                return
                
            except ValueError:
                await message.reply("⚠️ Veuillez entrer un ID utilisateur valide (chiffres seulement)")
                user_states.pop(message.from_user.id, None)
                await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)
                return

        elif isinstance(user_states.get(message.from_user.id), tuple) and user_states[message.from_user.id][0] == "admin_stop_script_select":
            target_user_id = user_states[message.from_user.id][1]
            filename = message.text
            
            if filename == "⬅️ Retour au menu principal":
                user_states.pop(message.from_user.id, None)
                keyboard = admin_keyboard if message.from_user.id in ADMINS else main_keyboard
                await message.reply("🏠 Retour au menu principal.", reply_markup=keyboard)
                return
            
            file_path = os.path.join(BASE_DIR, str(target_user_id), filename)
            
            process_stopped = False
            if (target_user_id, filename) in processes:
                process = processes[(target_user_id, filename)]
                if process.returncode is None:
                    try:
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), timeout=3)
                            process_stopped = True
                        except asyncio.TimeoutError:
                            process.kill()
                            process_stopped = True
                        await message.reply(f"⛔ Le script {filename} a été arrêté avec succès.")
                    except Exception as e:
                        await message.reply(f"⚠️ Erreur lors de l'arrêt du script: {str(e)}")
                    finally:
                        if (target_user_id, filename) in processes:
                            del processes[(target_user_id, filename)]
            
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    await message.reply(f"✅ Le script {filename} de l'utilisateur {target_user_id} a été supprimé avec succès.")
                else:
                    if not process_stopped:
                        await message.reply(f"⚠️ Le fichier {filename} n'existe pas pour l'utilisateur {target_user_id}.")
            except Exception as e:
                await message.reply(f"⚠️ Erreur lors de la suppression du script: {str(e)}")

            user_states.pop(message.from_user.id, None)
            await message.reply("👑 Panel d'administration", reply_markup=admin_panel_keyboard)
            return

    # Traiter les commandes normales
    user_folder = os.path.join(BASE_DIR, str(message.from_user.id))
    os.makedirs(user_folder, exist_ok=True)

    user_files = os.listdir(user_folder)
    filename = message.text
    file_path = os.path.join(user_folder, filename)

    if filename not in user_files:
        return

    if user_states.get(message.from_user.id) == "execution":
        missing_libraries = check_and_install_libraries(file_path)

        if missing_libraries:
            await message.reply(f"⚠️ Bibliothèques manquantes installées:\n" + "\n".join(missing_libraries))
        else:
            await message.reply(f"✅ Toutes les bibliothèques sont déjà installées.")

        await message.reply(f"🚀 Exécution du script {filename}...")
        process = await asyncio.create_subprocess_exec(
            'python', file_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        processes[(message.from_user.id, filename)] = process

        stdout, stderr = await process.communicate()

        if stdout:
            await message.reply(f"📤 Sortie:\n```\n{stdout.decode()}\n```", parse_mode="Markdown")
        if stderr:
            await message.reply(f"⚠️ Erreurs:\n```\n{stderr.decode()}\n```", parse_mode="Markdown")

        user_states.pop(message.from_user.id, None)

    elif user_states.get(message.from_user.id) == "suppression":
        if (message.from_user.id, filename) in processes:
            process = processes[(message.from_user.id, filename)]
            if process.returncode is None:
                process.terminate()
                try:
                    await process.wait(timeout=5)
                except asyncio.TimeoutError:
                    process.kill()
            del processes[(message.from_user.id, filename)]

        if os.path.exists(file_path):
            os.remove(file_path)
            await message.reply(f"✅ Le script {filename} a été supprimé avec succès.")
        else:
            await message.reply(f"⚠️ Le fichier {filename} n'existe pas.")

        user_states.pop(message.from_user.id, None)

# ==================== FONCTION PRINCIPALE ====================
_background_tasks = []  # garde une référence pour éviter le garbage collection


async def main():
    # Serveur web (/ et /health) sur le port PORT
    start_web_server()

    # Keep-alive automatique : ping du domaine public toutes les 30 s
    _background_tasks.append(asyncio.create_task(keep_alive_task()))

    print("🤖 Bot démarré avec succès!", flush=True)

    # Démarrer le polling du bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
