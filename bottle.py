import logging
import re
import os
import json
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import gspread
from gspread_formatting import *
from oauth2client.service_account import ServiceAccountCredentials

# --- BAGIAN 1: KONFIGURASI ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

if not all([TOKEN, WEB_APP_URL, SPREADSHEET_ID, GSPREAD_CREDENTIALS]):
    raise ValueError("Salah satu environment variable krusial tidak diatur.")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAGIAN 2: STATES ---
(
    MAIN_MENU, EDITOR_MENU, PILIH_TOKO_MENU, HAPUS_TOKO_MENU,
    AWAIT_NAMA_TOKO_BARU, AWAIT_KONFIRMASI_HAPUS_TOKO,
    SHEET_MENU, AWAIT_NAMA_RAK_BARU, PILIH_RAK_TAMBAH_PLU,
    AWAIT_PLU_BARU, PILIH_RAK_HAPUS_PLU, AWAIT_PLU_HAPUS,
    AWAIT_KONFIRMASI_HAPUS_PLU, AWAIT_RAK_HAPUS, AWAIT_KONFIRMASI_HAPUS_RAK,
) = range(15)

# --- BAGIAN 3: FUNGSI HELPER ---

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

# Helper Toko
def get_all_valid_stores():
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); return [s.title for s in spreadsheet.worksheets() if len(s.title) == 4 and s.title.isalnum()]
    except Exception as e: logger.error(f"Error get_all_valid_stores: {e}"); return []

def add_new_store(store_code):
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

# Helper Rak & PLU (Lengkap dan Konsisten)
def add_new_rack(store_code, rack_name):
    safe_rack_name = _to_safe_name(rack_name)
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        if safe_rack_name in [nr['name'] for nr in sheet.list_named_ranges()]: return False
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
        sheet.add_named_range(safe_rack_name, f"'{sheet.title}'!A{data_start_row}:A"); return True
    except Exception as e: logger.error(f"Error add_new_rack for '{rack_name}': {e}"); return False

def get_racks_in_sheet(store_code):
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code); return [_to_real_name(nr['name']) for nr in sheet.list_named_ranges()]
    except Exception as e: logger.error(f"Error get_racks_in_sheet for {store_code}: {e}"); return []

def delete_racks(store_code, racks_to_delete):
    deleted, not_found = [], []
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        all_named_ranges = {nr['name'] for nr in sheet.list_named_ranges()}
        for rack in racks_to_delete:
            safe_rack_name = _to_safe_name(rack)
            if safe_rack_name in all_named_ranges:
                sheet.delete_named_range(safe_rack_name)
                # Note: Menghapus baris/tabel secara visual adalah operasi yang kompleks dan berisiko.
                # Menghapus Named Range sudah cukup untuk logika bot.
                deleted.append(rack)
            else: not_found.append(rack)
        return deleted, not_found
    except Exception as e: logger.error(f"Error delete_racks: {e}"); return [], racks_to_delete

# --- BAGIAN 4: KEYBOARDS ---

def build_keyboard(buttons, n_cols): return [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
def main_menu_keyboard(): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL)), InlineKeyboardButton("Editor", callback_data="editor")], 2))
def editor_menu_keyboard(): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Pilih Toko", callback_data="pilih_toko"), InlineKeyboardButton("Tambah Toko", callback_data="tambah_toko"), InlineKeyboardButton("Hapus Toko", callback_data="hapus_toko"), InlineKeyboardButton("Kembali", callback_data="kembali_ke_main")], 2))
def store_list_keyboard(action_prefix):
    stores = get_all_valid_stores(); buttons = [InlineKeyboardButton(store, callback_data=f"{action_prefix}_{store}") for store in stores]
    buttons.append(InlineKeyboardButton("Kembali", callback_data="back_to_editor")); return InlineKeyboardMarkup(build_keyboard(buttons, 3)) if stores else None
def sheet_menu_keyboard(store_code): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Tambah Rak", callback_data=f"tambah_rak_{store_code}"), InlineKeyboardButton("Tambah Plu", callback_data=f"tambah_plu_{store_code}"), InlineKeyboardButton("Hapus Plu", callback_data=f"hapus_plu_{store_code}"), InlineKeyboardButton("Hapus Rak", callback_data=f"hapus_rak_{store_code}"), InlineKeyboardButton("Kembali", callback_data="kembali_ke_pilih_toko")], 2))
def rack_list_keyboard(store_code, action_prefix):
    racks = get_racks_in_sheet(store_code); buttons = [InlineKeyboardButton(rack, callback_data=f"{action_prefix}_{_to_safe_name(rack)}") for rack in racks]
    buttons.append(InlineKeyboardButton("Kembali", callback_data=f"back_to_sheet_menu_{store_code}")); return InlineKeyboardMarkup(build_keyboard(buttons, 2)) if racks else None
