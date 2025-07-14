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
# Ambil konfigurasi dari environment variables server.
TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEB_APP_URL = os.environ.get("WEB_APP_URL")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GSPREAD_CREDENTIALS = os.environ.get("GSPREAD_CREDENTIALS")

# Pemeriksaan penting: Pastikan semua variabel ada saat bot dimulai.
if not all([TOKEN, WEB_APP_URL, SPREADSHEET_ID, GSPREAD_CREDENTIALS]):
    raise ValueError("Kesalahan: Salah satu environment variable (TOKEN, WEB_APP_URL, SPREADSHEET_ID, GSPREAD_CREDENTIALS) tidak diatur.")

# Konfigurasi logging untuk debug
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- BAGIAN 2: STATE UNTUK CONVERSATION HANDLER ---
# (Tidak ada perubahan di bagian ini)
(
    MAIN_MENU, EDITOR_MENU, PILIH_TOKO_MENU, HAPUS_TOKO_MENU, AWAIT_NAMA_TOKO_BARU,
    AWAIT_KONFIRMASI_HAPUS_TOKO, SHEET_MENU, AWAIT_NAMA_RAK_BARU, PILIH_RAK_TAMBAH_PLU,
    AWAIT_PLU_BARU, PILIH_RAK_HAPUS_PLU, AWAIT_PLU_HAPUS, AWAIT_KONFIRMASI_HAPUS_PLU,
    AWAIT_RAK_HAPUS, AWAIT_KONFIRMASI_HAPUS_RAK,
) = range(15)

# --- BAGIAN 3: FUNGSI HELPER GOOGLE SHEETS (DENGAN PERUBAHAN PENTING) ---

def get_gspread_client():
    """
    Mengotorisasi dan mengembalikan client gspread menggunakan kredensial
    dari environment variable, bukan dari file.
    """
    # Ubah string JSON dari environment variable menjadi dictionary Python
    try:
        creds_dict = json.loads(GSPREAD_CREDENTIALS)
    except json.JSONDecodeError:
        raise ValueError("GSPREAD_CREDENTIALS tidak berisi JSON yang valid.")

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Gunakan from_json_keyfile_dict untuk membaca dari dictionary, bukan file
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client

# --- SISA FUNGSI HELPER (Tidak ada perubahan) ---
def get_all_valid_stores():
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheets = spreadsheet.worksheets()
        return [s.title for s in sheets if len(s.title) == 4 and s.title.isalnum()]
    except Exception as e:
        logger.error(f"Error getting stores: {e}")
        return []

# ... (Salin semua fungsi helper lainnya dari skrip sebelumnya, seperti add_new_store, delete_store_sheet, dll. SEMUANYA SAMA)
# ... Saya akan menyalinnya di bawah ini agar lengkap ...

def add_new_store(store_code):
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        spreadsheet.add_worksheet(title=store_code, rows="100", cols="50")
        try:
            spreadsheet.worksheet("produk")
        except gspread.WorksheetNotFound:
            produk_sheet = spreadsheet.add_worksheet(title="produk", rows="1000", cols="3")
            produk_sheet.update('A1:C1', [['plu', 'Nama Barang', 'Barcode']])
            set_frozen(produk_sheet, rows=1)
        return True
    except Exception as e:
        logger.error(f"Error adding new store {store_code}: {e}")
        return False

def delete_store_sheet(store_code):
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        spreadsheet.del_worksheet(spreadsheet.worksheet(store_code))
        return True
    except Exception as e:
        logger.error(f"Error deleting store {store_code}: {e}")
        return False

def get_racks_in_sheet(store_code):
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(store_code)
        return [nr['name'] for nr in sheet.list_named_ranges()]
    except Exception as e:
        logger.error(f"Error getting racks for {store_code}: {e}")
        return []

def find_next_available_row(worksheet):
    all_values = worksheet.get_all_values()
    if not all_values:
        return 1
    return len(all_values) + 4

