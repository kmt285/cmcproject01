import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import os
import uuid
import pymongo
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ.get("BOT_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
MONGO_URI = os.environ.get("MONGO_URI")

# Admin IDs များကို Comma (,) ခြားပြီး ရယူရန်
admin_ids_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(i.strip()) for i in admin_ids_env.split(",") if i.strip().isdigit()]

bot = telebot.TeleBot(TOKEN)
db_client = pymongo.MongoClient(MONGO_URI)
db = db_client["telegram_file_sharing_bot"] 
files_collection = db["stored_files"]
channels_collection = db["required_channels"] 

# Database ထဲမှ Channel များကို ပြန်ယူမည့် Function
def get_required_channels():
    channels = {}
    for doc in channels_collection.find():
        channels[doc["chat_id"]] = doc["link"]
    return channels

def get_unjoined_channels(user_id):
    unjoined = {}
    req_channels = get_required_channels()
    
    for chat_id, link in req_channels.items():
        try:
            check_id = int(chat_id) if chat_id.lstrip('-').isdigit() else chat_id
            member = bot.get_chat_member(check_id, user_id)
            if member.status not in ['member', 'creator', 'administrator']:
                unjoined[chat_id] = link
        except Exception as e:
            print(f"Error checking channel {chat_id}: {e}")
            unjoined[chat_id] = link 
    return unjoined

# ၅ မိနစ်ပြည့်လျှင် Message ကို ဖျက်မည့် Function
def delete_sent_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Failed to delete message {message_id}: {e}")

def send_file_to_user(chat_id, file_code):
    file_data = files_collection.find_one({"file_code": file_code})
    
    if file_data:
        file_id = file_data['file_id']
        file_type = file_data['file_type']
        original_caption = file_data.get('original_caption', '') 
        
        remove_kb = ReplyKeyboardRemove()
        sent_msg = None
        
        try:
            if file_type == 'document':
                sent_msg = bot.send_document(chat_id, file_id, caption=original_caption, parse_mode="HTML", reply_markup=remove_kb)
            elif file_type == 'video':
                sent_msg = bot.send_video(chat_id, file_id, caption=original_caption, parse_mode="HTML", reply_markup=remove_kb)
            elif file_type == 'photo':
                sent_msg = bot.send_photo(chat_id, file_id, caption=original_caption, parse_mode="HTML", reply_markup=remove_kb)
            
            # --- 🔴 အောက်ပါအပိုင်းကို အစားထိုး ပြင်ဆင်ရန် 🔴 ---
            if sent_msg:
                # ၁။ ဖိုင်ကို ၅ မိနစ် (စက္ကန့် ၃၀၀) အကြာတွင် ဖျက်ရန် Timer
                threading.Timer(300.0, delete_sent_message, args=[chat_id, sent_msg.message_id]).start()
                
                # ၂။ ၅ မိနစ်ပြည့်လျှင် ပျက်မည့်အကြောင်း သတိပေးစာ ပို့ရန်
                warning_text = "⚠️ <i>ဤဖိုင်သည် ၅ မိနစ်အကြာတွင် အလိုအလျောက် ပျက်သွားပါမည်။/n/n၅ မိနစ်မတိုင်ခင် Forward လုပ်၍သိမ်းထားပါ..</i>"
                warning_msg = bot.send_message(chat_id, warning_text, parse_mode="HTML")
                
                # ၃။ ထိုသတိပေးစာကိုပါ ၅ မိနစ်အကြာတွင် တွဲဖျက်ရန် Timer
                threading.Timer(300.0, delete_sent_message, args=[chat_id, warning_msg.message_id]).start()
            # ----------------------------------------------

        except Exception as e:
            print(f"Error sending file: {e}")
            bot.send_message(chat_id, "❌ ဖိုင်ပို့ရာတွင် အခက်အခဲရှိနေပါသည်။")
    else:
        bot.send_message(chat_id, "❌ 404, File not Found! ")

