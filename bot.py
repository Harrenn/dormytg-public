import json
import logging
import asyncio
import os
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
)
from googleapiclient.discovery import build
from google.oauth2 import service_account

# ----------------------------
# Load General Configuration from config.json
# ----------------------------
with open("config.json", "r") as f:
    config = json.load(f)

TELEGRAM_TOKEN = config["TELEGRAM_TOKEN"]
SPREADSHEET_ID = config["SPREADSHEET_ID"]
SERVICE_ACCOUNT_FILE = config["SERVICE_ACCOUNT_FILE"]
GCASH_NUMBER = config.get("GCASH_NUMBER", "Not Provided")
GCASH_QR = config.get("GCASH_QR", "gcashqr.jpg")
INFO_LINK = config.get("INFO_LINK", "")

# ----------------------------
# Load Mappings from mappings.json
# ----------------------------
with open("mappings.json", "r") as f:
    mappings = json.load(f)

role_rows = mappings["role_rows"]            # For general per-person data
abono_water_mapping = mappings["abono_water"]  # For abono water (payment) in Column F
abono_others_mapping = mappings["abono_others"]# For abono others: numeric in Column B and description in Column D

# ----------------------------
# Setup Logging
# ----------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ----------------------------
# Persistent Storage for Registered Users
# ----------------------------
USER_ROLES_FILE = "user_roles.json"
user_roles = {}

def load_user_roles():
    global user_roles
    if os.path.exists(USER_ROLES_FILE):
        try:
            with open(USER_ROLES_FILE, "r") as f:
                user_roles = json.load(f)
                user_roles = {int(k): v for k, v in user_roles.items()}
        except Exception as e:
            logger.error(f"Error loading user roles: {e}")
            user_roles = {}
    else:
        user_roles = {}

def save_user_roles():
    with open(USER_ROLES_FILE, "w") as f:
        json.dump(user_roles, f)

load_user_roles()

# ----------------------------
# Global variable for locking commands
# ----------------------------
locked = False

# ----------------------------
# Helper Functions
# ----------------------------
def append_info(text, bills=False):
    """Append the INFO_LINK only for billing-related commands."""
    if bills:
        return f"{text}\n\nFor more info: {INFO_LINK}"
    else:
        return text

async def get_bot_link(context: CallbackContext):
    """Return a direct link to the bot's DM using its username."""
    me = await context.bot.get_me()
    return f"https://t.me/{me.username}"

async def require_registration(update: Update, context: CallbackContext):
    bot_link = await get_bot_link(context)
    await update.message.reply_text(
        f"You are not registered. Please send me a direct message and type /start. Click here: {bot_link}"
    )

def registered_required(func):
    async def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        user_id = update.effective_user.id
        # If bot is locked and the user is not admin (role "admin"), block commands.
        if locked and (user_id not in user_roles or user_roles[user_id] != "admin"):
            await update.message.reply_text("Bot is locked. Only admin can call commands.")
            return
        if user_id not in user_roles:
            await require_registration(update, context)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ----------------------------
# Google Sheets API Setup
# ----------------------------
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build('sheets', 'v4', credentials=creds)
sheet = service.spreadsheets()

def get_cell_value(cell_range: str):
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_range}"
        ).execute()
        values = result.get("values", [])
        if not values or not values[0]:
            return None
        return values[0][0]
    except Exception as e:
        logger.error(f"Error retrieving cell {cell_range}: {e}")
        return None

def get_range_data(sheet_name: str, cell_range: str):
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{sheet_name}!{cell_range}"
        ).execute()
        return result.get("values", [])
    except Exception as e:
        logger.error(f"Error retrieving range {sheet_name}!{cell_range}: {e}")
        return None