def add_new_rack(store_code, rack_name):
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(store_code)
        start_row = find_next_available_row(sheet)
        header = ["Plu", "Nama Barang", "Barcode"]
        sheet.update(f"A{start_row}:C{start_row}", [header])
        header_format = CellFormat(backgroundColor=Color(0.75, 0.92, 0.61), textFormat=TextFormat(bold=True, fontSize=15), horizontalAlignment='CENTER')
        format_cell_range(sheet, f"A{start_row}:C{start_row}", header_format)
        data_format = CellFormat(backgroundColor=Color(0.85, 1, 1))
        format_cell_range(sheet, f"A{start_row+1}:C{start_row+10}", data_format)
        formula_nama = f'=IFERROR(INDEX(produk!B:B,MATCH(A{start_row+1},produk!A:A,0)),"")'
        formula_barcode = f'=IFERROR(INDEX(produk!C:C,MATCH(A{start_row+1},produk!A:A,0)),"")'
        sheet.update(f"B{start_row+1}", formula_nama, raw=False)
        sheet.update(f"C{start_row+1}", formula_barcode, raw=False)
        border = Border(style='SOLID')
        format_cell_range(sheet, f"A{start_row}:C{start_row+10}", CellFormat(borders=Borders(top=border, bottom=border, left=border, right=border)))
        sheet.add_named_range(rack_name, f"'{sheet.title}'!A{start_row+1}:A")
        return True
    except Exception as e:
        logger.error(f"Error adding new rack {rack_name} to {store_code}: {e}")
        return False

def add_plus_to_rack(store_code, rack_name, plus_to_add):
    added = []
    duplicates = []
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(store_code)
        named_range = sheet.get_named_range(rack_name)
        range_values = sheet.get(named_range['range'])
        existing_plus = [item for sublist in range_values for item in sublist] if range_values else []
        cells_to_update = []
        for plu in plus_to_add:
            if plu in existing_plus:
                duplicates.append(plu)
            else:
                cells_to_update.append(gspread.Cell(len(existing_plus) + len(added) + int(re.findall(r'\d+', named_range['range'])[0]), 1, value=plu))
                added.append(plu)
        if cells_to_update:
            sheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
        return added, duplicates
    except Exception as e:
        logger.error(f"Error adding PLUs to {rack_name}: {e}")
        return [], plus_to_add

def get_plus_in_rack(store_code, rack_name):
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(store_code)
        named_range_info = sheet.get_named_range(rack_name)
        range_a1 = named_range_info['range'] 
        start_cell_a1 = range_a1.split('!')[1] 
        start_cell = start_cell_a1.split(':')[0] 
        start_col_char = re.match(r"[A-Z]+", start_cell).group()
        end_col_char = chr(ord(start_col_char) + 2)
        start_row = re.search(r"\d+", start_cell).group()
        table_range = f"{start_col_char}{start_row}:{end_col_char}"
        data = sheet.get(table_range, value_render_option='FORMULA')
        formatted_data = sheet.get(table_range, value_render_option='FORMATTED_VALUE')
        combined_data = []
        for i, row in enumerate(data):
            if row:
                plu = row[0] if len(row) > 0 else ""
                nama = formatted_data[i][1] if len(formatted_data[i]) > 1 else ""
                barcode = formatted_data[i][2] if len(formatted_data[i]) > 2 else ""
                combined_data.append([plu, nama, barcode])
        return combined_data
    except Exception as e:
        logger.error(f"Error getting PLUs from {rack_name}: {e}")
        return []

def delete_plus_from_rack(store_code, rack_name, plus_to_delete):
    deleted = []
    not_found = []
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(store_code)
        named_range = sheet.get_named_range(rack_name)
        range_a1 = named_range['range']
        cells_to_find = []
        for plu in plus_to_delete:
            try:
                cell = sheet.find(plu, in_range=range_a1)
                if cell:
                    cells_to_find.append(cell)
            except gspread.exceptions.CellNotFound:
                continue
        rows_to_delete = sorted(list(set([cell.row for cell in cells_to_find])), reverse=True)
        found_plus = [cell.value for cell in cells_to_find]
        not_found = list(set(plus_to_delete) - set(found_plus))
        for row in rows_to_delete:
            sheet.delete_rows(row)
        deleted = list(set(plus_to_delete) - set(not_found))
        return deleted, not_found
    except Exception as e:
        logger.error(f"Error deleting PLUs from {rack_name}: {e}")
        return [], plus_to_delete

