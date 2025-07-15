import logging
import os
import json
import re
from functools import wraps

import gspread
from gspread import exceptions as gspread_exceptions
from google.oauth2.service_account import Credentials

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

# Konfigurasi Bot
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") # Gunakan environment variable atau fallback ke nilai default
WEB_APP_URL = os.getenv("WEB_APP_URL") # Gunakan environment variable atau fallback ke nilai default
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID") # Gunakan environment variable atau fallback ke nilai default

# Konfigurasi Google Sheets API
# Disarankan untuk menyimpan kredensial sebagai environment variable di Render
# Misalnya: GOOGLE_SERVICE_ACCOUNT_CREDENTIALS='{"type": "service_account", ...}'
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS", "{}"))

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for ConversationHandler
(
    ADD_STORE_CODE,
    DELETE_STORE_SELECT,
    DELETE_STORE_CONFIRM,
    ADD_RACK_SELECT_STORE,
    ADD_RACK_INPUT_NAMES,
    DELETE_RACK_SELECT_STORE,
    DELETE_RACK_SELECT_RACKS,
    DELETE_RACK_CONFIRM,
    ADD_PLU_SELECT_STORE,
    ADD_PLU_SELECT_RACK,
    ADD_PLU_INPUT_DATA,
    DELETE_PLU_SELECT_STORE,
    DELETE_PLU_SELECT_RACK,
    DELETE_PLU_INPUT_DATA,
    DELETE_PLU_CONFIRM,
) = range(15)

# Global variable to store Google Sheets client
gc = None

# --- Helper Functions ---

def authenticate_google_sheets():
    """Mengautentikasi dengan Google Sheets menggunakan kredensial akun layanan."""
    global gc
    if not SERVICE_ACCOUNT_INFO:
        logger.error("Kredensial akun layanan Google tidak ditemukan di environment variable.")
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS environment variable is not set.")

    try:
        # Menentukan cakupan API yang diperlukan
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        # Membuat objek kredensial dari informasi akun layanan
        creds = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
        # Mengautentikasi gspread client
        gc = gspread.authorize(creds)
        logger.info("Autentikasi Google Sheets berhasil.")
    except Exception as e:
        logger.error(f"Gagal mengautentikasi Google Sheets: {e}")
        raise

def get_spreadsheet():
    """Mendapatkan objek spreadsheet."""
    if gc is None:
        authenticate_google_sheets()
    try:
        spreadsheet = gc.open_by_id(SPREADSHEET_ID)
        return spreadsheet
    except gspread_exceptions.SpreadsheetNotFound:
        logger.error(f"Spreadsheet dengan ID '{SPREADSHEET_ID}' tidak ditemukan.")
        return None
    except Exception as e:
        logger.error(f"Gagal membuka spreadsheet: {e}")
        return None

def get_all_sheet_titles(spreadsheet):
    """Mendapatkan semua judul sheet dari spreadsheet."""
    try:
        return [ws.title for ws in spreadsheet.worksheets()]
    except Exception as e:
        logger.error(f"Gagal mendapatkan judul sheet: {e}")
        return []

def get_filtered_sheet_titles(spreadsheet):
    """Mendapatkan judul sheet yang hanya berisi 4 digit/huruf."""
    all_titles = get_all_sheet_titles(spreadsheet)
    return [title for title in all_titles if re.fullmatch(r'^[A-Z0-9]{4}$', title)]

def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    """Membangun menu inline keyboard dari daftar tombol."""
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, header_buttons)
    if footer_buttons:
        menu.append(footer_buttons)
    return InlineKeyboardMarkup(menu)

def clear_previous_message(func):
    """Decorator untuk menghapus pesan bot sebelumnya."""
    @wraps(func)
    async def wrapper(update: Update, context, *args, **kwargs):
        if update.callback_query:
            try:
                await update.callback_query.message.delete()
            except Exception as e:
                logger.warning(f"Gagal menghapus pesan callback query: {e}")
        elif update.message and update.message.text != "/start": # Jangan hapus pesan /start awal
            try:
                await update.message.delete()
            except Exception as e:
                logger.warning(f"Gagal menghapus pesan pengguna: {e}")
        return await func(update, context, *args, **kwargs)
    return wrapper

# --- Bot Commands and Handlers ---

@clear_previous_message
async def start(update: Update, context):
    """Menangani perintah /start dan menampilkan menu utama."""
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [
            InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
            InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
        ],
        [
            InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
            InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
        ],
        [
            InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
            InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Selamat Datang di Bot PJR by Edp Toko", reply_markup=reply_markup
    )
    return ConversationHandler.END # Akhiri konversasi sebelumnya jika ada

@clear_previous_message
async def invalid_input(update: Update, context):
    """Menangani input teks yang tidak diharapkan."""
    await update.message.reply_text("Data Salah, Harap Pilih Dari Menu")
    # Kembali ke menu utama
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [
            InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
            InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
        ],
        [
            InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
            InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
        ],
        [
            InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
            InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Silahkan pilih opsi dari menu:", reply_markup=reply_markup
    )
    return ConversationHandler.END

@clear_previous_message
async def cancel_action(update: Update, context):
    """Membatalkan operasi saat ini."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Operasi dibatalkan.")
    else:
        await update.message.reply_text("Operasi dibatalkan.")

    # Kembali ke menu utama
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [
            InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
            InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
        ],
        [
            InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
            InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
        ],
        [
            InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
            InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Silahkan pilih opsi dari menu:",
        reply_markup=reply_markup,
    )
    return ConversationHandler.END

# --- Tambah Toko Handlers ---

@clear_previous_message
async def add_store_start(update: Update, context):
    """Memulai proses penambahan toko."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Silahkan Masukan Kode Toko", reply_markup=reply_markup)
    return ADD_STORE_CODE

