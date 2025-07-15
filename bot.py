import logging
import re
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# --- BAGIAN 1: KONFIGURASI ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://telegram.org")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

if not all([TOKEN, SPREADSHEET_ID, GSPREAD_CREDENTIALS]):
    raise ValueError("TOKEN, SPREADSHEET_ID, dan GSPREAD_CREDENTIALS wajib diatur.")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAGIAN 2: FUNGSI HELPER (LENGKAP DAN BENAR) ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_formatting import *

def get_gspread_client():
    creds_dict = json.loads(GSPREAD_CREDENTIALS); scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope); return gspread.authorize(creds)
def find_next_available_row(worksheet):
    all_values = worksheet.get_all_values(); return 1 if not all_values else len(all_values) + 4
def _to_safe_name(name): return name.replace(" ", "_")
def _to_real_name(safe_name): return safe_name.replace("_", " ")

def get_all_valid_stores():
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); return [s.title for s in spreadsheet.worksheets() if len(s.title) == 4 and s.title.isalnum()]
    except Exception as e: logger.error(f"Error get_all_valid_stores: {e}"); return []
def add_new_store_and_produk_sheet(store_code):
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID)
        if store_code in [s.title for s in spreadsheet.worksheets()]: return False
        spreadsheet.add_worksheet(title=store_code, rows="1000", cols="50")
        try: spreadsheet.worksheet("produk")
        except gspread.WorksheetNotFound:
            produk_sheet = spreadsheet.add_worksheet(title="produk", rows="2000", cols="3")
            produk_sheet.update('A1:C1', [['plu', 'Nama Barang', 'Barcode']])
        return True
    except Exception as e: logger.error(f"Error add_new_store: {e}"); return False
def delete_store_sheet(store_code):
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); spreadsheet.del_worksheet(spreadsheet.worksheet(store_code)); return True
    except Exception as e: logger.error(f"Error delete_store_sheet: {e}"); return False
def get_racks_in_sheet(store_code):
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID)
        all_named_ranges = spreadsheet.list_named_ranges()
        sheet_racks = [nr['name'] for nr in all_named_ranges if nr.get('rangeName', '').startswith(f"'{store_code}'!")]
        return [_to_real_name(name) for name in sheet_racks]
    except Exception as e: logger.error(f"Error get_racks_in_sheet for {store_code}: {e}"); return []
def add_new_rack(store_code, rack_name):
    safe_rack_name = _to_safe_name(rack_name)
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID)
        if safe_rack_name in [nr['name'] for nr in spreadsheet.list_named_ranges()]: return False
        sheet = spreadsheet.worksheet(store_code)
        start_row = find_next_available_row(sheet); data_start_row = start_row + 1
        sheet.update(f"A{start_row}:C{start_row}", [["Plu", "Nama Barang", "Barcode"]], value_input_option='USER_ENTERED')
        header_format = CellFormat(backgroundColor=Color(0.75, 0.92, 0.61), textFormat=TextFormat(bold=True, fontSize=15), horizontalAlignment='CENTER')
        format_cell_range(sheet, f"A{start_row}:C{start_row}", header_format)
        formula_nama = f'=IFERROR(INDEX(produk!B:B, MATCH(A{data_start_row}, produk!A:A, 0)), "")'
        formula_barcode = f'=IFERROR(INDEX(produk!C:C, MATCH(A{data_start_row}, produk!A:A, 0)), "")'
        sheet.update_cells([gspread.Cell(data_start_row, 2, value=formula_nama), gspread.Cell(data_start_row, 3, value=formula_barcode)], value_input_option='USER_ENTERED')
        data_format = CellFormat(backgroundColor=Color(0.85, 1, 1)); border = Border(style='SOLID')
        range_to_format = f"A{data_start_row}:C{data_start_row + 49}"
        format_cell_range(sheet, range_to_format, data_format)
        format_cell_range(sheet, f"A{start_row}:C{data_start_row + 49}", CellFormat(borders=Borders(top=border, bottom=border, left=border, right=border)))
        spreadsheet.add_named_range(f"'{store_code}'!A{data_start_row}:A", safe_rack_name)
        return True
    except Exception as e: logger.error(f"Error add_new_rack for '{rack_name}': {e}"); return False
def delete_racks(store_code, rack_name):
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID)
        all_named_ranges = spreadsheet.list_named_ranges()
        safe_rack_name = _to_safe_name(rack_name)
        for nr in all_named_ranges:
            if nr.get('name') == safe_rack_name and nr.get('rangeName', '').startswith(f"'{store_code}'!"):
                spreadsheet.delete_named_range(nr['namedRangeId'])
                return True
        return False
    except Exception as e: logger.error(f"Error delete_racks: {e}"); return False

