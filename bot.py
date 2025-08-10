import os
import sqlite3
import datetime
import aiohttp
import asyncio

import openai
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

# --- Загрузка токенов из переменных окружения ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YOOKASSA_LINK = os.getenv("YOOKASSA_LINK")  # ссылка на оплату премиум в YooKassa

if not TELEGRAM_TOKEN or not OPENAI_API_KEY:
    print("ERROR: TELEGRAM_TOKEN или OPENAI_API_KEY не заданы!")
    exit(1)

openai.api_key = OPENAI_API_KEY

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

# --- Работа с базой данных ---
conn = sqlite3.connect('users.db')
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    language TEXT,
    requests_count INTEGER DEFAULT 0,
    last_request_date TEXT,
    registration_date TEXT,
    subscription_status TEXT DEFAULT 'free',
    subscription_expire TEXT
)
''')
conn.commit()

# --- Клавиатуры ---
lang_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
lang_kb.add(KeyboardButton("Русский 🇷🇺"), KeyboardButton("English 🇺🇸"))

main_kb = ReplyKeyboardMarkup(resize_keyboard=True)
main_kb.add(KeyboardButton("💬 Задать вопрос"), KeyboardButton("👤 Личный кабинет"))
main_kb.add(KeyboardButton("⭐ Купить Премиум"))

# --- Вспомогательные функции ---

def get_user(user_id):
    cursor.execute('SELECT language, requests_count, last_request_date, registration_date, subscription_status, subscription_expire FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if row:
        return {
            'language': row[0],
            'requests_count': row[1],
            'last_request_date': row[2],
            'registration_date': row[3],
            'subscription_status': row[4],
            'subscription_expire': row[5],
        }
    else:
        return None

def add_user(user_id, language):
    now = datetime.datetime.utcnow().date().isoformat()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, language, registration_date) VALUES (?, ?, ?)', (user_id, language, now))
    conn.commit()

def update_user_language(user_id, language):
    cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (language, user_id))
    conn.commit()

def reset_daily_requests_if_needed(user):
    today = datetime.datetime.utcnow().date().isoformat()
    if user['last_request_date'] != today:
        cursor.execute('UPDATE users SET requests_count = 0, last_request_date = ? WHERE user_id = ?', (today, user_id))
        conn.commit()
        user['requests_count'] = 0
        user['last_request_date'] = today

def increment_request_count(user_id):
    cursor.execute('UPDATE users SET requests_count = requests_count + 1, last_request_date = ? WHERE user_id = ?',
                   (datetime.datetime.utcnow().date().isoformat(), user_id))
    conn.commit()

def update_subscription(user_id, status, expire_date):
    cursor.execute('UPDATE users SET subscription_status = ?, subscription_expire = ? WHERE user_id = ?', (status, expire_date, user_id))
    conn.commit()

def check_subscription_expiry():
    today = datetime.datetime.utcnow().date()
    cursor.execute('SELECT user_id, subscription_expire FROM users WHERE subscription_status = "premium"')
    users = cursor.fetchall()
    for user_id, expire_str in users:
        if expire_str:
            expire_date = datetime.datetime.fromisoformat(expire_str).date()
            if expire_date < today:
                update_subscription(user_id, 'free', None)

async def send_typing_action(chat_id):
    await bot.send_chat_action(chat_id, action="typing")

# --- Хендлеры ---

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user = get_user(message.from_user.id)
    if user is None:
        await message.answer("Выберите язык / Choose your language:", reply_markup=lang_kb)
    else:
        await message.answer(get_welcome_message(user['language']), reply_markup=main_kb)

@dp.message_handler(lambda m: m.text in ["Русский 🇷🇺", "English 🇺🇸"])
async def set_language(message: types.Message):
    lang = 'rus' if message.text == "Русский 🇷🇺" else 'eng'
    user = get_user(message.from_user.id)
    if user is None:
        add_user(message.from_user.id, lang)
    else:
        update_user_language(message.from_user.id, lang)
    await message.answer(get_welcome_message(lang), reply_markup=main_kb)

def get_welcome_message(lang):
    if lang == 'rus':
        return (
            "Привет! 👋\n"
            "Я — самый быстрый и умный чат-бот в Telegram с GPT-5! 🚀\n\n"
            "Каждый день у тебя есть 5 бесплатных запросов — спрашивай что угодно!\n"
            "Хотите больше? Оформи Премиум за 250₽ в месяц и получай:\n"
            "🎙️ Голосовые сообщения для общения без текста\n"
            "♾️ Безграничное количество запросов — говори со мной сколько угодно!\n\n"
            "Готов начать? Просто отправь свой вопрос! 💬"
        )
    else:
        return (
            "Hey! 👋\n"
            "I’m the fastest and smartest chatbot on Telegram powered by GPT-5! 🚀\n\n"
            "You get 5 free requests per day — ask me anything!\n"
            "Want more? Get the Premium plan for $5/month and enjoy:\n"
            "🎙️ Voice messages for hands-free chatting\n"
            "♾️ Unlimited requests — talk to me as much as you want!\n\n"
            "Ready to start? Just send your question! 💬"
        )

@dp.message_handler(lambda m: m.text == "👤 Личный кабинет")
async def personal_cabinet(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала выберите язык через /start")
        return
    now = datetime.datetime.utcnow().date()
    sub_expire = user['subscription_expire']
    expire_str = sub_expire if sub_expire else "-"
    if user['subscription_status'] == 'premium':
        text = (
            "👤 Ваш профиль\n\n"
            f"📅 Дата регистрации: {user['registration_date']}\n"
            "💎 Статус подписки: Премиум активен\n"
            f"⏳ Истекает: {expire_str}"
        )
    else:
        left = max(0, 5 - user['requests_count'])
        text = (
            "👤 Ваш профиль\n\n"
            f"📅 Дата регистрации: {user['registration_date']}\n"
            "💎 Статус подписки: Бесплатный пользователь\n"
            f"📝 Осталось запросов сегодня: {left} из 5"
        )
    await message.answer(text)

@dp.message_handler(lambda m: m.text == "⭐ Купить Премиум")
async def buy_premium(message: types.Message):
    if not YOOKASSA_LINK:
        await message.answer("Оплата пока недоступна, попробуйте позже.")
        return
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(text="Оплатить 250₽ / month", url=YOOKASSA_LINK))
    await message.answer("Нажмите кнопку ниже, чтобы оплатить премиум подписку:", reply_markup=keyboard)

@dp.message_handler(content_types=types.ContentType.TEXT)
async def handle_text(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала выберите язык через /start")
        return

    # Проверка подписки на актуальность
    check_subscription_expiry()
    user = get_user(message.from_user.id)

    # Проверка лимитов
    today = datetime.datetime.utcnow().date().isoformat()
    if user['last_request_date'] != today:
        cursor.execute('UPDATE users SET requests_count=0, last_request_date=? WHERE user_id=?', (today, message.from_user.id))
        conn.commit()
        user['requests_count'] = 0

    if user['subscription_status'] != 'premium' and user['requests_count'] >= 5:
        if user['language'] == 'rus':
            await message.answer("Вы достигли суточного лимита бесплатной версии. Чтобы пользоваться ботом дальше, купите премиум подписку за 250₽ в месяц.")
        else:
            await message.answer("You have reached the daily limit of free requests. To continue, please purchase the Premium subscription for $5/month.")
        return

    msg = await message.answer("Chat GPT 5 думает..." if user['language']=='rus' else "Chat GPT 5 is thinking...")

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": message.text}],
            temperature=0.7
        )
        answer = response.choices[0].message["content"]
        increment_request_count(message.from_user.id)
        await msg.delete()
        await message.answer(answer)
    except Exception as e:
        await msg.delete()
        await message.answer(f"Ошибка: {e}")

@dp.message_handler(content_types=types.ContentType.VOICE)
async def handle_voice(message: types.Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала выберите язык через /start")
        return

    # Проверка подписки на актуальность
    check_subscription_expiry()
    user = get_user(message.from_user.id)

    # Проверка лимитов
    today = datetime.datetime.utcnow().date().isoformat()
    if user['last_request_date'] != today:
        cursor.execute('UPDATE users SET requests_count=0, last_request_date=? WHERE user_id=?', (today, message.from_user.id))
        conn.commit()
        user['requests_count'] = 0

    if user['subscription_status'] != 'premium' and user['requests_count'] >= 5:
        if user['language'] == 'rus':
            await message.answer("Вы достигли суточного лимита бесплатной версии. Чтобы пользоваться ботом дальше, купите премиум подписку за 250₽ в месяц.")
        else:
            await message.answer("You have reached the daily limit of free requests. To continue, please purchase the Premium subscription for $5/month.")
        return

    msg = await message.answer("Обрабатываю голосовое сообщение..." if user['language']=='rus' else "Processing voice message...")

    try:
        # Скачиваем голосовое сообщение
        file = await bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                voice_bytes = await resp.read()

        temp_path = f"voice_{message.message_id}.ogg"
        with open(temp_path, "wb") as f:
            f.write(voice_bytes)

        # Распознаем через openai Whisper (v0.28.0)
        with open(temp_path, "rb") as audio_file:
            transcript = openai.Audio.transcribe("whisper-1", audio_file)
        recognized_text = transcript["text"]

        # Обработка текста в GPT
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": recognized_text}],
            temperature=0.7
        )
        answer = response.choices[0].message["content"]

        increment_request_count(message.from_user.id)

        await msg.delete()
        await message.answer(f"🗣 Вы сказали: {recognized_text}\n\n💬 Ответ: {answer}")

        os.remove(temp_path)

    except Exception as e:
        await msg.delete()
        await message.answer(f"Ошибка при обработке голосового: {e}")

if __name__ == "__main__":
    print("Bot started...")
    executor.start_polling(dp, skip_updates=True)
