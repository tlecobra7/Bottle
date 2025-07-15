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

# --- BAGIAN 1: KONFIGURASI DARI ENVIRONMENT VARIABLES ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

if not all([TOKEN, WEB_APP_URL, SPREADSHEET_ID, GSPREAD_CREDENTIALS]):
    raise ValueError("Kesalahan: Salah satu environment variable tidak diatur.")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- BAGIAN 2: STATE UNTUK CONVERSATION HANDLER ---
(
    MAIN_MENU, EDITOR_MENU, PILIH_TOKO_MENU, HAPUS_TOKO_MENU, AWAIT_NAMA_TOKO_BARU,
    AWAIT_KONFIRMASI_HAPUS_TOKO, SHEET_MENU, AWAIT_NAMA_RAK_BARU, PILIH_RAK_TAMBAH_PLU,
    AWAIT_PLU_BARU, PILIH_RAK_HAPUS_PLU, AWAIT_PLU_HAPUS, AWAIT_KONFIRMASI_HAPUS_PLU,
    AWAIT_RAK_HAPUS, AWAIT_KONFIRMASI_HAPUS_RAK,
) = range(15)

# --- BAGIAN 3: FUNGSI HELPER GOOGLE SHEETS (DENGAN PERBAIKAN TOTAL) ---

def get_gspread_client():
    try:
        creds_dict = json.loads(GSPREAD_CREDENTIALS)
    except json.JSONDecodeError:
        raise ValueError("GSPREAD_CREDENTIALS tidak berisi JSON yang valid.")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# --- FUNGSI HELPER YANG TIDAK BERUBAH ---
def get_all_valid_stores():
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); return [s.title for s in spreadsheet.worksheets() if len(s.title) == 4 and s.title.isalnum()]
    except Exception as e: logger.error(f"Error getting stores: {e}"); return []
def add_new_store(store_code):
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); spreadsheet.add_worksheet(title=store_code, rows="100", cols="50");
    except Exception: pass; return True
def delete_store_sheet(store_code):
    try: client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); spreadsheet.del_worksheet(spreadsheet.worksheet(store_code)); return True
    except Exception as e: logger.error(f"Error deleting store {store_code}: {e}"); return False
def find_next_available_row(worksheet):
    all_values = worksheet.get_all_values(); return 1 if not all_values else len(all_values) + 4

# --- FUNGSI HELPER UNTUK RAK (SEMUA DIPERBAIKI) ---

def add_new_rack(store_code, rack_name):
    """PERBAIKAN: Membuat Named Range yang aman (mengganti spasi dengan '_')."""
    safe_rack_name = rack_name.replace(" ", "_")
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        if safe_rack_name in [nr['name'] for nr in sheet.list_named_ranges()]: return False
        start_row = find_next_available_row(sheet); sheet.update(f"A{start_row}:C{start_row}", [["Plu", "Nama Barang", "Barcode"]])
        header_format = CellFormat(backgroundColor=Color(0.75, 0.92, 0.61), textFormat=TextFormat(bold=True, fontSize=15), horizontalAlignment='CENTER')
        format_cell_range(sheet, f"A{start_row}:C{start_row}", header_format)
        sheet.add_named_range(safe_rack_name, f"'{sheet.title}'!A{start_row+1}:A")
        return True
    except Exception as e: logger.error(f"Error adding rack {rack_name}: {e}"); return False

def get_racks_in_sheet(store_code):
    """PERBAIKAN: Mengambil nama aman dan mengubahnya kembali menjadi nama asli."""
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        return [nr['name'].replace("_", " ") for nr in sheet.list_named_ranges()]
    except Exception as e: logger.error(f"Error getting racks for {store_code}: {e}"); return []

def delete_racks(store_code, racks_to_delete):
    """PERBAIKAN: Menggunakan nama aman untuk menghapus."""
    deleted, not_found = [], []
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        all_named_ranges = {nr['name'] for nr in sheet.list_named_ranges()}
        for rack in racks_to_delete:
            safe_rack_name = rack.replace(" ", "_")
            if safe_rack_name in all_named_ranges: sheet.delete_named_range(safe_rack_name); deleted.append(rack)
            else: not_found.append(rack)
        return deleted, not_found
    except Exception as e: logger.error(f"Error deleting racks: {e}"); return [], racks_to_delete

