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

# --- BAGIAN 3: KEYBOARDS (DENGAN EMOJI) ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("➕ Tambah Toko", callback_data="add_store_start"), InlineKeyboardButton("❌ Hapus Toko", callback_data="del_store_ask_sheet")],
        [InlineKeyboardButton("➕ Tambah Rak", callback_data="add_rack_ask_sheet"), InlineKeyboardButton("❌ Hapus Rak", callback_data="del_rack_ask_sheet")],
        [InlineKeyboardButton("➕ Tambah Plu", callback_data="plu_not_implemented"), InlineKeyboardButton("❌ Hapus Plu", callback_data="plu_not_implemented")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_dynamic_keyboard(prefix, items, include_back_button=True):
    keyboard = [InlineKeyboardButton(item, callback_data=f"{prefix}_{_to_safe_name(item)}") for item in items]
    if include_back_button:
        return InlineKeyboardMarkup.from_row(keyboard + [InlineKeyboardButton("« Kembali", callback_data="start_over")], width=2)
    return InlineKeyboardMarkup.from_row(keyboard, width=2)

def confirmation_keyboard(yes_callback, no_callback="start_over"):
    return InlineKeyboardMarkup.from_row([
        InlineKeyboardButton("✔️ YA", callback_data=yes_callback),
        InlineKeyboardButton("✖️ TIDAK", callback_data=no_callback)
    ])

# --- BAGIAN 4: HANDLERS (STRUKTUR PALING STABIL) ---
# States untuk ConversationHandler
ACTION, AWAIT_STORE, AWAIT_RACK, AWAIT_STORE_FOR_RACK, AWAIT_RACK_FOR_DEL = range(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Mengirim menu utama dan membersihkan state."""
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
    else:
        message = update.message
    
    context.user_data.clear()
    await message.reply_text("Selamat Datang! Silakan pilih opsi:", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- Handler untuk Aksi yang Memerlukan Input Lanjutan ---

async def ask_for_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Meminta pengguna memilih toko untuk aksi selanjutnya."""
    query = update.callback_query
    await query.answer()
    action = query.data # e.g., "del_store_ask_sheet"
    
    stores = get_all_valid_stores()
    if not stores:
        await query.edit_message_text("Tidak ada toko yang tersedia. Silakan buat toko terlebih dahulu.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    
    if action == "del_store_ask_sheet":
        context.user_data['action'] = 'delete_store'
        keyboard = build_dynamic_keyboard("select_store", stores)
        await query.edit_message_text("Pilih toko yang akan dihapus:", reply_markup=keyboard)
    elif action == "add_rack_ask_sheet":
        context.user_data['action'] = 'add_rack'
        keyboard = build_dynamic_keyboard("select_store", stores)
        await query.edit_message_text("Pilih toko untuk menambahkan rak:", reply_markup=keyboard)
    elif action == "del_rack_ask_sheet":
        context.user_data['action'] = 'delete_rack'
        keyboard = build_dynamic_keyboard("select_store", stores)
        await query.edit_message_text("Pilih toko untuk menghapus rak:", reply_markup=keyboard)
        
    return AWAIT_STORE

async def ask_for_rack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Meminta pengguna memilih rak setelah toko dipilih."""
    query = update.callback_query
    await query.answer()
    
    store_name = _to_real_name(query.data.split('_')[-1])
    context.user_data['store'] = store_name
    action = context.user_data.get('action')
    
    if action == 'delete_rack':
        racks = get_racks_in_sheet(store_name)
        if not racks:
            await query.edit_message_text(f"Tidak ada rak di toko '{store_name}'.", reply_markup=main_menu_keyboard())
            return ConversationHandler.END
        
        keyboard = build_dynamic_keyboard("select_rack", racks)
        await query.edit_message_text(f"Pilih rak yang akan dihapus dari toko '{store_name}':", reply_markup=keyboard)
        return AWAIT_RACK
    
    return ConversationHandler.END # Fallback

async def ask_for_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Meminta input teks setelah semua pilihan dibuat."""
    query = update.callback_query
    await query.answer()
    
    action = context.user_data.get('action')
    
    if action == 'add_store':
        await query.edit_message_text("Masukkan Kode Toko baru (4 digit alfanumerik):")
        return AWAIT_INPUT
    
    elif action == 'add_rack':
        context.user_data['store'] = _to_real_name(query.data.split('_')[-1])
        await query.edit_message_text(f"Di toko '{context.user_data['store']}':\nMasukkan nama Rak baru (untuk >1, pisahkan dengan koma).")
        return AWAIT_INPUT
        
    elif action == 'delete_store':
        store_name = _to_real_name(query.data.split('_')[-1])
        context.user_data['store'] = store_name
        await query.edit_message_text(f"Yakin ingin menghapus toko '{store_name}'?", reply_markup=confirmation_keyboard("confirm_delete"))
        return ACTION

    elif action == 'delete_rack':
        rack_name = _to_real_name(query.data.split('_')[-1])
        context.user_data['rack'] = rack_name
        store_name = context.user_data.get('store')
        await query.edit_message_text(f"Yakin ingin menghapus rak '{rack_name}' dari toko '{store_name}'?", reply_markup=confirmation_keyboard("confirm_delete"))
        return ACTION

    return ConversationHandler.END

# --- Handler untuk Memproses Input & Konfirmasi ---
AWAIT_INPUT = 0 # State tunggal untuk semua input teks

async def process_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memproses jawaban YA dari tombol konfirmasi."""
    query = update.callback_query
    await query.answer()
    
    action = context.user_data.get('action')
    store = context.user_data.get('store')
    rack = context.user_data.get('rack')
    
    if action == 'delete_store' and store:
        if delete_store_sheet(store):
            await query.edit_message_text(f"Toko '{store}' berhasil dihapus.", reply_markup=main_menu_keyboard())
        else:
            await query.edit_message_text(f"Gagal menghapus toko '{store}'.", reply_markup=main_menu_keyboard())
            
    elif action == 'delete_rack' and store and rack:
        if delete_racks(store, [rack]):
            await query.edit_message_text(f"Rak '{rack}' dari toko '{store}' berhasil dihapus.", reply_markup=main_menu_keyboard())
        else:
            await query.edit_message_text(f"Gagal menghapus rak '{rack}'.", reply_markup=main_menu_keyboard())
            
    context.user_data.clear()
    return ConversationHandler.END

async def process_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memproses semua input teks berdasarkan 'action'."""
    action = context.user_data.get('action')
    text = update.message.text
    
    if action == 'add_store':
        store_code = text.upper()
        if len(store_code) != 4 or not store_code.isalnum():
            await update.message.reply_text("Input salah. Kode Toko harus 4 digit alfanumerik. Coba lagi:")
            return AWAIT_INPUT
        if add_new_store_and_produk_sheet(store_code):
            await update.message.reply_text(f"Berhasil menambah toko '{store_code}'.", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"Toko '{store_code}' sudah ada.", reply_markup=main_menu_keyboard())
            
    elif action == 'add_rack':
        store = context.user_data.get('store')
        rack_names = [name.strip() for name in text.split(',') if name.strip()]
        added, existed = [], []
        for name in rack_names:
            if add_new_rack(store, name): added.append(name)
            else: existed.append(name)
        parts = [f"Berhasil: {', '.join(added)}." if added else "", f"Sudah ada: {', '.join(existed)}." if existed else ""]
        await update.message.reply_text(f"Di toko {store}:\n" + ("\n".join(filter(None, parts)) or "Tidak ada rak ditambahkan."), reply_markup=main_menu_keyboard())
        
    context.user_data.clear()
    return ConversationHandler.END

async def plu_not_implemented(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pesan placeholder untuk fitur PLU."""
    query = update.callback_query
    await query.answer("Fitur ini sedang dalam pengembangan.", show_alert=True)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani semua error dan mencetaknya ke log."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Maaf, terjadi kesalahan internal. Coba lagi nanti.")

# --- BAGIAN 5: MAIN ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handler untuk alur multi-langkah
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_for_input, pattern="^add_store_start$"),
            CallbackQueryHandler(ask_for_store, pattern=r"^(del_store_ask_sheet|add_rack_ask_sheet|del_rack_ask_sheet)$"),
            CallbackQueryHandler(ask_for_rack, pattern="^select_store_"),
            CallbackQueryHandler(ask_for_input, pattern="^select_rack_")
        ],
        states={
            AWAIT_STORE: [CallbackQueryHandler(ask_for_rack, pattern="^select_store_")],
            AWAIT_RACK: [CallbackQueryHandler(ask_for_input, pattern="^select_rack_")],
            AWAIT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_text_input)],
            ACTION: [CallbackQueryHandler(process_confirmation, pattern="^confirm_delete$")],
        },
        fallbacks=[CallbackQueryHandler(start, pattern="^start_over$")],
        conversation_timeout=300 # 5 menit
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(plu_not_implemented, pattern="^plu_not_implemented$"))
    application.add_handler(conv_handler)
    
    # Tambahkan error handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot sedang berjalan dengan polling...")
    application.run_polling()

if __name__ == "__main__":
    main()