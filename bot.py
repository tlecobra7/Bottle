import logging
import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# --- BAGIAN 1: KONFIGURASI DAN SETUP DASAR ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://telegram.org")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

if not all([TOKEN, SPREADSHEET_ID, GSPREAD_CREDENTIALS]):
    raise ValueError("TOKEN, SPREADSHEET_ID, dan GSPREAD_CREDENTIALS wajib diatur.")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAGIAN 2: FUNGSI HELPER (TIDAK ADA PERUBAHAN, SUDAH BENAR) ---
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

# --- BAGIAN 3: KEYBOARDS ---
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("➕ Tambah Toko", callback_data="add_store_start"), InlineKeyboardButton("❌ Hapus Toko", callback_data="del_store_ask_sheet")],
        [InlineKeyboardButton("➕ Tambah Rak", callback_data="add_rack_ask_sheet"), InlineKeyboardButton("❌ Hapus Rak", callback_data="del_rack_ask_sheet")],
    ]
    return InlineKeyboardMarkup(keyboard)
def build_dynamic_keyboard(prefix, items, width=2):
    keyboard = [InlineKeyboardButton(item, callback_data=f"{prefix}_{_to_safe_name(item)}") for item in items]
    keyboard.append(InlineKeyboardButton("« Kembali", callback_data="start"))
    return InlineKeyboardMarkup.from_column(keyboard, width=width)
def confirmation_keyboard(yes_callback, no_callback="start"):
    return InlineKeyboardMarkup.from_row([
        InlineKeyboardButton("✔️ YA", callback_data=yes_callback),
        InlineKeyboardButton("✖️ TIDAK", callback_data=no_callback)
    ])

# --- BAGIAN 4: HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.callback_query.message
    if update.callback_query: await update.callback_query.answer()
    context.user_data.clear()
    await message.reply_text("Selamat Datang!", reply_markup=main_menu_keyboard())