# ----------------------------
# /start & Role Registration (accessible without registration)
# ----------------------------
async def start_handler(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id in user_roles:
        role = user_roles[user_id]
        await update.message.reply_text(append_info(f"Welcome back, {role}!\n\n{COMMANDS_TEXT}", bills=True))
    else:
        keyboard = [
            [InlineKeyboardButton("Haren (admin)", callback_data="admin")],
            [InlineKeyboardButton("Seander/Francia", callback_data="Seander/Francia")],
            [InlineKeyboardButton("Resident 1", callback_data="Resident 1")],
            [InlineKeyboardButton("Laloy", callback_data="Laloy")],
            [InlineKeyboardButton("Gelo", callback_data="Gelo")],
            [InlineKeyboardButton("Allamads", callback_data="Allamads")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Who are you? Choose one:", reply_markup=reply_markup)

async def role_selection_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    selected_role = query.data
    user_id = query.from_user.id
    if user_id in user_roles:
        await query.edit_message_text(text=append_info(f"You already chose: {user_roles[user_id]}", bills=True))
    else:
        user_roles[user_id] = selected_role
        save_user_roles()
        await query.edit_message_text(text=append_info(f"Role set to: {selected_role}", bills=True))
        await context.bot.send_message(chat_id=query.from_user.id, text=append_info(COMMANDS_TEXT, bills=True))

# ----------------------------
# Command List Text (non-admin commands)
# ----------------------------
COMMANDS_TEXT = (
    "Public Commands:\n"
    "• /dormkuryente - Check total dormitory electricity bill.\n"
    "• /dormwater - Check total dormitory water bill.\n"
    "• /listcommands - List available commands.\n"
    "• /gcash - Show GCash details.\n\n"
    "Per Person Commands:\n"
    "• /mywater\n"
    "• /mykuryente\n"
    "• /myinternet\n"
    "• /mytotal\n"
    "• /mybalance\n"
    "• /myabonoothers\n"
    "• /myabonowater\n"
    "• /mytotalabono\n"
    "• /add_abono_water <value>\n"
    "• /add_abono_others <value> <description>\n"
    "• /paid <amount> (Records a payment: first 2500 goes to Rent Payment, excess to Other Payments; for Seander/Francia, threshold is 7500)\n\n"
    "To register, use /start in a direct message with the bot."
)

# ----------------------------
# Public Commands (require registration)
# ----------------------------
@registered_required
async def dormkuryente_handler(update: Update, context: CallbackContext):
    value = get_cell_value("B25")
    text = f"Dorm kuryente: {value}" if value is not None else "No data found in cell B25."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def dormwater_handler(update: Update, context: CallbackContext):
    value = get_cell_value("B27")
    text = f"Dorm water: {value}" if value is not None else "No data found in cell B27."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def listcommands_handler(update: Update, context: CallbackContext):
    await update.message.reply_text(append_info(COMMANDS_TEXT, bills=False))

@registered_required
async def gcash_handler(update: Update, context: CallbackContext):
    text = f"GCash Number: {GCASH_NUMBER}"
    await update.message.reply_text(append_info(text, bills=False))
    try:
        with open(GCASH_QR, "rb") as photo:
            await context.bot.send_photo(chat_id=update.message.chat_id, photo=photo)
    except Exception as e:
        logger.error(f"Error sending GCash QR: {e}")
        await update.message.reply_text(append_info("Error sending GCash QR.", bills=False))

# ----------------------------
# Per Person Commands (require registration)
# ----------------------------
@registered_required
async def mywater_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in role_rows:
        await update.message.reply_text(append_info("Your role is not mapped for general data.", bills=True))
        return
    row = role_rows[role]
    cell = f"B{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Water: {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def mykuryente_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in role_rows:
        await update.message.reply_text(append_info("Your role is not mapped for general data.", bills=True))
        return
    row = role_rows[role]
    cell = f"G{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Kuryente: {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def myinternet_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in role_rows:
        await update.message.reply_text(append_info("Your role is not mapped for general data.", bills=True))
        return
    row = role_rows[role]
    cell = f"H{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Internet: {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def mytotal_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in role_rows:
        await update.message.reply_text(append_info("Your role is not mapped for general data.", bills=True))
        return
    row = role_rows[role]
    cell = f"K{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Total: {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def mybalance_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in role_rows:
        await update.message.reply_text(append_info("Your role is not mapped for general data.", bills=True))
        return
    row = role_rows[role]
    cell = f"P{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Balance: {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def myabonoothers_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in abono_others_mapping:
        await update.message.reply_text(append_info("Your role is not mapped for abono others.", bills=True))
        return
    row = abono_others_mapping[role]
    cell = f"B{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Abono (others): {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def myabonowater_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in abono_water_mapping:
        await update.message.reply_text(append_info("Your role is not mapped for abono water.", bills=True))
        return
    row = abono_water_mapping[role]
    cell = f"F{row}"
    value = get_cell_value(cell)
    text = f"{role}'s Abono (water): {value}" if value is not None else f"No data found in cell {cell}."
    await update.message.reply_text(append_info(text, bills=True))

@registered_required
async def mytotalabono_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in abono_others_mapping or role not in abono_water_mapping:
        await update.message.reply_text(append_info("Your role is not mapped for abono totals.", bills=True))
        return
    others_row = abono_others_mapping[role]
    water_row = abono_water_mapping[role]
    cell_others = f"B{others_row}"
    cell_water = f"F{water_row}"
    value_others = get_cell_value(cell_others)
    value_water = get_cell_value(cell_water)
    if value_others is None or value_water is None:
        await update.message.reply_text(append_info(f"Error retrieving data from {cell_others} or {cell_water}.", bills=True))
        return
    try:
        total = float(value_others) + float(value_water)
        await update.message.reply_text(append_info(f"{role}'s Total Abono: {total}", bills=True))
    except Exception as e:
        logger.error(f"Error calculating total abono: {e}")
        await update.message.reply_text(append_info("Error calculating total abono.", bills=True))

# ----------------------------
# Abono Update Commands (Modified Syntax) (require registration)
# ----------------------------
@registered_required
async def add_abono_water_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in abono_water_mapping:
        await update.message.reply_text(append_info("Your role is not mapped for abono water update.", bills=True))
        return
    try:
        amount = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text(append_info("Usage: /add_abono_water <value>", bills=True))
        return
    row = abono_water_mapping[role]
    cell = f"F{row}"
    current_value = get_cell_value(cell)
    try:
        current_value = float(current_value) if current_value not in [None, ""] else 0
    except Exception:
        current_value = 0
    new_value = current_value + amount
    body = {"values": [[new_value]]}
    try:
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell}",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
        await update.message.reply_text(append_info(f"New abono (water) for {role}: {new_value}", bills=True))
    except Exception as e:
        logger.error(f"Error updating {cell}: {e}")
        await update.message.reply_text(append_info("Error updating abono (water).", bills=True))

@registered_required
async def add_abono_others_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in abono_others_mapping:
        await update.message.reply_text(append_info("Your role is not mapped for abono others update.", bills=True))
        return
    try:
        amount = float(context.args[0])
        new_desc = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    except (IndexError, ValueError):
        await update.message.reply_text(append_info("Usage: /add_abono_others <value> <description>", bills=True))
        return
    row = abono_others_mapping[role]
    cell_numeric = f"B{row}"
    current_value = get_cell_value(cell_numeric)
    try:
        current_value = float(current_value) if current_value not in [None, ""] else 0
    except Exception:
        current_value = 0
    new_value = current_value + amount
    body_value = {"values": [[new_value]]}
    try:
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_numeric}",
            valueInputOption="USER_ENTERED",
            body=body_value
        ).execute()
    except Exception as e:
        logger.error(f"Error updating {cell_numeric}: {e}")
        await update.message.reply_text(append_info("Error updating abono (others) value.", bills=True))
        return

    cell_desc = f"D{row}"
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_desc}"
        ).execute()
        values = result.get("values", [])
        current_desc = values[0][0] if values and values[0] else ""
    except Exception as e:
        logger.error(f"Error reading {cell_desc}: {e}")
        current_desc = ""
    
    if current_desc and new_desc:
        combined_desc = current_desc + "\n" + new_desc
    elif new_desc:
        combined_desc = new_desc
    else:
        combined_desc = current_desc
    
    body_desc = {"values": [[combined_desc]]}
    try:
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_desc}",
            valueInputOption="USER_ENTERED",
            body=body_desc
        ).execute()
    except Exception as e:
        logger.error(f"Error updating {cell_desc}: {e}")
        await update.message.reply_text(append_info("Error updating abono (others) description.", bills=True))
        return

    await update.message.reply_text(append_info(f"New abono (others) for {role}: {new_value}\nDescription:\n{combined_desc}", bills=True))