def delete_racks(store_code, racks_to_delete):
    deleted = []
    not_found = []
    try:
        client = get_gspread_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        sheet = spreadsheet.worksheet(store_code)
        all_named_ranges = {nr['name']: nr for nr in sheet.list_named_ranges()}
        for rack in racks_to_delete:
            if rack in all_named_ranges:
                range_info = all_named_ranges[rack]
                range_a1 = range_info['range']
                start_cell = range_a1.split('!')[1].split(':')[0]
                start_row = int(re.findall(r'\d+', start_cell)[0])
                header_row = start_row - 1
                sheet.delete_named_range(rack)
                col_values = sheet.col_values(1)
                last_row_in_sheet = len(col_values)
                range_to_clear = f"A{header_row}:C{last_row_in_sheet + 4}"
                sheet.batch_clear([range_to_clear])
                deleted.append(rack)
            else:
                not_found.append(rack)
        return deleted, not_found
    except Exception as e:
        logger.error(f"Error deleting racks: {e}")
        return [], racks_to_delete


# --- BAGIAN 4 & 5: KEYBOARD DAN HANDLER BOT (Tidak ada perubahan di sini) ---
# ... (Salin seluruh fungsi keyboard dan handler dari skrip sebelumnya) ...
# ... Saya akan menyalinnya di bawah ini agar lengkap ...

def build_keyboard(buttons, n_cols):
    return [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]

def main_menu_keyboard():
    buttons = [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL)), InlineKeyboardButton("Editor", callback_data="editor")]
    return InlineKeyboardMarkup(build_keyboard(buttons, 2))

def editor_menu_keyboard():
    buttons = [InlineKeyboardButton("Pilih Toko", callback_data="pilih_toko"), InlineKeyboardButton("Tambah Toko", callback_data="tambah_toko"), InlineKeyboardButton("Hapus Toko", callback_data="hapus_toko"), InlineKeyboardButton("Kembali", callback_data="kembali_ke_main")]
    return InlineKeyboardMarkup(build_keyboard(buttons, 2))

def store_list_keyboard(action_prefix):
    stores = get_all_valid_stores()
    buttons = [InlineKeyboardButton(store, callback_data=f"{action_prefix}_{store}") for store in stores]
    if action_prefix in ["pilih", "hapus"]:
        buttons.append(InlineKeyboardButton("Kembali", callback_data="kembali_ke_editor"))
    return InlineKeyboardMarkup(build_keyboard(buttons, 3)) if buttons else None

def rack_list_keyboard(store_code, action_prefix):
    racks = get_racks_in_sheet(store_code)
    buttons = [InlineKeyboardButton(rack, callback_data=f"{action_prefix}_{rack}") for rack in racks]
    buttons.append(InlineKeyboardButton("Kembali", callback_data=f"back_to_sheet_menu_{store_code}"))
    return InlineKeyboardMarkup(build_keyboard(buttons, 2)) if racks else None

def sheet_menu_keyboard(store_code):
    buttons = [InlineKeyboardButton("Tambah Rak", callback_data=f"tambah_rak_{store_code}"), InlineKeyboardButton("Tambah Plu", callback_data=f"tambah_plu_{store_code}"), InlineKeyboardButton("Hapus Plu", callback_data=f"hapus_plu_{store_code}"), InlineKeyboardButton("Hapus Rak", callback_data=f"hapus_rak_{store_code}"), InlineKeyboardButton("Kembali", callback_data="kembali_ke_pilih_toko")]
    return InlineKeyboardMarkup(build_keyboard(buttons, 2))

