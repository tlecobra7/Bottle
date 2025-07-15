import logging
import re
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# --- BAGIAN 1: KONFIGURASI ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://google.com") # Default URL jika tidak diatur
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

if not all([TOKEN, SPREADSHEET_ID, GSPREAD_CREDENTIALS]):
    raise ValueError("TOKEN, SPREADSHEET_ID, dan GSPREAD_CREDENTIALS wajib diatur.")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAGIAN 2: FUNGSI HELPER ---
# (Semua fungsi helper dari jawaban sebelumnya yang sudah benar dan lengkap)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_formatting import *

def get_gspread_client():
    creds_dict = json.loads(GSPREAD_CREDENTIALS)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)
def find_next_available_row(worksheet):
    all_values = worksheet.get_all_values()
    return 1 if not all_values else len(all_values) + 4
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
def delete_racks(store_code, racks_to_delete):
    deleted, not_found = [], []
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID)
        all_named_ranges = spreadsheet.list_named_ranges()
        for rack in racks_to_delete:
            safe_rack_name = _to_safe_name(rack)
            found = False
            for nr in all_named_ranges:
                if nr.get('name') == safe_rack_name:
                    spreadsheet.delete_named_range(nr['namedRangeId'])
                    deleted.append(rack); found = True; break
            if not found: not_found.append(rack)
        return deleted, not_found
    except Exception as e: logger.error(f"Error delete_racks: {e}"); return [], racks_to_delete

# --- BAGIAN 3: KEYBOARDS ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("Tambah Toko", callback_data="add_store"), InlineKeyboardButton("Hapus Toko", callback_data="del_store_ask_sheet")],
        [InlineKeyboardButton("Tambah Rak", callback_data="add_rack_ask_sheet"), InlineKeyboardButton("Hapus Rak", callback_data="del_rack_ask_sheet")],
        # [InlineKeyboardButton("Tambah Plu", callback_data="add_plu_ask_sheet"), InlineKeyboardButton("Hapus Plu", callback_data="del_plu_ask_sheet")], # Sementara dinonaktifkan
    ]
    return InlineKeyboardMarkup(keyboard)

def build_dynamic_keyboard(prefix, items):
    keyboard = [InlineKeyboardButton(item, callback_data=f"{prefix}_{_to_safe_name(item)}") for item in items]
    keyboard.append(InlineKeyboardButton("<< Kembali", callback_data="start_over"))
    return InlineKeyboardMarkup.from_row(keyboard, width=2)

# --- BAGIAN 4: HANDLERS ---
AWAIT_INPUT = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan menu utama."""
    await update.message.reply_text("Silakan pilih salah satu opsi:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

async def start_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kembali ke menu utama dari callback."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Silakan pilih salah satu opsi:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# Alur Tambah Toko
async def add_store_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['next_action'] = 'add_store_final'
    await query.edit_message_text("Masukkan Kode Toko baru (4 digit alfanumerik):")
    return AWAIT_INPUT

# Alur Hapus Toko
async def del_store_ask_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stores = get_all_valid_stores()
    if not stores:
        await query.edit_message_text("Tidak ada toko untuk dihapus.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    keyboard = build_dynamic_keyboard("del_store_confirm", stores)
    await query.edit_message_text("Pilih toko yang akan dihapus:", reply_markup=keyboard)

async def del_store_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    safe_store_name = query.data.split('_')[-1]
    store_name = _to_real_name(safe_store_name)
    context.user_data['store_to_delete'] = store_name
    keyboard = InlineKeyboardMarkup.from_row([
        InlineKeyboardButton("YA, HAPUS", callback_data="del_store_final_yes"),
        InlineKeyboardButton("TIDAK", callback_data="start_over")
    ])
    await query.edit_message_text(f"Apakah Anda yakin ingin menghapus toko '{store_name}'?", reply_markup=keyboard)

async def del_store_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    store_name = context.user_data.pop('store_to_delete', None)
    if store_name and delete_store_sheet(store_name):
        await query.edit_message_text(f"Toko '{store_name}' berhasil dihapus.", reply_markup=main_menu_keyboard())
    else:
        await query.edit_message_text(f"Gagal menghapus toko.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# Alur Tambah Rak
async def add_rack_ask_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stores = get_all_valid_stores()
    if not stores:
        await query.edit_message_text("Tidak ada toko. Silakan buat toko terlebih dahulu.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    keyboard = build_dynamic_keyboard("add_rack_ask_name", stores)
    await query.edit_message_text("Pilih toko untuk menambahkan rak:", reply_markup=keyboard)

async def add_rack_ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    safe_store_name = query.data.split('_')[-1]
    context.user_data['store_for_rack'] = _to_real_name(safe_store_name)
    context.user_data['next_action'] = 'add_rack_final'
    await query.edit_message_text("Masukkan nama Rak baru (bisa dengan spasi). Untuk >1, pisahkan dengan koma.")
    return AWAIT_INPUT

# Handler Umum untuk Input Teks
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.pop('next_action', None)
    text = update.message.text
    
    if action == 'add_store_final':
        store_code = text.upper()
        if len(store_code) != 4 or not store_code.isalnum():
            await update.message.reply_text("Input tidak valid. Kode Toko harus 4 digit alfanumerik. Coba lagi:")
            context.user_data['next_action'] = 'add_store_final' # Set ulang aksi
            return AWAIT_INPUT
        if add_new_store_and_produk_sheet(store_code):
            await update.message.reply_text(f"Berhasil menambah toko '{store_code}'.", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"Toko '{store_code}' sudah ada.", reply_markup=main_menu_keyboard())
    
    elif action == 'add_rack_final':
        store_name = context.user_data.pop('store_for_rack', None)
        if not store_name:
            await update.message.reply_text("Sesi berakhir. Silakan ulangi.", reply_markup=main_menu_keyboard())
            return ConversationHandler.END
        
        rack_names = [name.strip() for name in text.split(',') if name.strip()]
        added, existed = [], []
        for name in rack_names:
            if add_new_rack(store_name, name):
                added.append(name)
            else:
                existed.append(name)
        
        parts = []
        if added: parts.append(f"Berhasil menambah rak: {', '.join(added)} di toko {store_name}.")
        if existed: parts.append(f"Rak sudah ada: {', '.join(existed)}.")
        await update.message.reply_text("\n".join(parts) or "Tidak ada rak ditambahkan.", reply_markup=main_menu_keyboard())

    else:
        await update.message.reply_text("Silakan pilih salah satu opsi dari menu.", reply_markup=main_menu_keyboard())

    return ConversationHandler.END

# --- BAGIAN 5: MAIN ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handler sederhana untuk menangani input teks
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_store_start, pattern="^add_store$"),
            CallbackQueryHandler(add_rack_ask_name, pattern="^add_rack_ask_name_"),
        ],
        states={
            AWAIT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(start_over, pattern="^start_over$"))
    application.add_handler(CallbackQueryHandler(del_store_ask_sheet, pattern="^del_store_ask_sheet$"))
    application.add_handler(CallbackQueryHandler(del_store_confirm, pattern="^del_store_confirm_"))
    application.add_handler(CallbackQueryHandler(del_store_final, pattern="^del_store_final_yes$"))
    application.add_handler(CallbackQueryHandler(add_rack_ask_sheet, pattern="^add_rack_ask_sheet$"))
    
    application.add_handler(conv_handler)
    
    # Jalankan sebagai Background Worker (tanpa Flask/Gunicorn)
    logger.info("Bot sedang berjalan dengan polling...")
    application.run_polling()

if __name__ == "__main__":
    main()