# --- ⚙️ Admin Control Panel (Buttons Menu) ---

def get_admin_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📋 Required Channels စာရင်းကြည့်ရန်", callback_data="adm_list_chan"),
        InlineKeyboardButton("➕ Channel အသစ်ထည့်ရန်", callback_data="adm_add_chan"),
        InlineKeyboardButton("❌ Channel ပြန်ဖျက်ရန်", callback_data="adm_del_chan")
    )
    return markup

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    bot.send_message(
        message.chat.id, 
        "⚙️ <b>Admin Control Panel</b>\n\nလုပ်ဆောင်လိုသည့် လုပ်ငန်းစဉ်ကို အောက်ပါ Button များမှတစ်ဆင့် ရွေးချယ်နိုင်ပါသည်၊၊", 
        parse_mode="HTML", 
        reply_markup=get_admin_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith('adm_'))
def handle_admin_callbacks(call):
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "❌ သင်သည် Admin မဟုတ်ပါ။", show_alert=True)
        return
    
    action = call.data
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    if action == "adm_list_chan":
        channels = get_required_channels()
        if not channels:
            text = "📭 ထည့်သွင်းထားသော Channel မရှိသေးပါ။"
        else:
            text = "📋 <b>Required Channels စာရင်း:</b>\n\n"
            for cid, link in channels.items():
                text += f"ID: <code>{cid}</code>\nLink: {link}\n\n"
        
        back_kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ Admin Menu သို့ ပြန်သွားရန်", callback_data="adm_main_menu"))
        bot.edit_message_text(text, chat_id, message_id, parse_mode="HTML", reply_markup=back_kb, disable_web_page_preview=True)
        
    elif action == "adm_main_menu":
        bot.edit_message_text(
            "⚙️ <b>Admin Control Panel</b>\n\nလုပ်ဆောင်လိုသည့် လုပ်ငန်းစဉ်ကို အောက်ပါ Button များမှတစ်ဆင့် ရွေးချယ်နိုင်ပါသည်၊၊", 
            chat_id, message_id, parse_mode="HTML", reply_markup=get_admin_keyboard()
        )
        
    elif action == "adm_add_chan":
        msg = bot.send_message(chat_id, "ℹ️ <b>[အဆင့် ၁/၂]</b>\n\nထည့်သွင်းလိုသော Channel ၏ <b>Chat ID</b> ကို ပေးပို့ပေးပါ\n(ဥပမာ: <code>-100123456789</code>):", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_add_channel_id)
        bot.answer_callback_query(call.id)
        
    elif action == "adm_del_chan":
        msg = bot.send_message(chat_id, "ℹ️ ဖယ်ရှားလိုသော Channel ၏ <b>Chat ID</b> ကို ပေးပို့ပေးပါ:", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_delete_channel)
        bot.answer_callback_query(call.id)

# --- Admin Next Step Handlers ---

def process_add_channel_id(message):
    if message.from_user.id not in ADMIN_IDS: return
    chat_id = message.text.strip()
    msg = bot.send_message(message.chat.id, f"ℹ️ <b>[အဆင့် ၂/၂]</b>\n\nChannel ID: <code>{chat_id}</code> အတွက် အသုံးပြုမည့် <b>Invite Link (လင့်ခ်)</b> ကို ပေးပို့ပေးပါ:", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_add_channel_link, chat_id)

def process_add_channel_link(message, chat_id):
    if message.from_user.id not in ADMIN_IDS: return
    link = message.text.strip()
    
    channels_collection.update_one(
        {"chat_id": chat_id}, 
        {"$set": {"link": link}}, 
        upsert=True
    )
    back_kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⚙️ Admin Menu သို့", callback_data="adm_main_menu"))
    bot.send_message(message.chat.id, f"✅ Channel <code>{chat_id}</code> ကို အောင်မြင်စွာ ထည့်သွင်း/ပြင်ဆင်ပြီးပါပြီ။", parse_mode="HTML", reply_markup=back_kb)

