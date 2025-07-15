import logging
import os
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
    CallbackContext,
)

# --- Konfigurasi Awal ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Memuat Konfigurasi dari Environment Variables (AMAN untuk GitHub) ---
TOKEN = os.getenv("TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
WEB_APP_URL = os.getenv("WEB_APP_URL")

if not all([TOKEN, SPREADSHEET_ID, WEB_APP_URL]):
    logger.error("FATAL: Variabel lingkungan TOKEN, SPREADSHEET_ID, atau WEB_APP_URL tidak diatur!")
    # Hentikan bot jika konfigurasi penting tidak ada
    exit()

# --- Definisi State untuk ConversationHandler ---
(SELECTING_ACTION,
 ADD_STORE_NAME, SELECT_STORE_TO_DELETE, CONFIRM_DELETE_STORE,
 SELECT_STORE_FOR_RAK, ADD_RAK_NAME,
 SELECT_STORE_FOR_DELETE_RAK, SELECT_RAK_TO_DELETE, CONFIRM_DELETE_RAK,
 SELECT_STORE_FOR_PLU, SELECT_RAK_FOR_PLU, ADD_PLU_DATA,
 SELECT_STORE_FOR_DELETE_PLU, SELECT_RAK_FOR_DELETE_PLU, LIST_PLU_TO_DELETE, CONFIRM_DELETE_PLU
) = range(16)


# --- Koneksi ke Google Sheets ---
try:
    scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/spreadsheets',
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    logger.info("Berhasil terhubung dengan Google Sheets.")
except FileNotFoundError:
    logger.error("FATAL: File 'credentials.json' tidak ditemukan.")
    exit()
except Exception as e:
    logger.error(f"FATAL: Gagal terhubung ke Google Sheets: {e}")
    exit()


# --- Fungsi Bantuan (Helpers) ---
def get_store_codes():
    """Mengambil semua nama sheet yang valid sebagai kode toko."""
    try:
        return [s.title for s in spreadsheet.worksheets() if len(s.title) == 4 and s.title.isalnum()]
    except Exception as e:
        logger.error(f"Error saat mengambil kode toko: {e}")
        return []

def get_rak_names(worksheet):
    """Mengambil semua nama rak (named ranges) dari sebuah worksheet."""
    try:
        return [nr['name'] for nr in worksheet.list_named_ranges()]
    except Exception as e:
        logger.error(f"Error saat mengambil nama rak: {e}")
        return []

def build_menu(buttons, n_cols, header_buttons=None, footer_buttons=None):
    """Membangun keyboard inline dari daftar tombol."""
    menu = [buttons[i:i + n_cols] for i in range(0, len(buttons), n_cols)]
    if header_buttons:
        menu.insert(0, [header_buttons] if not isinstance(header_buttons, list) else header_buttons)
    if footer_buttons:
        menu.append([footer_buttons] if not isinstance(footer_buttons, list) else footer_buttons)
    return InlineKeyboardMarkup(menu)

def parse_a1_notation(a1_notation):
    """Mengurai notasi A1 (misal: 'Sheet1'!A1:C10) menjadi bagian-bagiannya."""
    match = re.match(r"(?:'([^']*)'!)?([A-Z]+)(\d+):([A-Z]+)(\d+)", a1_notation)
    if not match:
        return None
    _, start_col, start_row, end_col, end_row = match.groups()
    return {
        'start_col': gspread.utils.a1_to_rowcol(f"{start_col}{start_row}")[1],
        'start_row': int(start_row),
        'end_col': gspread.utils.a1_to_rowcol(f"{end_col}{end_row}")[1],
        'end_row': int(end_row)
    }

def clear_and_restart(update: Update, context: CallbackContext, message_text: str):
    """Membersihkan pesan dan menampilkan menu utama setelah jeda."""
    query = update.callback_query
    if query:
        query.edit_message_text(text=message_text)
    else:
        # Jika dipanggil dari MessageHandler, kita perlu menemukan pesan bot untuk diedit
        chat_id = update.effective_chat.id
        bot_message_id = context.user_data.get('last_bot_message_id')
        if bot_message_id:
            try:
                context.bot.edit_message_text(chat_id=chat_id, message_id=bot_message_id, text=message_text)
            except Exception as e:
                logger.warning(f"Tidak dapat mengedit pesan lama: {e}")
                context.bot.send_message(chat_id, text=message_text)

    context.job_queue.run_once(lambda ctx: start(update, ctx, is_restart=True), 5, name=f"restart_{update.effective_chat.id}")


# --- Handler Perintah /start dan Menu Utama ---
def start(update: Update, context: CallbackContext, is_restart=False):
    """Menampilkan menu utama."""
    chat_id = update.effective_chat.id
    
    # Hapus pesan sebelumnya jika memungkinkan
    if not is_restart:
        try:
            if update.message: update.message.delete()
        except: pass
    
    # Bersihkan state percakapan jika dimulai ulang
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("Buka Aplikasi", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton("Tambah Toko", callback_data='add_store'), InlineKeyboardButton("Hapus Toko", callback_data='delete_store')],
        [InlineKeyboardButton("Tambah Rak", callback_data='add_rak'), InlineKeyboardButton("Hapus Rak", callback_data='delete_rak')],
        [InlineKeyboardButton("Tambah Plu", callback_data='add_plu'), InlineKeyboardButton("Hapus Plu", callback_data='delete_plu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Jika ini adalah restart, edit pesan yang ada. Jika tidak, kirim yang baru.
    if is_restart and update.callback_query:
        try:
            update.callback_query.edit_message_text("Selamat Datang di Bot PJR by Edp Toko", reply_markup=reply_markup)
        except Exception as e: # Jika pesan terlalu tua untuk diedit
             context.bot.send_message(chat_id, "Selamat Datang di Bot PJR by Edp Toko", reply_markup=reply_markup)
    else:
        context.bot.send_message(chat_id, "Selamat Datang di Bot PJR by Edp Toko", reply_markup=reply_markup)
        
    return SELECTING_ACTION

# --- Universal Cancel & Fallback ---
def cancel(update: Update, context: CallbackContext) -> int:
    """Membatalkan operasi saat ini dan kembali ke menu utama."""
    clear_and_restart(update, context, "Perintah dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

def invalid_input(update: Update, context: CallbackContext):
    """Menangani input teks saat tombol diharapkan."""
    if update.message:
        update.message.reply_text("Data Salah, Harap Pilih Dari Menu", quote=True)
    # Tidak mengakhiri conversation, biarkan pengguna mencoba lagi atau membatalkan.


# --- Alur Tambah Toko ---
def add_store_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel')]]
    msg = query.edit_message_text(text="Silahkan Masukan Kode Toko (4 digit angka/huruf)", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['last_bot_message_id'] = msg.message_id
    return ADD_STORE_NAME

def add_store_process(update: Update, context: CallbackContext):
    store_code = update.message.text.upper()
    chat_id = update.effective_chat.id
    
    try: update.message.delete()
    except: pass
    
    if not (len(store_code) == 4 and store_code.isalnum()):
        context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['last_bot_message_id'],
                                      text="Kode Toko Harus 4 Digit. Silahkan masukan lagi.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='cancel')]]))
        return ADD_STORE_NAME

    if store_code in get_store_codes():
        context.bot.edit_message_text(chat_id=chat_id, message_id=context.user_data['last_bot_message_id'],
                                      text=f"Nama {store_code} Sudah Ada. Silahkan masukan lagi.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='cancel')]]))
        return ADD_STORE_NAME

    try:
        spreadsheet.add_worksheet(title=store_code, rows="100", cols="26")
        clear_and_restart(update, context, f"Berhasil Menambahkan {store_code}")
    except Exception as e:
        logger.error(f"Gagal menambahkan sheet {store_code}: {e}")
        clear_and_restart(update, context, f"Gagal menambahkan toko. Error: {e}")

    return ConversationHandler.END


# --- Alur Hapus Toko ---
def delete_store_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    stores = get_store_codes()
    if not stores:
        clear_and_restart(update, context, "Tidak ada toko yang bisa dihapus.")
        return ConversationHandler.END

    keyboard = [InlineKeyboardButton(s, callback_data=f"del_store_{s}") for s in stores]
    reply_markup = build_menu(keyboard, 3, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text("Silahkan Pilih Kode Toko Yang Akan Dihapus", reply_markup=reply_markup)
    return SELECT_STORE_TO_DELETE

def delete_store_confirm(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = query.data.split('_')[-1]
    context.user_data['store_to_delete'] = store_code
    keyboard = [[
        InlineKeyboardButton("Ya, Hapus", callback_data='confirm_delete_store_yes'),
        InlineKeyboardButton("Tidak, Batal", callback_data='cancel')
    ]]
    query.edit_message_text(f"Yakin ingin menghapus toko {store_code}? Semua data di dalamnya akan hilang permanen.",
                            reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_DELETE_STORE

def delete_store_execute(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = context.user_data['store_to_delete']
    try:
        worksheet = spreadsheet.worksheet(store_code)
        spreadsheet.del_worksheet(worksheet)
        clear_and_restart(update, context, f"Kode Toko {store_code} Berhasil Dihapus")
    except Exception as e:
        logger.error(f"Error menghapus {store_code}: {e}")
        clear_and_restart(update, context, f"Gagal menghapus toko {store_code}.")
    return ConversationHandler.END


# --- Alur Tambah Rak ---
def rak_select_store(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    stores = get_store_codes()
    if not stores:
        clear_and_restart(update, context, "Tidak ada toko. Buat toko terlebih dahulu.")
        return ConversationHandler.END

    keyboard = [InlineKeyboardButton(s, callback_data=f"store_{s}") for s in stores]
    reply_markup = build_menu(keyboard, 3, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text("Tambah Rak: Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return SELECT_STORE_FOR_RAK

def add_rak_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = query.data.split('_')[1]
    context.user_data['store'] = store_code
    worksheet = spreadsheet.worksheet(store_code)
    existing_raks = get_rak_names(worksheet)

    message_text = f"Toko: {store_code}\n\n"
    if existing_raks:
        message_text += "Rak yang sudah ada:\n- " + "\n- ".join(existing_raks)
    else:
        message_text += "Belum ada rak di toko ini."
    message_text += "\n\nMasukkan nama rak baru. Pisahkan dengan koma (,) atau titik (.) untuk menambah banyak."

    keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel')]]
    msg = query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['last_bot_message_id'] = msg.message_id
    return ADD_RAK_NAME

def add_rak_process(update: Update, context: CallbackContext):
    rak_input = update.message.text
    store_code = context.user_data['store']
    
    try: update.message.delete()
    except: pass

    rak_names = [name.strip().upper() for name in re.split(r'[,.]', rak_input) if name.strip()]
    if not rak_names:
        context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['last_bot_message_id'],
                                      text="Input tidak valid. Masukkan nama rak.",
                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data='cancel')]]))
        return ADD_RAK_NAME

    worksheet = spreadsheet.worksheet(store_code)
    existing_raks = get_rak_names(worksheet)
    all_values = worksheet.get_all_values()
    next_row = len(all_values) + 1 + 3  # Jarak 3 baris

    added, existed = [], []
    for rak_name in rak_names:
        if rak_name in existing_raks:
            existed.append(rak_name)
            continue
        
        try:
            # Header
            header = ["PLU", "Nama Barang", "Barcode"]
            worksheet.update(f'A{next_row}', [header])
            
            # Formula (untuk 20 baris data sebagai contoh)
            for i in range(1, 21):
                data_row = next_row + i
                worksheet.update(f'B{data_row}', f'=IFERROR(VLOOKUP(A{data_row},produk!A:C,2,FALSE), "")', raw=False)
                worksheet.update(f'C{data_row}', f'=IFERROR(VLOOKUP(A{data_row},produk!A:C,3,FALSE), "")', raw=False)
            
            # Named Range (mencakup header dan 20 baris data)
            range_a1 = f'A{next_row}:C{next_row + 20}'
            worksheet.add_named_range(range_a1, rak_name)
            
            # Catatan: gspread tidak bisa format warna, border, tebal. Ini harus manual atau via Sheets API v4.
            
            added.append(rak_name)
            next_row += 25 # Pindah ke baris selanjutnya untuk rak berikutnya
        except Exception as e:
            logger.error(f"Gagal membuat rak {rak_name}: {e}")
            existed.append(f"{rak_name} (gagal dibuat)")

    # Buat pesan hasil
    result_message = ""
    if added:
        result_message += f"Berhasil menambahkan rak: {', '.join(added)}\n"
    if existed:
        result_message += f"Rak berikut sudah ada/gagal: {', '.join(existed)}"
    
    clear_and_restart(update, context, result_message.strip())
    return ConversationHandler.END


# --- Alur Tambah PLU ---
def plu_select_store(update: Update, context: CallbackContext):
    # Sama seperti rak_select_store, tapi state dan callback berbeda
    query = update.callback_query
    query.answer()
    stores = get_store_codes()
    if not stores:
        clear_and_restart(update, context, "Tidak ada toko. Buat toko terlebih dahulu.")
        return ConversationHandler.END

    keyboard = [InlineKeyboardButton(s, callback_data=f"store_{s}") for s in stores]
    reply_markup = build_menu(keyboard, 3, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text("Tambah PLU: Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return SELECT_STORE_FOR_PLU

def plu_select_rak(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = query.data.split('_')[1]
    context.user_data['store'] = store_code
    worksheet = spreadsheet.worksheet(store_code)
    raks = get_rak_names(worksheet)

    if not raks:
        clear_and_restart(update, context, f"Toko {store_code} tidak memiliki rak. Buat rak terlebih dahulu.")
        return ConversationHandler.END

    keyboard = [InlineKeyboardButton(r, callback_data=f"rak_{r}") for r in raks]
    reply_markup = build_menu(keyboard, 2, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text(f"Toko: {store_code}\n\nSilahkan Pilih Nama Rak", reply_markup=reply_markup)
    return SELECT_RAK_FOR_PLU

def add_plu_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    rak_name = query.data.split('_', 1)[1]
    context.user_data['rak'] = rak_name
    store_code = context.user_data['store']
    
    message_text = f"Toko: {store_code}\nRak: {rak_name}\n\nSilakan Masukan Data PLU.\nPisahkan dengan spasi, koma, atau baris baru."
    keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel')]]
    msg = query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['last_bot_message_id'] = msg.message_id
    return ADD_PLU_DATA

def add_plu_process(update: Update, context: CallbackContext):
    plu_input = update.message.text
    store_code = context.user_data['store']
    rak_name = context.user_data['rak']

    try: update.message.delete()
    except: pass
    
    plu_list = [p.strip().upper() for p in re.split(r'[\s,.]+', plu_input) if p.strip()]
    if not plu_list:
        # User mengirim input kosong
        return ADD_PLU_DATA

    try:
        worksheet = spreadsheet.worksheet(store_code)
        rak_range_obj = worksheet.get_named_range(rak_name)
        if not rak_range_obj:
            clear_and_restart(update, context, f"Error: Rak {rak_name} tidak ditemukan lagi.")
            return ConversationHandler.END
            
        rak_range = rak_range_obj.range
        range_coords = parse_a1_notation(rak_range)
        start_row, end_row = range_coords['start_row'], range_coords['end_row']
        
        # Ambil data PLU yang ada di kolom pertama dari range tersebut
        existing_plus_in_rak = [item for sublist in worksheet.get(f'A{start_row+1}:A{end_row}') for item in sublist if item]
        
        added, existed = [], []
        plu_to_add = []
        for plu in plu_list:
            if plu in existing_plus_in_rak:
                existed.append(plu)
            else:
                plu_to_add.append([plu]) # gspread expects a list of lists for append_rows
                added.append(plu)
        
        if plu_to_add:
            # Cari baris kosong pertama di dalam range
            plu_col_data = worksheet.col_values(range_coords['start_col'])[start_row : end_row]
            first_empty_offset = len(plu_col_data)
            first_empty_row = start_row + 1 + first_empty_offset

            # Update sel per sel
            for i, plu_val in enumerate(plu_to_add):
                worksheet.update_cell(first_empty_row + i, range_coords['start_col'], plu_val[0])
        
        result_message = f"Berhasil menambahkan PLU ke {rak_name} di toko {store_code}:\n"
        if added: result_message += f"Ditambahkan: {', '.join(added)}\n"
        if existed: result_message += f"Sudah Ada: {', '.join(existed)}\n"

        clear_and_restart(update, context, result_message.strip())

    except Exception as e:
        logger.error(f"Error saat tambah PLU: {e}")
        clear_and_restart(update, context, "Terjadi kesalahan saat menambahkan PLU.")
        
    return ConversationHandler.END

# --- Alur Hapus Rak & Hapus PLU (Contoh Hapus Rak) ---

def delete_rak_select_store(update: Update, context: CallbackContext):
    # Mirip dengan rak_select_store
    query = update.callback_query
    query.answer()
    stores = get_store_codes()
    if not stores:
        clear_and_restart(update, context, "Tidak ada toko.")
        return ConversationHandler.END

    keyboard = [InlineKeyboardButton(s, callback_data=f"store_{s}") for s in stores]
    reply_markup = build_menu(keyboard, 3, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text("Hapus Rak: Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return SELECT_STORE_FOR_DELETE_RAK

def delete_rak_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = query.data.split('_')[1]
    context.user_data['store'] = store_code
    worksheet = spreadsheet.worksheet(store_code)
    raks = get_rak_names(worksheet)

    if not raks:
        clear_and_restart(update, context, f"Toko {store_code} tidak memiliki rak untuk dihapus.")
        return ConversationHandler.END

    message_text = f"Toko: {store_code}\nRak yang ada: {', '.join(raks)}\n\nMasukkan nama rak yang akan dihapus. Pisahkan dengan koma (,) atau titik (.)."
    keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel')]]
    msg = query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['last_bot_message_id'] = msg.message_id
    return SELECT_RAK_TO_DELETE

def delete_rak_confirm(update: Update, context: CallbackContext):
    rak_input = update.message.text
    try: update.message.delete()
    except: pass
    
    rak_to_delete = [name.strip().upper() for name in re.split(r'[,.]', rak_input) if name.strip()]
    if not rak_to_delete: return SELECT_RAK_TO_DELETE

    context.user_data['raks_to_delete'] = rak_to_delete
    keyboard = [[
        InlineKeyboardButton("Ya, Hapus Rak", callback_data='confirm_delete_rak_yes'),
        InlineKeyboardButton("Tidak, Batal", callback_data='cancel')
    ]]
    query_text = f"Yakin ingin menghapus rak: {', '.join(rak_to_delete)}? Semua PLU di dalamnya akan hilang."
    context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['last_bot_message_id'],
                                  text=query_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_DELETE_RAK

def delete_rak_execute(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = context.user_data['store']
    raks_to_delete = context.user_data['raks_to_delete']
    worksheet = spreadsheet.worksheet(store_code)

    deleted, not_found = [], []
    for rak_name in raks_to_delete:
        try:
            # Hapus data dalam range, lalu hapus named range itu sendiri
            rak_range_obj = worksheet.get_named_range(rak_name)
            if rak_range_obj:
                worksheet.clear(rak_range_obj.range)
                worksheet.delete_named_range(rak_name)
                deleted.append(rak_name)
            else:
                not_found.append(rak_name)
        except Exception as e:
            logger.error(f"Gagal hapus rak {rak_name}: {e}")
            not_found.append(f"{rak_name} (error)")

    result_message = ""
    if deleted: result_message += f"Berhasil menghapus rak: {', '.join(deleted)}\n"
    if not_found: result_message += f"Rak tidak ditemukan/gagal dihapus: {', '.join(not_found)}"
    
    clear_and_restart(update, context, result_message.strip())
    return ConversationHandler.END

# --- Alur Hapus PLU ---
def delete_plu_select_store(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    stores = get_store_codes()
    if not stores:
        clear_and_restart(update, context, "Tidak ada toko.")
        return ConversationHandler.END
    keyboard = [InlineKeyboardButton(s, callback_data=f"store_{s}") for s in stores]
    reply_markup = build_menu(keyboard, 3, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text("Hapus PLU: Silahkan Pilih Kode Toko", reply_markup=reply_markup)
    return SELECT_STORE_FOR_DELETE_PLU

def delete_plu_select_rak(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = query.data.split('_')[1]
    context.user_data['store'] = store_code
    worksheet = spreadsheet.worksheet(store_code)
    raks = get_rak_names(worksheet)
    if not raks:
        clear_and_restart(update, context, f"Toko {store_code} tidak memiliki rak.")
        return ConversationHandler.END
    keyboard = [InlineKeyboardButton(r, callback_data=f"rak_{r}") for r in raks]
    reply_markup = build_menu(keyboard, 2, footer_buttons=InlineKeyboardButton("Cancel", callback_data='cancel'))
    query.edit_message_text(f"Toko: {store_code}\n\nSilahkan Pilih Rak untuk menghapus PLU", reply_markup=reply_markup)
    return SELECT_RAK_FOR_DELETE_PLU

def delete_plu_start(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    rak_name = query.data.split('_', 1)[1]
    context.user_data['rak'] = rak_name
    store_code = context.user_data['store']
    worksheet = spreadsheet.worksheet(store_code)

    try:
        rak_range_obj = worksheet.get_named_range(rak_name)
        range_coords = parse_a1_notation(rak_range_obj.range)
        # Ambil data PLU dan Nama Barang
        data = worksheet.get(f'A{range_coords["start_row"]+1}:B{range_coords["end_row"]}')
        
        message_text = f"Toko: {store_code}\nRak: {rak_name}\n\nPLU\t\tNama Barang\n"
        message_text += "----\t\t-----------\n"
        if not data:
            message_text += "Rak ini kosong.\n\n"
        else:
            for row in data:
                plu = row[0] if len(row) > 0 else ""
                nama = row[1] if len(row) > 1 else "[kosong]"
                message_text += f"{plu}\t\t{nama}\n"
        
        message_text += "\nMasukkan PLU yang akan dihapus. Pisahkan dengan spasi, koma, atau baris baru."
        keyboard = [[InlineKeyboardButton("Cancel", callback_data='cancel')]]
        msg = query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['last_bot_message_id'] = msg.message_id
        return LIST_PLU_TO_DELETE
    except Exception as e:
        logger.error(f"Error saat menampilkan PLU untuk dihapus: {e}")
        clear_and_restart(update, context, "Gagal mengambil data PLU dari rak.")
        return ConversationHandler.END

def delete_plu_confirm(update: Update, context: CallbackContext):
    plu_input = update.message.text
    try: update.message.delete()
    except: pass
    
    plus_to_delete = [p.strip().upper() for p in re.split(r'[\s,.]+', plu_input) if p.strip()]
    if not plus_to_delete: return LIST_PLU_TO_DELETE

    context.user_data['plus_to_delete'] = plus_to_delete
    keyboard = [[
        InlineKeyboardButton("Ya, Hapus PLU", callback_data='confirm_delete_plu_yes'),
        InlineKeyboardButton("Tidak, Batal", callback_data='cancel')
    ]]
    query_text = f"Yakin ingin menghapus PLU berikut: {', '.join(plus_to_delete)}?"
    context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=context.user_data['last_bot_message_id'],
                                  text=query_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_DELETE_PLU

def delete_plu_execute(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    store_code = context.user_data['store']
    rak_name = context.user_data['rak']
    plus_to_delete = context.user_data['plus_to_delete']
    worksheet = spreadsheet.worksheet(store_code)

    try:
        rak_range_obj = worksheet.get_named_range(rak_name)
        range_coords = parse_a1_notation(rak_range_obj.range)
        
        cells_to_find = [worksheet.find(plu, in_range=rak_range_obj.range) for plu in plus_to_delete]
        rows_to_delete = sorted(list(set([cell.row for cell in cells_to_find if cell is not None])), reverse=True)
        
        found_plu_values = [worksheet.cell(row, range_coords['start_col']).value for row in rows_to_delete]
        not_found = [plu for plu in plus_to_delete if plu not in found_plu_values]

        if rows_to_delete:
            worksheet.delete_rows(rows_to_delete[0], rows_to_delete[-1]) # More efficient for contiguous rows

        result_message = ""
        if found_plu_values: result_message += f"Berhasil menghapus PLU: {', '.join(found_plu_values)}\n"
        if not_found: result_message += f"PLU tidak ditemukan di Rak {rak_name}: {', '.join(not_found)}"

        clear_and_restart(update, context, result_message.strip())

    except Exception as e:
        logger.error(f"Error saat hapus PLU: {e}")
        clear_and_restart(update, context, "Terjadi kesalahan saat menghapus PLU.")

    return ConversationHandler.END


# --- Main Function ---
def main() -> None:
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(add_store_start, pattern='^add_store$'),
            CallbackQueryHandler(delete_store_start, pattern='^delete_store$'),
            CallbackQueryHandler(rak_select_store, pattern='^add_rak$'),
            CallbackQueryHandler(delete_rak_select_store, pattern='^delete_rak$'),
            CallbackQueryHandler(plu_select_store, pattern='^add_plu$'),
            CallbackQueryHandler(delete_plu_select_store, pattern='^delete_plu$'),
        ],
        states={
            SELECTING_ACTION: [CallbackQueryHandler(start)], # Default state
            # Add Store Flow
            ADD_STORE_NAME: [MessageHandler(Filters.text & ~Filters.command, add_store_process)],
            # Delete Store Flow
            SELECT_STORE_TO_DELETE: [CallbackQueryHandler(delete_store_confirm, pattern='^del_store_')],
            CONFIRM_DELETE_STORE: [CallbackQueryHandler(delete_store_execute, pattern='^confirm_delete_store_yes$')],
            # Add Rak Flow
            SELECT_STORE_FOR_RAK: [CallbackQueryHandler(add_rak_start, pattern='^store_')],
            ADD_RAK_NAME: [MessageHandler(Filters.text & ~Filters.command, add_rak_process)],
            # Delete Rak Flow
            SELECT_STORE_FOR_DELETE_RAK: [CallbackQueryHandler(delete_rak_start, pattern='^store_')],
            SELECT_RAK_TO_DELETE: [MessageHandler(Filters.text & ~Filters.command, delete_rak_confirm)],
            CONFIRM_DELETE_RAK: [CallbackQueryHandler(delete_rak_execute, pattern='^confirm_delete_rak_yes$')],
            # Add PLU Flow
            SELECT_STORE_FOR_PLU: [CallbackQueryHandler(plu_select_rak, pattern='^store_')],
            SELECT_RAK_FOR_PLU: [CallbackQueryHandler(add_plu_start, pattern='^rak_')],
            ADD_PLU_DATA: [MessageHandler(Filters.text & ~Filters.command, add_plu_process)],
            # Delete PLU Flow
            SELECT_STORE_FOR_DELETE_PLU: [CallbackQueryHandler(delete_plu_select_rak, pattern='^store_')],
            SELECT_RAK_FOR_DELETE_PLU: [CallbackQueryHandler(delete_plu_start, pattern='^rak_')],
            LIST_PLU_TO_DELETE: [MessageHandler(Filters.text & ~Filters.command, delete_plu_confirm)],
            CONFIRM_DELETE_PLU: [CallbackQueryHandler(delete_plu_execute, pattern='^confirm_delete_plu_yes$')],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern='^cancel$'),
            CommandHandler('start', start),
            MessageHandler(Filters.text & ~Filters.command, invalid_input),
        ],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    dispatcher.add_handler(conv_handler)
    # Fallback untuk jika user menekan tombol dari pesan lama
    dispatcher.add_handler(CallbackQueryHandler(lambda u,c: start(u,c,is_restart=True)))


    updater.start_polling()
    logger.info("Bot PJR by Edp Toko sudah berjalan...")
    updater.idle()


if __name__ == '__main__':
    main()```