# ----------------------------
# Payment Commands
# ----------------------------
@registered_required
async def paid_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role not in role_rows:
        await update.message.reply_text("Your role is not mapped for payment.")
        return
    row = role_rows[role]
    cell_M = f"M{row}"  # Rent Payment
    cell_O = f"O{row}"  # Other Payments
    try:
        current_M = float(get_cell_value(cell_M)) if get_cell_value(cell_M) not in [None, ""] else 0
    except:
        current_M = 0
    try:
        current_O = float(get_cell_value(cell_O)) if get_cell_value(cell_O) not in [None, ""] else 0
    except:
        current_O = 0
    try:
        amount = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /paid <amount>")
        return

    # For Seander/Francia, threshold is 7500; for others, 2500.
    threshold = 7500 if role == "Seander/Francia" else 2500

    if current_M < threshold:
        available = threshold - current_M
        if amount <= available:
            new_M = current_M + amount
            new_O = current_O
        else:
            new_M = threshold
            new_O = current_O + (amount - available)
    else:
        new_M = current_M
        new_O = current_O + amount

    body_M = {"values": [[new_M]]}
    body_O = {"values": [[new_O]]}
    try:
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_M}",
            valueInputOption="USER_ENTERED",
            body=body_M
        ).execute()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_O}",
            valueInputOption="USER_ENTERED",
            body=body_O
        ).execute()
    except Exception as e:
        logger.error(f"Error updating payment cells: {e}")
        await update.message.reply_text("Error processing payment.")
        return
    total_payment = new_M + new_O
    await update.message.reply_text(f"Payment updated. Rent Payment: {new_M}, Other Payments: {new_O}. Total payment: {total_payment}")