# --- Alur Manual ---
async def text_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Satu handler untuk semua input teks."""
    action_data = context.user_data.get('action_data')
    if not action_data:
        await update.message.reply_text("Data Salah, Harap Pilih Menu Terlebih Dahulu.", reply_markup=main_menu_keyboard())
        return

    action = action_data.get('action')
    text = update.message.text
    context.user_data.clear() # Hapus state setelah digunakan

    if action == 'add_store':
        store_code = text.upper()
        if len(store_code) != 4 or not store_code.isalnum():
            await update.message.reply_text("Input salah. Kode Toko harus 4 digit. Silakan tekan tombol lagi.", reply_markup=main_menu_keyboard())
            return
        if add_new_store_and_produk_sheet(store_code):
            await update.message.reply_text(f"Berhasil menambah toko '{store_code}'.", reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(f"Toko '{store_code}' sudah ada.", reply_markup=main_menu_keyboard())

    elif action == 'add_rack':
        store_name = action_data.get('store')
        rack_names = [name.strip() for name in text.split(',') if name.strip()]
        added, existed = [], []
        for name in rack_names:
            if add_new_rack(store_name, name): added.append(name)
            else: existed.append(name)
        parts = [f"Berhasil: {', '.join(added)}." if added else "", f"Sudah ada: {', '.join(existed)}." if existed else ""]
        await update.message.reply_text(f"Di toko {store_name}:\n" + ("\n".join(filter(None, parts)) or "Tidak ada rak ditambahkan."), reply_markup=main_menu_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Satu handler untuk semua callback query."""
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')
    command = data[0]

    if command == "start":
        await start(update, context)
        return

    # --- Aksi yang meminta input teks ---
    if command == "add" and data[1] == "store" and data[2] == "start":
        context.user_data['action_data'] = {'action': 'add_store'}
        await query.edit_message_text("Masukkan Kode Toko baru (4 digit alfanumerik):")
    
    elif command == "add" and data[1] == "rack" and data[2] == "ask" and data[3] == "name":
        store_name = _to_real_name(data[4])
        context.user_data['action_data'] = {'action': 'add_rack', 'store': store_name}
        await query.edit_message_text(f"Di toko '{store_name}':\nMasukkan nama Rak baru (untuk >1, pisahkan dengan koma).")

    # --- Aksi yang menampilkan daftar ---
    elif command == "del" and data[1] == "store" and data[2] == "ask":
        stores = get_all_valid_stores()
        if not stores: await query.edit_message_text("Tidak ada toko.", reply_markup=main_menu_keyboard()); return
        keyboard = build_dynamic_keyboard("del-store-confirm", stores)
        await query.edit_message_text("Pilih toko yang akan dihapus:", reply_markup=keyboard)

    elif command == "add" and data[1] == "rack" and data[2] == "ask":
        stores = get_all_valid_stores()
        if not stores: await query.edit_message_text("Tidak ada toko.", reply_markup=main_menu_keyboard()); return
        keyboard = build_dynamic_keyboard("add-rack-ask-name", stores)
        await query.edit_message_text("Pilih toko untuk menambahkan rak:", reply_markup=keyboard)

    elif command == "del" and data[1] == "rack" and data[2] == "ask":
        stores = get_all_valid_stores()
        if not stores: await query.edit_message_text("Tidak ada toko.", reply_markup=main_menu_keyboard()); return
        keyboard = build_dynamic_keyboard("del-rack-ask-rack", stores)
        await query.edit_message_text("Pilih toko untuk menghapus rak:", reply_markup=keyboard)

    elif command == "del-rack-ask-rack":
        store_name = _to_real_name(data[1])
        racks = get_racks_in_sheet(store_name)
        if not racks: await query.edit_message_text(f"Tidak ada rak di toko '{store_name}'.", reply_markup=main_menu_keyboard()); return
        keyboard = build_dynamic_keyboard(f"del-rack-confirm-{_to_safe_name(store_name)}", racks)
        await query.edit_message_text(f"Pilih rak yang akan dihapus dari '{store_name}':", reply_markup=keyboard)
        
    # --- Aksi konfirmasi ---
    elif command == "del-store-confirm":
        store_name = _to_real_name(data[1])
        context.user_data['item_to_delete'] = {'type': 'store', 'name': store_name}
        keyboard = confirmation_keyboard("confirm-delete-yes")
        await query.edit_message_text(f"Yakin ingin menghapus toko '{store_name}'?", reply_markup=keyboard)

    elif command == "del-rack-confirm":
        store_name = _to_real_name(data[1])
        rack_name = _to_real_name(data[2])
        context.user_data['item_to_delete'] = {'type': 'rack', 'store': store_name, 'name': rack_name}
        keyboard = confirmation_keyboard("confirm-delete-yes")
        await query.edit_message_text(f"Yakin ingin menghapus rak '{rack_name}' dari toko '{store_name}'?", reply_markup=keyboard)

    # --- Aksi final (setelah konfirmasi YA) ---
    elif command == "confirm-delete-yes":
        item = context.user_data.pop('item_to_delete', None)
        if not item: await query.edit_message_text("Sesi berakhir.", reply_markup=main_menu_keyboard()); return
        
        if item['type'] == 'store':
            if delete_store_sheet(item['name']):
                await query.edit_message_text(f"Toko '{item['name']}' berhasil dihapus.", reply_markup=main_menu_keyboard())
            else:
                await query.edit_message_text(f"Gagal menghapus toko '{item['name']}'.", reply_markup=main_menu_keyboard())
        
        elif item['type'] == 'rack':
            if delete_racks(item['store'], [item['name']]):
                await query.edit_message_text(f"Rak '{item['name']}' berhasil dihapus.", reply_markup=main_menu_keyboard())
            else:
                await query.edit_message_text(f"Gagal menghapus rak '{item['name']}'.", reply_markup=main_menu_keyboard())
                
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Maaf, terjadi kesalahan internal. Coba lagi nanti.")

# --- BAGIAN 5: MAIN ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    
    application.add_error_handler(error_handler)
    
    logger.info("Bot sedang berjalan dengan polling...")
    application.run_polling()

if __name__ == "__main__":
    main()