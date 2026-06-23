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

# 🔴 အသစ်ထည့်ထားသော Database Channel ID
DB_CHANNEL_ID = os.environ.get("DB_CHANNEL_ID") 

# Admin IDs များကို Comma (,) ခြားပြီး ရယူရန်
admin_ids_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(i.strip()) for i in admin_ids_env.split(",") if i.strip().isdigit()]

bot = telebot.TeleBot(TOKEN)
db_client = pymongo.MongoClient(MONGO_URI)
db = db_client["telegram_file_sharing_bot"] 
files_collection = db["stored_files"]
channels_collection = db["required_channels"] 
bot_channels_collection = db["bot_channels"]

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

def delete_sent_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"Failed to delete message {message_id}: {e}")

# 🔴 ပြင်ဆင်ထားသော ဖိုင်ပို့သည့် Function (Copy Message အသုံးပြုထားသည်)
def send_file_to_user(chat_id, file_code):
    file_data = files_collection.find_one({"file_code": file_code})
    
    if file_data:
        remove_kb = ReplyKeyboardRemove()
        sent_msg = None
        
        try:
            # စနစ်သစ် (Copy Message) ဖြင့် ပို့ခြင်း
            if "message_id" in file_data:
                msg_id = file_data["message_id"]
                sent_msg = bot.copy_message(chat_id, DB_CHANNEL_ID, msg_id, reply_markup=remove_kb)
                
            # စနစ်ဟောင်းလင့်ခ်များ (File ID) အတွက် ချို့ယွင်းမှုမရှိစေရန် ချန်ထားခြင်း
            else:
                file_id = file_data['file_id']
                file_type = file_data['file_type']
                original_caption = file_data.get('original_caption', '') 
                
                if file_type == 'document':
                    sent_msg = bot.send_document(chat_id, file_id, caption=original_caption, parse_mode="HTML", reply_markup=remove_kb)
                elif file_type == 'video':
                    sent_msg = bot.send_video(chat_id, file_id, caption=original_caption, parse_mode="HTML", reply_markup=remove_kb)
                elif file_type == 'photo':
                    sent_msg = bot.send_photo(chat_id, file_id, caption=original_caption, parse_mode="HTML", reply_markup=remove_kb)
            
            # ၅ မိနစ် (စက္ကန့် ၃၀၀) အကြာတွင် ဖျက်ရန်
            if sent_msg:
                threading.Timer(300.0, delete_sent_message, args=[chat_id, sent_msg.message_id]).start()
                
                warning_text = "⚠️ <i>ဤဖိုင်သည် ၅ မိနစ်အကြာတွင် အလိုအလျောက် ပျက်သွားပါမည်။ ၅ မိနစ်မတိုင်ခင် Forward လုပ်၍သိမ်းထားပါ..</i>"
                warning_msg = bot.send_message(chat_id, warning_text, parse_mode="HTML")
                
                threading.Timer(300.0, delete_sent_message, args=[chat_id, warning_msg.message_id]).start()

        except Exception as e:
            print(f"Error sending file: {e}")
            bot.send_message(chat_id, "❌ ဖိုင်ပို့ရာတွင် အခက်အခဲရှိနေပါသည်။ (ဖိုင်ဖျက်ခံရခြင်း ဖြစ်နိုင်ပါသည်)")
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
        if user_id in ADMIN_IDS:
            markup = InlineKeyboardMarkup().add(InlineKeyboardButton("⚙️ Admin Control Panel", callback_data="adm_main_menu"))
            bot.send_message(message.chat.id, "👋 မင်္ဂလာပါ Admin! Bot ကို စီမံခန့်ခွဲရန် အောက်ပါ Button ကို နှိပ်ပါ။", reply_markup=markup)
        else:
            bot.send_message(message.chat.id, "ဒီမိန်းချန်နယ်လေးကိုဂျွိူင်းထားပေးကြပါဗျ.. https://t.me/relaxingwithmovies2")