@registered_required
async def adminpaid_handler(update: Update, context: CallbackContext):
    try:
        target_username = context.args[0].lstrip("@").lower()
        amount = float(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /adminpaid <telegram username> <amount>")
        return
    target_user_id = None
    for user_id in user_roles:
        try:
            chat = await context.bot.get_chat(user_id)
            if chat.username and chat.username.lower() == target_username:
                target_user_id = user_id
                break
        except Exception as e:
            logger.error(f"Error fetching chat for user {user_id}: {e}")
    if not target_user_id:
        await update.message.reply_text("User not found or not registered.")
        return
    role = user_roles[target_user_id]
    if role not in role_rows:
        await update.message.reply_text("Target user's role is not mapped for payment.")
        return
    row = role_rows[role]
    cell_M = f"M{row}"
    cell_O = f"O{row}"
    try:
        current_M = float(get_cell_value(cell_M)) if get_cell_value(cell_M) not in [None, ""] else 0
    except:
        current_M = 0
    try:
        current_O = float(get_cell_value(cell_O)) if get_cell_value(cell_O) not in [None, ""] else 0
    except:
        current_O = 0
    threshold = 7500 if role == "Seander/Francia" else 2500
    if current_M < threshold:
        available = threshold - current_M
        if amount <= available:
            new_M = current_M + amount
            new_O = current_O
        else:
            new_M = threshold
            new_O = current_O + (amount - available)
    else:
        new_M = current_M
        new_O = current_O + amount
    body_M = {"values": [[new_M]]}
    body_O = {"values": [[new_O]]}
    try:
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_M}",
            valueInputOption="USER_ENTERED",
            body=body_M
        ).execute()
        sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"DUES!{cell_O}",
            valueInputOption="USER_ENTERED",
            body=body_O
        ).execute()
    except Exception as e:
        logger.error(f"Error updating payment cells for admin: {e}")
        await update.message.reply_text("Error processing payment for target user.")
        return
    total_payment = new_M + new_O
    await update.message.reply_text(f"Payment updated for {target_username}. Rent Payment: {new_M}, Other Payments: {new_O}. Total payment: {total_payment}")

# ----------------------------
# New Admin Command: /sendallpaymentdeets
# ----------------------------
@registered_required
async def sendallpaymentdeets_handler(update: Update, context: CallbackContext):
    details_all = ""
    for user_id, role in user_roles.items():
        row = role_rows.get(role)
        if not row:
            continue
        water = get_cell_value(f"B{row}")
        kuryente = get_cell_value(f"G{row}")
        internet = get_cell_value(f"H{row}")
        total = get_cell_value(f"K{row}")
        balance = get_cell_value(f"P{row}")
        payment_M = get_cell_value(f"M{row}")
        payment_O = get_cell_value(f"O{row}")
        details_all += f"User {role} (Row {row}):\n"
        details_all += f"  Water: {water}\n"
        details_all += f"  Kuryente: {kuryente}\n"
        details_all += f"  Internet: {internet}\n"
        details_all += f"  Total: {total}\n"
        details_all += f"  Balance: {balance}\n"
        details_all += f"  Rent Payment (M): {payment_M}\n"
        details_all += f"  Other Payments (O): {payment_O}\n\n"
    if not details_all:
        await update.message.reply_text("No registered users or no data found.")
        return
    await update.message.reply_text(details_all)

