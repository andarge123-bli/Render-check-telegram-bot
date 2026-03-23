import logging
import telebot
from telebot import types
import json
import os
import re
import time
import threading
from flask import Flask

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('BOT_TOKEN', 'xxxxxxxxxx')
OWNER_ID = 5392468999

GOOGLE_API_KEYS = [
    os.environ.get('GOOGLE_API_KEY_1', os.environ.get('GOOGLE_API_KEY', '')),
    os.environ.get('GOOGLE_API_KEY_2', ''),
    os.environ.get('GOOGLE_API_KEY_3', ''),
    os.environ.get('GOOGLE_API_KEY_4', ''),
    os.environ.get('GOOGLE_API_KEY_5', ''),
]
GOOGLE_API_KEYS = [k for k in GOOGLE_API_KEYS if k]

print(f"[STARTUP] GEMINI_AVAILABLE={GEMINI_AVAILABLE}")
print(f"[STARTUP] GOOGLE_API_KEYS count={len(GOOGLE_API_KEYS)}")
if not GEMINI_AVAILABLE:
    print("[STARTUP] ERROR: google-genai failed to import. Run: pip install google-genai")
if not GOOGLE_API_KEYS:
    print("[STARTUP] ERROR: No API keys found. Check GOOGLE_API_KEY_1 ... env vars on Render.")

_api_key_index = 0
_api_key_lock = threading.Lock()


def get_next_api_key():
    global _api_key_index
    with _api_key_lock:
        if not GOOGLE_API_KEYS:
            return None
        key = GOOGLE_API_KEYS[_api_key_index % len(GOOGLE_API_KEYS)]
        _api_key_index = (_api_key_index + 1) % len(GOOGLE_API_KEYS)
        return key


bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

DB_FILE = "database.json"
STATE_FILE = "user_choices.json"

ai_chat_histories = {}
ai_histories_lock = threading.Lock()

pending_reply_targets = {}
pending_reply_lock = threading.Lock()

FACULTIES = {
    "🔧 Engineering": [
        "💻 Software Engineering",
        "⚡ Electrical & Computer Engineering",
        "⚙️ Mechanical Engineering",
        "🏗️ Civil Engineering",
        "🖥️ Computer Science",
        "🌐 Information Technology",
        "🏭 Industrial Engineering",
        "💧 Water Resources & Irrigation Engineering",
        "🧱 Architecture",
        "⚗️ Chemical Engineering",
        "🌊 Hydraulics Engineering",
        "🌾 Agricultural Engineering",
        "🗄️ Information System",
    ],
    "🔬 Natural Sciences": [
        "⚛️ Physics",
        "🧪 Chemistry",
        "🧬 Biology",
        "📐 Mathematics",
        "📊 Statistics",
        "🌍 Geology",
        "🌿 Environmental Science",
        "🏃 Sport Science",
    ],
    "🏥 Health Sciences": [
        "💉 Nursing",
        "🩺 Medicine",
        "💊 Pharmacy",
        "🌡️ Public Health",
        "👶 Midwifery",
        "🔬 Medical Laboratory Science",
        "😴 Anesthesia",
        "🌱 Environmental Health",
    ],
    "🎓 Freshman": [],
    "🎯 Remedial": [],
}

SPECIAL_FACULTIES = {"Freshman", "Remedial"}
NO_SEMESTER_FACULTIES = {"Remedial"}

YEARS = ["📗 Year 1", "📘 Year 2", "📙 Year 3", "📕 Year 4", "📓 Year 5"]
YEAR_LABELS = ["Year1", "Year2", "Year3", "Year4", "Year5"]
SEMESTERS = [("📙 Semester 1", "Sem1"), ("📗 Semester 2", "Sem2")]

ALLOWED_EXTENSIONS = {".pdf", ".ppt", ".pptx", ".doc", ".docx"}
MAX_FILE_SIZE = 20 * 1024 * 1024

MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

DIVIDER = "━" * 20
STARS_MAP = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}

IDENTITY_KEYWORDS = [
    "who made you", "who are you", "who created you", "who built you",
    "who developed you", "your creator", "your developer", "your maker",
    "are you gemini", "are you chatgpt", "are you openai", "are you google",
    "what are you", "tell me about yourself", "introduce yourself",
    "who is your creator", "your origin", "who owns you",
    "ማን ሰራህ", "ማን ነህ", "ማን ፈጠርህ",
]

IDENTITY_RESPONSE_EN = (
    "🤖 *I am mtu.ai*\n"
    f"{DIVIDER}\n"
    "I was developed by *Andarge Girma*.\n\n"
    "If you wish to reach my creator, tap the\n"
    "💬 *Contact* button to speak with them directly."
)

IDENTITY_RESPONSE_AM = (
    "🤖 *እኔ mtu.ai ነኝ*\n"
    f"{DIVIDER}\n"
    "እኔ የተሰራሁት በ *አንዳርጌ ጊርማ* ነው።\n\n"
    "ፈጣሪዬን ለማግኘት\n"
    "💬 *ያግኙ* ቁልፍን ይጫኑ።"
)

MTU_WELCOME_EN = (
    "🤖 *mtu.ai — Your Smart Study Assistant*\n"
    f"{DIVIDER}\n"
    "Ask me anything academic!\n\n"
    "📚 Study tips\n"
    "🔬 Science questions\n"
    "📐 Math problems\n"
    "💡 General knowledge\n"
    f"{DIVIDER}\n"
    "Type your question below 👇\n"
    "_(tap *Exit Chat* when done)_"
)

MTU_WELCOME_AM = (
    "🤖 *mtu.ai — ብልህ የጥናት ረዳትዎ*\n"
    f"{DIVIDER}\n"
    "ማንኛውንም ጥያቄ ይጠይቁ!\n\n"
    "📚 የጥናት ምክሮች\n"
    "🔬 የሳይንስ ጥያቄዎች\n"
    "📐 የሒሳብ ችግሮች\n"
    "💡 አጠቃላይ እውቀት\n"
    f"{DIVIDER}\n"
    "ጥያቄዎን ከዚህ ይጻፉ 👇\n"
    "_(ሲጨርሱ *ውይይት አቁም* ይጫኑ)_"
)

AI_SYSTEM_PROMPT = (
    "You are mtu.ai, a smart academic assistant for university students in Ethiopia. "
    "Help students with their studies, explain concepts clearly, and give practical advice. "
    "Format your responses beautifully for Telegram using: "
    "• Bullet points for lists, "
    "*bold* for key terms, "
    "numbered steps for procedures, "
    "and keep responses concise and mobile-friendly (under 400 words). "
    "Never reveal that you are Gemini or any Google product. "
    "If asked about your identity, you are mtu.ai developed by Andarge Girma."
)

if GEMINI_AVAILABLE and GOOGLE_API_KEYS:
    logger.info("Gemini AI ready with %d API key(s) for rotation ✅", len(GOOGLE_API_KEYS))
else:
    logger.warning("Gemini AI not available — missing library or API keys")

