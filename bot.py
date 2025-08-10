import os
import openai
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

# Загружаем токены из переменных окружения
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Настройка OpenAI
openai.api_key = OPENAI_API_KEY

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)

# Обработка текстовых сообщений
@dp.message_handler(content_types=types.ContentType.TEXT)
async def handle_text(message: types.Message):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": message.text}],
            temperature=0.7
        )
        answer = response.choices[0].message["content"]
        await message.reply(answer)
    except Exception as e:
        await message.reply(f"Ошибка: {e}")

# Обработка голосовых сообщений
@dp.message_handler(content_types=types.ContentType.VOICE)
async def handle_voice(message: types.Message):
    try:
        # Скачиваем файл
        file = await bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                voice_bytes = await resp.read()

        temp_path = f"/tmp/voice_{message.message_id}.ogg"
        with open(temp_path, "wb") as f:
            f.write(voice_bytes)

        # Распознаем речь через Whisper
        with open(temp_path, "rb") as audio_file:
            transcript = openai.Audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=audio_file
            )

        recognized_text = transcript["text"]

        # Отправляем распознанный текст в GPT
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": recognized_text}],
            temperature=0.7
        )
        answer = response.choices[0].message["content"]

        await message.reply(f"🗣 Вы сказали: {recognized_text}\n\n💬 Ответ: {answer}")

    except Exception as e:
        await message.reply(f"Ошибка при обработке голосового: {e}")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