# ----------------------------
# New Admin Command: /admincommands (lists admin-only commands)
# ----------------------------
@registered_required
async def admincommands_handler(update: Update, context: CallbackContext):
    admin_cmds = (
        "Admin Commands:\n"
        "• /sendbills\n"
        "• /announce <text>\n"
        "• /list\n"
        "• /billspic\n"
        "• /adminpaid <telegram username> <amount>\n"
        "• /sendallpaymentdeets\n"
        "• /paid <amount>\n"
        "• /start_check_fill_up_status\n"
        "• /check_fill_up_status\n"
        "• /lock\n"
        "• /unlock\n"
        "• /granular_billspic\n"
    )
    await update.message.reply_text(admin_cmds)

# ----------------------------
# Existing Admin Commands (sendbills, announce, list, billspic)
# ----------------------------
@registered_required
async def sendbills_handler(update: Update, context: CallbackContext):
    for user_id, role in user_roles.items():
        if role not in role_rows or role not in abono_water_mapping or role not in abono_others_mapping:
            continue
        row_per_person = role_rows[role]
        row_abono_others = abono_others_mapping[role]
        row_abono_water = abono_water_mapping[role]
        cells = {
            "Water": f"B{row_per_person}",
            "Kuryente": f"G{row_per_person}",
            "Internet": f"H{row_per_person}",
            "Abono (others)": f"B{row_abono_others}",
            "Abono (water)": f"F{row_abono_water}",
            "Total": f"K{row_per_person}",
            "Balance": f"P{row_per_person}"
        }
        details = ""
        for key, cell_ref in cells.items():
            value = get_cell_value(cell_ref)
            details += f"{key}: {value}\n"
        try:
            await context.bot.send_message(chat_id=user_id, text=append_info(f"Billing Details for {role}:\n{details}", bills=True))
        except Exception as e:
            logger.error(f"Error sending bills to user {user_id}: {e}")
    await update.message.reply_text("Success")

@registered_required
async def announce_handler(update: Update, context: CallbackContext):
    announcement = " ".join(context.args)
    if not announcement:
        await update.message.reply_text("Usage: /announce <text>")
        return
    for user_id in user_roles.keys():
        try:
            await context.bot.send_message(chat_id=user_id, text=append_info(f"Announcement:\n{announcement}", bills=True))
        except Exception as e:
            logger.error(f"Error sending announcement to user {user_id}: {e}")
    await update.message.reply_text("Success")

@registered_required
async def list_registered_handler(update: Update, context: CallbackContext):
    if not user_roles:
        await update.message.reply_text("No registered users.")
        return
    msg = "Registered Users:\n"
    for user_id, role in user_roles.items():
        try:
            chat = await context.bot.get_chat(user_id)
            username = chat.username or chat.first_name or str(user_id)
        except Exception as e:
            logger.error(f"Error fetching chat info for user {user_id}: {e}")
            username = str(user_id)
        msg += f"{username} (ID: {user_id}): {role}\n"
    await update.message.reply_text(msg)