TEXTS = {
    "en": {
        "welcome": (
            "🎓 *Uni Book Sharing Bot*\n"
            f"{DIVIDER}\n"
            "📚 Share · Discover · Learn\n"
            "🤝 By students, for students\n"
            f"{DIVIDER}\n"
            "🌍 *Pick your language:*"
        ),
        "main_menu": "🏠 *Main Menu* — choose below 👇",
        "browse": "📥 Download Center",
        "upload": "📤 Upload",
        "leaderboard": "🏆 Leaderboard",
        "help": "❓ Help",
        "contact": "💬 Contact",
        "mtu_ai": "🤖 mtu.ai",
        "select_faculty": "🏫 *[1] Pick Category* 👇",
        "select_department": "📂 *[2] Pick Department* 👇",
        "select_year": "📅 *[3] Pick Year* 👇",
        "select_semester": "📖 *Pick Semester* 👇",
        "no_books": (
            "📭 *Empty Category*\n"
            f"{DIVIDER}\n"
            "No books here yet.\n"
            "💡 Be the first to upload! 🌟"
        ),
        "books_list": "📚 *Books Available* — tap to download 👇",
        "download_success": (
            "✅ *File sent!* Good luck! 📖\n"
            f"{DIVIDER}\n"
            "⭐ *Rate this book:*"
        ),
        "already_voted": "⚠️ You already rated this book.",
        "vote_recorded": "🎉 *Rating saved!* Thanks! 💪",
        "upload_select_location": (
            "📤 *Upload*\n"
            f"{DIVIDER}\n"
            "Select where to place the book:\n"
            "Category → Dept → Year → Semester"
        ),
        "upload_prompt": (
            "📎 *Send your file now!*\n"
            f"{DIVIDER}\n"
            "✅ `PDF · PPT · PPTX · DOC · DOCX`\n"
            "📏 Max: `20 MB`"
        ),
        "upload_success": (
            "🎊 *Uploaded!* Thank you! 🌟\n"
            "You earned +1 upload badge 📛"
        ),
        "upload_duplicate": "⚠️ *Duplicate* — file already exists here.",
        "upload_invalid_type": (
            "❌ *Wrong file type*\n"
            "Use: `PDF · PPT · PPTX · DOC · DOCX`"
        ),
        "upload_too_large": "❌ *Too large* — max is *20 MB*.",
        "upload_error": "❌ Upload failed. Try again.",
        "leaderboard_title": "🏆 *Top Contributors* 💪\n" + f"{DIVIDER}\n\n",
        "leaderboard_empty": (
            "🏆 *Leaderboard*\n"
            f"{DIVIDER}\n"
            "No one yet!\n"
            "📤 Upload and claim 🥇!"
        ),
        "help_text": (
            "❓ *Help*\n"
            f"{DIVIDER}\n"
            "📥 *Download Center* → Category › Dept › Year › Semester\n"
            "📤 *Upload* → share PDF/PPT/DOC (20MB max)\n"
            "⭐ *Rate* → after downloading\n"
            "🤖 *mtu.ai* → AI study assistant\n"
            "🏆 *Leaderboard* → top uploaders\n"
            "💬 *Contact* → message the owner\n"
            "🔍 */search* → find any book\n"
            f"{DIVIDER}\n"
            "💡 More uploads = higher rank! 🚀"
        ),
        "contact_prompt": (
            "💬 *Contact Owner*\n"
            f"{DIVIDER}\n"
            "Type your message 👇\n"
            "_(name & ID auto-included)_"
        ),
        "contact_sent": "✅ *Sent!* Owner will reply soon 😊",
        "contact_error": "❌ Failed to send. Try again.",
        "back": "⬅️ Back",
        "main_menu_btn": "🏠 Menu",
        "exit_chat": "🚪 Exit Chat",
        "rate_1": "1⭐", "rate_2": "2⭐", "rate_3": "3⭐",
        "rate_4": "4⭐", "rate_5": "5⭐",
        "books": "📚", "stars": "⭐",
        "search_prompt": (
            "🔍 *Search*\n"
            f"{DIVIDER}\n"
            "Type a book name or keyword 👇"
        ),
        "search_results": "🔍 *Results* — tap to download 👇",
        "search_no_results": "🔍 *Nothing found*\nTry a shorter word or browse 📚",
        "not_admin": "⛔ Not authorized.",
        "spam_warning": "⏳ Wait before uploading again.",
        "uploading": "⏳ *Saving...* please wait!",
        "file_not_found": "❌ File not found or removed.",
        "ai_thinking": "🤖 *mtu.ai is thinking...*",
        "ai_error": "⚠️ AI is unavailable right now. Try again later.",
        "ai_no_key": "⚠️ AI feature is not configured yet.",
    },
    "am": {
        "welcome": (
            "🎓 *ዩኒ መጽሐፍ መካፈያ ቦት*\n"
            f"{DIVIDER}\n"
            "📚 ያጋሩ · ያግኙ · ይማሩ\n"
            "🤝 በተማሪዎች ለተማሪዎች\n"
            f"{DIVIDER}\n"
            "🌍 *ቋንቋ ይምረጡ:*"
        ),
        "main_menu": "🏠 *ዋና ምናሌ* — ይምረጡ 👇",
        "browse": "📥 ማውረጃ ማዕከል",
        "upload": "📤 ያስቀምጡ",
        "leaderboard": "🏆 ሰንጠረዥ",
        "help": "❓ እርዳታ",
        "contact": "💬 ያግኙ",
        "mtu_ai": "🤖 mtu.ai",
        "select_faculty": "🏫 *[1] ምድብ ይምረጡ* 👇",
        "select_department": "📂 *[2] ዲፓርትመንት ይምረጡ* 👇",
        "select_year": "📅 *[3] ዓመት ይምረጡ* 👇",
        "select_semester": "📖 *ሴሚስተር ይምረጡ* 👇",
        "no_books": (
            "📭 *ምንም የለም*\n"
            f"{DIVIDER}\n"
            "ይህ ምድብ ባዶ ነው።\n"
            "💡 ቀዳሚ ሁኑ! 🌟"
        ),
        "books_list": "📚 *መጽሐፍት* — ለማውረድ ይጫኑ 👇",
        "download_success": (
            "✅ *ፋይሉ ደረሰ!* ጥናትዎ ይሳካ! 📖\n"
            f"{DIVIDER}\n"
            "⭐ *ምዘና ይስጡ:*"
        ),
        "already_voted": "⚠️ ቀድሞ ምዘና ሰጥተዋል።",
        "vote_recorded": "🎉 *ምዘናዎ ተቀበልን!* አመሰግናለሁ! 💪",
        "upload_select_location": (
            "📤 *ያስቀምጡ*\n"
            f"{DIVIDER}\n"
            "ቦታ ይምረጡ:\n"
            "ምድብ → ዲፓ → ዓመት → ሴሚስተር"
        ),
        "upload_prompt": (
            "📎 *ፋይሉን ይላኩ!*\n"
            f"{DIVIDER}\n"
            "✅ `PDF · PPT · PPTX · DOC · DOCX`\n"
            "📏 ከፍ: `20 MB`"
        ),
        "upload_success": (
            "🎊 *ተጭኗል!* አመሰግናለሁ! 🌟\n"
            "+1 ስኬት አግኝተዋል! 📛"
        ),
        "upload_duplicate": "⚠️ *ተደጋጋሚ* — ፋይሉ ቀድሞ አለ።",
        "upload_invalid_type": (
            "❌ *ልክ ያልሆነ*\n"
            "`PDF · PPT · PPTX · DOC · DOCX` ብቻ"
        ),
        "upload_too_large": "❌ *ትልቅ ነው* — ከፍ: *20 MB*",
        "upload_error": "❌ አልተሳካም። ድጋሚ ሞክሩ።",
        "leaderboard_title": "🏆 *ምርጥ አስተዋጽዖ አድራጊዎች* 💪\n" + f"{DIVIDER}\n\n",
        "leaderboard_empty": (
            "🏆 *ሰንጠረዥ*\n"
            f"{DIVIDER}\n"
            "ማንም እስካሁን የለም!\n"
            "📤 ያስቀምጡ እና 🥇 ያሸንፉ!"
        ),
        "help_text": (
            "❓ *እርዳታ*\n"
            f"{DIVIDER}\n"
            "📥 *ማውረጃ ማዕከል* → ምድብ › ዲፓ › ዓመት › ሴሚ\n"
            "📤 *ያስቀምጡ* → PDF/PPT/DOC (20MB)\n"
            "⭐ *ምዘና* → ካወረዱ በኋላ\n"
            "🤖 *mtu.ai* → ብልህ የጥናት ረዳት\n"
            "🏆 *ሰንጠረዥ* → ምርጥ አስተዋጽዖ\n"
            "💬 *ያግኙ* → ለባለቤቱ\n"
            "🔍 */search* → ፋይል ይፈልጉ\n"
            f"{DIVIDER}\n"
            "💡 ብዙ ያስቀምጡ = ሰፊ ደረጃ! 🚀"
        ),
        "contact_prompt": (
            "💬 *ባለቤቱን ያግኙ*\n"
            f"{DIVIDER}\n"
            "መልዕክትዎን ይጻፉ 👇\n"
            "_(ስምዎ ራስ-ሰር ይካተታል)_"
        ),
        "contact_sent": "✅ *ተልኳል!* ብዙ ሳይቆይ ይደርስዎታል 😊",
        "contact_error": "❌ አልተሳካም። ድጋሚ ሞክሩ።",
        "back": "⬅️ ተመለስ",
        "main_menu_btn": "🏠 ምናሌ",
        "exit_chat": "🚪 ውይይት አቁም",
        "rate_1": "1⭐", "rate_2": "2⭐", "rate_3": "3⭐",
        "rate_4": "4⭐", "rate_5": "5⭐",
        "books": "📚", "stars": "⭐",
        "search_prompt": (
            "🔍 *ፍለጋ*\n"
            f"{DIVIDER}\n"
            "የመጽሐፍ ስም ወይም ቃል ይጻፉ 👇"
        ),
        "search_results": "🔍 *ውጤቶች* — ለማውረድ ይጫኑ 👇",
        "search_no_results": "🔍 *ምንም አልተገኘም*\nአጭር ቃል ሞክሩ ወይም ፈልጉ 📚",
        "not_admin": "⛔ ፈቃድ የለዎትም።",
        "spam_warning": "⏳ ትንሽ ይጠብቁ።",
        "uploading": "⏳ *እየተቀመጠ ነው...* ይጠብቁ!",
        "file_not_found": "❌ ፋይሉ አልተገኘም።",
        "ai_thinking": "🤖 *mtu.ai እያሰበ ነው...*",
        "ai_error": "⚠️ AI አሁን አይሰራም። ቆይቶ ሞክሩ።",
        "ai_no_key": "⚠️ AI ባህሪ አልተዋቀረም።",
    },
}