# --- BAGIAN 3: KEYBOARDS (DIKEMBALIKAN SEMUA TOMBOL) ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("Tambah Toko", callback_data="add_store_start"), InlineKeyboardButton("Hapus Toko", callback_data="del_store_ask_sheet")],
        [InlineKeyboardButton("Tambah Rak", callback_data="add_rack_ask_sheet"), InlineKeyboardButton("Hapus Rak", callback_data="del_rack_ask_sheet")],
        [InlineKeyboardButton("Tambah Plu", callback_data="add_plu_ask_sheet"), InlineKeyboardButton("Hapus Plu", callback_data="del_plu_ask_sheet")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_dynamic_keyboard(prefix, items, include_back_button=True):
    keyboard = [InlineKeyboardButton(item, callback_data=f"{prefix}_{_to_safe_name(item)}") for item in items]
    if include_back_button:
        return InlineKeyboardMarkup.from_row(keyboard + [InlineKeyboardButton("<< Kembali", callback_data="start_over")], width=2)
    return InlineKeyboardMarkup.from_row(keyboard, width=2)

# --- BAGIAN 4: HANDLERS (STRUKTUR DIPERBAIKI TOTAL) ---
AWAIT_STORE_CODE, AWAIT_RACK_NAME = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan menu utama."""
    message = update.message or update.callback_query.message
    await message.reply_text("Silakan pilih salah satu opsi:", reply_markup=main_menu_keyboard())
    # Akhiri percakapan apa pun yang mungkin sedang berjalan
    if 'current_conversation' in context.user_data:
        del context.user_data['current_conversation']
    return ConversationHandler.END

async def start_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kembali ke menu utama dari callback, membersihkan state."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Silakan pilih salah satu opsi:", reply_markup=main_menu_keyboard())
    # Akhiri percakapan apa pun yang mungkin sedang berjalan
    if 'current_conversation' in context.user_data:
        del context.user_data['current_conversation']
    return ConversationHandler.END

# Alur Tambah Toko
async def add_store_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Masukkan Kode Toko baru (4 digit alfanumerik):")
    return AWAIT_STORE_CODE

async def add_store_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = update.message.text.upper()
    if len(store_code) != 4 or not store_code.isalnum():
        await update.message.reply_text("Input tidak valid. Kode Toko harus 4 digit alfanumerik. Coba lagi:")
        return AWAIT_STORE_CODE # Tetap di state yang sama untuk input ulang
    
    if add_new_store_and_produk_sheet(store_code):
        await update.message.reply_text(f"Berhasil menambah toko '{store_code}'.", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(f"Toko '{store_code}' sudah ada.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# Alur Hapus Toko
async def del_store_ask_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    stores = get_all_valid_stores()
    if not stores:
        await query.edit_message_text("Tidak ada toko untuk dihapus.", reply_markup=main_menu_keyboard())
        return
    keyboard = build_dynamic_keyboard("del_store_confirm", stores)
    await query.edit_message_text("Pilih toko yang akan dihapus:", reply_markup=keyboard)

async def del_store_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    store_name = _to_real_name(query.data.split('_')[-1])
    context.user_data['store_to_delete'] = store_name
    keyboard = InlineKeyboardMarkup.from_row([
        InlineKeyboardButton("YA, HAPUS", callback_data="del_store_final_yes"),
        InlineKeyboardButton("TIDAK", callback_data="start_over")])
    await query.edit_message_text(f"Yakin ingin menghapus toko '{store_name}'?", reply_markup=keyboard)

async def del_store_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    store_name = context.user_data.pop('store_to_delete', None)
    if store_name and delete_store_sheet(store_name):
        await query.edit_message_text(f"Toko '{store_name}' berhasil dihapus.", reply_markup=main_menu_keyboard())
    else:
        await query.edit_message_text("Gagal menghapus toko.", reply_markup=main_menu_keyboard())

# Alur Tambah Rak
async def add_rack_ask_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    stores = get_all_valid_stores()
    if not stores:
        await query.edit_message_text("Buat toko terlebih dahulu.", reply_markup=main_menu_keyboard()); return
    keyboard = build_dynamic_keyboard("add_rack_ask_name", stores)
    await query.edit_message_text("Pilih toko untuk menambahkan rak:", reply_markup=keyboard)

async def add_rack_ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    context.user_data['store_for_rack'] = _to_real_name(query.data.split('_')[-1])
    await query.edit_message_text("Masukkan nama Rak baru.\nUntuk >1, pisahkan dengan koma.")
    return AWAIT_RACK_NAME

async def add_rack_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_name = context.user_data.pop('store_for_rack', None)
    if not store_name:
        await update.message.reply_text("Sesi berakhir, silakan ulangi.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    
    rack_names = [name.strip() for name in update.message.text.split(',') if name.strip()]
    added, existed = [], []
    for name in rack_names:
        if add_new_rack(store_name, name): added.append(name)
        else: existed.append(name)
    
    parts = [f"Berhasil: {', '.join(added)}." if added else "", f"Sudah ada: {', '.join(existed)}." if existed else ""]
    await update.message.reply_text(f"Di toko {store_name}:\n" + ("\n".join(filter(None, parts)) or "Tidak ada rak ditambahkan."), reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# Alur Hapus Rak
async def del_rack_ask_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    stores = get_all_valid_stores()
    if not stores:
        await query.edit_message_text("Buat toko terlebih dahulu.", reply_markup=main_menu_keyboard()); return
    keyboard = build_dynamic_keyboard("del_rack_ask_rack", stores)
    await query.edit_message_text("Pilih toko untuk menghapus rak:", reply_markup=keyboard)

async def del_rack_ask_rack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    store_name = _to_real_name(query.data.split('_')[-1])
    context.user_data['store_for_del_rack'] = store_name
    racks = get_racks_in_sheet(store_name)
    if not racks:
        await query.edit_message_text(f"Tidak ada rak di toko '{store_name}'.", reply_markup=main_menu_keyboard()); return
    keyboard = build_dynamic_keyboard(f"del_rack_confirm_{_to_safe_name(store_name)}", racks)
    await query.edit_message_text(f"Pilih rak yang akan dihapus dari toko '{store_name}':", reply_markup=keyboard)

async def del_rack_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    parts = query.data.split('_')
    store_name = _to_real_name(parts[3])
    rack_name = _to_real_name(parts[4])
    context.user_data['rack_to_delete'] = {'store': store_name, 'rack': rack_name}
    keyboard = InlineKeyboardMarkup.from_row([
        InlineKeyboardButton("YA, HAPUS", callback_data="del_rack_final_yes"),
        InlineKeyboardButton("TIDAK", callback_data="start_over")])
    await query.edit_message_text(f"Yakin ingin menghapus rak '{rack_name}' dari toko '{store_name}'?", reply_markup=keyboard)

async def del_rack_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    data = context.user_data.pop('rack_to_delete', None)
    if data and delete_racks(data['store'], [data['rack']]):
        await query.edit_message_text(f"Rak '{data['rack']}' berhasil dihapus.", reply_markup=main_menu_keyboard())
    else:
        await query.edit_message_text("Gagal menghapus rak.", reply_markup=main_menu_keyboard())

# --- BAGIAN 5: MAIN ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handler untuk menangani input teks yang memerlukan state
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_store_start, pattern="^add_store_start$"),
            CallbackQueryHandler(add_rack_ask_name, pattern="^add_rack_ask_name_"),
        ],
        states={
            AWAIT_STORE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_store_received)],
            AWAIT_RACK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rack_received)],
        },
        fallbacks=[CallbackQueryHandler(start_over, pattern="^start_over$")],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start_over, pattern="^start_over$"))
    # Daftarkan semua handler callback yang tidak memerlukan state
    application.add_handler(CallbackQueryHandler(del_store_ask_sheet, pattern="^del_store_ask_sheet$"))
    application.add_handler(CallbackQueryHandler(del_store_confirm, pattern="^del_store_confirm_"))
    application.add_handler(CallbackQueryHandler(del_store_final, pattern="^del_store_final_yes$"))
    application.add_handler(CallbackQueryHandler(add_rack_ask_sheet, pattern="^add_rack_ask_sheet$"))
    application.add_handler(CallbackQueryHandler(del_rack_ask_sheet, pattern="^del_rack_ask_sheet$"))
    application.add_handler(CallbackQueryHandler(del_rack_ask_rack, pattern="^del_rack_ask_rack_"))
    application.add_handler(CallbackQueryHandler(del_rack_confirm, pattern=r"^del_rack_confirm_"))
    application.add_handler(CallbackQueryHandler(del_rack_final, pattern="^del_rack_final_yes$"))
    
    # Tambahkan handler utama
    application.add_handler(conv_handler)
    
    logger.info("Bot sedang berjalan dengan polling...")
    application.run_polling()

if __name__ == "__main__":
    main()