@registered_required
async def billspic_handler(update: Update, context: CallbackContext):
    SHEET_NAME = "xtra"
    RANGE = "B3:E19"
    data = get_range_data(SHEET_NAME, RANGE)
    if not data:
        await update.message.reply_text("No data found in the specified range.")
        return
    max_cols = max(len(row) for row in data)
    data_padded = [row + [""] * (max_cols - len(row)) for row in data]
    data_arr = np.array(data_padded)
    
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.axis("tight")
    ax.axis("off")
    table = ax.table(
        cellText=data_arr,
        loc="center",
        cellLoc="center",
        colWidths=[1.0 / max_cols] * max_cols
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    image_path = "billspic.png"
    plt.savefig(image_path, bbox_inches="tight", dpi=150)
    plt.close()
    try:
        await context.bot.send_photo(chat_id=update.message.chat_id, photo=open(image_path, "rb"))
        os.remove(image_path)
    except Exception as e:
        logger.error(f"Error sending billspic: {e}")
        await update.message.reply_text("Error sending the picture.")

# ----------------------------
# New Command: /granular_billspic
# ----------------------------
@registered_required
async def granular_billspic_handler(update: Update, context: CallbackContext):
    SHEET_NAME = "DUES"
    RANGE = "A2:K9"
    data = get_range_data(SHEET_NAME, RANGE)
    if not data:
        await update.message.reply_text("No data found in the specified range.")
        return
    max_cols = max(len(row) for row in data)
    data_padded = [row + [""]*(max_cols - len(row)) for row in data]
    data_arr = np.array(data_padded)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.axis("tight")
    ax.axis("off")
    table = ax.table(cellText=data_arr, loc="center", cellLoc="center", colWidths=[1.0/max_cols]*max_cols)
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    image_path = "granular_billspic.png"
    plt.savefig(image_path, bbox_inches="tight", dpi=150)
    plt.close()
    try:
        await context.bot.send_photo(chat_id=update.message.chat_id, photo=open(image_path, "rb"))
        os.remove(image_path)
    except Exception as e:
        logger.error(f"Error sending granular_billspic: {e}")
        await update.message.reply_text("Error sending the picture.")

# ----------------------------
# New Fill-up Status Commands
# ----------------------------
@registered_required
async def check_fill_up_status_handler(update: Update, context: CallbackContext):
    status = get_cell_value("I27")
    if status == "0":
        data = get_range_data("DUES", "H19:I26")
        if not data:
            await update.message.reply_text("No data found for fill-up status.")
            return
        max_cols = max(len(row) for row in data)
        data_padded = [row + [""] * (max_cols - len(row)) for row in data]
        data_arr = np.array(data_padded)
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.axis("tight")
        ax.axis("off")
        table = ax.table(cellText=data_arr, loc="center", cellLoc="center", colWidths=[1.0/max_cols]*max_cols)
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        image_path = "fillup_status.png"
        plt.savefig(image_path, bbox_inches="tight", dpi=150)
        plt.close()
        await update.message.reply_photo(photo=open(image_path, "rb"))
        os.remove(image_path)
    else:
        await update.message.reply_text("Fill-up status already finalized.")

async def check_fill_up_status_job(context: CallbackContext):
    today = datetime.now()
    if today.day < 15:
        return
    status = get_cell_value("I27")
    chat_id = context.job.chat_id
    if status == "0":
        data = get_range_data("DUES", "H19:I26")
        if not data:
            return
        max_cols = max(len(row) for row in data)
        data_padded = [row + [""] * (max_cols - len(row)) for row in data]
        data_arr = np.array(data_padded)
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.axis("tight")
        ax.axis("off")
        table = ax.table(cellText=data_arr, loc="center", cellLoc="center", colWidths=[1.0/max_cols]*max_cols)
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        image_path = "fillup_status_auto.png"
        plt.savefig(image_path, bbox_inches="tight", dpi=150)
        plt.close()
        try:
            await context.bot.send_photo(chat_id=chat_id, photo=open(image_path, "rb"))
            os.remove(image_path)
        except Exception as e:
            logger.error(f"Error sending automated fill up status image: {e}")
    elif status == "1":
        data = get_range_data("xtra", "B3:E19")
        if not data:
            return
        max_cols = max(len(row) for row in data)
        data_padded = [row + [""] * (max_cols - len(row)) for row in data]
        data_arr = np.array(data_padded)
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.axis("tight")
        ax.axis("off")
        table = ax.table(cellText=data_arr, loc="center", cellLoc="center", colWidths=[1.0/max_cols]*max_cols)
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        image_path = "finalized_computation.png"
        plt.savefig(image_path, bbox_inches="tight", dpi=150)
        plt.close()
        try:
            await context.bot.send_photo(chat_id=chat_id, photo=open(image_path, "rb"), caption="Finalized computation")
            os.remove(image_path)
        except Exception as e:
            logger.error(f"Error sending finalized computation image: {e}")
    if status == "1":
        context.job.schedule_removal()
        next_15 = datetime.now().replace(day=15, hour=6, minute=0, second=0, microsecond=0)
        if datetime.now() >= next_15:
            # If today is already 15 or later, schedule for next month.
            month = next_15.month + 1 if next_15.month < 12 else 1
            year = next_15.year if next_15.month < 12 else next_15.year + 1
            next_15 = next_15.replace(year=year, month=month, day=15)
        delay = (next_15 - datetime.now()).total_seconds()
        context.job_queue.run_once(check_fill_up_status_job, delay, name="fillup_status", chat_id=chat_id)

@registered_required
async def start_check_fill_up_status_handler(update: Update, context: CallbackContext):
    target_time = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
    if datetime.now() >= target_time:
        target_time = target_time.replace(day=datetime.now().day + 1)
    context.job_queue.run_daily(check_fill_up_status_job, time=target_time.time(), name="fillup_status", chat_id=update.effective_chat.id)
    await update.message.reply_text("Automated fill-up status check scheduled for 6am daily (if day >= 15).")

# ----------------------------
# New Command: /granular_billspic
# ----------------------------
@registered_required
async def granular_billspic_handler(update: Update, context: CallbackContext):
    SHEET_NAME = "DUES"
    RANGE = "A2:K9"
    data = get_range_data(SHEET_NAME, RANGE)
    if not data:
        await update.message.reply_text("No data found in the specified range.")
        return
    max_cols = max(len(row) for row in data)
    data_padded = [row + [""]*(max_cols - len(row)) for row in data]
    data_arr = np.array(data_padded)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.axis("tight")
    ax.axis("off")
    table = ax.table(cellText=data_arr, loc="center", cellLoc="center", colWidths=[1.0/max_cols]*max_cols)
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    image_path = "granular_billspic.png"
    plt.savefig(image_path, bbox_inches="tight", dpi=150)
    plt.close()
    try:
        await context.bot.send_photo(chat_id=update.message.chat_id, photo=open(image_path, "rb"))
        os.remove(image_path)
    except Exception as e:
        logger.error(f"Error sending granular_billspic: {e}")
        await update.message.reply_text("Error sending the picture.")

# ----------------------------
# New Admin Commands: /lock and /unlock
# ----------------------------
@registered_required
async def lock_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role != "admin":
        await update.message.reply_text("Only admin can lock the bot.")
        return
    global locked
    locked = True
    await update.message.reply_text("Bot locked. Only admin can call commands.")

@registered_required
async def unlock_handler(update: Update, context: CallbackContext):
    role = user_roles[update.effective_user.id]
    if role != "admin":
        await update.message.reply_text("Only admin can unlock the bot.")
        return
    global locked
    locked = False
    await update.message.reply_text("Bot unlocked. All users can call commands.")

# ----------------------------
# Main Function
# ----------------------------
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # /start and role selection (accessible without registration)
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(role_selection_callback))

    # Public commands
    app.add_handler(CommandHandler("dormkuryente", dormkuryente_handler))
    app.add_handler(CommandHandler("dormwater", dormwater_handler))
    app.add_handler(CommandHandler("listcommands", listcommands_handler))
    app.add_handler(CommandHandler("gcash", gcash_handler))

    # Per person commands
    app.add_handler(CommandHandler("mywater", mywater_handler))
    app.add_handler(CommandHandler("mykuryente", mykuryente_handler))
    app.add_handler(CommandHandler("myinternet", myinternet_handler))
    app.add_handler(CommandHandler("mytotal", mytotal_handler))
    app.add_handler(CommandHandler("mybalance", mybalance_handler))
    app.add_handler(CommandHandler("myabonoothers", myabonoothers_handler))
    app.add_handler(CommandHandler("myabonowater", myabonowater_handler))
    app.add_handler(CommandHandler("mytotalabono", mytotalabono_handler))

    # Abono update commands
    app.add_handler(CommandHandler("add_abono_water", add_abono_water_handler))
    app.add_handler(CommandHandler("add_abono_others", add_abono_others_handler))

    # Payment commands
    app.add_handler(CommandHandler("paid", paid_handler))
    app.add_handler(CommandHandler("adminpaid", adminpaid_handler))
    app.add_handler(CommandHandler("sendallpaymentdeets", sendallpaymentdeets_handler))
    app.add_handler(CommandHandler("admincommands", admincommands_handler))

    # Admin commands (existing)
    app.add_handler(CommandHandler("sendbills", sendbills_handler))
    app.add_handler(CommandHandler("announce", announce_handler))
    app.add_handler(CommandHandler("list", list_registered_handler))
    app.add_handler(CommandHandler("billspic", billspic_handler))

    # New fill-up status commands
    app.add_handler(CommandHandler("check_fill_up_status", check_fill_up_status_handler))
    app.add_handler(CommandHandler("start_check_fill_up_status", start_check_fill_up_status_handler))

    # New granular billspic command
    app.add_handler(CommandHandler("granular_billspic", granular_billspic_handler))

    # New lock/unlock commands
    app.add_handler(CommandHandler("lock", lock_handler))
    app.add_handler(CommandHandler("unlock", unlock_handler))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == '__main__':
    main()