async def add_store_code(update: Update, context):
    """Menerima kode toko dan menambahkannya."""
    store_code = update.message.text.strip().upper()
    chat_id = update.effective_chat.id

    if not re.fullmatch(r'^[A-Z0-9]{4}$', store_code):
        await update.message.reply_text("Kode Toko Harus 4 Digit")
        return ADD_STORE_CODE # Tetap di state ini

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await update.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        existing_sheets = get_all_sheet_titles(spreadsheet)
        if store_code in existing_sheets:
            await update.message.reply_text(f"Nama {store_code} Sudah Ada")
            return ADD_STORE_CODE # Tetap di state ini
        else:
            spreadsheet.add_worksheet(title=store_code, rows=100, cols=20)
            await update.message.reply_text(f"Berhasil Menambahkan {store_code}")
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"Gagal menambahkan toko: {e}")
        await update.message.reply_text("Terjadi kesalahan saat menambahkan toko. Silakan coba lagi.")
        return ConversationHandler.END
    finally:
        # Kembali ke menu utama setelah operasi selesai
        keyboard = [
            [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
            [
                InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
                InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
            ],
            [
                InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
                InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
            ],
            [
                InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
                InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Silahkan pilih opsi dari menu:",
            reply_markup=reply_markup,
        )

# --- Hapus Toko Handlers ---

@clear_previous_message
async def delete_store_start(update: Update, context):
    """Memulai proses penghapusan toko."""
    query = update.callback_query
    await query.answer()

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    sheet_titles = get_filtered_sheet_titles(spreadsheet)
    if not sheet_titles:
        await query.message.reply_text("Tidak ada kode toko yang tersedia untuk dihapus.")
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(title, callback_data=f"select_store_delete_{title}") for title in sheet_titles]
    reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
    await query.message.reply_text("Silahkan Pilih Kode Toko Yang Akan Dihapus", reply_markup=reply_markup)
    return DELETE_STORE_SELECT

@clear_previous_message
async def delete_store_select(update: Update, context):
    """Menangani pemilihan toko untuk dihapus."""
    query = update.callback_query
    await query.answer()
    store_code = query.data.replace("select_store_delete_", "")
    context.user_data["store_to_delete"] = store_code

    keyboard = [
        [
            InlineKeyboardButton("Ya", callback_data="confirm_delete_store_yes"),
            InlineKeyboardButton("Tidak", callback_data="confirm_delete_store_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(
        f"Anda yakin ingin menghapus toko {store_code}? Ini akan menghapus sheet dan semua datanya.",
        reply_markup=reply_markup,
    )
    return DELETE_STORE_CONFIRM

@clear_previous_message
async def delete_store_confirm(update: Update, context):
    """Menangani konfirmasi penghapusan toko."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    chat_id = update.effective_chat.id

    if choice == "confirm_delete_store_yes":
        store_code = context.user_data.get("store_to_delete")
        if not store_code:
            await query.message.reply_text("Kesalahan: Kode toko tidak ditemukan.")
            return ConversationHandler.END

        spreadsheet = get_spreadsheet()
        if not spreadsheet:
            await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
            return ConversationHandler.END

        try:
            worksheet = spreadsheet.worksheet(store_code)
            spreadsheet.del_worksheet(worksheet)
            await query.message.reply_text(f"Kode Toko {store_code} Berhasil Dihapus")
        except gspread_exceptions.WorksheetNotFound:
            await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        except Exception as e:
            logger.error(f"Gagal menghapus toko {store_code}: {e}")
            await query.message.reply_text(f"Terjadi kesalahan saat menghapus toko {store_code}. Silakan coba lagi.")
    else:
        await query.message.reply_text("Batal Menghapus Kode Toko")

    context.user_data.pop("store_to_delete", None)
    # Kembali ke menu utama setelah operasi selesai
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [
            InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
            InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
        ],
        [
            InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
            InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
        ],
        [
            InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
            InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Silahkan pilih opsi dari menu:",
        reply_markup=reply_markup,
    )
    return ConversationHandler.END

# --- Tambah Rak Handlers ---

@clear_previous_message
async def add_rack_start(update: Update, context):
    """Memulai proses penambahan rak."""
    query = update.callback_query
    await query.answer()

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    sheet_titles = get_filtered_sheet_titles(spreadsheet)
    if not sheet_titles:
        await query.message.reply_text("Tidak ada kode toko yang tersedia untuk ditambahkan rak.")
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(title, callback_data=f"select_store_add_rack_{title}") for title in sheet_titles]
    reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
    await query.message.reply_text("Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return ADD_RACK_SELECT_STORE

@clear_previous_message
async def add_rack_select_store(update: Update, context):
    """Menangani pemilihan toko untuk penambahan rak."""
    query = update.callback_query
    await query.answer()
    store_code = query.data.replace("select_store_add_rack_", "")
    context.user_data["selected_store_add_rack"] = store_code

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        named_ranges = worksheet.get_named_ranges()
        existing_racks = [nr.name for nr in named_ranges if not nr.name.startswith('_')] # Filter out internal named ranges
        
        message_text = f"Nama Rak Yang sudah ada di {store_code}:\n"
        if existing_racks:
            message_text += "\n".join(existing_racks)
        else:
            message_text += "Tidak ada rak yang tersedia."

        keyboard = [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"{message_text}\n\nSilakan Masukan Nama Rak (pisahkan dengan koma atau titik jika lebih dari satu):", reply_markup=reply_markup)
        return ADD_RACK_INPUT_NAMES
    except gspread_exceptions.WorksheetNotFound:
        await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Gagal mendapatkan rak yang sudah ada: {e}")
        await query.message.reply_text("Terjadi kesalahan saat mengambil daftar rak. Silakan coba lagi.")
        return ConversationHandler.END

async def add_rack_input_names(update: Update, context):
    """Menerima nama rak dan menambahkannya."""
    rack_names_input = update.message.text.strip()
    store_code = context.user_data.get("selected_store_add_rack")
    chat_id = update.effective_chat.id

    if not store_code:
        await update.message.reply_text("Kesalahan: Kode toko tidak ditemukan dalam konteks.")
        return ConversationHandler.END

    rack_names = re.split(r'[,.]', rack_names_input)
    rack_names = [name.strip().replace(" ", "_") for name in rack_names if name.strip()] # Clean and replace spaces with underscores

    if not rack_names:
        await update.message.reply_text("Silakan masukan nama rak yang valid.")
        return ADD_RACK_INPUT_NAMES

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await update.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        existing_named_ranges = worksheet.get_named_ranges()
        existing_rack_names = {nr.name for nr in existing_named_ranges}

        added_racks = []
        already_exists_racks = []
        
        # Find the last row used in the sheet to determine where to start new tables
        last_row = 1
        try:
            all_values = worksheet.get_all_values()
            if all_values:
                last_row = len(all_values) + 1
        except Exception as e:
            logger.warning(f"Could not get all values for last row calculation, starting from row 1: {e}")
            last_row = 1

        for rack_name in rack_names:
            if rack_name in existing_rack_names:
                already_exists_racks.append(rack_name)
                continue

            # Add 3 empty rows spacing if it's not the very first table
            if added_racks or already_exists_racks:
                last_row += 3 # Add 3 rows for spacing

            # Define the range for the new table (e.g., 5 rows for initial table)
            start_row = last_row
            end_row = start_row + 4 # 1 header row + 4 data rows initially

            # Define headers
            headers = ["Plu", "Nama Barang", "Barcode"]
            worksheet.update(f'A{start_row}:{chr(ord("A") + len(headers) - 1)}{start_row}', [headers])

            # Apply formulas (assuming 'produk' and 'plu' named ranges exist globally or in the sheet)
            # Formulas are applied to the first data row (start_row + 1)
            # and then extended for a few more rows.
            # Note: Google Sheets automatically extends formulas often, but we can pre-fill
            # a few rows to ensure it works.
            for i in range(1, 5): # Apply to 4 initial data rows
                row_num = start_row + i
                worksheet.update_cell(row_num, 2, f'=IFERROR(INDEX(produk;MATCH(A{row_num};plu;0);2))')
                worksheet.update_cell(row_num, 3, f'=IFERROR(INDEX(produk;MATCH(A{row_num};plu;0);3))')

            # Create a named range for the table
            # The named range will cover the header and initial data rows
            worksheet.add_named_range(f'{store_code}!A{start_row}:{chr(ord("A") + len(headers) - 1)}{end_row}', rack_name)
            
            added_racks.append(rack_name)
            last_row = end_row # Update last_row for the next table

        response_message = ""
        if added_racks:
            response_message += f"Berhasil Menambahkan Rak: {', '.join(added_racks)}\n"
        if already_exists_racks:
            response_message += f"Rak yang sudah ada: {', '.join(already_exists_racks)}\n"
        
        if not added_racks and not already_exists_racks:
            response_message = "Tidak ada rak yang ditambahkan atau ditemukan."

        await update.message.reply_text(response_message.strip())

    except gspread_exceptions.WorksheetNotFound:
        await update.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
    except Exception as e:
        logger.error(f"Gagal menambahkan rak di toko {store_code}: {e}")
        await update.message.reply_text("Terjadi kesalahan saat menambahkan rak. Silakan coba lagi.")
    finally:
        context.user_data.pop("selected_store_add_rack", None)
        # Kembali ke menu utama setelah operasi selesai
        keyboard = [
            [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
            [
                InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
                InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
            ],
            [
                InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
                InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
            ],
            [
                InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
                InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Silahkan pilih opsi dari menu:",
            reply_markup=reply_markup,
        )
        return ConversationHandler.END

# --- Hapus Rak Handlers ---

@clear_previous_message
async def delete_rack_start(update: Update, context):
    """Memulai proses penghapusan rak."""
    query = update.callback_query
    await query.answer()

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    sheet_titles = get_filtered_sheet_titles(spreadsheet)
    if not sheet_titles:
        await query.message.reply_text("Tidak ada kode toko yang tersedia untuk dihapus rak.")
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(title, callback_data=f"select_store_delete_rack_{title}") for title in sheet_titles]
    reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
    await query.message.reply_text("Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return DELETE_RACK_SELECT_STORE

@clear_previous_message
async def delete_rack_select_store(update: Update, context):
    """Menangani pemilihan toko untuk penghapusan rak."""
    query = update.callback_query
    await query.answer()
    store_code = query.data.replace("select_store_delete_rack_", "")
    context.user_data["selected_store_delete_rack"] = store_code

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        named_ranges = worksheet.get_named_ranges()
        existing_racks = [nr.name for nr in named_ranges if not nr.name.startswith('_')]

        if not existing_racks:
            await query.message.reply_text(f"Tidak ada rak yang tersedia di {store_code} untuk dihapus.")
            return ConversationHandler.END

        message_text = f"{store_code}\n" + "\t".join(existing_racks)
        
        keyboard = [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"{message_text}\n\nSilakan Masukan Nama Rak yang akan dihapus (pisahkan dengan koma atau titik):", reply_markup=reply_markup)
        return DELETE_RACK_SELECT_RACKS
    except gspread_exceptions.WorksheetNotFound:
        await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Gagal mendapatkan rak yang sudah ada: {e}")
        await query.message.reply_text("Terjadi kesalahan saat mengambil daftar rak. Silakan coba lagi.")
        return ConversationHandler.END

async def delete_rack_select_racks(update: Update, context):
    """Menerima nama rak yang akan dihapus dan meminta konfirmasi."""
    rack_names_input = update.message.text.strip()
    store_code = context.user_data.get("selected_store_delete_rack")
    chat_id = update.effective_chat.id

    if not store_code:
        await update.message.reply_text("Kesalahan: Kode toko tidak ditemukan dalam konteks.")
        return ConversationHandler.END

    rack_names = re.split(r'[,.]', rack_names_input)
    rack_names = [name.strip().replace(" ", "_") for name in rack_names if name.strip()]

    if not rack_names:
        await update.message.reply_text("Silakan masukan nama rak yang valid untuk dihapus.")
        return DELETE_RACK_SELECT_RACKS

    context.user_data["racks_to_delete"] = rack_names

    keyboard = [
        [
            InlineKeyboardButton("Ya", callback_data="confirm_delete_rack_yes"),
            InlineKeyboardButton("Tidak", callback_data="confirm_delete_rack_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Anda yakin ingin menghapus rak: {', '.join(rack_names)} di toko {store_code}? Ini akan menghapus tabel dan semua datanya.",
        reply_markup=reply_markup,
    )
    return DELETE_RACK_CONFIRM

@clear_previous_message
async def delete_rack_confirm(update: Update, context):
    """Menangani konfirmasi penghapusan rak."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    chat_id = update.effective_chat.id
    store_code = context.user_data.get("selected_store_delete_rack")
    racks_to_delete = context.user_data.get("racks_to_delete")

    if not store_code or not racks_to_delete:
        await query.message.reply_text("Kesalahan: Informasi toko atau rak tidak ditemukan.")
        return ConversationHandler.END

    if choice == "confirm_delete_rack_yes":
        spreadsheet = get_spreadsheet()
        if not spreadsheet:
            await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
            return ConversationHandler.END

        try:
            worksheet = spreadsheet.worksheet(store_code)
            existing_named_ranges = worksheet.get_named_ranges()
            existing_rack_names = {nr.name: nr for nr in existing_named_ranges}

            deleted_racks = []
            not_found_racks = []

            for rack_name in racks_to_delete:
                if rack_name in existing_rack_names:
                    named_range_obj = existing_rack_names[rack_name]
                    # Get the range of the named range
                    range_name = named_range_obj.range
                    
                    # Delete the named range
                    worksheet.delete_named_range(named_range_obj.id)
                    
                    # Clear the content of the cells covered by the named range
                    # Note: gspread's clear() method can be used on a range
                    # However, to truly "delete" the table, we would need to delete rows/columns,
                    # which can affect other data. For now, we will just clear the content
                    # and remove the named range.
                    worksheet.clear(range_name)
                    deleted_racks.append(rack_name)
                else:
                    not_found_racks.append(rack_name)
            
            response_message = ""
            if deleted_racks:
                response_message += f"Berhasil Menghapus Rak: {', '.join(deleted_racks)}\n"
            if not_found_racks:
                response_message += f"Rak tidak ditemukan: {', '.join(not_found_racks)}\n"
            
            await query.message.reply_text(response_message.strip())

        except gspread_exceptions.WorksheetNotFound:
            await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        except Exception as e:
            logger.error(f"Gagal menghapus rak di toko {store_code}: {e}")
            await query.message.reply_text("Terjadi kesalahan saat menghapus rak. Silakan coba lagi.")
    else:
        await query.message.reply_text("Batal Menghapus Rak")

    context.user_data.pop("selected_store_delete_rack", None)
    context.user_data.pop("racks_to_delete", None)
    # Kembali ke menu utama setelah operasi selesai
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [
            InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
            InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
        ],
        [
            InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
            InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
        ],
        [
                InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
                InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Silahkan pilih opsi dari menu:",
        reply_markup=reply_markup,
    )
    return ConversationHandler.END

# --- Tambah Plu Handlers ---

@clear_previous_message
async def add_plu_start(update: Update, context):
    """Memulai proses penambahan PLU."""
    query = update.callback_query
    await query.answer()

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    sheet_titles = get_filtered_sheet_titles(spreadsheet)
    if not sheet_titles:
        await query.message.reply_text("Tidak ada kode toko yang tersedia untuk ditambahkan PLU.")
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(title, callback_data=f"select_store_add_plu_{title}") for title in sheet_titles]
    reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
    await query.message.reply_text("Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return ADD_PLU_SELECT_STORE

@clear_previous_message
async def add_plu_select_store(update: Update, context):
    """Menangani pemilihan toko untuk penambahan PLU."""
    query = update.callback_query
    await query.answer()
    store_code = query.data.replace("select_store_add_plu_", "")
    context.user_data["selected_store_add_plu"] = store_code

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        named_ranges = worksheet.get_named_ranges()
        existing_racks = [nr.name for nr in named_ranges if not nr.name.startswith('_')]

        if not existing_racks:
            await query.message.reply_text(f"Tidak ada rak yang tersedia di {store_code} untuk ditambahkan PLU.")
            return ConversationHandler.END

        buttons = [InlineKeyboardButton(rack_name, callback_data=f"select_rack_add_plu_{rack_name}") for rack_name in existing_racks]
        reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
        await query.message.reply_text("Silahkan Pilih Nama Rak", reply_markup=reply_markup)
        return ADD_PLU_SELECT_RACK
    except gspread_exceptions.WorksheetNotFound:
        await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Gagal mendapatkan rak yang sudah ada: {e}")
        await query.message.reply_text("Terjadi kesalahan saat mengambil daftar rak. Silakan coba lagi.")
        return ConversationHandler.END

@clear_previous_message
async def add_plu_select_rack(update: Update, context):
    """Menangani pemilihan rak untuk penambahan PLU."""
    query = update.callback_query
    await query.answer()
    rack_name = query.data.replace("select_rack_add_plu_", "")
    context.user_data["selected_rack_add_plu"] = rack_name

    keyboard = [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Silakan Masukan Data Plu (pisahkan dengan spasi, koma, titik, atau enter):", reply_markup=reply_markup)
    return ADD_PLU_INPUT_DATA

async def add_plu_input_data(update: Update, context):
    """Menerima data PLU dan menambahkannya ke rak."""
    plu_input = update.message.text.strip()
    store_code = context.user_data.get("selected_store_add_plu")
    rack_name = context.user_data.get("selected_rack_add_plu")
    chat_id = update.effective_chat.id

    if not store_code or not rack_name:
        await update.message.reply_text("Kesalahan: Informasi toko atau rak tidak ditemukan dalam konteks.")
        return ConversationHandler.END

    # Split PLU input by various delimiters
    plu_list = re.split(r'[\s,.]|\n', plu_input)
    plu_list = [p.strip() for p in plu_list if p.strip()]

    if len(plu_list) < 2:
        await update.message.reply_text("Silakan masukan minimal 2 data PLU.")
        return ADD_PLU_INPUT_DATA

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await update.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        
        # Get the named range object for the rack
        named_ranges = worksheet.get_named_ranges()
        rack_named_range = next((nr for nr in named_ranges if nr.name == rack_name), None)

        if not rack_named_range:
            await update.message.reply_text(f"Rak '{rack_name}' tidak ditemukan di toko '{store_code}'.")
            return ConversationHandler.END

        # Get the current values in the rack's PLU column (column A of the named range)
        # Assuming the named range starts at column A
        rack_range_str = rack_named_range.range
        # Parse the range string to get start_row and end_row for column A
        match = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', rack_range_str)
        if not match:
            await update.message.reply_text(f"Gagal mengurai rentang rak: {rack_range_str}")
            return ConversationHandler.END
        
        start_col_letter, start_row, end_col_letter, end_row = match.groups()
        start_row = int(start_row)
        end_row = int(end_row)

        # Get existing PLUs in the rack's PLU column (assuming it's the first column of the named range)
        # We need to get the actual column A values from the sheet, not just the named range.
        # This is because the named range might not cover all data if new data was added beyond it.
        # So we fetch all values from column A starting from the rack's header row + 1
        current_plu_column_values = worksheet.col_values(1, start=start_row + 1) # Column A, starting after header
        existing_plu_in_rack = set(current_plu_column_values)

        new_plu_data = []
        duplicate_plu = []
        
        # Prepare data for batch update
        values_to_append = []
        for plu in plu_list:
            if plu in existing_plu_in_rack:
                duplicate_plu.append(plu)
            else:
                values_to_append.append([plu, '', '']) # PLU, Nama Barang (formula), Barcode (formula)
                new_plu_data.append(plu)
                existing_plu_in_rack.add(plu) # Add to set to prevent duplicates within the new list

        if values_to_append:
            # Find the first empty row below the existing data in the rack
            # This is a bit tricky with named ranges. A simpler approach is to append to the sheet
            # and then update the named range to include the new rows.
            # Or, we can find the last used row in the specific column of the rack.
            
            # Let's find the actual last row in the named range's first column (PLU column)
            plu_column_values = worksheet.col_values(1, value_render_option='UNFORMATTED_VALUE')
            # Find the actual row number of the last non-empty cell in the PLU column
            last_plu_row = start_row # Start from the header row
            for i in range(start_row -1, len(plu_column_values)): # Iterate from 0-indexed values
                if plu_column_values[i].strip():
                    last_plu_row = i + 1 # Convert to 1-indexed row number
            
            # The row to start appending new data is last_plu_row + 1
            append_start_row = last_plu_row + 1

            # Update the sheet with new PLU data
            worksheet.update(f'A{append_start_row}', values_to_append)

            # Re-fetch the named range to update its extent to include new rows
            # This is crucial for formulas to apply correctly and for the named range to reflect the new data.
            # We need to calculate the new end row for the named range.
            new_end_row = append_start_row + len(values_to_append) - 1
            
            # Update the named range to cover the new data.
            # This requires deleting the old named range and creating a new one.
            worksheet.delete_named_range(rack_named_range.id)
            worksheet.add_named_range(f'{store_code}!A{start_row}:{end_col_letter}{new_end_row}', rack_name)


        response_message = ""
        if new_plu_data:
            response_message += f"Berhasil Menambahkan Plu Ke {rack_name} di toko {store_code}:\n"
            response_message += "Plu\t\tNama Barang\n"
            # To get Nama Barang, we'd need to read the sheet again after formulas are applied.
            # This is a bit complex for a single message, as it depends on external 'produk' range.
            # For simplicity, I'll just list the PLUs added.
            for plu in new_plu_data:
                response_message += f"{plu}\t\t[text]\n" # Placeholder as per requirement
        
        if duplicate_plu:
            response_message += f"Plu yang sudah ada di {rack_name}: {', '.join(duplicate_plu)}\n"
        
        if not new_plu_data and not duplicate_plu:
            response_message = "Tidak ada PLU yang ditambahkan."

        await update.message.reply_text(response_message.strip())

    except gspread_exceptions.WorksheetNotFound:
        await update.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
    except Exception as e:
        logger.error(f"Gagal menambahkan PLU di rak {rack_name} toko {store_code}: {e}")
        await update.message.reply_text("Terjadi kesalahan saat menambahkan PLU. Silakan coba lagi.")
    finally:
        context.user_data.pop("selected_store_add_plu", None)
        context.user_data.pop("selected_rack_add_plu", None)
        # Kembali ke menu utama setelah operasi selesai
        keyboard = [
            [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
            [
                InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
                InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
            ],
            [
                InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
                InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
            ],
            [
                InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
                InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Silahkan pilih opsi dari menu:",
            reply_markup=reply_markup,
        )
        return ConversationHandler.END

# --- Hapus Plu Handlers ---

@clear_previous_message
async def delete_plu_start(update: Update, context):
    """Memulai proses penghapusan PLU."""
    query = update.callback_query
    await query.answer()

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    sheet_titles = get_filtered_sheet_titles(spreadsheet)
    if not sheet_titles:
        await query.message.reply_text("Tidak ada kode toko yang tersedia untuk dihapus PLU.")
        return ConversationHandler.END

    buttons = [InlineKeyboardButton(title, callback_data=f"select_store_delete_plu_{title}") for title in sheet_titles]
    reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
    await query.message.reply_text("Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return DELETE_PLU_SELECT_STORE

@clear_previous_message
async def delete_plu_select_store(update: Update, context):
    """Menangani pemilihan toko untuk penghapusan PLU."""
    query = update.callback_query
    await query.answer()
    store_code = query.data.replace("select_store_delete_plu_", "")
    context.user_data["selected_store_delete_plu"] = store_code

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        named_ranges = worksheet.get_named_ranges()
        existing_racks = [nr.name for nr in named_ranges if not nr.name.startswith('_')]

        if not existing_racks:
            await query.message.reply_text(f"Tidak ada rak yang tersedia di {store_code} untuk dihapus PLU.")
            return ConversationHandler.END

        buttons = [InlineKeyboardButton(rack_name, callback_data=f"select_rack_delete_plu_{rack_name}") for rack_name in existing_racks]
        reply_markup = build_menu(buttons, n_cols=2, footer_buttons=[InlineKeyboardButton("Cancel", callback_data="cancel")])
        await query.message.reply_text("Silahkan Pilih Rak", reply_markup=reply_markup)
        return DELETE_PLU_SELECT_RACK

    except gspread_exceptions.WorksheetNotFound:
        await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Gagal mendapatkan rak yang sudah ada: {e}")
        await query.message.reply_text("Terjadi kesalahan saat mengambil daftar rak. Silakan coba lagi.")
        return ConversationHandler.END

@clear_previous_message
async def delete_plu_select_rack(update: Update, context):
    """Menangani pemilihan rak untuk penghapusan PLU dan menampilkan daftar PLU."""
    query = update.callback_query
    await query.answer()
    rack_name = query.data.replace("select_rack_delete_plu_", "")
    context.user_data["selected_rack_delete_plu"] = rack_name
    store_code = context.user_data.get("selected_store_delete_plu")

    if not store_code or not rack_name:
        await query.message.reply_text("Kesalahan: Informasi toko atau rak tidak ditemukan dalam konteks.")
        return ConversationHandler.END

    spreadsheet = get_spreadsheet()
    if not spreadsheet:
        await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
        return ConversationHandler.END

    try:
        worksheet = spreadsheet.worksheet(store_code)
        named_ranges = worksheet.get_named_ranges()
        rack_named_range = next((nr for nr in named_ranges if nr.name == rack_name), None)

        if not rack_named_range:
            await query.message.reply_text(f"Rak '{rack_name}' tidak ditemukan di toko '{store_code}'.")
            return ConversationHandler.END

        # Get all values from the named range
        # Assuming the named range covers the entire table including headers
        range_values = worksheet.get_values(rack_named_range.range)
        
        if not range_values or len(range_values) < 2: # No header or no data
            await query.message.reply_text(f"Tidak ada data PLU di rak '{rack_name}'.")
            return ConversationHandler.END

        # Extract PLU and Nama Barang from the data rows
        # Assuming PLU is in column 0 (A), Nama Barang in column 1 (B)
        plu_data_display = f"{rack_name}\nPlu\tNama Barang\n"
        for row in range_values[1:]: # Skip header row
            plu = row[0] if len(row) > 0 else ""
            nama_barang = row[1] if len(row) > 1 else "[text]" # Use [text] as placeholder
            if plu.strip(): # Only display rows with actual PLU
                plu_data_display += f"{plu}\t{nama_barang}\n"
        
        keyboard = [[InlineKeyboardButton("Cancel", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(f"{plu_data_display}\nSilakan Masukan Data Plu yang akan dihapus (pisahkan dengan spasi, koma, titik, atau enter):", reply_markup=reply_markup)
        return DELETE_PLU_INPUT_DATA

async def delete_plu_input_data(update: Update, context):
    """Menerima data PLU yang akan dihapus dan meminta konfirmasi."""
    plu_input = update.message.text.strip()
    store_code = context.user_data.get("selected_store_delete_plu")
    rack_name = context.user_data.get("selected_rack_delete_plu")
    chat_id = update.effective_chat.id

    if not store_code or not rack_name:
        await update.message.reply_text("Kesalahan: Informasi toko atau rak tidak ditemukan dalam konteks.")
        return ConversationHandler.END

    plu_list_to_delete = re.split(r'[\s,.]|\n', plu_input)
    plu_list_to_delete = [p.strip() for p in plu_list_to_delete if p.strip()]

    if not plu_list_to_delete:
        await update.message.reply_text("Silakan masukan PLU yang valid untuk dihapus.")
        return DELETE_PLU_INPUT_DATA

    context.user_data["plu_to_delete"] = plu_list_to_delete

    keyboard = [
        [
            InlineKeyboardButton("Ya", callback_data="confirm_delete_plu_yes"),
            InlineKeyboardButton("Tidak", callback_data="confirm_delete_plu_no"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Anda yakin ingin menghapus PLU: {', '.join(plu_list_to_delete)} dari rak {rack_name} di toko {store_code}?",
        reply_markup=reply_markup,
    )
    return DELETE_PLU_CONFIRM

@clear_previous_message
async def delete_plu_confirm(update: Update, context):
    """Menangani konfirmasi penghapusan PLU."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    chat_id = update.effective_chat.id
    store_code = context.user_data.get("selected_store_delete_plu")
    rack_name = context.user_data.get("selected_rack_delete_plu")
    plu_list_to_delete = context.user_data.get("plu_to_delete")

    if not store_code or not rack_name or not plu_list_to_delete:
        await query.message.reply_text("Kesalahan: Informasi toko, rak, atau PLU tidak ditemukan.")
        return ConversationHandler.END

    if choice == "confirm_delete_plu_yes":
        spreadsheet = get_spreadsheet()
        if not spreadsheet:
            await query.message.reply_text("Terjadi kesalahan saat mengakses spreadsheet. Silakan coba lagi.")
            return ConversationHandler.END

        try:
            worksheet = spreadsheet.worksheet(store_code)
            named_ranges = worksheet.get_named_ranges()
            rack_named_range = next((nr for nr in named_ranges if nr.name == rack_name), None)

            if not rack_named_range:
                await query.message.reply_text(f"Rak '{rack_name}' tidak ditemukan di toko '{store_code}'.")
                return ConversationHandler.END

            # Get all values from the named range
            range_values = worksheet.get_values(rack_named_range.range)
            
            if not range_values or len(range_values) < 2:
                await query.message.reply_text(f"Tidak ada data PLU di rak '{rack_name}' untuk dihapus.")
                return ConversationHandler.END

            header_row = range_values[0]
            data_rows = range_values[1:] # Actual data rows

            plu_found_and_deleted = []
            plu_not_found = []
            updated_data_rows = []
            
            # Find the actual start row of the named range in the sheet
            match = re.match(r'([A-Z]+)(\d+):([A-Z]+)(\d+)', rack_named_range.range)
            if not match:
                await query.message.reply_text(f"Gagal mengurai rentang rak: {rack_named_range.range}")
                return ConversationHandler.END
            
            start_row_in_sheet = int(match.groups()[1])

            rows_to_clear_indices = [] # Store 0-indexed row numbers relative to data_rows
            
            for i, row in enumerate(data_rows):
                plu_in_row = row[0] if len(row) > 0 else ""
                if plu_in_row in plu_list_to_delete:
                    plu_found_and_deleted.append(plu_in_row)
                    rows_to_clear_indices.append(i) # Mark for clearing
                else:
                    updated_data_rows.append(row)

            # Identify PLUs that were requested but not found
            for requested_plu in plu_list_to_delete:
                if requested_plu not in plu_found_and_deleted:
                    plu_not_found.append(requested_plu)

            if rows_to_clear_indices:
                # Clear the content of the rows that contain the PLUs to be deleted
                # We need to calculate the actual sheet row numbers
                cells_to_clear = []
                for idx in rows_to_clear_indices:
                    sheet_row_num = start_row_in_sheet + 1 + idx # +1 for header, +idx for data row offset
                    # Assuming the table has 3 columns (A, B, C)
                    cells_to_clear.append(f'A{sheet_row_num}:C{sheet_row_num}')
                
                # Batch clear the cells
                for cell_range in cells_to_clear:
                    worksheet.clear(cell_range)
                
                # Optional: Sort the remaining data to fill gaps if desired.
                # This can be complex if there are multiple tables.
                # For simplicity, we'll just clear the cells.
                
                response_message = "Berhasil Menghapus Plu:\n" + "\n".join(plu_found_and_deleted)
            else:
                response_message = "Tidak ada PLU yang dihapus."

            if plu_not_found:
                response_message += "\nPlu Tidak Ditemukan di Rak " + rack_name + ": " + ", ".join(plu_not_found)
            
            await query.message.reply_text(response_message.strip())

        except gspread_exceptions.WorksheetNotFound:
            await query.message.reply_text(f"Kode Toko {store_code} tidak ditemukan.")
        except Exception as e:
            logger.error(f"Gagal menghapus PLU di rak {rack_name} toko {store_code}: {e}")
            await query.message.reply_text("Terjadi kesalahan saat menghapus PLU. Silakan coba lagi.")
    else:
        await query.message.reply_text("Batal Menghapus Plu")

    context.user_data.pop("selected_store_delete_plu", None)
    context.user_data.pop("selected_rack_delete_plu", None)
    context.user_data.pop("plu_to_delete", None)
    # Kembali ke menu utama setelah operasi selesai
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [
            InlineKeyboardButton("Tambah Toko", callback_data="add_store"),
            InlineKeyboardButton("Hapus Toko", callback_data="delete_store"),
        ],
        [
            InlineKeyboardButton("Tambah Rak", callback_data="add_rack"),
            InlineKeyboardButton("Hapus Rak", callback_data="delete_rack"),
        ],
        [
            InlineKeyboardButton("Tambah Plu", callback_data="add_plu"),
            InlineKeyboardButton("Hapus Plu", callback_data="delete_plu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Silahkan pilih opsi dari menu:",
        reply_markup=reply_markup,
    )
    return ConversationHandler.END

def main():
    """Menjalankan bot."""
    try:
        authenticate_google_sheets()
    except ValueError as e:
        logger.error(f"Bot tidak dapat dimulai karena kesalahan autentikasi: {e}")
        return

    application = Application.builder().token(TOKEN).build()

    # Conversation Handler for Add Store
    add_store_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_store_start, pattern="^add_store$")],
        states={
            ADD_STORE_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_store_code),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )
    application.add_handler(add_store_conv_handler)

    # Conversation Handler for Delete Store
    delete_store_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_store_start, pattern="^delete_store$")],
        states={
            DELETE_STORE_SELECT: [
                CallbackQueryHandler(delete_store_select, pattern="^select_store_delete_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            DELETE_STORE_CONFIRM: [
                CallbackQueryHandler(delete_store_confirm, pattern="^confirm_delete_store_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )
    application.add_handler(delete_store_conv_handler)

    # Conversation Handler for Add Rack
    add_rack_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_rack_start, pattern="^add_rack$")],
        states={
            ADD_RACK_SELECT_STORE: [
                CallbackQueryHandler(add_rack_select_store, pattern="^select_store_add_rack_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            ADD_RACK_INPUT_NAMES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_rack_input_names),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )
    application.add_handler(add_rack_conv_handler)

    # Conversation Handler for Delete Rack
    delete_rack_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_rack_start, pattern="^delete_rack$")],
        states={
            DELETE_RACK_SELECT_STORE: [
                CallbackQueryHandler(delete_rack_select_store, pattern="^select_store_delete_rack_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            DELETE_RACK_SELECT_RACKS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_rack_select_racks),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            DELETE_RACK_CONFIRM: [
                CallbackQueryHandler(delete_rack_confirm, pattern="^confirm_delete_rack_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )
    application.add_handler(delete_rack_conv_handler)

    # Conversation Handler for Add PLU
    add_plu_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_plu_start, pattern="^add_plu$")],
        states={
            ADD_PLU_SELECT_STORE: [
                CallbackQueryHandler(add_plu_select_store, pattern="^select_store_add_plu_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            ADD_PLU_SELECT_RACK: [
                CallbackQueryHandler(add_plu_select_rack, pattern="^select_rack_add_plu_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            ADD_PLU_INPUT_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plu_input_data),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )
    application.add_handler(add_plu_conv_handler)

    # Conversation Handler for Delete PLU
    delete_plu_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(delete_plu_start, pattern="^delete_plu$")],
        states={
            DELETE_PLU_SELECT_STORE: [
                CallbackQueryHandler(delete_plu_select_store, pattern="^select_store_delete_plu_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            DELETE_PLU_SELECT_RACK: [
                CallbackQueryHandler(delete_plu_select_rack, pattern="^select_rack_delete_plu_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            DELETE_PLU_INPUT_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_plu_input_data),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
            DELETE_PLU_CONFIRM: [
                CallbackQueryHandler(delete_plu_confirm, pattern="^confirm_delete_plu_"),
                CallbackQueryHandler(cancel_action, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input),
            CommandHandler("start", start),
        ],
        allow_reentry=True,
    )
    application.add_handler(delete_plu_conv_handler)

    # Main Command Handler
    application.add_handler(CommandHandler("start", start))
    
    # Fallback for any unexpected text input outside of a conversation
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, invalid_input))

    # Run the bot (for Render, use webhook)
    PORT = int(os.environ.get("PORT", "8080"))
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{WEB_APP_URL.split('//')[1].split('/')[0]}/{TOKEN}", # Construct webhook URL from WEB_APP_URL
        # We need to ensure the WEB_APP_URL is the base URL for the Render service
        # and append the token as the path.
        # Example: if WEB_APP_URL is https://my-render-app.onrender.com/index.php
        # then webhook_url should be https://my-render-app.onrender.com/<TOKEN>
    )

if __name__ == "__main__":
    main()