def confirmation_keyboard(yes_callback, no_callback):
    return InlineKeyboardMarkup(build_keyboard([InlineKeyboardButton("Ya", callback_data=yes_callback), InlineKeyboardButton("Tidak", callback_data=no_callback)], 2))

def cancel_keyboard(callback_data):
    return InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data=callback_data)]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    context.user_data.clear()
    await update.message.reply_html(f"Selamat Datang di Bot PJR by Edp Toko, {user.mention_html()}!", reply_markup=main_menu_keyboard())
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Menu Utama", reply_markup=main_menu_keyboard())
    return MAIN_MENU

async def editor_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Anda berada di menu Editor. Silahkan pilih opsi:", reply_markup=editor_menu_keyboard())
    return EDITOR_MENU

# ... (Semua handler lainnya sama persis) ...
# ... (Salin dari skrip sebelumnya) ...
# (Saya sertakan lengkap di bawah ini)

async def request_new_store_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.edit_message_text(text="Silahkan masukan Kode Toko (harus 4 digit angka atau huruf).", reply_markup=cancel_keyboard("cancel_tambah_toko"))
    return AWAIT_NAMA_TOKO_BARU

async def add_store_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = update.message.text.upper()
    if len(store_code) != 4 or not store_code.isalnum():
        await update.message.reply_text("Kode Toko Harus 4 Digit dan alfanumerik. Coba lagi.", reply_markup=cancel_keyboard("cancel_tambah_toko")); return AWAIT_NAMA_TOKO_BARU
    if store_code in get_all_valid_stores():
        await update.message.reply_text(f"Nama Toko '{store_code}' sudah ada. Silahkan gunakan nama lain.", reply_markup=cancel_keyboard("cancel_tambah_toko")); return AWAIT_NAMA_TOKO_BARU
    if add_new_store(store_code): await update.message.reply_text(f"Berhasil menambahkan toko '{store_code}'.", reply_markup=editor_menu_keyboard())
    else: await update.message.reply_text(f"Gagal menambahkan toko '{store_code}'. Terjadi error.", reply_markup=editor_menu_keyboard())
    return EDITOR_MENU