def confirmation_keyboard(yes_callback, no_callback): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Ya", callback_data=yes_callback), InlineKeyboardButton("Tidak", callback_data=no_callback)], 2))
def cancel_keyboard(callback_data): return InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=callback_data)]])


# --- BAGIAN 5: HANDLERS ---

# Navigasi & Fallback
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear(); await update.message.reply_html(f"Selamat Datang!", reply_markup=main_menu_keyboard()); return MAIN_MENU
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text(text="Menu Utama", reply_markup=main_menu_keyboard()); return MAIN_MENU
async def editor_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text(text="Menu Editor", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
async def cancel_to_editor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text("Dibatalkan.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
async def cancel_to_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data.get('active_store')
    await query.edit_message_text("Dibatalkan.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def wrong_state_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Input Salah. Pilih menu yang tersedia.")

# Handler Toko
async def request_new_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text(text="Masukkan Kode Toko (4 digit).", reply_markup=cancel_keyboard("cancel_to_editor")); return AWAIT_NAMA_TOKO_BARU
async def add_store_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = update.message.text.upper()
    if len(store_code) != 4 or not store_code.isalnum(): await update.message.reply_text("Kode Toko harus 4 digit alfanumerik."); return AWAIT_NAMA_TOKO_BARU
    if add_new_store(store_code): await update.message.reply_text(f"Berhasil menambah toko '{store_code}'.", reply_markup=editor_menu_keyboard())
    else: await update.message.reply_text(f"Toko '{store_code}' sudah ada.", reply_markup=editor_menu_keyboard())
    return EDITOR_MENU
async def show_stores_to_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); keyboard = store_list_keyboard("pilih")
    await query.edit_message_text("Pilih toko:", reply_markup=keyboard) if keyboard else await query.edit_message_text("Tidak ada toko.", reply_markup=editor_menu_keyboard()); return PILIH_TOKO_MENU if keyboard else EDITOR_MENU
async def select_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = query.data.split("_")[-1]; context.user_data['active_store'] = store_code
    await query.edit_message_text(text=f"Masuk ke Toko '{store_code}'", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def back_to_pilih_toko(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); context.user_data.pop('active_store', None)
    return await editor_menu_handler(update, context) # Kembali ke menu editor
async def show_stores_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); keyboard = store_list_keyboard("hapus")
    await query.edit_message_text("Pilih toko untuk dihapus:", reply_markup=keyboard) if keyboard else await query.edit_message_text("Tidak ada toko.", reply_markup=editor_menu_keyboard()); return HAPUS_TOKO_MENU if keyboard else EDITOR_MENU
async def confirm_delete_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = query.data.split("_")[-1]; context.user_data["item_to_delete"] = store_code
    await query.edit_message_text(f"Yakin hapus toko '{store_code}'?", reply_markup=confirmation_keyboard("confirm_del_store_yes", "confirm_del_store_no")); return AWAIT_KONFIRMASI_HAPUS_TOKO
async def delete_store_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data.pop("item_to_delete", None)
    msg = f"Toko {store_code} dihapus." if store_code and delete_store_sheet(store_code) else f"Gagal hapus {store_code}."
    await query.edit_message_text(msg, reply_markup=editor_menu_keyboard()); return EDITOR_MENU

# Handler Rak
async def request_new_rack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; existing_racks = get_racks_in_sheet(store_code)
    message = "Masukkan nama Rak baru.\nUntuk >1, pisahkan dengan koma.\nContoh: RAK SATU, RAK DUA"
    if existing_racks: message += "\n\nRak yang sudah ada:\n- " + "\n- ".join(existing_racks)
    await query.edit_message_text(text=message, reply_markup=cancel_keyboard(f"cancel_to_sheet")); return AWAIT_NAMA_RAK_BARU
async def add_rack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = context.user_data['active_store']
    rack_names = [name.strip() for name in update.message.text.split(',') if name.strip()]
    if not rack_names: await update.message.reply_text("Input tidak valid.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
    added, existed = [], []
    for name in rack_names:
        if add_new_rack(store_code, name): added.append(name)
        else: existed.append(name)
    parts = [f"Berhasil: {', '.join(added)}." if added else "", f"Sudah ada: {', '.join(existed)}." if existed else ""]
    await update.message.reply_text("\n".join(filter(None, parts)), reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def request_racks_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; racks = get_racks_in_sheet(store_code)
    if not racks: await query.edit_message_text("Tidak ada rak.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
    msg = f"Rak di Toko {store_code}:\n- " + "\n- ".join(racks) + "\n\nMasukkan nama rak yg akan dihapus (pisahkan dengan koma):"
    await query.edit_message_text(msg, reply_markup=cancel_keyboard(f"cancel_to_sheet")); return AWAIT_RAK_HAPUS
async def confirm_delete_rack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    racks = [r.strip() for r in update.message.text.split(',') if r.strip()]; context.user_data['items_to_delete'] = racks
    await update.message.reply_text(f"Yakin hapus Rak: {', '.join(racks)}?", reply_markup=confirmation_keyboard("confirm_del_rack_yes", "confirm_del_rack_no")); return AWAIT_KONFIRMASI_HAPUS_RAK
async def delete_rack_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; racks = context.user_data.pop('items_to_delete', [])
    deleted, not_found = delete_racks(store_code, racks)
    parts = [f"Berhasil hapus: {', '.join(deleted)}." if deleted else "", f"Tidak ditemukan: {', '.join(not_found)}." if not_found else ""]
    await query.edit_message_text("\n".join(filter(None, parts)) or "Operasi selesai.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

# Handler PLU
async def show_racks_for_plu_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']
    action_prefix = "addplu" if "tambah_plu" in query.data else "delplu"
    next_state = PILIH_RAK_TAMBAH_PLU if action_prefix == "addplu" else PILIH_RAK_HAPUS_PLU
    keyboard = rack_list_keyboard(store_code, f"{action_prefix}_{store_code}")
    await query.edit_message_text("Pilih Rak:", reply_markup=keyboard) if keyboard else await query.edit_message_text("Tidak ada rak.", reply_markup=sheet_menu_keyboard(store_code))
    return next_state if keyboard else SHEET_MENU
async def back_to_sheet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = query.data.split('_')[-1]
    await query.edit_message_text(f"Menu Toko '{store_code}'", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

# --- BAGIAN 6: MAIN & CONVERSATION HANDLER ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(editor_menu_handler, pattern="^editor$")],
            EDITOR_MENU: [
                CallbackQueryHandler(main_menu_handler, pattern="^kembali_ke_main$"),
                CallbackQueryHandler(show_stores_to_select, pattern="^pilih_toko$"),
                CallbackQueryHandler(request_new_store_name, pattern="^tambah_toko$"),
                CallbackQueryHandler(show_stores_to_delete, pattern="^hapus_toko$"),
            ],
            # Alur Toko
            AWAIT_NAMA_TOKO_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_store_handler), CallbackQueryHandler(cancel_to_editor, pattern="^cancel_to_editor$")],
            PILIH_TOKO_MENU: [CallbackQueryHandler(editor_menu_handler, pattern="^back_to_editor$"), CallbackQueryHandler(select_store, pattern="^pilih_")],
            HAPUS_TOKO_MENU: [CallbackQueryHandler(editor_menu_handler, pattern="^back_to_editor$"), CallbackQueryHandler(confirm_delete_store, pattern="^hapus_")],
            AWAIT_KONFIRMASI_HAPUS_TOKO: [CallbackQueryHandler(delete_store_confirmed, pattern="^confirm_del_store_yes$"), CallbackQueryHandler(cancel_to_editor, pattern="^confirm_del_store_no$")],
            # Alur di dalam Sheet
            SHEET_MENU: [
                CallbackQueryHandler(back_to_pilih_toko, pattern="^kembali_ke_pilih_toko$"),
                CallbackQueryHandler(request_new_rack_name, pattern="^tambah_rak_"),
                CallbackQueryHandler(request_racks_to_delete, pattern="^hapus_rak_"),
                CallbackQueryHandler(show_racks_for_plu_menu, pattern=r"^(tambah|hapus)_plu_"),
            ],
            # Alur Rak
            AWAIT_NAMA_RAK_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rack_handler), CallbackQueryHandler(cancel_to_sheet, pattern="^cancel_to_sheet$")],
            AWAIT_RAK_HAPUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_rack), CallbackQueryHandler(cancel_to_sheet, pattern="^cancel_to_sheet$")],
            AWAIT_KONFIRMASI_HAPUS_RAK: [CallbackQueryHandler(delete_rack_confirmed, pattern="^confirm_del_rack_yes$"), CallbackQueryHandler(cancel_to_sheet, pattern="^confirm_del_rack_no$")],
            # Alur PLU (bisa dikembangkan dari sini)
            PILIH_RAK_TAMBAH_PLU: [CallbackQueryHandler(back_to_sheet_menu, pattern=r"^back_to_sheet_menu_")], # Tambahkan handler input PLU di sini
            PILIH_RAK_HAPUS_PLU: [CallbackQueryHandler(back_to_sheet_menu, pattern=r"^back_to_sheet_menu_")], # Tambahkan handler hapus PLU di sini
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, wrong_state_handler)],
        per_message=False, allow_reentry=True
    )
    application.add_handler(conv_handler)
    logger.info("Bot sedang berjalan...")
    application.run_polling()

if __name__ == "__main__":
    main()