import logging
import asyncio
import re
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    filters
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, DOWNLOAD_DIR, COOKIES_FILE, MAX_FILE_SIZE
from youtube_downloader import YouTubeDownloader
from video_processor_fast import FastVideoProcessor

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация загрузчика и процессора
downloader = YouTubeDownloader(DOWNLOAD_DIR, COOKIES_FILE)
processor = FastVideoProcessor(DOWNLOAD_DIR / 'temp')

# Регулярное выражение для YouTube URL
YOUTUBE_URL_PATTERN = re.compile(
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
    r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    welcome_text = (
        "🎥 <b>YouTube Video Processor Bot</b>\n\n"
        "Привет! Я создаю крутые вертикальные видео из YouTube роликов!\n\n"
        "🚀 <b>Что я умею:</b>\n"
        "• 📥 Скачиваю видео в лучшем качестве\n"
        "• ✂️ Нарезаю длинные видео на чанки по 5 минут\n"
        "• 🎤 Генерирую субтитры через AI (Whisper)\n"
        "• 📱 Создаю вертикальный формат 9:16\n"
        "• 🎨 Добавляю размытый фон\n"
        "• ✨ Анимирую субтитры по словам\n\n"
        "📋 <b>Как пользоваться:</b>\n"
        "Просто отправь мне ссылку на YouTube видео!\n\n"
        "⚙️ <b>Команды:</b>\n"
        "/start - показать это сообщение\n"
        "/help - подробная помощь\n\n"
        "🎬 Отправь ссылку и начнем создавать контент!"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.HTML
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    help_text = (
        "🆘 <b>Подробная помощь</b>\n\n"
        "📝 <b>Поддерживаемые форматы ссылок:</b>\n"
        "• https://www.youtube.com/watch?v=VIDEO_ID\n"
        "• https://youtu.be/VIDEO_ID\n"
        "• https://m.youtube.com/watch?v=VIDEO_ID\n\n"
        "🎬 <b>Процесс обработки:</b>\n"
        "1️⃣ <b>Скачивание</b> - получаю видео в HD качестве\n"
        "2️⃣ <b>Анализ</b> - проверяю длительность\n"
        "3️⃣ <b>Нарезка</b> - делю на чанки по 5 минут (если нужно)\n"
        "4️⃣ <b>Субтитры</b> - генерирую через Whisper AI\n"
        "5️⃣ <b>Формат</b> - создаю вертикальное 9:16\n"
        "6️⃣ <b>Анимация</b> - добавляю анимированные субтитры\n\n"
        "⚡ <b>Особенности:</b>\n"
        "• Автоматическое объединение видео и аудио\n"
        "• Обход ограничений с помощью cookies\n"
        "• Размытый фон из оригинального видео\n"
        "• Субтитры появляются по одному слову\n"
        "• Готово для TikTok, Instagram, YouTube Shorts\n\n"
        "❗ <b>Ограничения:</b>\n"
        "• Максимальный размер файла: 50MB\n"
        "• Только публичные видео\n"
        "• Обработка может занять 2-10 минут\n\n"
        "🔧 <b>Проблемы?</b>\n"
        "Попробуйте другую ссылку или видео покороче."
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML
    )

def is_youtube_url(text: str) -> bool:
    """Проверить, является ли текст YouTube URL"""
    return bool(YOUTUBE_URL_PATTERN.search(text))

async def handle_youtube_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик YouTube ссылок - скачивает и обрабатывает видео"""
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if not is_youtube_url(url):
        await update.message.reply_text(
            "❌ Это не похоже на ссылку YouTube. Пожалуйста, отправьте корректную ссылку."
        )
        return
    
    # Отправляем сообщение о начале обработки
    status_message = await update.message.reply_text(
        "🎬 Начинаю обработку видео...\n"
        "📥 Скачивание → ✂️ Нарезка → 🎤 Субтитры → 📱 Вертикальный формат\n\n"
        "⏳ Это может занять несколько минут..."
    )
    
    try:
        # Этап 1: Скачиваем видео
        await status_message.edit_text(
            "📥 <b>Этап 1/4:</b> Скачивание видео...\n"
            "⏳ Получаю видео в лучшем качестве",
            parse_mode=ParseMode.HTML
        )
        
        file_path = await downloader.download_video(url, chat_id)
        
        if not file_path:
            await status_message.edit_text(
                "❌ Не удалось скачать видео. Возможно, видео недоступно или слишком большое."
            )
            return
        
        # Этап 2: Обрабатываем видео (нарезка, субтитры, вертикальный формат)
        await status_message.edit_text(
            "🎞️ <b>Этап 2/4:</b> Анализ и нарезка видео...\n"
            "⏳ Проверяю длительность и нарезаю на чанки при необходимости",
            parse_mode=ParseMode.HTML
        )
        
        # Обрабатываем видео через новый процессор
        processed_videos = await processor.process_video(file_path, chat_id)
        
        if not processed_videos:
            await status_message.edit_text(
                "❌ Не удалось обработать видео. Попробуйте другое видео."
            )
            downloader.cleanup_file(file_path)
            return
        
        # Этап 3: Отправляем обработанные видео
        await status_message.edit_text(
            f"📤 <b>Этап 4/4:</b> Отправка готовых видео...\n"
            f"✨ Создано {len(processed_videos)} вертикальных видео с субтитрами",
            parse_mode=ParseMode.HTML
        )
        
        # Отправляем каждое обработанное видео
        for i, processed_video in enumerate(processed_videos):
            # Проверяем размер файла
            file_size = processor.get_file_size(processed_video)
            
            if file_size > MAX_FILE_SIZE:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Видео {i+1} слишком большое ({file_size / (1024*1024):.1f} MB) для отправки в Telegram"
                )
                continue
            
            # Отправляем видео
            with open(processed_video, 'rb') as video_file:
                caption = f"✅ Готовое видео {i+1}/{len(processed_videos)}\n"
                caption += "🎬 Вертикальный формат 9:16\n"
                caption += "🎤 Анимированные субтитры\n"
                caption += "🎨 Размытый фон"
                
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=caption,
                    supports_streaming=True
                )
        
        # Удаляем сообщение о статусе
        await status_message.delete()
        
        # Отправляем финальное сообщение
        final_message = f"🎉 <b>Обработка завершена!</b>\n\n"
        final_message += f"📊 <b>Результат:</b>\n"
        final_message += f"• Создано видео: {len(processed_videos)}\n"
        final_message += f"• Формат: 9:16 (вертикальный)\n"
        final_message += f"• Субтитры: Анимированные по словам\n"
        final_message += f"• Фон: Размытый оригинал\n\n"
        final_message += f"🚀 Готово к публикации в соцсетях!"
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=final_message,
            parse_mode=ParseMode.HTML
        )
        
        # Очищаем файлы
        downloader.cleanup_file(file_path)
        processor.cleanup_temp_files(chat_id)
        
    except Exception as e:
        logger.error(f"Ошибка обработки видео: {e}")
        await status_message.edit_text(
            "❌ Произошла ошибка при обработке видео. Попробуйте позже.\n\n"
            f"Детали ошибки: {str(e)[:100]}..."
        )
        
        # Очищаем файлы в случае ошибки
        try:
            if 'file_path' in locals():
                downloader.cleanup_file(file_path)
            processor.cleanup_temp_files(chat_id)
        except:
            pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    text = update.message.text
    
    if is_youtube_url(text):
        await handle_youtube_url(update, context)
    else:
        await update.message.reply_text(
            "🤔 Я умею обрабатывать только видео с YouTube.\n"
            "Отправьте мне ссылку на YouTube видео для создания крутого вертикального контента!"
        )

def main() -> None:
    """Запуск бота"""
    if BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ Ошибка: Не установлен BOT_TOKEN!")
        print("Получите токен у @BotFather и установите переменную окружения BOT_TOKEN")
        print("Или измените значение в config.py")
        return
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запускаем бота
    print("🚀 YouTube Video Processor Bot запущен!")
    print("📱 Готов создавать вертикальный контент с субтитрами!")
    print("Нажмите Ctrl+C для остановки.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()