def add_plus_to_rack(store_code, rack_name, plus_to_add):
    """PERBAIKAN: Menggunakan nama aman untuk menambah PLU."""
    safe_rack_name = rack_name.replace(" ", "_"); added, duplicates = [], []
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        named_range = sheet.get_named_range(safe_rack_name); range_values = sheet.get(named_range['range'])
        existing_plus = [item for sublist in range_values for item in sublist] if range_values else []
        for plu in plus_to_add:
            if plu in existing_plus: duplicates.append(plu)
            else: sheet.append_row([plu], table_range=named_range['range']); added.append(plu)
        return added, duplicates
    except Exception as e: logger.error(f"Error adding PLUs to {rack_name}: {e}"); return [], plus_to_add

def get_plus_in_rack(store_code, rack_name):
    """PERBAIKAN: Menggunakan nama aman untuk mengambil data PLU."""
    safe_rack_name = rack_name.replace(" ", "_")
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        named_range_info = sheet.get_named_range(safe_rack_name); range_a1 = named_range_info['range']
        start_cell_a1 = range_a1.split('!')[1]; start_cell = start_cell_a1.split(':')[0]
        start_col_char = re.match(r"[A-Z]+", start_cell).group(); end_col_char = chr(ord(start_col_char) + 2); start_row = re.search(r"\d+", start_cell).group()
        table_range = f"{start_col_char}{start_row}:{end_col_char}{int(start_row)+50}"
        formatted_data = sheet.get(table_range, value_render_option='FORMATTED_VALUE')
        return [[row[0], row[1] if len(row) > 1 else ""] for row in formatted_data if row and row[0]]
    except Exception as e: logger.error(f"Error getting PLUs from {rack_name}: {e}"); return []

def delete_plus_from_rack(store_code, rack_name, plus_to_delete):
    """PERBAIKAN: Menggunakan nama aman untuk menghapus PLU."""
    safe_rack_name = rack_name.replace(" ", "_"); deleted, not_found = [], []
    try:
        client = get_gspread_client(); spreadsheet = client.open_by_key(SPREADSHEET_ID); sheet = spreadsheet.worksheet(store_code)
        named_range = sheet.get_named_range(safe_rack_name); range_a1 = named_range['range']
        cells_to_find = [sheet.find(plu, in_range=range_a1) for plu in plus_to_delete]
        rows_to_delete = sorted(list(set([cell.row for cell in cells_to_find if cell])), reverse=True)
        found_plus = [cell.value for cell in cells_to_find if cell]; not_found = list(set(plus_to_delete) - set(found_plus))
        for row in rows_to_delete: sheet.delete_rows(row)
        deleted = list(set(plus_to_delete) - set(not_found)); return deleted, not_found
    except Exception as e: logger.error(f"Error deleting PLUs from {rack_name}: {e}"); return [], plus_to_delete

# --- BAGIAN 4: FUNGSI KEYBOARD (DENGAN PERBAIKAN) ---

def build_keyboard(buttons, n_cols): return [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
def main_menu_keyboard(): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL)), InlineKeyboardButton("Editor", callback_data="editor")], 2))
def editor_menu_keyboard(): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Pilih Toko", callback_data="pilih_toko"), InlineKeyboardButton("Tambah Toko", callback_data="tambah_toko"), InlineKeyboardButton("Hapus Toko", callback_data="hapus_toko"), InlineKeyboardButton("Kembali", callback_data="kembali_ke_main")], 2))
def store_list_keyboard(action_prefix):
    stores = get_all_valid_stores(); buttons = [InlineKeyboardButton(store, callback_data=f"{action_prefix}_{store}") for store in stores]
    buttons.append(InlineKeyboardButton("Kembali", callback_data="kembali_ke_editor")); return InlineKeyboardMarkup(build_keyboard(buttons, 3)) if buttons else None
def confirmation_keyboard(yes_callback, no_callback): return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Ya", callback_data=yes_callback), InlineKeyboardButton("Tidak", callback_data=no_callback)], 2))
def cancel_keyboard(callback_data): return InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=callback_data)]])
def sheet_menu_keyboard(store_code):
    buttons = [InlineKeyboardButton("Tambah Rak", callback_data=f"tambah_rak_{store_code}"), InlineKeyboardButton("Tambah Plu", callback_data=f"tambah_plu_{store_code}"), InlineKeyboardButton("Hapus Plu", callback_data=f"hapus_plu_{store_code}"), InlineKeyboardButton("Hapus Rak", callback_data=f"hapus_rak_{store_code}"), InlineKeyboardButton("Kembali", callback_data="kembali_ke_pilih_toko")]
    return InlineKeyboardMarkup(build_keyboard(buttons, 2))