UPLOAD_COOLDOWN = 60
last_upload_time = {}


def load_db():
    if not os.path.exists(DB_FILE):
        data = {"books": [], "users": {}}
        save_db(data)
        return data
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_states():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_states(states):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(states, f, ensure_ascii=False, indent=2)


def get_state(user_id):
    return load_states().get(str(user_id), {})


def set_state(user_id, state_data):
    states = load_states()
    states[str(user_id)] = state_data
    save_states(states)


def clear_state(user_id):
    states = load_states()
    states.pop(str(user_id), None)
    save_states(states)


def get_lang(user_id):
    return get_state(user_id).get("lang", "en")


def t(user_id, key):
    lang = get_lang(user_id)
    return TEXTS.get(lang, TEXTS["en"]).get(key, key)


def get_user_info(db, user_id):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {"uploaded_books": 0, "stars_received": 0, "name": ""}
    return db["users"][uid]


def clean_filename(name):
    name = name.lower()
    name = re.sub(r"[^\w.\-]", "_", name)
    name = re.sub(r"_+", "_", name)
    return name


def strip_emoji(text):
    return re.sub(
        r"^[\U00010000-\U0010ffff\u2600-\u26FF\u2700-\u27BF\U0001F300-\U0001F9FF\s]+",
        "", text
    ).strip()


def is_special_faculty(faculty):
    return strip_emoji(faculty) in SPECIAL_FACULTIES


def is_no_semester_faculty(faculty):
    return strip_emoji(faculty) in NO_SEMESTER_FACULTIES


def remove_inline_keyboard(chat_id, message_id):
    try:
        bot.edit_message_reply_markup(
            chat_id, message_id, reply_markup=types.InlineKeyboardMarkup()
        )
    except Exception:
        pass


def is_identity_question(text):
    text_lower = text.lower()
    return any(kw in text_lower for kw in IDENTITY_KEYWORDS)


def format_ai_response(text):
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^[\-\*]\s+", "• ", text, flags=re.MULTILINE)
    text = re.sub(r"_(.+?)_", r"_\1_", text)
    if len(text) > 3500:
        text = text[:3497] + "..."
    return text.strip()


def ai_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(types.KeyboardButton(t(user_id, "exit_chat")))
    return markup


def main_menu_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.row(
        types.KeyboardButton(t(user_id, "browse")),
        types.KeyboardButton(t(user_id, "upload")),
    )
    markup.row(
        types.KeyboardButton(t(user_id, "leaderboard")),
        types.KeyboardButton(t(user_id, "help")),
    )
    markup.row(
        types.KeyboardButton(t(user_id, "contact")),
        types.KeyboardButton(t(user_id, "mtu_ai")),
    )
    return markup


def language_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🇬🇧  English", callback_data="lang_en"),
        types.InlineKeyboardButton("🇪🇹  አማርኛ", callback_data="lang_am"),
    )
    return markup


def faculty_keyboard(user_id, prefix="browse"):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for faculty in FACULTIES:
        markup.add(
            types.InlineKeyboardButton(
                faculty,
                callback_data=f"{prefix}_fac_{strip_emoji(faculty)[:18]}",
            )
        )
    markup.add(
        types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu")
    )
    return markup


def department_keyboard(user_id, faculty, prefix="browse"):
    markup = types.InlineKeyboardMarkup(row_width=1)
    fac_key = strip_emoji(faculty)[:14]
    for dept in FACULTIES.get(faculty, []):
        dept_key = strip_emoji(dept)[:14]
        markup.add(
            types.InlineKeyboardButton(
                dept, callback_data=f"{prefix}_dep_{fac_key}|{dept_key}"
            )
        )
    markup.add(
        types.InlineKeyboardButton(t(user_id, "back"), callback_data=f"{prefix}_bk_fac")
    )
    return markup


def year_keyboard(user_id, faculty, dept, prefix="browse"):
    markup = types.InlineKeyboardMarkup(row_width=3)
    fac_key = strip_emoji(faculty)[:14]
    dept_key = strip_emoji(dept)[:14]
    buttons = [
        types.InlineKeyboardButton(
            label, callback_data=f"{prefix}_yr_{fac_key}|{dept_key}|{yr}"
        )
        for label, yr in zip(YEARS, YEAR_LABELS)
    ]
    markup.add(*buttons)
    markup.add(
        types.InlineKeyboardButton(
            t(user_id, "back"), callback_data=f"{prefix}_bk_dep_{fac_key}"
        )
    )
    return markup


def semester_keyboard(user_id, faculty, dept, year, prefix="browse"):
    markup = types.InlineKeyboardMarkup(row_width=2)
    fac_key = strip_emoji(faculty)[:14]
    dept_key = strip_emoji(dept)[:12] if dept else ""
    yr_key = year if year else "direct"
    markup.row(
        types.InlineKeyboardButton(
            "📙 Semester 1",
            callback_data=f"{prefix}_s_{fac_key}|{dept_key}|{yr_key}|Sem1",
        ),
        types.InlineKeyboardButton(
            "📗 Semester 2",
            callback_data=f"{prefix}_s_{fac_key}|{dept_key}|{yr_key}|Sem2",
        ),
    )
    if dept:
        back_cb = f"{prefix}_bk_yr_{fac_key}|{dept_key}"
    else:
        back_cb = f"{prefix}_bk_fac"
    markup.add(
        types.InlineKeyboardButton(t(user_id, "back"), callback_data=back_cb)
    )
    return markup


def books_keyboard(user_id, books, faculty, dept, year, semester):
    markup = types.InlineKeyboardMarkup(row_width=1)
    fac_key = strip_emoji(faculty)[:12]
    dept_key = strip_emoji(dept)[:10] if dept else ""
    yr_key = year if year else "direct"
    icons = ["📗", "📘", "📙", "📕", "📓", "📔", "📒", "📃", "📄", "📑"]
    for idx, book in enumerate(books):
        stars = book.get("stars", 0)
        voters = len(book.get("voters", []))
        icon = icons[idx % len(icons)]
        avg = round(stars / voters) if voters > 0 else 0
        star_display = "⭐" * avg if avg > 0 else "☆"
        name = book["file_name"].replace("_", " ").title()[:22]
        label = f"{icon} {name} {star_display}"
        markup.add(
            types.InlineKeyboardButton(
                label,
                callback_data=f"dl_{idx}_{fac_key}|{dept_key}|{yr_key}|{semester}",
            )
        )
    if is_no_semester_faculty(faculty):
        back_cb = "browse_bk_fac"
    else:
        back_cb = f"browse_bk_sem_{fac_key}|{dept_key}|{yr_key}"
    markup.row(
        types.InlineKeyboardButton(t(user_id, "back"), callback_data=back_cb),
        types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu"),
    )
    return markup