# --- 🔴 Bot ကို Admin ခန့်လျှင် Database တွင် အလိုအလျောက် မှတ်သားမည့်စနစ် ---
@bot.my_chat_member_handler()
def track_admin_channels(message):
    if message.chat.type == 'channel':
        new_status = message.new_chat_member.status
        chat_id = message.chat.id
        chat_title = message.chat.title
        
        # Admin အဖြစ် အသစ်ခန့်ခံရလျှင် (သို့) ရှိနေလျှင်
        if new_status in ['administrator', 'creator']:
            bot_channels_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"title": chat_title, "status": new_status}},
                upsert=True
            )
        # Admin အဖြုတ်ခံရလျှင် (သို့) Channel ထဲမှ ထုတ်ခံရလျှင် စာရင်းထဲမှ ပြန်ဖျက်မည်
        elif new_status in ['left', 'kicked', 'member']:
            bot_channels_collection.delete_one({"chat_id": chat_id})

# --- 🔴 လျှို့ဝှက် Command (/listallch) ဖြင့် Channel များကြည့်ရန် ---
@bot.message_handler(commands=['listallch'])
def list_all_bot_channels(message):
    # Admin သာ သုံးခွင့်ရှိစေရန် စစ်ဆေးခြင်း
    if message.from_user.id not in ADMIN_IDS:
        return
    
    # Database ထဲမှ မှတ်ထားသမျှ Channel များကို ဆွဲထုတ်ခြင်း
    channels = list(bot_channels_collection.find())
    
    if len(channels) == 0:
        bot.reply_to(message, "📭 Bot ကို Admin ခန့်ထားသော Channel များ မရှိသေးပါ။\n\n(မှတ်ချက် - ယခုမှစ၍ အသစ်ခန့်သော (သို့) Permission ပြန်ပြင်ပေးသော Channel များကိုသာ မှတ်သားနိုင်မည်ဖြစ်သည်)")
        return
        
    text = "📋 <b>Bot Admin အဖြစ်ရှိနေသော Channel များ:</b>\n\n"
    
    for ch in channels:
        chat_id = ch['chat_id']
        title = ch.get('title', 'Unknown Channel')
        
        try:
            # Channel သို့ ဝင်ရန် Invite Link ကို အလိုအလျောက် Generate လုပ်ခြင်း
            link = bot.export_chat_invite_link(chat_id)
            text += f"▪️ <b>{title}</b>\nID: <code>{chat_id}</code>\n🔗 <a href='{link}'>Channel သို့ ဝင်ရန်</a>\n\n"
        except Exception as e:
            text += f"▪️ <b>{title}</b>\nID: <code>{chat_id}</code>\n🔗 <i>(Link ထုတ်၍မရပါ - Admin Permission အပြည့်အစုံ လိုအပ်သည်)</i>\n\n"
            
    bot.reply_to(message, text, parse_mode="HTML", disable_web_page_preview=True)

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

# 🔴 ပြင်ဆင်ထားသော ဖိုင်လက်ခံသည့် Function (Database Channel သို့ Forward လုပ်ခြင်း)
@bot.message_handler(content_types=['document', 'video', 'photo'])
def handle_files(message):
    if message.from_user.id not in ADMIN_IDS:
        return

    # Database Channel ID သတ်မှတ်ထားခြင်း မရှိလျှင် Error ပြမည်
    if not DB_CHANNEL_ID:
        bot.reply_to(message, "❌ အက်ဒမင်.. DB_CHANNEL_ID ကို Environment Variable တွင် ထည့်သွင်းထားခြင်း မရှိသေးပါ။")
        return

    try:
        # Admin ပို့လိုက်သောဖိုင်ကို Database Channel သို့ Copy ကူးထည့်မည်
        copied_msg = bot.copy_message(DB_CHANNEL_ID, message.chat.id, message.message_id)
        db_message_id = copied_msg.message_id
    except Exception as e:
        bot.reply_to(message, f"❌ Database Channel သို့ ဖိုင်သိမ်းဆည်း၍ မရပါ။ Channel ID မှားယွင်းနေခြင်း (သို့) Bot ကို ထို Channel တွင် Admin မပေးထားခြင်းကြောင့် ဖြစ်နိုင်ပါသည်။\n\nError: {e}")
        return

    file_code = str(uuid.uuid4())[:8]
    
    # 🔴 File ID အစား Message ID ကို သိမ်းဆည်းပါမည်
    document_to_save = {
        "file_code": file_code,
        "message_id": db_message_id, 
        "uploader_id": message.from_user.id
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

print("Bot with Copy Message (Thumbnail Fix) is running...")
bot.polling(none_stop=True)