async def show_stores_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    keyboard = store_list_keyboard("hapus")
    if keyboard: await query.edit_message_text(text="Pilih toko yang ingin dihapus:", reply_markup=keyboard); return HAPUS_TOKO_MENU
    else: await query.edit_message_text(text="Tidak ada toko yang bisa dihapus.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU

async def confirm_delete_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = query.data.split("_")[-1]; context.user_data["store_to_delete"] = store_code
    await query.edit_message_text(text=f"Apakah Anda yakin ingin menghapus toko '{store_code}'? Tindakan ini tidak bisa dibatalkan.", reply_markup=confirmation_keyboard("confirm_delete_yes", "confirm_delete_no"))
    return AWAIT_KONFIRMASI_HAPUS_TOKO

async def delete_store_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data.get("store_to_delete")
    if store_code and delete_store_sheet(store_code): await query.edit_message_text(text=f"Kode Toko {store_code} berhasil dihapus.", reply_markup=editor_menu_keyboard())
    else: await query.edit_message_text(text=f"Gagal menghapus toko {store_code}.", reply_markup=editor_menu_keyboard())
    context.user_data.pop("store_to_delete", None); return EDITOR_MENU

async def show_stores_to_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    keyboard = store_list_keyboard("pilih")
    if keyboard: await query.edit_message_text(text="Silahkan pilih toko untuk diedit:", reply_markup=keyboard); return PILIH_TOKO_MENU
    else: await query.edit_message_text(text="Tidak ada toko yang tersedia. Silahkan buat toko baru.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU

async def select_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = query.data.split("_")[-1]; context.user_data['active_store'] = store_code
    await query.edit_message_text(text=f"Berhasil masuk ke Toko '{store_code}'. Apa yang ingin Anda lakukan?", reply_markup=sheet_menu_keyboard(store_code))
    return SHEET_MENU

async def request_new_rack_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']; existing_racks = get_racks_in_sheet(store_code)
    message = "Silahkan masukan nama Rak baru.\nBisa lebih dari satu, pisahkan dengan spasi, koma, atau titik."
    if existing_racks: message += "\n\nNama Rak yang sudah ada:\n- " + "\n- ".join(existing_racks)
    await query.edit_message_text(text=message, reply_markup=cancel_keyboard(f"cancel_op_{store_code}")); return AWAIT_NAMA_RAK_BARU

async def add_rack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = context.user_data['active_store']; rack_names = re.split(r'[\s,.]+', update.message.text.strip())
    existing_racks = get_racks_in_sheet(store_code); added, existed = [], []
    for name in filter(None, rack_names):
        if name in existing_racks: existed.append(name)
        else:
            if add_new_rack(store_code, name): added.append(name)
    msg = ""
    if added: msg += f"Berhasil menambahkan rak: {', '.join(added)}.\n"
    if existed: msg += f"Rak berikut sudah ada: {', '.join(existed)}."
    await update.message.reply_text(msg or "Input tidak valid.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

async def show_racks_for_plu_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']; keyboard = rack_list_keyboard(store_code, f"addplu_{store_code}")
    if keyboard: await query.edit_message_text("Pilih Rak untuk menambahkan PLU:", reply_markup=keyboard); return PILIH_RAK_TAMBAH_PLU
    else: await query.edit_message_text("Tidak ada rak di toko ini. Buat rak dahulu.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

async def request_plu_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    parts = query.data.split('_'); context.user_data['rack_to_modify'] = parts[2]
    await query.edit_message_text("Silahkan input PLU (pisahkan dengan spasi, koma, titik atau baris baru).", reply_markup=cancel_keyboard(f"cancel_op_{parts[1]}")); return AWAIT_PLU_BARU

async def add_plu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    store_code = context.user_data['active_store']; rack_name = context.user_data['rack_to_modify']
    plus_to_add = list(filter(None, re.split(r'[\s,.\n]+', update.message.text.strip())))
    added, duplicates = add_plus_to_rack(store_code, rack_name, plus_to_add); msg = ""
    if added:
        new_data = [row for row in get_plus_in_rack(store_code, rack_name) if row and row[0] in added]
        summary = "\n".join([f"{row[0]:<10}{row[1]}" for row in new_data])
        msg += f"Berhasil menambahkan PLU ke {rack_name}:\n`Plu       Nama Barang`\n`{summary}`\n"
    if duplicates: msg += f"\nPLU berikut sudah ada di {rack_name}: {', '.join(duplicates)}"
    await update.message.reply_text(msg or "Tidak ada PLU yang ditambahkan.", reply_markup=sheet_menu_keyboard(store_code), parse_mode='Markdown')
    context.user_data.pop('rack_to_modify', None); return SHEET_MENU

async def show_racks_for_plu_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']; keyboard = rack_list_keyboard(store_code, f"delplu_{store_code}")
    if keyboard: await query.edit_message_text("Pilih Rak untuk menghapus PLU:", reply_markup=keyboard); return PILIH_RAK_HAPUS_PLU
    else: await query.edit_message_text("Tidak ada rak di toko ini.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU

async def request_plu_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    parts = query.data.split('_'); rack_name = parts[2]; context.user_data['rack_to_modify'] = rack_name
    plu_data = get_plus_in_rack(parts[1], rack_name)
    if not plu_data: await query.edit_message_text(f"Tidak ada PLU di rak {rack_name}.", reply_markup=sheet_menu_keyboard(parts[1])); return SHEET_MENU
    summary = "\n".join([f"{row[0]:<10}{row[1]}" for row in plu_data if row and row[0]])
    msg = f"PLU di {rack_name}:\n`Plu       Nama Barang`\n`{summary}`\n\nMasukkan PLU yg akan dihapus:"
    await query.edit_message_text(msg, reply_markup=cancel_keyboard(f"cancel_op_{parts[1]}"), parse_mode='Markdown'); return AWAIT_PLU_HAPUS

async def confirm_delete_plu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    plus = list(filter(None, re.split(r'[\s,.\n]+', update.message.text.strip()))); context.user_data['items_to_delete'] = plus
    await update.message.reply_text(f"Anda akan menghapus PLU: {', '.join(plus)}. Lanjutkan?", reply_markup=confirmation_keyboard("confirm_del_plu_yes", "confirm_del_plu_no")); return AWAIT_KONFIRMASI_HAPUS_PLU

async def delete_plu_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']; rack_name = context.user_data['rack_to_modify']; plus_to_delete = context.user_data['items_to_delete']
    deleted, not_found = delete_plus_from_rack(store_code, rack_name, plus_to_delete); msg = ""
    if deleted: msg += f"Berhasil menghapus PLU: {', '.join(deleted)}.\n"
    if not_found: msg += f"PLU berikut tidak ditemukan di Rak {rack_name}: {', '.join(not_found)}."
    await query.edit_message_text(msg or "Tidak ada PLU yang dihapus.", reply_markup=sheet_menu_keyboard(store_code))
    context.user_data.pop('rack_to_modify', None); context.user_data.pop('items_to_delete', None); return SHEET_MENU

async def request_racks_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']; racks = get_racks_in_sheet(store_code)
    if not racks: await query.edit_message_text("Tidak ada rak di toko ini.", reply_markup=sheet_menu_keyboard(store_code)); return SHEET_MENU
    racks_formatted = '\n'.join(['\t'.join(racks[i:i+2]) for i in range(0, len(racks), 2)])
    msg = f"Rak di Toko {store_code}:\n`{racks_formatted}`\n\nMasukkan nama rak yg akan dihapus:"
    await query.edit_message_text(msg, reply_markup=cancel_keyboard(f"cancel_op_{store_code}"), parse_mode='Markdown'); return AWAIT_RAK_HAPUS

async def confirm_delete_rack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    racks = list(filter(None, re.split(r'[\s,.]+', update.message.text.strip()))); context.user_data['items_to_delete'] = racks
    await update.message.reply_text(f"Anda akan menghapus Rak: {', '.join(racks)} & seluruh isinya. Lanjutkan?", reply_markup=confirmation_keyboard("confirm_del_rack_yes", "confirm_del_rack_no")); return AWAIT_KONFIRMASI_HAPUS_RAK

async def delete_rack_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']; racks_to_delete = context.user_data['items_to_delete']
    deleted, not_found = delete_racks(store_code, racks_to_delete); msg = ""
    if deleted: msg += f"Berhasil menghapus rak: {', '.join(deleted)}.\n"
    if not_found: msg += f"Rak berikut tidak ditemukan: {', '.join(not_found)}."
    await query.edit_message_text(msg or "Tidak ada rak yang dihapus.", reply_markup=sheet_menu_keyboard(store_code))
    context.user_data.pop('items_to_delete', None); return SHEET_MENU

async def back_to_pilih_toko(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data.pop('active_store', 'yg tidak diketahui')
    await query.edit_message_text(f"Anda keluar dari Toko '{store_code}'.")
    return await show_stores_to_select(update, context)

async def back_to_sheet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = query.data.split('_')[-1]; context.user_data['active_store'] = store_code
    await query.edit_message_text(f"Anda di Toko '{store_code}'.", reply_markup=sheet_menu_keyboard(store_code))
    return SHEET_MENU

async def cancel_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data['active_store']
    await query.edit_message_text("Operasi dibatalkan.", reply_markup=sheet_menu_keyboard(store_code))
    context.user_data.pop('rack_to_modify', None); context.user_data.pop('items_to_delete', None); return SHEET_MENU

async def no_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    store_code = context.user_data.get('active_store')
    if 'store_to_delete' in context.user_data:
        context.user_data.pop('store_to_delete', None)
        await query.edit_message_text("Batal menghapus kode toko.", reply_markup=editor_menu_keyboard()); return EDITOR_MENU
    else:
        await query.edit_message_text("Operasi dibatalkan.", reply_markup=sheet_menu_keyboard(store_code))
        context.user_data.pop('rack_to_modify', None); context.user_data.pop('items_to_delete', None); return SHEET_MENU

async def wrong_state_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Data Salah, Harap Pilih Menu Terlebih Dahulu.")

# --- BAGIAN 6: FUNGSI UTAMA UNTUK MENJALANKAN BOT ---
def main() -> None:
    """Jalankan bot."""
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        # (Isi dari ConversationHandler sama persis, tidak ada yang diubah)
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(editor_menu, pattern="^editor$")],
            EDITOR_MENU: [
                CallbackQueryHandler(main_menu, pattern="^kembali_ke_main$"),
                CallbackQueryHandler(show_stores_to_select, pattern="^pilih_toko$"),
                CallbackQueryHandler(request_new_store_name, pattern="^tambah_toko$"),
                CallbackQueryHandler(show_stores_to_delete, pattern="^hapus_toko$"),
            ],
            PILIH_TOKO_MENU: [CallbackQueryHandler(editor_menu, pattern="^kembali_ke_editor$"), CallbackQueryHandler(select_store, pattern="^pilih_")],
            HAPUS_TOKO_MENU: [CallbackQueryHandler(editor_menu, pattern="^kembali_ke_editor$"), CallbackQueryHandler(confirm_delete_store, pattern="^hapus_")],
            AWAIT_NAMA_TOKO_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_store_handler), CallbackQueryHandler(editor_menu, pattern="^cancel_tambah_toko$")],
            AWAIT_KONFIRMASI_HAPUS_TOKO: [CallbackQueryHandler(delete_store_confirmed, pattern="^confirm_delete_yes$"), CallbackQueryHandler(no_confirm, pattern="^confirm_delete_no$")],
            
            SHEET_MENU: [
                CallbackQueryHandler(back_to_pilih_toko, pattern="^kembali_ke_pilih_toko$"),
                CallbackQueryHandler(request_new_rack_name, pattern="^tambah_rak_"),
                CallbackQueryHandler(show_racks_for_plu_add, pattern="^tambah_plu_"),
                CallbackQueryHandler(show_racks_for_plu_delete, pattern="^hapus_plu_"),
                CallbackQueryHandler(request_racks_to_delete, pattern="^hapus_rak_"),
            ],
            AWAIT_NAMA_RAK_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rack_handler), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            
            PILIH_RAK_TAMBAH_PLU: [CallbackQueryHandler(request_plu_input, pattern="^addplu_"), CallbackQueryHandler(back_to_sheet_menu, pattern="^back_to_sheet_menu_")],
            AWAIT_PLU_BARU: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_plu_handler), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            
            PILIH_RAK_HAPUS_PLU: [CallbackQueryHandler(request_plu_to_delete, pattern="^delplu_"), CallbackQueryHandler(back_to_sheet_menu, pattern="^back_to_sheet_menu_")],
            AWAIT_PLU_HAPUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_plu), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            AWAIT_KONFIRMASI_HAPUS_PLU: [CallbackQueryHandler(delete_plu_confirmed, pattern="^confirm_del_plu_yes$"), CallbackQueryHandler(no_confirm, pattern="^confirm_del_plu_no$")],
            
            AWAIT_RAK_HAPUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete_rack), CallbackQueryHandler(cancel_operation, pattern="^cancel_op_")],
            AWAIT_KONFIRMASI_HAPUS_RAK: [CallbackQueryHandler(delete_rack_confirmed, pattern="^confirm_del_rack_yes$"), CallbackQueryHandler(no_confirm, pattern="^confirm_del_rack_no$")],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, wrong_state_handler)
        ],
        per_message=False,
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    
    logger.info("Bot sedang berjalan...")
    application.run_polling()

if __name__ == "__main__":
    main()