def rack_list_keyboard(store_code, action_prefix):
    """PERBAIKAN: Menampilkan nama asli, mengirim nama aman di callback."""
    racks = get_racks_in_sheet(store_code); buttons = []
    for rack in racks: buttons.append(InlineKeyboardButton(rack, callback_data=f"{action_prefix}_{rack.replace(' ', '_')}"))
    buttons.append(InlineKeyboardButton("Kembali", callback_data=f"back_to_sheet_menu_{store_code}"))
    return InlineKeyboardMarkup(build_keyboard(buttons, 2)) if racks else None

# --- BAGIAN 5: HANDLER BOT (DENGAN PERBAIKAN) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear(); await update.message.reply_html(f"Selamat Datang!", reply_markup=main_menu_keyboard()); return MAIN_MENU
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text(text="Menu Utama", reply_markup=main_menu_keyboard()); return MAIN_MENU
async def editor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); await query.edit_message_text(text="Menu Editor", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
async def show_stores_to_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    keyboard = store_list_keyboard("pilih")
    if keyboard: await query.edit_message_text(text="Pilih toko:", reply_markup=keyboard); return PILIH_TOKO_MENU
    else: await query.edit_message_text(text="Tidak ada toko.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
async def select_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = query.data.split("_")[-1]; context.user_data['active_store'] = store_code
    await query.edit_message_text(text=f"Masuk ke Toko '{store_code}'", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def back_to_pilih_toko(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); context.user_data.pop('active_store', None)
    await query.edit_message_text("Keluar dari Toko."); return await show_stores_to_select(update, context)

# --- Handler Tambah Rak (DIPERBAIKI) ---
async def request_new_rack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; existing_racks = get_racks_in_sheet(store_code)
    message = "Masukkan nama Rak baru.\nUntuk >1, pisahkan dengan koma atau titik.\nContoh: RAK SATU, RAK DUA"
    if existing_racks: message += "\n\nRak yang sudah ada:\n- " + "\n- ".join(existing_racks)
    await query.edit_message_text(text=message, reply_markup=cancel_keyboard(f"cancel_op_{store_code}")); return AWAIT_NAMA_RAK_BARU

async def add_rack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler yang sudah diperbaiki untuk menambahkan rak."""
    store_code = context.user_data['active_store']
    rack_names_raw = re.split(r'[,\.]', update.message.text.strip())
    rack_names = [name.strip() for name in rack_names_raw if name.strip()]
    if not rack_names: await update.message.reply_text("Input tidak valid.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
    added, existed = [], []
    for name in rack_names:
        if add_new_rack(store_code, name): added.append(name)
        else: existed.append(name)
    response_parts = []
    if added: response_parts.append(f"Berhasil menambah rak: {', '.join(added)}.")
    if existed: response_parts.append(f"Rak berikut sudah ada: {', '.join(existed)}.")
    await update.message.reply_text("\n".join(response_parts) if response_parts else "Tidak ada rak ditambahkan.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

# --- Handler Lainnya yang Terkait Rak (DIPERBAIKI) ---
async def back_to_sheet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = query.data.split('_')[-1]
    await query.edit_message_text(f"Menu Toko '{store_code}'", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']
    await query.edit_message_text("Operasi dibatalkan.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

async def show_racks_for_plu_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']
    keyboard = rack_list_keyboard(store_code, f"addplu_{store_code}")
    if keyboard: await query.edit_message_text("Pilih Rak untuk tambah PLU:", reply_markup=keyboard); return PILIH_RAK_TAMBAH_PLU
    else: await query.edit_message_text("Tidak ada rak.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

async def request_plu_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """PERBAIKAN: Mengambil nama aman dari callback dan mengubahnya jadi nama asli."""
    query = update.callback_query; await query.answer(); parts = query.data.split('_')
    store_code, safe_rack_name = parts[1], parts[2]; rack_name = safe_rack_name.replace("_", " ")
    context.user_data['rack_to_modify'] = rack_name
    await query.edit_message_text(f"Rak dipilih: {rack_name}.\nSilahkan input PLU.", reply_markup=cancel_keyboard(f"cancel_op_{store_code}")); return AWAIT_PLU_BARU

async def add_plu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = context.user_data['active_store']; rack_name = context.user_data['rack_to_modify']
    plus = list(filter(None, re.split(r'[\s,.\n]+', update.message.text.strip())))
    added, duplicates = add_plus_to_rack(store_code, rack_name, plus); msg = ""
    if added:
        new_data = [row for row in get_plus_in_rack(store_code, rack_name) if row and row[0] in added]
        summary = "\n".join([f"{row[0]:<10}{row[1]}" for row in new_data])
        msg += f"Berhasil menambah PLU ke {rack_name}:\n`{summary}`\n"
    if duplicates: msg += f"PLU sudah ada: {', '.join(duplicates)}"
    await update.message.reply_text(msg or "Tidak ada PLU ditambahkan.", reply_markup=sheet_menu_keyboard(store_code), parse_mode='Markdown')
    return SHEET_MENU

# --- Handler Hapus Rak & PLU ---
# (Struktur handler hapus toko, plu, dan rak tetap sama, tidak perlu diubah karena logikanya sudah diperbaiki di dalam fungsi helper)
# ... Salin semua handler yang tersisa dari skrip lama Anda ...
# Saya sertakan di bawah ini untuk kelengkapan
async def show_stores_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); keyboard = store_list_keyboard("hapus")
    if keyboard: await query.edit_message_text(text="Pilih toko untuk dihapus:", reply_markup=keyboard); return HAPUS_TOKO_MENU
    else: await query.edit_message_text(text="Tidak ada toko.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
async def confirm_delete_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = query.data.split("_")[-1]; context.user_data["store_to_delete"] = store_code
    await query.edit_message_text(text=f"Yakin hapus toko '{store_code}'?", reply_markup=confirmation_keyboard("confirm_delete_yes", "confirm_delete_no")); return AWAIT_KONFIRMASI_HAPUS_TOKO
async def delete_store_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data.get("store_to_delete")
    if store_code and delete_store_sheet(store_code): await query.edit_message_text(text=f"Toko {store_code} dihapus.", reply_markup=editor_menu_keyboard())
    else: await query.edit_message_text(text=f"Gagal hapus toko {store_code}.", reply_markup=editor_menu_keyboard())
    context.user_data.pop("store_to_delete", None); return EDITOR_MENU
async def show_racks_for_plu_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; keyboard = rack_list_keyboard(store_code, f"delplu_{store_code}")
    if keyboard: await query.edit_message_text("Pilih Rak untuk hapus PLU:", reply_markup=keyboard); return PILIH_RAK_HAPUS_PLU
    else: await query.edit_message_text("Tidak ada rak.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def request_plu_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); parts = query.data.split('_'); store_code, safe_rack_name = parts[1], parts[2]; rack_name = safe_rack_name.replace("_", " ")
    context.user_data['rack_to_modify'] = rack_name; plu_data = get_plus_in_rack(store_code, rack_name)
    if not plu_data: await query.edit_message_text(f"Tidak ada PLU di {rack_name}.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
    summary = "\n".join([f"{row[0]:<10}{row[1]}" for row in plu_data]); msg = f"PLU di {rack_name}:\n`{summary}`\n\nMasukkan PLU yg akan dihapus:"
    await query.edit_message_text(msg, reply_markup=cancel_keyboard(f"cancel_op_{store_code}"), parse_mode='Markdown'); return AWAIT_PLU_HAPUS
async def confirm_delete_plu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plus = list(filter(None, re.split(r'[\s,.\n]+', update.message.text.strip()))); context.user_data['items_to_delete'] = plus
    await update.message.reply_text(f"Yakin hapus PLU: {', '.join(plus)}?", reply_markup=confirmation_keyboard("confirm_del_plu_yes", "confirm_del_plu_no")); return AWAIT_KONFIRMASI_HAPUS_PLU
async def delete_plu_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; rack_name = context.user_data['rack_to_modify']; plus_to_delete = context.user_data['items_to_delete']
    deleted, not_found = delete_plus_from_rack(store_code, rack_name, plus_to_delete); msg = ""
    if deleted: msg += f"Berhasil hapus PLU: {', '.join(deleted)}.\n"
    if not_found: msg += f"PLU tidak ditemukan: {', '.join(not_found)}."
    await query.edit_message_text(msg or "Tidak ada PLU dihapus.", reply_markup=sheet_menu_keyboard(store_code)); context.user_data.pop('rack_to_modify', None); context.user_data.pop('items_to_delete', None); return SHEET_MENU
async def request_racks_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; racks = get_racks_in_sheet(store_code)
    if not racks: await query.edit_message_text("Tidak ada rak.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
    msg = f"Rak di Toko {store_code}:\n- " + "\n- ".join(racks) + "\n\nMasukkan nama rak yg akan dihapus:"
    await query.edit_message_text(msg, reply_markup=cancel_keyboard(f"cancel_op_{store_code}")); return AWAIT_RAK_HAPUS
async def confirm_delete_rack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    racks = list(filter(None, re.split(r'[,\.]', update.message.text.strip()))); context.user_data['items_to_delete'] = [r.strip() for r in racks]
    await update.message.reply_text(f"Yakin hapus Rak: {', '.join(context.user_data['items_to_delete'])}?", reply_markup=confirmation_keyboard("confirm_del_rack_yes", "confirm_del_rack_no")); return AWAIT_KONFIRMASI_HAPUS_RAK
async def delete_rack_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data['active_store']; racks_to_delete = context.user_data['items_to_delete']
    deleted, not_found = delete_racks(store_code, racks_to_delete); msg = ""
    if deleted: msg += f"Berhasil hapus rak: {', '.join(deleted)}.\n"
    if not_found: msg += f"Rak tidak ditemukan: {', '.join(not_found)}."
    await query.edit_message_text(msg or "Tidak ada rak dihapus.", reply_markup=sheet_menu_keyboard(store_code)); context.user_data.pop('items_to_delete', None); return SHEET_MENU
async def no_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); store_code = context.user_data.get('active_store')
    if 'store_to_delete' in context.user_data: context.user_data.pop('store_to_delete', None); await query.edit_message_text("Batal hapus toko.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
    else: await query.edit_message_text("Operasi dibatalkan.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
async def wrong_state_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text("Input Salah.")


# --- BAGIAN 6: FUNGSI UTAMA (Tidak ada perubahan) ---
def main() -> None:
    application = Application.builder().token(TOKEN).build()
    # ConversationHandler tetap sama, tidak perlu diubah
    conv_handler = ConversationHandler(entry_points=[CommandHandler("start", start)], states={
            MAIN_MENU: [CallbackQueryHandler(editor_menu, pattern="^editor$")],
            EDITOR_MENU: [CallbackQueryHandler(main_menu, pattern="^kembali_ke_main$"), CallbackQueryHandler(show_stores_to_select, pattern="^pilih_toko$"), CallbackQueryHandler(request_new_rack_name, pattern="^tambah_toko$"), CallbackQueryHandler(show_stores_to_delete, pattern="^hapus_toko$")],
            PILIH_TOKO_MENU: [CallbackQueryHandler(editor_menu, pattern="^kembali_ke_editor$"), CallbackQueryHandler(select_store, pattern="^pilih_")],
            HAPUS_TOKO_MENU: [CallbackQueryHandler(editor_menu, pattern="^kembali_ke_editor$"), CallbackQueryHandler(confirm_delete_store, pattern="^hapus_")],
            AWAIT_NAMA_TOKO_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rack_handler), CallbackQueryHandler(editor_menu, pattern="^cancel_tambah_toko$")],
            AWAIT_KONFIRMASI_HAPUS_TOKO: [CallbackQueryHandler(delete_store_confirmed, pattern="^confirm_delete_yes$"), CallbackQueryHandler(no_confirm, pattern="^confirm_delete_no$")],
            SHEET_MENU: [CallbackQueryHandler(back_to_pilih_toko, pattern="^kembali_ke_pilih_toko$"), CallbackQueryHandler(request_new_rack_name, pattern="^tambah_rak_"), CallbackQueryHandler(show_racks_for_plu_add, pattern="^tambah_plu_"), CallbackQueryHandler(show_racks_for_plu_delete, pattern="^hapus_plu_"), CallbackQueryHandler(request_racks_to_delete, pattern="^hapus_rak_")],
            AWAIT_NAMA_RAK_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rack_handler), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            PILIH_RAK_TAMBAH_PLU: [CallbackQueryHandler(request_plu_input, pattern="^addplu_"), CallbackQueryHandler(back_to_sheet_menu, pattern="^back_to_sheet_menu_")],
            AWAIT_PLU_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plu_handler), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            PILIH_RAK_HAPUS_PLU: [CallbackQueryHandler(request_plu_to_delete, pattern="^delplu_"), CallbackQueryHandler(back_to_sheet_menu, pattern="^back_to_sheet_menu_")],
            AWAIT_PLU_HAPUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_plu), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            AWAIT_KONFIRMASI_HAPUS_PLU: [CallbackQueryHandler(delete_plu_confirmed, pattern="^confirm_del_plu_yes$"), CallbackQueryHandler(no_confirm, pattern="^confirm_del_plu_no$")],
            AWAIT_RAK_HAPUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_rack), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            AWAIT_KONFIRMASI_HAPUS_RAK: [CallbackQueryHandler(delete_rack_confirmed, pattern="^confirm_del_rack_yes$"), CallbackQueryHandler(no_confirm, pattern="^confirm_del_rack_no$")],
        }, fallbacks=[CommandHandler("start", start), MessageHandler(filters.TEXT & ~filters.COMMAND, wrong_state_handler)], per_message=False, allow_reentry=True)
    application.add_handler(conv_handler)
    logger.info("Bot sedang berjalan...")
    application.run_polling()

if __name__ == "__main__":
    main()