def process_delete_channel(message):
    if message.from_user.id not in ADMIN_IDS: return
    chat_id = message.text.strip()
    result = channels_collection.delete_one({"chat_id": chat_id})
    back_kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⚙️ Admin Menu သို့", callback_data="adm_main_menu"))
    if result.deleted_count > 0:
        bot.send_message(message.chat.id, f"✅ Channel <code>{chat_id}</code> ကို စာရင်းထဲမှ ဖယ်ရှားပြီးပါပြီ။", parse_mode="HTML", reply_markup=back_kb)
    else:
        bot.send_message(message.chat.id, "❌ အဆိုပါ Channel ID ကို ရှာမတွေ့ပါ။", reply_markup=back_kb)

# --- End Admin Section ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    args = message.text.split()
    user_id = message.from_user.id

    if len(args) > 1:
        file_code = args[1]
        unjoined_channels = get_unjoined_channels(user_id)
        
        if unjoined_channels:
            markup = InlineKeyboardMarkup(row_width=1)
            
            for chat_id, link in unjoined_channels.items():
                markup.add(InlineKeyboardButton(" Join Channel ", url=link))
                
            markup.add(InlineKeyboardButton("✅ Join ပြီးပါပြီ ", callback_data=f"check_{file_code}"))
            
            bot.send_message(
                message.chat.id, 
                "⚠️ ဖိုင်ရယူနိုင်ရန် အောက်ပါ Channel များကို Join ပေးပါ။ \n\nJoin ပြီးပါက '✅ Join ပြီးပါပြီ' ကိုနှိပ်ပါ။", 
                reply_markup=markup,
                parse_mode="Markdown"
            )
            return

        send_file_to_user(message.chat.id, file_code)
        
    else:
        # Admin ဆိုလျှင် Control Panel ခလုတ် တိုက်ရိုက်ပြပေးမည်
        if user_id in ADMIN_IDS:
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⚙️ Admin Control Panel", callback_data="adm_main_menu"))
            bot.send_message(message.chat.id, "👋 မင်္ဂလာပါ Admin! Bot ကို စီမံခန့်ခွဲရန် အောက်ပါ Button ကို နှိပ်ပါ။", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "ဒီမိန်းချန်နယ်လေးကိုဂျွိူင်းထားပေးကြပါဗျ.. https://t.me/relaxingwithmovies2")

@bot.callback_query_handler(func=lambda call: call.data.startswith('check_'))
def handle_check_join(call):
    file_code = call.data.split('_')[1]
    user_id = call.from_user.id
    
    unjoined_channels = get_unjoined_channels(user_id)
    
    if unjoined_channels:
        bot.answer_callback_query(call.id, "Channel Join ရန် လိုအပ်ပါသေးသည်!", show_alert=True)
    else:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_file_to_user(call.message.chat.id, file_code)

@bot.message_handler(content_types=['document', 'video', 'photo'])
def handle_files(message):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.document:
        file_id = message.document.file_id
        file_type = 'document'
    elif message.video:
        file_id = message.video.file_id
        file_type = 'video'
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_type = 'photo'

    original_caption = message.html_caption if message.html_caption else ""

    file_code = str(uuid.uuid4())[:8]
    
    document_to_save = {
        "file_code": file_code,
        "file_id": file_id,
        "file_type": file_type,
        "uploader_id": message.from_user.id,
        "original_caption": original_caption
    }
    files_collection.insert_one(document_to_save)

    link = f"https://t.me/{BOT_USERNAME}?start={file_code}"
    reply_text = f"✅Successful Generated!\n\n📌 Link :\n<code>{link}</code>"
    
    bot.reply_to(message, reply_text, parse_mode="HTML")

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_dummy_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

print("Bot with Admin Button Dashboard (No File Delete) is running...")
bot.polling(none_stop=True)