def rating_keyboard(user_id, book_idx, fac_key, dept_key, yr_key, semester):
    markup = types.InlineKeyboardMarkup(row_width=5)
    buttons = [
        types.InlineKeyboardButton(
            t(user_id, f"rate_{i}"),
            callback_data=f"rt_{i}_{book_idx}_{fac_key}|{dept_key}|{yr_key}|{semester}",
        )
        for i in range(1, 6)
    ]
    markup.add(*buttons)
    markup.row(types.InlineKeyboardButton("⏭️ Skip", callback_data="main_menu"))
    return markup


def find_faculty_by_key(fac_key):
    for faculty in FACULTIES:
        clean = strip_emoji(faculty)
        if clean[:len(fac_key)] == fac_key or fac_key in clean:
            return faculty
    return None


def find_faculty_dept_by_key(fac_key, dept_key):
    for faculty, depts in FACULTIES.items():
        clean_fac = strip_emoji(faculty)
        if clean_fac[:len(fac_key)] == fac_key or fac_key in clean_fac:
            if not dept_key:
                return faculty, ""
            for dept in depts:
                clean_dept = strip_emoji(dept)
                if clean_dept[:len(dept_key)] == dept_key or dept_key in clean_dept:
                    return faculty, dept
    return None, None


def get_books_for(faculty, dept, year, semester):
    db = load_db()
    fac_clean = strip_emoji(faculty)
    dept_clean = strip_emoji(dept) if dept else ""
    no_sem = is_no_semester_faculty(faculty)
    result = []
    for b in db["books"]:
        b_fac = strip_emoji(b.get("faculty", ""))
        b_dept = strip_emoji(b.get("department", ""))
        b_yr = b.get("year", "")
        b_sem = b.get("semester", "")
        fac_match = b_fac == fac_clean
        dept_match = b_dept == dept_clean
        yr_match = b_yr == year
        sem_match = no_sem or (b_sem == semester)
        if fac_match and dept_match and yr_match and sem_match:
            result.append(b)
    return result


@bot.message_handler(commands=["start"])
def cmd_start(message):
    user_id = message.from_user.id
    clear_state(user_id)
    bot.send_message(
        user_id,
        TEXTS["en"]["welcome"],
        reply_markup=language_keyboard(),
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["aicheck"])
def cmd_aicheck(message):
    user_id = message.from_user.id
    if user_id != OWNER_ID:
        return
    status = (
        f"🔍 AI Diagnostic\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📦 Package loaded: {'✅ Yes (google-genai)' if GEMINI_AVAILABLE else '❌ No (import failed)'}\n"
        f"🔑 Keys detected: {'✅ ' + str(len(GOOGLE_API_KEYS)) if GOOGLE_API_KEYS else '❌ 0 (none found)'}\n"
    )
    bot.send_message(user_id, status)

    if not GEMINI_AVAILABLE or not GOOGLE_API_KEYS:
        return

    bot.send_message(user_id, "⏳ Listing available models on your API key...")
    api_key = GOOGLE_API_KEYS[0]
    try:
        client = genai.Client(api_key=api_key)
        models = client.models.list()
        names = [m.name for m in models if "generateContent" in (m.supported_actions or [])]
        if names:
            model_list = "\n".join(names[:20])
            bot.send_message(user_id, f"✅ Available models:\n```\n{model_list}\n```", parse_mode="Markdown")
        else:
            all_names = [m.name for m in models][:20]
            bot.send_message(user_id, f"⚠️ No generateContent models found.\nAll models:\n```\n{chr(10).join(all_names)}\n```", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(user_id, f"❌ Failed to list models!\nError:\n`{str(e)[:500]}`", parse_mode="Markdown")


@bot.message_handler(commands=["admin6843"])
def cmd_admin(message):
    user_id = message.from_user.id
    if user_id != OWNER_ID:
        bot.send_message(user_id, t(user_id, "not_admin"))
        return
    db = load_db()
    text = (
        f"🔧 *Admin Panel*\n"
        f"{DIVIDER}\n"
        f"📚 Total Books: *{len(db['books'])}*\n"
        f"👤 Total Users: *{len(db['users'])}*\n"
        f"🔑 Active Gemini Keys: *{len(GOOGLE_API_KEYS)}*\n"
        f"{DIVIDER}"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📋 Books", callback_data="admin_list_books"),
        types.InlineKeyboardButton("👥 Users", callback_data="admin_list_users"),
    )
    markup.add(
        types.InlineKeyboardButton("🗑️ Delete Book", callback_data="admin_delete_prompt"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast_prompt"),
    )
    markup.add(
        types.InlineKeyboardButton("✉️ Direct Message", callback_data="admin_dm_prompt"),
    )
    bot.send_message(user_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(commands=["search"])
def cmd_search(message):
    user_id = message.from_user.id
    state = get_state(user_id)
    state["action"] = "search"
    set_state(user_id, state)
    bot.send_message(user_id, t(user_id, "search_prompt"), parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("lang_"))
def cb_language(call):
    user_id = call.from_user.id
    lang = call.data.split("_")[1]
    state = get_state(user_id)
    state["lang"] = lang
    state["action"] = None
    set_state(user_id, state)
    db = load_db()
    user_info = get_user_info(db, user_id)
    fname = call.from_user.first_name or ""
    lname = call.from_user.last_name or ""
    user_info["name"] = (fname + " " + lname).strip() or str(user_id)
    save_db(db)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    welcome_name = (fname + " " + lname).strip() or "there"
    greet = f"👋 *Hello, {welcome_name}!*\n" if lang == "en" else f"👋 *ሰላም, {welcome_name}!*\n"
    bot.send_message(
        user_id,
        greet + t(user_id, "main_menu"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def cb_main_menu(call):
    user_id = call.from_user.id
    state = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "main_menu"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda msg: True, content_types=["text"])
def handle_text(message):
    user_id = message.from_user.id
    text = message.text.strip()
    state = get_state(user_id)

    if user_id == OWNER_ID:
        with pending_reply_lock:
            target_user_id = pending_reply_targets.get(OWNER_ID)
        if target_user_id and state.get("action") == "admin_reply":
            send_owner_reply(message, target_user_id)
            return

        if state.get("action") == "admin_broadcast":
            do_broadcast(message)
            return

        if state.get("action") == "admin_dm_target":
            handle_admin_dm_target(message)
            return

        if state.get("action") == "admin_dm_message":
            handle_admin_dm_message(message)
            return

    if state.get("action") == "ai_chat":
        if text == t(user_id, "exit_chat"):
            with ai_histories_lock:
                ai_chat_histories.pop(user_id, None)
            state["action"] = None
            set_state(user_id, state)
            bot.send_message(
                user_id,
                t(user_id, "main_menu"),
                reply_markup=main_menu_keyboard(user_id),
                parse_mode="Markdown",
            )
        else:
            handle_ai_message(message)
        return

    if state.get("action") == "contact":
        send_contact_message(message)
        return
    if state.get("action") == "search":
        handle_search(message)
        return
    if state.get("action") == "admin_delete":
        handle_admin_delete(message)
        return

    if text == t(user_id, "browse"):
        state["action"] = "browse"
        set_state(user_id, state)
        bot.send_message(
            user_id,
            t(user_id, "select_faculty"),
            reply_markup=faculty_keyboard(user_id, prefix="browse"),
            parse_mode="Markdown",
        )
    elif text == t(user_id, "upload"):
        state["action"] = "upload"
        set_state(user_id, state)
        bot.send_message(
            user_id,
            t(user_id, "upload_select_location"),
            reply_markup=faculty_keyboard(user_id, prefix="upload"),
            parse_mode="Markdown",
        )
    elif text == t(user_id, "leaderboard"):
        show_leaderboard(user_id)
    elif text == t(user_id, "help"):
        show_help(user_id)
    elif text == t(user_id, "contact"):
        state["action"] = "contact"
        set_state(user_id, state)
        bot.send_message(user_id, t(user_id, "contact_prompt"), parse_mode="Markdown")
    elif text == t(user_id, "mtu_ai"):
        with ai_histories_lock:
            ai_chat_histories.pop(user_id, None)
        state["action"] = "ai_chat"
        set_state(user_id, state)
        welcome = MTU_WELCOME_EN if get_lang(user_id) == "en" else MTU_WELCOME_AM
        bot.send_message(
            user_id,
            welcome,
            reply_markup=ai_keyboard(user_id),
            parse_mode="Markdown",
        )
    else:
        bot.send_message(
            user_id,
            t(user_id, "main_menu"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )


def handle_ai_message(message):
    user_id = message.from_user.id
    user_text = message.text.strip()
    lang = get_lang(user_id)

    if is_identity_question(user_text):
        response = IDENTITY_RESPONSE_EN if lang == "en" else IDENTITY_RESPONSE_AM
        bot.send_message(user_id, response, parse_mode="Markdown")
        return

    if not GEMINI_AVAILABLE or not GOOGLE_API_KEYS:
        bot.send_message(user_id, t(user_id, "ai_no_key"))
        return

    thinking_msg = bot.send_message(
        user_id, t(user_id, "ai_thinking"), parse_mode="Markdown"
    )

    with ai_histories_lock:
        if user_id not in ai_chat_histories:
            ai_chat_histories[user_id] = []
        history = list(ai_chat_histories[user_id])

    prompt = user_text
    if lang == "am":
        prompt = f"Please respond in Amharic (አማርኛ). Question: {user_text}"

    last_error = None
    keys_tried = 0
    total_keys = len(GOOGLE_API_KEYS)

    while keys_tried < total_keys:
        api_key = get_next_api_key()
        keys_tried += 1
        try:
            client = genai.Client(api_key=api_key, http_options={"api_version": "v1"})

            genai_history = []
            for entry in history:
                role = entry.get("role", "user")
                parts_text = entry.get("parts", [""])
                if isinstance(parts_text, list):
                    content_text = parts_text[0] if parts_text else ""
                else:
                    content_text = str(parts_text)
                genai_history.append(
                    genai_types.Content(
                        role=role,
                        parts=[genai_types.Part(text=content_text)]
                    )
                )

            chat = client.chats.create(
                model="gemini-1.5-flash",
                config=genai_types.GenerateContentConfig(
                    system_instruction=AI_SYSTEM_PROMPT,
                ),
                history=genai_history,
            )

            response = chat.send_message(prompt)
            raw = response.text or ""
            formatted = format_ai_response(raw)

            with ai_histories_lock:
                if user_id not in ai_chat_histories:
                    ai_chat_histories[user_id] = []
                ai_chat_histories[user_id].append({"role": "user", "parts": [prompt]})
                ai_chat_histories[user_id].append({"role": "model", "parts": [raw]})
                if len(ai_chat_histories[user_id]) > 40:
                    ai_chat_histories[user_id] = ai_chat_histories[user_id][-40:]

            try:
                bot.delete_message(user_id, thinking_msg.message_id)
            except Exception:
                pass
            header = "🤖 *mtu.ai*\n" + DIVIDER + "\n"
            try:
                bot.send_message(user_id, header + formatted, parse_mode="Markdown")
            except Exception:
                bot.send_message(user_id, header + raw[:3500])
            return

        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if "quota" in err_str or "rate" in err_str or "429" in err_str or "resource" in err_str:
                logger.warning("Key quota hit, rotating to next key. Error: %s", e)
                continue
            else:
                logger.error("AI error (non-quota): %s", e)
                break

    logger.error("All AI keys exhausted or non-recoverable error: %s", last_error)
    try:
        bot.delete_message(user_id, thinking_msg.message_id)
    except Exception:
        pass
    bot.send_message(user_id, t(user_id, "ai_error"))


def show_leaderboard(user_id):
    db = load_db()
    sorted_users = sorted(
        db.get("users", {}).items(),
        key=lambda x: x[1].get("stars_received", 0),
        reverse=True,
    )
    if not sorted_users:
        bot.send_message(
            user_id,
            t(user_id, "leaderboard_empty"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return
    text = t(user_id, "leaderboard_title")
    for i, (uid, info) in enumerate(sorted_users[:10]):
        medal = MEDALS[i]
        name = (info.get("name", uid) or uid)[:16]
        books_count = info.get("uploaded_books", 0)
        stars = info.get("stars_received", 0)
        text += f"{medal} *{name}*  {t(user_id, 'books')}{books_count} {t(user_id, 'stars')}{stars}\n"
    text += f"\n{DIVIDER}"
    bot.send_message(
        user_id, text, reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown"
    )


def show_help(user_id):
    bot.send_message(
        user_id,
        t(user_id, "help_text"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )


def send_contact_message(message):
    user_id = message.from_user.id
    db = load_db()
    name = get_user_info(db, user_id).get("name", str(user_id))
    text = (
        f"📨 *New Message from Student*\n"
        f"{DIVIDER}\n"
        f"👤 *{name}*\n"
        f"🆔 `{user_id}`\n"
        f"{DIVIDER}\n"
        f"💬 {message.text}\n"
        f"{DIVIDER}\n"
        f"_Reply to this message to send a reply back to the student._"
    )
    state = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    try:
        sent = bot.send_message(OWNER_ID, text, parse_mode="Markdown")
        with pending_reply_lock:
            pending_reply_targets[sent.message_id] = user_id
        bot.send_message(
            user_id,
            t(user_id, "contact_sent"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Contact forward failed: %s", e)
        bot.send_message(
            user_id, t(user_id, "contact_error"), reply_markup=main_menu_keyboard(user_id)
        )


@bot.message_handler(
    func=lambda msg: msg.from_user.id == OWNER_ID and msg.reply_to_message is not None,
    content_types=["text"]
)
def handle_owner_reply(message):
    replied_to_msg_id = message.reply_to_message.message_id
    with pending_reply_lock:
        target_user_id = pending_reply_targets.get(replied_to_msg_id)

    if not target_user_id:
        return

    try:
        reply_text = (
            f"📩 *Reply from Owner*\n"
            f"{DIVIDER}\n"
            f"{message.text}"
        )
        bot.send_message(target_user_id, reply_text, parse_mode="Markdown")
        bot.send_message(
            OWNER_ID,
            f"✅ *Reply sent* to user `{target_user_id}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Failed to forward owner reply: %s", e)
        bot.send_message(OWNER_ID, f"❌ Failed to send reply: {e}")


def send_owner_reply(message, target_user_id):
    state = get_state(OWNER_ID)
    state["action"] = None
    state.pop("dm_target", None)
    set_state(OWNER_ID, state)
    with pending_reply_lock:
        pending_reply_targets.pop(OWNER_ID, None)

    try:
        reply_text = (
            f"📩 *Reply from Owner*\n"
            f"{DIVIDER}\n"
            f"{message.text}"
        )
        bot.send_message(target_user_id, reply_text, parse_mode="Markdown")
        bot.send_message(
            OWNER_ID,
            f"✅ *Reply sent* to user `{target_user_id}`",
            reply_markup=main_menu_keyboard(OWNER_ID),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Failed to send owner reply: %s", e)
        bot.send_message(OWNER_ID, f"❌ Failed to send reply: {e}")


def do_broadcast(message):
    state = get_state(OWNER_ID)
    state["action"] = None
    set_state(OWNER_ID, state)
    db = load_db()
    user_ids = list(db.get("users", {}).keys())
    broadcast_text = (
        f"📢 *Announcement*\n"
        f"{DIVIDER}\n"
        f"{message.text}"
    )
    success = 0
    failed = 0
    for uid_str in user_ids:
        try:
            bot.send_message(int(uid_str), broadcast_text, parse_mode="Markdown")
            success += 1
            time.sleep(0.05)
        except Exception as e:
            logger.warning("Broadcast failed for %s: %s", uid_str, e)
            failed += 1
    bot.send_message(
        OWNER_ID,
        f"📢 *Broadcast Done*\n"
        f"{DIVIDER}\n"
        f"✅ Sent: *{success}*\n"
        f"❌ Failed: *{failed}*",
        reply_markup=main_menu_keyboard(OWNER_ID),
        parse_mode="Markdown",
    )


def handle_admin_dm_target(message):
    state = get_state(OWNER_ID)
    target_id_str = message.text.strip()
    try:
        target_id = int(target_id_str)
    except ValueError:
        bot.send_message(OWNER_ID, "❌ Invalid user ID. Please send a valid numeric ID.")
        return
    state["action"] = "admin_dm_message"
    state["dm_target"] = target_id
    set_state(OWNER_ID, state)
    bot.send_message(
        OWNER_ID,
        f"✉️ *Direct Message*\n"
        f"{DIVIDER}\n"
        f"Target: `{target_id}`\n\n"
        f"Now type the message to send to this user:",
        parse_mode="Markdown",
    )


def handle_admin_dm_message(message):
    state = get_state(OWNER_ID)
    target_id = state.get("dm_target")
    state["action"] = None
    state.pop("dm_target", None)
    set_state(OWNER_ID, state)

    if not target_id:
        bot.send_message(OWNER_ID, "❌ No target user set. Please try again.")
        return

    try:
        dm_text = (
            f"📩 *Message from Owner*\n"
            f"{DIVIDER}\n"
            f"{message.text}"
        )
        bot.send_message(int(target_id), dm_text, parse_mode="Markdown")
        bot.send_message(
            OWNER_ID,
            f"✅ *Message sent* to `{target_id}`",
            reply_markup=main_menu_keyboard(OWNER_ID),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("DM failed: %s", e)
        bot.send_message(OWNER_ID, f"❌ Failed to send message: {e}")


def handle_search(message):
    user_id = message.from_user.id
    query = message.text.strip().lower()
    db = load_db()
    results = [b for b in db["books"] if query in b["file_name"].lower()]
    state = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)
    if not results:
        bot.send_message(
            user_id,
            t(user_id, "search_no_results"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    icons = ["📗", "📘", "📙", "📕", "📓", "📔", "📒", "📃", "📄", "📑",
             "📗", "📘", "📙", "📕", "📓"]
    for i, book in enumerate(results[:15]):
        stars = book.get("stars", 0)
        voters = len(book.get("voters", []))
        avg = round(stars / voters) if voters > 0 else 0
        star_str = "⭐" * avg if avg > 0 else "☆"
        name = book["file_name"].replace("_", " ").title()[:20]
        sem = book.get("semester", "")
        yr = book.get("year", "")
        loc = f"{yr}·{sem}" if yr else sem
        label = f"{icons[i]} {name} · {loc} {star_str}"
        tg_file_id = book.get("telegram_file_id", "")
        markup.add(
            types.InlineKeyboardButton(label, callback_data=f"dlf_{tg_file_id[:30]}")
        )
    markup.add(
        types.InlineKeyboardButton(t(user_id, "main_menu_btn"), callback_data="main_menu")
    )
    bot.send_message(
        user_id,
        t(user_id, "search_results"),
        reply_markup=markup,
        parse_mode="Markdown",
    )


def handle_admin_delete(message):
    user_id = message.from_user.id
    if user_id != OWNER_ID:
        return
    file_name = message.text.strip().lower()
    db = load_db()
    before = len(db["books"])
    db["books"] = [b for b in db["books"] if b["file_name"] != file_name]
    if len(db["books"]) < before:
        save_db(db)
        bot.send_message(
            user_id, f"✅ *Deleted:* `{file_name}`",
            reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown"
        )
    else:
        bot.send_message(
            user_id, f"❌ *Not found:* `{file_name}`",
            reply_markup=main_menu_keyboard(user_id), parse_mode="Markdown"
        )
    state = get_state(user_id)
    state["action"] = None
    set_state(user_id, state)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_fac_"))
def cb_browse_faculty(call):
    user_id = call.from_user.id
    fac_key = call.data.replace("browse_fac_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["browse_faculty"] = faculty
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    if is_no_semester_faculty(faculty):
        books = get_books_for(faculty, "", "", "")
        fac_display = strip_emoji(faculty)
        if not books:
            bot.send_message(
                user_id,
                t(user_id, "no_books"),
                reply_markup=main_menu_keyboard(user_id),
                parse_mode="Markdown",
            )
        else:
            header = (
                f"📂 *{fac_display}*\n"
                f"{DIVIDER}\n"
                f"🗂️ {len(books)} book(s) — tap to download 👇"
            )
            bot.send_message(
                user_id,
                header,
                reply_markup=books_keyboard(user_id, books, faculty, "", "", ""),
                parse_mode="Markdown",
            )
    elif is_special_faculty(faculty):
        bot.send_message(
            user_id,
            t(user_id, "select_semester"),
            reply_markup=semester_keyboard(user_id, faculty, "", "", prefix="browse"),
            parse_mode="Markdown",
        )
    else:
        bot.send_message(
            user_id,
            t(user_id, "select_department"),
            reply_markup=department_keyboard(user_id, faculty, prefix="browse"),
            parse_mode="Markdown",
        )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_dep_"))
def cb_browse_dept(call):
    user_id = call.from_user.id
    parts = call.data.replace("browse_dep_", "").split("|", 1)
    if len(parts) != 2:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["browse_faculty"] = faculty
    state["browse_dept"] = dept
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "select_year"),
        reply_markup=year_keyboard(user_id, faculty, dept, prefix="browse"),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_yr_"))
def cb_browse_year(call):
    user_id = call.from_user.id
    parts = call.data.replace("browse_yr_", "").split("|", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
    year = parts[2]
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["browse_faculty"] = faculty
    state["browse_dept"] = dept
    state["browse_year"] = year
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "select_semester"),
        reply_markup=semester_keyboard(user_id, faculty, dept, year, prefix="browse"),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_s_"))
def cb_browse_semester(call):
    user_id = call.from_user.id
    parts = call.data.replace("browse_s_", "").split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["browse_faculty"] = faculty
    state["browse_dept"] = dept
    state["browse_year"] = year
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    books = get_books_for(faculty, dept, year, semester)
    fac_display = strip_emoji(faculty)
    dept_display = strip_emoji(dept) if dept else fac_display
    sem_label = "Semester 1" if semester == "Sem1" else "Semester 2"
    if not books:
        bot.send_message(
            user_id,
            t(user_id, "no_books"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
    else:
        header = (
            f"📂 *{dept_display}*"
            + (f" · {year}" if year else "")
            + f" · {sem_label}\n"
            f"{DIVIDER}\n"
            f"🗂️ {len(books)} book(s) — tap to download 👇"
        )
        bot.send_message(
            user_id,
            header,
            reply_markup=books_keyboard(user_id, books, faculty, dept, year, semester),
            parse_mode="Markdown",
        )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("browse_bk_"))
def cb_browse_back(call):
    user_id = call.from_user.id
    data = call.data
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)

    if data == "browse_bk_fac":
        bot.send_message(
            user_id,
            t(user_id, "select_faculty"),
            reply_markup=faculty_keyboard(user_id, prefix="browse"),
            parse_mode="Markdown",
        )
    elif data.startswith("browse_bk_dep_"):
        faculty = find_faculty_by_key(data.replace("browse_bk_dep_", ""))
        if faculty:
            bot.send_message(
                user_id,
                t(user_id, "select_department"),
                reply_markup=department_keyboard(user_id, faculty, prefix="browse"),
                parse_mode="Markdown",
            )
    elif data.startswith("browse_bk_yr_"):
        parts = data.replace("browse_bk_yr_", "").split("|", 1)
        if len(parts) == 2:
            faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
            if faculty:
                bot.send_message(
                    user_id,
                    t(user_id, "select_year"),
                    reply_markup=year_keyboard(user_id, faculty, dept, prefix="browse"),
                    parse_mode="Markdown",
                )
    elif data.startswith("browse_bk_sem_"):
        parts = data.replace("browse_bk_sem_", "").split("|", 2)
        if len(parts) == 3:
            fac_key, dept_key, yr_key = parts
            faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
            year = "" if yr_key == "direct" else yr_key
            if faculty:
                bot.send_message(
                    user_id,
                    t(user_id, "select_semester"),
                    reply_markup=semester_keyboard(
                        user_id, faculty, dept, year, prefix="browse"
                    ),
                    parse_mode="Markdown",
                )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def cb_download(call):
    user_id = call.from_user.id
    raw = call.data.replace("dl_", "")
    parts = raw.split("_", 1)
    if len(parts) < 2:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    try:
        idx = int(parts[0])
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid index.")
        return
    loc_parts = parts[1].split("|", 3)
    if len(loc_parts) != 4:
        bot.answer_callback_query(call.id, "Invalid location.")
        return
    fac_key, dept_key, yr_key, semester = loc_parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    books = get_books_for(faculty, dept, year, semester)
    if idx >= len(books):
        bot.answer_callback_query(call.id, "Book not found.")
        return
    book = books[idx]
    tg_file_id = book.get("telegram_file_id")
    if not tg_file_id:
        bot.answer_callback_query(call.id, t(user_id, "file_not_found"))
        return
    bot.answer_callback_query(call.id, "📥 Sending...")
    try:
        name_display = book["file_name"].replace("_", " ").title()[:30]
        voters = len(book.get("voters", []))
        avg = round(book.get("stars", 0) / voters) if voters > 0 else 0
        stars_display = "⭐" * avg if avg > 0 else "☆ Unrated"
        sem_label = "Sem 1" if semester == "Sem1" else "Sem 2"
        dept_display = strip_emoji(dept) if dept else strip_emoji(faculty)
        caption = (
            f"📄 *{name_display}*\n"
            f"{dept_display} · {year + ' · ' if year else ''}{sem_label}\n"
            f"{stars_display} ({voters})"
        )
        bot.send_document(user_id, tg_file_id, caption=caption, parse_mode="Markdown")
        bot.send_message(
            user_id,
            t(user_id, "download_success"),
            reply_markup=rating_keyboard(user_id, idx, fac_key, dept_key, yr_key, semester),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Send document failed: %s", e)
        bot.send_message(user_id, f"❌ Error: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("dlf_"))
def cb_download_by_file_id(call):
    user_id = call.from_user.id
    tg_prefix = call.data.replace("dlf_", "")
    db = load_db()
    book = next(
        (b for b in db["books"] if b.get("telegram_file_id", "").startswith(tg_prefix)),
        None,
    )
    if not book:
        bot.answer_callback_query(call.id, t(user_id, "file_not_found"))
        return
    bot.answer_callback_query(call.id, "📥 Sending...")
    try:
        name_display = book["file_name"].replace("_", " ").title()[:30]
        voters = len(book.get("voters", []))
        avg = round(book.get("stars", 0) / voters) if voters > 0 else 0
        stars_display = "⭐" * avg if avg > 0 else "☆ Unrated"
        sem = book.get("semester", "")
        yr = book.get("year", "")
        sem_label = "Sem 1" if sem == "Sem1" else ("Sem 2" if sem == "Sem2" else "")
        dept_display = strip_emoji(book.get("department", "")) or strip_emoji(book.get("faculty", ""))
        caption = (
            f"📄 *{name_display}*\n"
            f"{dept_display} · {yr + ' · ' if yr else ''}{sem_label}\n"
            f"{stars_display} ({voters})"
        )
        bot.send_document(user_id, book["telegram_file_id"], caption=caption, parse_mode="Markdown")
        bot.send_message(
            user_id,
            t(user_id, "download_success"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error("Send document (by file id) failed: %s", e)
        bot.send_message(user_id, f"❌ Error: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("rt_"))
def cb_rate(call):
    user_id = call.from_user.id
    raw = call.data.replace("rt_", "")
    parts = raw.split("_", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    try:
        stars_given = int(parts[0])
        idx = int(parts[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    if not 1 <= stars_given <= 5:
        bot.answer_callback_query(call.id, "Invalid rating.")
        return
    loc_parts = parts[2].split("|", 3)
    if len(loc_parts) != 4:
        bot.answer_callback_query(call.id, "Invalid location.")
        return
    fac_key, dept_key, yr_key, semester = loc_parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    db = load_db()
    all_books = get_books_for(faculty, dept, year, semester)
    if idx >= len(all_books):
        bot.answer_callback_query(call.id, "Book not found.")
        return
    book = all_books[idx]
    uid = str(user_id)
    if uid in book.get("voters", []):
        bot.answer_callback_query(call.id, t(user_id, "already_voted"), show_alert=True)
        return
    book.setdefault("voters", []).append(uid)
    book["stars"] = book.get("stars", 0) + stars_given
    uploader_id = str(book.get("uploader_id", ""))
    if uploader_id and uploader_id in db["users"]:
        db["users"][uploader_id]["stars_received"] = (
            db["users"][uploader_id].get("stars_received", 0) + stars_given
        )
    save_db(db)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    stars_str = STARS_MAP.get(stars_given, "⭐")
    bot.send_message(
        user_id,
        f"{t(user_id, 'vote_recorded')} {stars_str}",
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id, f"Rated {stars_given} ⭐")


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_fac_"))
def cb_upload_faculty(call):
    user_id = call.from_user.id
    fac_key = call.data.replace("upload_fac_", "")
    faculty = find_faculty_by_key(fac_key)
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["upload_faculty"] = faculty
    state["upload_dept"] = ""
    state["upload_year"] = ""
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    if is_no_semester_faculty(faculty):
        state["upload_semester"] = ""
        state["action"] = "awaiting_file"
        set_state(user_id, state)
        fac_display = strip_emoji(faculty)
        confirm_text = (
            f"📍 *{fac_display}*\n"
            f"{DIVIDER}\n"
            + t(user_id, "upload_prompt")
        )
        bot.send_message(
            user_id,
            confirm_text,
            reply_markup=types.ReplyKeyboardRemove(),
            parse_mode="Markdown",
        )
    elif is_special_faculty(faculty):
        bot.send_message(
            user_id,
            t(user_id, "select_semester"),
            reply_markup=semester_keyboard(user_id, faculty, "", "", prefix="upload"),
            parse_mode="Markdown",
        )
    else:
        bot.send_message(
            user_id,
            t(user_id, "select_department"),
            reply_markup=department_keyboard(user_id, faculty, prefix="upload"),
            parse_mode="Markdown",
        )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_dep_"))
def cb_upload_dept(call):
    user_id = call.from_user.id
    parts = call.data.replace("upload_dep_", "").split("|", 1)
    if len(parts) != 2:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["upload_faculty"] = faculty
    state["upload_dept"] = dept
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "select_year"),
        reply_markup=year_keyboard(user_id, faculty, dept, prefix="upload"),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_yr_"))
def cb_upload_year(call):
    user_id = call.from_user.id
    parts = call.data.replace("upload_yr_", "").split("|", 2)
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
    year = parts[2]
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["upload_faculty"] = faculty
    state["upload_dept"] = dept
    state["upload_year"] = year
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    bot.send_message(
        user_id,
        t(user_id, "select_semester"),
        reply_markup=semester_keyboard(user_id, faculty, dept, year, prefix="upload"),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_s_"))
def cb_upload_semester(call):
    user_id = call.from_user.id
    parts = call.data.replace("upload_s_", "").split("|", 3)
    if len(parts) != 4:
        bot.answer_callback_query(call.id, "Invalid data.")
        return
    fac_key, dept_key, yr_key, semester = parts
    faculty, dept = find_faculty_dept_by_key(fac_key, dept_key)
    year = "" if yr_key == "direct" else yr_key
    if not faculty:
        bot.answer_callback_query(call.id, "Not found.")
        return
    state = get_state(user_id)
    state["upload_faculty"] = faculty
    state["upload_dept"] = dept
    state["upload_year"] = year
    state["upload_semester"] = semester
    state["action"] = "awaiting_file"
    set_state(user_id, state)
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    fac_display = strip_emoji(faculty)
    dept_display = strip_emoji(dept) if dept else fac_display
    sem_label = "Semester 1" if semester == "Sem1" else "Semester 2"
    loc = f"*{dept_display}*" + (f" · {year}" if year else "") + f" · {sem_label}"
    confirm_text = (
        f"📍 {loc}\n"
        f"{DIVIDER}\n"
        + t(user_id, "upload_prompt")
    )
    bot.send_message(
        user_id,
        confirm_text,
        reply_markup=types.ReplyKeyboardRemove(),
        parse_mode="Markdown",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_bk_"))
def cb_upload_back(call):
    user_id = call.from_user.id
    data = call.data
    remove_inline_keyboard(call.message.chat.id, call.message.message_id)
    if data == "upload_bk_fac":
        bot.send_message(
            user_id,
            t(user_id, "select_faculty"),
            reply_markup=faculty_keyboard(user_id, prefix="upload"),
            parse_mode="Markdown",
        )
    elif data.startswith("upload_bk_dep_"):
        faculty = find_faculty_by_key(data.replace("upload_bk_dep_", ""))
        if faculty:
            bot.send_message(
                user_id,
                t(user_id, "select_department"),
                reply_markup=department_keyboard(user_id, faculty, prefix="upload"),
                parse_mode="Markdown",
            )
    elif data.startswith("upload_bk_yr_"):
        parts = data.replace("upload_bk_yr_", "").split("|", 1)
        if len(parts) == 2:
            faculty, dept = find_faculty_dept_by_key(parts[0], parts[1])
            if faculty:
                bot.send_message(
                    user_id,
                    t(user_id, "select_year"),
                    reply_markup=year_keyboard(user_id, faculty, dept, prefix="upload"),
                    parse_mode="Markdown",
                )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def cb_admin(call):
    user_id = call.from_user.id
    if user_id != OWNER_ID:
        bot.answer_callback_query(call.id, t(user_id, "not_admin"))
        return
    data = call.data
    db = load_db()
    if data == "admin_list_books":
        books = db["books"]
        if not books:
            bot.send_message(user_id, "📭 No books.")
        else:
            lines = [
                f"📄 `{b['file_name']}`\n"
                f"   {strip_emoji(b.get('faculty',''))} · {b.get('department','')} · {b.get('year','')} · {b.get('semester','')}"
                for b in books
            ]
            text = f"📚 *Books ({len(books)})*\n{DIVIDER}\n" + "\n\n".join(lines)
            for i in range(0, len(text), 4000):
                bot.send_message(user_id, text[i: i + 4000], parse_mode="Markdown")
    elif data == "admin_list_users":
        users = db["users"]
        if not users:
            bot.send_message(user_id, "👥 No users.")
        else:
            lines = [
                f"👤 *{info.get('name', uid)}*  `{uid}`\n   📚{info.get('uploaded_books', 0)} ⭐{info.get('stars_received', 0)}"
                for uid, info in users.items()
            ]
            text = f"👥 *Users ({len(users)})*\n{DIVIDER}\n" + "\n\n".join(lines)
            for i in range(0, len(text), 4000):
                bot.send_message(user_id, text[i: i + 4000], parse_mode="Markdown")
    elif data == "admin_delete_prompt":
        state = get_state(user_id)
        state["action"] = "admin_delete"
        set_state(user_id, state)
        bot.send_message(
            user_id,
            f"🗑️ *Delete Book*\n{DIVIDER}\nSend the exact file name:",
            parse_mode="Markdown",
        )
    elif data == "admin_broadcast_prompt":
        state = get_state(user_id)
        state["action"] = "admin_broadcast"
        set_state(user_id, state)
        db2 = load_db()
        total = len(db2.get("users", {}))
        bot.send_message(
            user_id,
            f"📢 *Broadcast Message*\n{DIVIDER}\n"
            f"This will be sent to all *{total}* users.\n\n"
            f"Type your announcement message now:",
            parse_mode="Markdown",
        )
    elif data == "admin_dm_prompt":
        state = get_state(user_id)
        state["action"] = "admin_dm_target"
        set_state(user_id, state)
        bot.send_message(
            user_id,
            f"✉️ *Direct Message*\n{DIVIDER}\n"
            f"Send the *User ID* of the person you want to message:\n\n"
            f"_(Tip: User IDs are shown in the Users list and contact messages)_",
            parse_mode="Markdown",
        )
    bot.answer_callback_query(call.id)


@bot.message_handler(content_types=["document"])
def handle_document(message):
    user_id = message.from_user.id
    state = get_state(user_id)

    if state.get("action") != "awaiting_file":
        bot.send_message(
            user_id,
            t(user_id, "main_menu"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return

    now = time.time()
    last = last_upload_time.get(user_id, 0)
    if now - last < UPLOAD_COOLDOWN:
        remaining = int(UPLOAD_COOLDOWN - (now - last))
        bot.send_message(
            user_id,
            f"{t(user_id, 'spam_warning')} ⏳ *{remaining}s*",
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return

    faculty = state.get("upload_faculty", "")
    dept = state.get("upload_dept", "")
    year = state.get("upload_year", "")
    semester = state.get("upload_semester", "")

    if not faculty or not semester:
        bot.send_message(
            user_id,
            t(user_id, "upload_select_location"),
            reply_markup=faculty_keyboard(user_id, prefix="upload"),
            parse_mode="Markdown",
        )
        return

    doc = message.document
    file_name = doc.file_name or "unknown"
    ext = os.path.splitext(file_name)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        bot.send_message(
            user_id,
            t(user_id, "upload_invalid_type"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        bot.send_message(
            user_id,
            t(user_id, "upload_too_large"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return

    clean_name = clean_filename(file_name)
    db = load_db()
    fac_clean = strip_emoji(faculty)
    dept_clean = strip_emoji(dept) if dept else ""

    duplicate = any(
        strip_emoji(b.get("faculty", "")) == fac_clean
        and strip_emoji(b.get("department", "")) == dept_clean
        and b.get("year", "") == year
        and b.get("semester", "") == semester
        and b["file_name"] == clean_name
        for b in db["books"]
    )
    if duplicate:
        bot.send_message(
            user_id,
            t(user_id, "upload_duplicate"),
            reply_markup=main_menu_keyboard(user_id),
            parse_mode="Markdown",
        )
        return

    wait_msg = bot.send_message(user_id, t(user_id, "uploading"), parse_mode="Markdown")

    try:
        book_entry = {
            "file_name": clean_name,
            "faculty": fac_clean,
            "department": dept_clean,
            "year": year,
            "semester": semester,
            "uploader_id": str(user_id),
            "telegram_file_id": doc.file_id,
            "stars": 0,
            "voters": [],
        }
        db["books"].append(book_entry)

        user_info = get_user_info(db, user_id)
        user_info["uploaded_books"] = user_info.get("uploaded_books", 0) + 1
        fname = message.from_user.first_name or ""
        lname = message.from_user.last_name or ""
        user_info["name"] = (fname + " " + lname).strip() or str(user_id)
        save_db(db)

    except Exception as e:
        logger.error("Upload error for user %s: %s", user_id, e)
        try:
            bot.delete_message(user_id, wait_msg.message_id)
        except Exception:
            pass
        bot.send_message(
            user_id,
            f"{t(user_id, 'upload_error')}\n`{e}`",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    last_upload_time[user_id] = now
    state["action"] = None
    set_state(user_id, state)

    try:
        bot.delete_message(user_id, wait_msg.message_id)
    except Exception:
        pass

    total_books = user_info.get("uploaded_books", 1)
    bot.send_message(
        user_id,
        t(user_id, "upload_success"),
        reply_markup=main_menu_keyboard(user_id),
        parse_mode="Markdown",
    )

    try:
        sem_label = "Sem 1" if semester == "Sem1" else "Sem 2"
        dept_display = dept_clean if dept_clean else fac_clean
        bot.send_message(
            OWNER_ID,
            f"📤 *New Upload*\n"
            f"{DIVIDER}\n"
            f"👤 *{user_info['name']}*\n"
            f"📄 `{clean_name}`\n"
            f"📍 {fac_clean} · {dept_display} · {year} · {sem_label}\n"
            f"📚 Total by user: {total_books}",
            parse_mode="Markdown",
        )
    except Exception:
        pass


app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is running! 🤖", 200


@app.route("/ping")
def ping():
    return "pong", 200


def run_bot():
    logger.info("🤖 University Book Sharing Bot (mtu.ai) starting up...")
    time.sleep(5)
    while True:
        try:
            bot.delete_webhook(drop_pending_updates=True)
            logger.info("Webhook cleared ✅")
        except Exception as e:
            logger.warning("Could not clear webhook: %s", e)
        try:
            logger.info("Starting polling...")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                skip_pending=True,
                allowed_updates=["message", "callback_query"],
            )
        except Exception as e:
            err_str = str(e)
            logger.error("Polling stopped: %s", err_str)
            if "409" in err_str or "Conflict" in err_str:
                logger.warning("Conflict detected (409) — another instance may be running. Waiting 60s before retry...")
                time.sleep(60)
            else:
                logger.warning("Restarting in 15s...")
                time.sleep(15)


bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
