import logging
import asyncio
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes, 
    CallbackQueryHandler,
    filters
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

from config import BOT_TOKEN, DOWNLOAD_DIR, COOKIES_FILE, MAX_FILE_SIZE, DEFAULT_TOP_HEADER, DEFAULT_BOTTOM_HEADER
from youtube_downloader import YouTubeDownloader
from video_processor_fast import FastVideoProcessor
from user_settings import load_user_settings, update_user_settings, get_value

USER_ASSETS_DIR = Path('user_assets')
USER_ASSETS_DIR.mkdir(exist_ok=True)

# ======= УТИЛИТЫ =======

def normalize_cookies_text(raw: str) -> str:
    lines = raw.splitlines()
    out_lines = []
    for line in lines:
        if not line.strip():
            out_lines.append('')
            continue
        if line.lstrip().startswith('#'):
            out_lines.append(line)
            continue
        parts = re.split(r'\s+', line.strip())
        if len(parts) >= 7:
            parts = parts[:7]
            out_lines.append('\t'.join(parts))
        else:
            # keep original to avoid data loss
            out_lines.append(line)
    return '\n'.join(out_lines) + ('\n' if not raw.endswith('\n') else '')

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

# Состояние ожидаемых действий от пользователя
pending_actions = {}

# Словарь для хранения пользовательских заголовков (устаревшее, оставлено для совместимости)
user_headers = {}
user_timelines = {}
DEFAULT_TIMELINE = 30

# ======= КНОПКИ НАСТРОЕК =======

def build_main_settings_kb(chat_id: int) -> InlineKeyboardMarkup:
    settings = load_user_settings(chat_id)
    def as_on_off(path: str) -> str:
        return 'ON' if bool(get_value(settings, path, False)) else 'OFF'
    keyboard = [
        [InlineKeyboardButton('📝 Заголовки', callback_data='CFG:HEADERS')],
        [InlineKeyboardButton('⏱️ Таймлайн', callback_data='CFG:TIMELINE')],
        [InlineKeyboardButton('🎛️ Субтитры', callback_data='CFG:SUBTITLES')],
        [InlineKeyboardButton('📐 Макет', callback_data='CFG:LAYOUT')],
        [InlineKeyboardButton(f'🎵 Фоновая музыка: {as_on_off("background_music.enabled")}', callback_data='CFG:BG_MUSIC')],
        [InlineKeyboardButton(f'🖼️ Баннер: {as_on_off("banner.enabled")}', callback_data='CFG:BANNER')],
        [InlineKeyboardButton('🍪 Cookies', callback_data='CFG:COOKIES')],
        [InlineKeyboardButton('❌ Закрыть', callback_data='CFG:CLOSE')]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_headers_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Тексты: оба', callback_data='CFG:H:SET_BOTH')],
        [InlineKeyboardButton('Текст: верх', callback_data='CFG:H:SET_TOP'), InlineKeyboardButton('Текст: низ', callback_data='CFG:H:SET_BOTTOM')],
        [InlineKeyboardButton('Размер: верх', callback_data='CFG:H:TOP_SIZE'), InlineKeyboardButton('Размер: низ', callback_data='CFG:H:BOTTOM_SIZE')],
        [InlineKeyboardButton('Цвет текста', callback_data='CFG:H:COLOR'), InlineKeyboardButton('Цвет контура', callback_data='CFG:H:STROKE_COLOR')],
        [InlineKeyboardButton('Толщина контура', callback_data='CFG:H:STROKE_WIDTH')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

def build_timeline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Изменить длительность', callback_data='CFG:T:SET')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

def build_subtitles_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Размер шрифта', callback_data='CFG:S:FONT_SIZE'), InlineKeyboardButton('Цвет текста', callback_data='CFG:S:FONT_COLOR')],
        [InlineKeyboardButton('Контур цвет', callback_data='CFG:S:STROKE_COLOR'), InlineKeyboardButton('Контур толщина', callback_data='CFG:S:STROKE_WIDTH')],
        [InlineKeyboardButton('Файл шрифта (путь)', callback_data='CFG:S:FONT_PATH')],
        [InlineKeyboardButton('Загрузить файл шрифта', callback_data='CFG:S:FONT_UPLOAD')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

def build_layout_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Масштаб основного видео', callback_data='CFG:L:SCALE')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

def build_bg_music_kb(chat_id: int) -> InlineKeyboardMarkup:
    settings = load_user_settings(chat_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Переключить ON/OFF', callback_data='CFG:BGM:TOGGLE')],
        [InlineKeyboardButton('Путь к файлу', callback_data='CFG:BGM:PATH'), InlineKeyboardButton('Громкость', callback_data='CFG:BGM:VOL')],
        [InlineKeyboardButton('Загрузить файл музыки', callback_data='CFG:BGM:UPLOAD')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

def build_banner_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Переключить ON/OFF', callback_data='CFG:BN:TOGGLE')],
        [InlineKeyboardButton('Путь к файлу', callback_data='CFG:BN:PATH')],
        [InlineKeyboardButton('Загрузить файл баннера', callback_data='CFG:BN:UPLOAD')],
        [InlineKeyboardButton('Позиция X', callback_data='CFG:BN:X'), InlineKeyboardButton('Позиция Y', callback_data='CFG:BN:Y')],
        [InlineKeyboardButton('Chroma цвет', callback_data='CFG:BN:COLOR')],
        [InlineKeyboardButton('Chroma similarity', callback_data='CFG:BN:SIM'), InlineKeyboardButton('Chroma blend', callback_data='CFG:BN:BLEND')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

def build_cookies_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Загрузить cookies.txt файлом', callback_data='CFG:CK:UPLOAD')],
        [InlineKeyboardButton('Вставить текст cookies', callback_data='CFG:CK:TEXT')],
        [InlineKeyboardButton('⬅️ Назад', callback_data='CFG:BACK')]
    ])

# ======= КОМАНДЫ =======

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    welcome_text = (
        "👋 <b>Привет!</b>\n\n"
        "Я превращаю YouTube‑видео в вертикальные клипы 9:16 с субтитрами, заголовками, фоновой музыкой и баннером.\n\n"
        "🔹 <b>Как начать</b>\n"
        "1) Пришлите ссылку на YouTube\n"
        "2) Подождите — я всё сделаю автоматически\n\n"
        "⚙️ <b>Настройки</b>\n"
        "• /settings — меню с кнопками\n\n"
        "ℹ️ <b>Подсказки</b>\n"
        "• Длинные видео нарезаются на чанки\n"
        "• Если архив >50MB — пришлю ссылки Google Drive"
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
        "6️⃣ <b>Анимация</b> - добавляю анимированные субтитры\n"
        "7️⃣ <b>Заголовки</b> - добавляю настраиваемые заголовки сверху\n\n"
        "⚡ <b>Особенности:</b>\n"
        "• Автоматическое объединение видео и аудио\n"
        "• Обход ограничений с помощью cookies\n"
        "• Размытый фон из оригинального видео\n"
        "• Субтитры появляются по одному слову\n"
        "• Настраиваемые заголовки сверху экрана\n"
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

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "⚙️ <b>Меню настроек</b>\nВыберите раздел. Нажмите параметр — пришлю пример, затем отправьте своё значение.",
        parse_mode=ParseMode.HTML,
        reply_markup=build_main_settings_kb(chat_id)
    )

async def headers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /headers - настройка заголовков"""
    chat_id = update.effective_chat.id
    
    settings = load_user_settings(chat_id)
    current_top = get_value(settings, 'headers.top', DEFAULT_TOP_HEADER)
    current_bottom = get_value(settings, 'headers.bottom', DEFAULT_BOTTOM_HEADER)
    
    help_text = (
        "📝 <b>Настройка заголовков</b>\n\n"
        "Текущий верх: <code>" + str(current_top) + "</code>\n"
        "Текущий низ: <code>" + str(current_bottom) + "</code>\n\n"
        "Откройте /settings → Заголовки, выберите параметр — пришлю пример, затем отправьте своё значение."
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML
    )

async def reset_headers_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /reset_headers - сброс заголовков"""
    chat_id = update.effective_chat.id
    
    update_user_settings(chat_id, {"headers": {"top": DEFAULT_TOP_HEADER, "bottom": DEFAULT_BOTTOM_HEADER}})
    
    await update.message.reply_text(
        "🔄 <b>Заголовки сброшены!</b>\n\n"
        f"🔝 <b>Верхний заголовок:</b> {DEFAULT_TOP_HEADER}\n"
        f"🔻 <b>Нижний заголовок:</b> {DEFAULT_BOTTOM_HEADER}\n\n"
        "Теперь будут использоваться заголовки по умолчанию.",
        parse_mode=ParseMode.HTML
    )

async def timeline_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /timeline - настройка длительности нарезки"""
    chat_id = update.effective_chat.id
    
    settings = load_user_settings(chat_id)
    current_timeline = int(get_value(settings, 'clips.duration_seconds', DEFAULT_TIMELINE))
    
    help_text = (
        f"⏱️ <b>Настройка длительности нарезки</b>\n\n"
        f"🕒 <b>Текущая длительность:</b> {current_timeline} секунд\n\n"
        f"📋 <b>Пример:</b> <code>таймлайн: 60</code>\n"
        f"Или откройте /settings для кнопок."
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode=ParseMode.HTML
    )

async def handle_timeline_setting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик настройки таймлайна"""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    try:
        duration_str = text.split(':')[1].strip()
        duration = int(duration_str)
        
        if 5 <= duration <= 300:
            update_user_settings(chat_id, {"clips": {"duration_seconds": duration}})
            await update.message.reply_text(
                f"✅ <b>Длительность нарезки обновлена!</b>\n\n"
                f"🕒 <b>Новая длительность:</b> {duration} секунд",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text("❌ Длительность должна быть от 5 до 300 секунд.")
            
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ <b>Неверный формат!</b>\n\n"
            "Используйте формат: <code>таймлайн: [секунды]</code>",
            parse_mode=ParseMode.HTML
        )

def get_user_timeline(chat_id: int) -> int:
    """Получить длительность нарезки для пользователя"""
    settings = load_user_settings(chat_id)
    return int(get_value(settings, 'clips.duration_seconds', DEFAULT_TIMELINE))

def get_user_headers(chat_id: int) -> tuple:
    
    
    """Получить заголовки для конкретного пользователя"""
    settings = load_user_settings(chat_id)
    top = get_value(settings, 'headers.top', DEFAULT_TOP_HEADER)
    bottom = get_value(settings, 'headers.bottom', DEFAULT_BOTTOM_HEADER)
    return top, bottom

def is_youtube_url(text: str) -> bool:
    """Проверить, является ли текст YouTube URL"""
    return bool(YOUTUBE_URL_PATTERN.search(text))

# ======= CALLBACKS ДЛЯ КНОПОК =======

async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data = query.data

    if data == 'CFG:CLOSE':
        pending_actions.pop(chat_id, None)
        try:
            await query.edit_message_text("Меню настроек закрыто.")
        except BadRequest:
            pass
        return

    if data == 'CFG:BACK':
        try:
            await query.edit_message_text("⚙️ <b>Меню настроек</b>\nВыберите раздел. Нажмите параметр — пришлю пример, затем отправьте своё значение.", parse_mode=ParseMode.HTML, reply_markup=build_main_settings_kb(chat_id))
        except BadRequest:
            pass
        pending_actions.pop(chat_id, None)
        return

    if data == 'CFG:HEADERS':
        try:
            await query.edit_message_text("📝 Заголовки — выберите параметр. После выбора пришлю пример, затем отправьте своё значение.", reply_markup=build_headers_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:TIMELINE':
        try:
            await query.edit_message_text("⏱️ Таймлайн — выберите действие.", reply_markup=build_timeline_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:SUBTITLES':
        try:
            await query.edit_message_text("🎛️ Субтитры — выберите параметр.", reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:LAYOUT':
        try:
            await query.edit_message_text("📐 Макет — выберите параметр.", reply_markup=build_layout_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:BG_MUSIC':
        settings = load_user_settings(chat_id)
        state = 'ON' if bool(get_value(settings, 'background_music.enabled', True)) else 'OFF'
        try:
            await query.edit_message_text(f"🎵 Фоновая музыка — сейчас: {state}", reply_markup=build_bg_music_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BANNER':
        settings = load_user_settings(chat_id)
        state = 'ON' if bool(get_value(settings, 'banner.enabled', True)) else 'OFF'
        try:
            await query.edit_message_text(f"🖼️ Баннер — сейчас: {state}", reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:COOKIES':
        try:
            await query.edit_message_text("🍪 Cookies — выберите способ добавить файл:", reply_markup=build_cookies_kb())
        except BadRequest:
            pass
        return

    # Headers-specific
    if data == 'CFG:H:SET_BOTH':
        pending_actions[chat_id] = {"path": ["headers.top", "headers.bottom"], "type": "headers"}
        try:
            await query.edit_message_text(
                "Пример: <code>заголовки: МОЙ ВЕРХ | МОЙ НИЗ</code>\nОтправьте в одном сообщении.",
                parse_mode=ParseMode.HTML,
                reply_markup=build_headers_kb()
            )
        except BadRequest:
            pass
        return
    if data == 'CFG:H:SET_TOP':
        pending_actions[chat_id] = {"path": "headers.top", "type": "str", "maxlen": 50}
        try:
            await query.edit_message_text(
                "Пример: <code>верх: МОЙ ВЕРХНИЙ</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=build_headers_kb()
            )
        except BadRequest:
            pass
        return
    if data == 'CFG:H:SET_BOTTOM':
        pending_actions[chat_id] = {"path": "headers.bottom", "type": "str", "maxlen": 50}
        try:
            await query.edit_message_text(
                "Пример: <code>низ: МОЙ НИЖНИЙ</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=build_headers_kb()
            )
        except BadRequest:
            pass
        return
    if data == 'CFG:H:TOP_SIZE':
        pending_actions[chat_id] = {"path": "headers.top_font_size", "type": "int", "min": 10, "max": 200}
        try:
            await query.edit_message_text("Пример: <code>заголовки: верх размер 50</code>", parse_mode=ParseMode.HTML, reply_markup=build_headers_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:H:BOTTOM_SIZE':
        pending_actions[chat_id] = {"path": "headers.bottom_font_size", "type": "int", "min": 10, "max": 200}
        try:
            await query.edit_message_text("Пример: <code>заголовки: низ размер 70</code>", parse_mode=ParseMode.HTML, reply_markup=build_headers_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:H:COLOR':
        pending_actions[chat_id] = {"path": "headers.header_font_color", "type": "color"}
        try:
            await query.edit_message_text("Пример: <code>заголовки: цвет #FF0000</code>", parse_mode=ParseMode.HTML, reply_markup=build_headers_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:H:STROKE_COLOR':
        pending_actions[chat_id] = {"path": "headers.header_stroke_color", "type": "color"}
        try:
            await query.edit_message_text("Пример: <code>заголовки: контур цвет #000000</code>", parse_mode=ParseMode.HTML, reply_markup=build_headers_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:H:STROKE_WIDTH':
        pending_actions[chat_id] = {"path": "headers.header_stroke_width", "type": "int", "min": 0, "max": 20}
        try:
            await query.edit_message_text("Пример: <code>заголовки: контур 2</code>", parse_mode=ParseMode.HTML, reply_markup=build_headers_kb())
        except BadRequest:
            pass
        return

    # Timeline
    if data == 'CFG:T:SET':
        pending_actions[chat_id] = {"path": "clips.duration_seconds", "type": "int", "min": 5, "max": 300}
        try:
            await query.edit_message_text(
                "Пример: <code>таймлайн: 60</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=build_timeline_kb()
            )
        except BadRequest:
            pass
        return

    # Subtitles
    if data == 'CFG:S:FONT_SIZE':
        pending_actions[chat_id] = {"path": "subtitles.font_size", "type": "int", "min": 10, "max": 120}
        try:
            await query.edit_message_text("Пример: <code>sub: размер 42</code>", parse_mode=ParseMode.HTML, reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:S:FONT_COLOR':
        pending_actions[chat_id] = {"path": "subtitles.font_color", "type": "color"}
        try:
            await query.edit_message_text("Пример: <code>sub: цвет #FFFFFF</code>", parse_mode=ParseMode.HTML, reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:S:STROKE_COLOR':
        pending_actions[chat_id] = {"path": "subtitles.stroke_color", "type": "color"}
        try:
            await query.edit_message_text("Пример: <code>sub: контур цвет #000000</code>", parse_mode=ParseMode.HTML, reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:S:STROKE_WIDTH':
        pending_actions[chat_id] = {"path": "subtitles.stroke_width", "type": "int", "min": 0, "max": 20}
        try:
            await query.edit_message_text("Пример: <code>sub: контур 2</code>", parse_mode=ParseMode.HTML, reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:S:FONT_PATH':
        pending_actions[chat_id] = {"path": "subtitles.font_path", "type": "str", "maxlen": 200}
        try:
            await query.edit_message_text("Пример: <code>sub: шрифт Obelix_Pro.ttf</code>", parse_mode=ParseMode.HTML, reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:S:FONT_UPLOAD':
        pending_actions[chat_id] = {"path": "subtitles.font_path", "type": "file_setting", "accept": [".ttf", ".otf"]}
        try:
            await query.edit_message_text("Пришлите файл шрифта (.ttf/.otf) сообщением.", reply_markup=build_subtitles_kb())
        except BadRequest:
            pass
        return

    # Layout
    if data == 'CFG:L:SCALE':
        pending_actions[chat_id] = {"path": "layout.main_video_scale", "type": "float", "minf": 0.3, "maxf": 1.0}
        try:
            await query.edit_message_text("Пример: <code>макет: масштаб 0.70</code>", parse_mode=ParseMode.HTML, reply_markup=build_layout_kb())
        except BadRequest:
            pass
        return

    # Background music
    if data == 'CFG:BGM:TOGGLE':
        settings = load_user_settings(chat_id)
        new_val = not bool(get_value(settings, 'background_music.enabled', True))
        update_user_settings(chat_id, {"background_music": {"enabled": new_val}})
        state = 'ON' if new_val else 'OFF'
        try:
            await query.edit_message_text(f"🎵 Переключено: {state}", reply_markup=build_bg_music_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BGM:PATH':
        pending_actions[chat_id] = {"path": "background_music.path", "type": "str", "maxlen": 300}
        try:
            await query.edit_message_text("Пример: <code>музыка: путь assets/default_background_music.mp3</code>", parse_mode=ParseMode.HTML, reply_markup=build_bg_music_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BGM:VOL':
        pending_actions[chat_id] = {"path": "background_music.volume", "type": "float", "minf": 0.0, "maxf": 2.0}
        try:
            await query.edit_message_text("Пример: <code>музыка: громкость 0.1</code>", parse_mode=ParseMode.HTML, reply_markup=build_bg_music_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BGM:UPLOAD':
        pending_actions[chat_id] = {"path": "background_music.path", "type": "file_setting", "accept": [".mp3", ".wav", ".m4a", ".aac"]}
        try:
            await query.edit_message_text("Пришлите аудиофайл музыки (mp3/wav/m4a/aac).", reply_markup=build_bg_music_kb(chat_id))
        except BadRequest:
            pass
        return

    # Banner
    if data == 'CFG:BN:TOGGLE':
        settings = load_user_settings(chat_id)
        new_val = not bool(get_value(settings, 'banner.enabled', True))
        update_user_settings(chat_id, {"banner": {"enabled": new_val}})
        state = 'ON' if new_val else 'OFF'
        try:
            await query.edit_message_text(f"🖼️ Переключено: {state}", reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:PATH':
        pending_actions[chat_id] = {"path": "banner.path", "type": "str", "maxlen": 300}
        try:
            await query.edit_message_text("Пример: <code>баннер: путь 0830.mov</code>", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:UPLOAD':
        pending_actions[chat_id] = {"path": "banner.path", "type": "file_setting", "accept": [".mp4", ".mov", ".mkv", ".webm"]}
        try:
            await query.edit_message_text("Пришлите видеофайл баннера (mp4/mov/mkv/webm).", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:X':
        pending_actions[chat_id] = {"path": "banner.x", "type": "int", "min": -5000, "max": 5000}
        try:
            await query.edit_message_text("Пример: <code>баннер: x 0</code>", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:Y':
        pending_actions[chat_id] = {"path": "banner.y", "type": "int", "min": -5000, "max": 5000}
        try:
            await query.edit_message_text("Пример: <code>баннер: y 360</code>", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:COLOR':
        pending_actions[chat_id] = {"path": "banner.chroma_key_color", "type": "color"}
        try:
            await query.edit_message_text("Пример: <code>баннер: цвет #000000</code>", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:SIM':
        pending_actions[chat_id] = {"path": "banner.chroma_key_similarity", "type": "float", "minf": 0.0, "maxf": 1.0}
        try:
            await query.edit_message_text("Пример: <code>баннер: sim 0.1</code>", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return
    if data == 'CFG:BN:BLEND':
        pending_actions[chat_id] = {"path": "banner.chroma_key_blend", "type": "float", "minf": 0.0, "maxf": 1.0}
        try:
            await query.edit_message_text("Пример: <code>баннер: blend 0.2</code>", parse_mode=ParseMode.HTML, reply_markup=build_banner_kb(chat_id))
        except BadRequest:
            pass
        return

    # Cookies
    if data == 'CFG:CK:UPLOAD':
        pending_actions[chat_id] = {"type": "cookies_file"}
        try:
            await query.edit_message_text("Пришлите файл cookies.txt сообщением.", reply_markup=build_cookies_kb())
        except BadRequest:
            pass
        return
    if data == 'CFG:CK:TEXT':
        pending_actions[chat_id] = {"type": "cookies_text"}
        try:
            await query.edit_message_text("Вставьте текст cookies (как в cookies.txt).", reply_markup=build_cookies_kb())
        except BadRequest:
            pass
        return

# ======= ПРИЕМ ТЕКСТА/ФАЙЛОВ ДЛЯ ПАРАМЕТРОВ =======

def _parse_color(value: str) -> str:
    v = value.strip()
    if re.fullmatch(r'#([0-9A-Fa-f]{6})', v):
        return v
    raise ValueError('color')

async def _apply_pending(chat_id: int, text: str, update: Update) -> bool:
    action = pending_actions.get(chat_id)
    if not action:
        return False
    try:
        if action.get('type') == 'headers':
            if ':' in text and '|' in text:
                top, bottom = text.split(':', 1)[1].split('|', 1)
                top = top.strip()
                bottom = bottom.strip()
                if len(top) > 50 or len(bottom) > 50:
                    await update.message.reply_text("❌ Слишком длинно (макс 50). Попробуйте снова.")
                    return True
                update_user_settings(chat_id, {"headers": {"top": top, "bottom": bottom}})
                await update.message.reply_text("✅ Заголовки сохранены.")
                pending_actions.pop(chat_id, None)
                return True
            else:
                await update.message.reply_text("❌ Формат: 'заголовки: ВЕРХ | НИЗ'")
                return True
        if action.get('type') == 'cookies_text':
            # Normalize and save cookies text to both global and per-user paths
            normalized = normalize_cookies_text(text)
            global_path = Path(COOKIES_FILE)
            user_dir = USER_ASSETS_DIR / str(chat_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            user_path = user_dir / 'cookies.txt'
            with open(global_path, 'w', encoding='utf-8') as f:
                f.write(normalized)
            with open(user_path, 'w', encoding='utf-8') as f:
                f.write(normalized)
            await update.message.reply_text(f"✅ Cookies сохранены.\nГлобально: {global_path}\nДля пользователя: {user_path}")
            pending_actions.pop(chat_id, None)
            return True
        path = action['path']
        t = action.get('type')
        if t == 'str':
            # берём часть после ':' если есть
            val = text.split(':', 1)[-1].strip()
            if action.get('maxlen') and len(val) > action['maxlen']:
                await update.message.reply_text("❌ Слишком длинное значение.")
                return True
            _patch = {}
            d = _patch
            keys = path.split('.')
            for k in keys[:-1]:
                d.setdefault(k, {})
                d = d[k]
            d[keys[-1]] = val
            update_user_settings(chat_id, _patch)
            await update.message.reply_text("✅ Сохранено.")
            pending_actions.pop(chat_id, None)
            return True
        if t == 'int':
            val_str = re.findall(r'(-?\d+)', text)
            if not val_str:
                raise ValueError('int')
            val = int(val_str[0])
            if ('min' in action and val < action['min']) or ('max' in action and val > action['max']):
                await update.message.reply_text("❌ Вне допустимого диапазона.")
                return True
            _patch = {}; d = _patch; keys = path.split('.')
            for k in keys[:-1]: d.setdefault(k, {}); d = d[k]
            d[keys[-1]] = val
            update_user_settings(chat_id, _patch)
            await update.message.reply_text("✅ Сохранено.")
            pending_actions.pop(chat_id, None)
            return True
        if t == 'float':
            m = re.search(r'(-?\d+(?:[\.,]\d+)?)', text)
            if not m:
                raise ValueError('float')
            val = float(m.group(1).replace(',', '.'))
            if ('minf' in action and val < action['minf']) or ('maxf' in action and val > action['maxf']):
                await update.message.reply_text("❌ Вне допустимого диапазона.")
                return True
            _patch = {}; d = _patch; keys = path.split('.')
            for k in keys[:-1]: d.setdefault(k, {}); d = d[k]
            d[keys[-1]] = val
            update_user_settings(chat_id, _patch)
            await update.message.reply_text("✅ Сохранено.")
            pending_actions.pop(chat_id, None)
            return True
        if t == 'color':
            color_match = re.search(r'#([0-9A-Fa-f]{6})', text)
            if not color_match:
                raise ValueError('color')
            color = f"#{color_match.group(1)}"
            _patch = {}; d = _patch; keys = path.split('.')
            for k in keys[:-1]: d.setdefault(k, {}); d = d[k]
            d[keys[-1]] = color
            update_user_settings(chat_id, _patch)
            await update.message.reply_text("✅ Цвет сохранен.")
            pending_actions.pop(chat_id, None)
            return True
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Посмотрите пример и попробуйте снова.")
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения настройки: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте снова.")
        return True
    return False

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    action = pending_actions.get(chat_id)
    if not action:
        await update.message.reply_text("Файл получен. Откройте /settings, чтобы указать, куда применить файл.")
        return
    try:
        if update.message.document is None:
            await update.message.reply_text("❌ Это не документ. Пришлите файл сообщением.")
            return
        file = await context.bot.get_file(update.message.document.file_id)
        filename = update.message.document.file_name or 'file'
        suffix = ''.join(Path(filename).suffixes)
        # Cookies upload (global + per-user)
        if action.get('type') == 'cookies_file':
            # Download to memory then normalize
            tmp_path = USER_ASSETS_DIR / str(chat_id) / ('tmp_' + filename)
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            await file.download_to_drive(custom_path=str(tmp_path))
            raw = ''
            try:
                raw = tmp_path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                raw = tmp_path.read_text(errors='ignore')
            normalized = normalize_cookies_text(raw)
            # Save global
            dest = Path(COOKIES_FILE)
            dest.parent.mkdir(exist_ok=True)
            dest.write_text(normalized, encoding='utf-8')
            # Save per-user
            user_dir = USER_ASSETS_DIR / str(chat_id)
            user_dir.mkdir(parents=True, exist_ok=True)
            user_path = user_dir / 'cookies.txt'
            user_path.write_text(normalized, encoding='utf-8')
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            pending_actions.pop(chat_id, None)
            await update.message.reply_text(f"✅ Cookies сохранены.\nГлобально: {dest}\nДля пользователя: {user_path}")
            return
        # Setting file upload
        if action.get('type') == 'file_setting':
            accept = action.get('accept')
            if accept and suffix.lower() not in accept:
                await update.message.reply_text("❌ Неверный тип файла для этого параметра.")
                return
            save_dir = USER_ASSETS_DIR / str(chat_id)
            save_dir.mkdir(parents=True, exist_ok=True)
            dest = save_dir / filename
            await file.download_to_drive(custom_path=str(dest))
            # Patch settings
            path = action['path']
            _patch = {}; d = _patch; keys = path.split('.')
            for k in keys[:-1]: d.setdefault(k, {}); d = d[k]
            d[keys[-1]] = str(dest)
            update_user_settings(chat_id, _patch)
            pending_actions.pop(chat_id, None)
            await update.message.reply_text(f"✅ Файл сохранен и применен: {dest}")
            return
        await update.message.reply_text("❌ Этот тип файла здесь не ожидается.")
    except Exception as e:
        logger.error(f"Ошибка загрузки файла: {e}")
        await update.message.reply_text("❌ Не удалось сохранить файл. Попробуйте снова.")

# ======= ОСНОВНОЙ ФЛОУ ОБРАБОТКИ =======

async def handle_youtube_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик YouTube ссылок - скачивает и обрабатывает видео"""
    url = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    if not is_youtube_url(url):
        await update.message.reply_text(
            "❌ Это не похоже на ссылку YouTube. Пожалуйста, отправьте корректную ссылку."
        )
        return
    
    status_message = await update.message.reply_text(
        "🎬 Начинаю обработку видео..."
    )
    
    try:
        await status_message.edit_text(
            "📥 <b>Этап 1/5:</b> Скачивание видео...",
            parse_mode=ParseMode.HTML
        )
        
        file_path = await downloader.download_video(url, chat_id)
        
        if not file_path:
            await status_message.edit_text(
                "❌ Не удалось скачать видео. Возможно, видео недоступно или слишком большое."
            )
            return
        
        await status_message.edit_text(
            "🎞️ <b>Этап 2/5:</b> Анализ и нарезка на чанки...",
            parse_mode=ParseMode.HTML
        )
        
        top_header, bottom_header = get_user_headers(chat_id)
        timeline = get_user_timeline(chat_id)
        
        await status_message.edit_text(
            "🎤 <b>Этап 3/5:</b> Создание вертикальных видео с субтитрами...",
            parse_mode=ParseMode.HTML
        )

        settings = load_user_settings(chat_id)
        
        archive_path = await processor.process_video(file_path, chat_id, top_header, bottom_header, segment_duration=timeline, settings=settings)
        
        if not archive_path:
            await status_message.edit_text(
                "❌ Не удалось обработать видео. Попробуйте другое видео."
            )
            downloader.cleanup_file(file_path)
            return

        if archive_path.endswith('.txt'):
            await status_message.edit_text(
                "☁️ <b>Этап 4/5:</b> Загрузка на Google Drive...",
                parse_mode=ParseMode.HTML
            )
            with open(archive_path, 'rb') as links_file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=links_file,
                    filename=f"uploaded_links_{chat_id}.txt",
                    caption="✅ Ссылки на все клипы загружены!"
                )
            processor.cleanup_temp_files(chat_id)
            await status_message.edit_text(
                "✅ <b>Этап 5/5:</b> Готово!",
                parse_mode=ParseMode.HTML
            )
            await status_message.delete()
        elif archive_path.endswith('.zip'):
            await status_message.edit_text(
                "📦 <b>Этап 4/5:</b> Финальная нарезка и архивация...",
                parse_mode=ParseMode.HTML
            )

            await status_message.edit_text(
                f"📤 <b>Этап 5/5:</b> Отправка архива...",
                parse_mode=ParseMode.HTML
            )
            
            file_size = processor.get_file_size(archive_path)
            
            if file_size > MAX_FILE_SIZE:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Архив слишком большой ({file_size / (1024*1024):.1f} MB) для отправки в Telegram.\n\n" 
                         f"Он сохранен в кеше проекта по пути: {archive_path}"
                )
            else:
                with open(archive_path, 'rb') as archive_file:
                    caption = f"✅ Готовый архив с видео\n"
                    caption += f"📦 Все видео нарезаны на {timeline}-секундные клипы\n"
                    caption += "🚀 Готово к публикации!"
                    
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=archive_file,
                        filename=f"final_videos_{chat_id}.zip",
                        caption=caption
                    )
                # Удаляем только после успешной отправки
                processor.cleanup_temp_files(chat_id)
            
            await status_message.delete() 
            
            final_message = f"🎉 <b>Обработка завершена!</b>\n\n"
            final_message += f"📊 <b>Результат:</b>\n"
            final_message += f"• Создан ZIP-архив с короткими видео\n"
            final_message += f"• Формат: 9:16 (вертикальный)\n"
            final_message += f"• Субтитры: Анимированные по словам\n\n"
            final_message += f"🚀 Готово к публикации в соцсетях!"
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=final_message,
                parse_mode=ParseMode.HTML
            )
        else: # It's a message from the google drive uploader
            await status_message.edit_text(
                "☁️ <b>Этап 4/5:</b> Загрузка на Google Drive...",
                parse_mode=ParseMode.HTML
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=archive_path,
                parse_mode=ParseMode.HTML
            )
            processor.cleanup_temp_files(chat_id)
            await status_message.edit_text(
                "✅ <b>Этап 5/5:</b> Готово!",
                parse_mode=ParseMode.HTML
            )
            await status_message.delete()

        downloader.cleanup_file(file_path)
        
    except Exception as e:
        logger.error(f"Ошибка обработки видео: {e}")
        await status_message.edit_text(
            "❌ Произошла ошибка при обработке видео. Попробуйте позже.\n\n"
            f"Детали ошибки: {str(e)[:100]}..."
        )
        
        try:
            if 'file_path' in locals():
                downloader.cleanup_file(file_path)
            processor.cleanup_temp_files(chat_id)
        except:
            pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    # Если ожидаем ввод по кнопке — обрабатываем в первую очередь
    if await _apply_pending(chat_id, text, update):
        return
    
    # Проверяем команду настройки заголовков
    if text.lower().startswith('заголовки:'):
        await handle_headers_setting(update, context)
        return

    if text.lower().startswith('таймлайн:'):
        await handle_timeline_setting(update, context)
        return
    
    if is_youtube_url(text):
        await handle_youtube_url(update, context)
    else:
        await update.message.reply_text(
            "🤔 Я умею обрабатывать только видео с YouTube.\n"
            "Отправьте мне ссылку на YouTube видео для создания крутого вертикального контента!\n\n"
            "💡 <b>Также доступны команды:</b>\n"
            "/settings — кнопки настроек\n"
            "/reset_headers — сброс заголовков",
            parse_mode=ParseMode.HTML
        )

async def handle_headers_setting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик настройки заголовков"""
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    
    try:
        # Извлекаем заголовки из текста
        if ':' in text and '|' in text:
            # Формат: "заголовки: верхний текст | нижний текст"
            parts = text.split(':', 1)
            if len(parts) == 2:
                headers_part = parts[1].strip()
                if '|' in headers_part:
                    top_header, bottom_header = headers_part.split('|', 1)
                    top_header = top_header.strip()
                    bottom_header = bottom_header.strip()
                    
                    # Проверяем длину заголовков
                    if len(top_header) > 50:
                        await update.message.reply_text(
                            "❌ Верхний заголовок слишком длинный! Максимум 50 символов."
                        )
                        return
                    
                    if len(bottom_header) > 50:
                        await update.message.reply_text(
                            "❌ Нижний заголовок слишком длинный! Максимум 50 символов."
                        )
                        return
                    
                    # Сохраняем заголовки пользователя
                    update_user_settings(chat_id, {"headers": {"top": top_header, "bottom": bottom_header}})
                    
                    await update.message.reply_text(
                        f"✅ <b>Заголовки успешно обновлены!</b>\n\n"
                        f"🔝 <b>Верхний заголовок:</b>\n"
                        f"<code>{top_header}</code>\n\n"
                        f"🔻 <b>Нижний заголовок:</b>\n"
                        f"<code>{bottom_header}</code>\n\n"
                        f"Теперь все новые ролики будут создаваться с этими заголовками!",
                        parse_mode=ParseMode.HTML
                    )
                    return
                else:
                    await update.message.reply_text(
                        "❌ <b>Неверный формат!</b>\n\n"
                        "Используйте формат:\n"
                        "<code>заголовки: верхний текст | нижний текст</code>\n\n"
                        "💡 <b>Пример:</b>\n"
                        "<code>заголовки: 🎬 МОЙ КАНАЛ | 💫 Подписывайтесь!</code>",
                        parse_mode=ParseMode.HTML
                    )
                    return
            else:
                await update.message.reply_text(
                    "❌ <b>Неверный формат!</b>\n\n"
                    "Используйте формат:\n"
                    "<code>заголовки: верхний текст | нижний текст</code>",
                    parse_mode=ParseMode.HTML
                )
                return
        else:
            await update.message.reply_text(
                "❌ <b>Неверный формат!</b>\n\n"
                "Используйте формат:\n"
                "<code>заголовки: верхний текст | нижний текст</code>\n\n"
                "💡 <b>Пример:</b>\n"
                "<code>заголовки: 🎬 МОЙ КАНАЛ | 💫 Подписывайтесь!</code>",
                parse_mode=ParseMode.HTML
            )
            return
            
    except Exception as e:
        logger.error(f"Ошибка настройки заголовков: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при настройке заголовков. Попробуйте еще раз."
        )

def main() -> None:
    """Запуск бота"""
    sentinel_tokens = {'BOT_TOKEN'}
    # Stronger validation: empty/placeholder/invalid format
    import re
    def is_probably_valid_token(token: str) -> bool:
        return bool(token) and token not in sentinel_tokens and re.match(r'^\d+:[A-Za-z0-9_-]{30,}$', token or '') is not None
    if not is_probably_valid_token(BOT_TOKEN):
        print("❌ Ошибка: Неверный или отсутствует BOT_TOKEN!")
        print("Установите переменную окружения BOT_TOKEN или измените значение в config.py")
        print("Windows PowerShell:  $env:BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        print("Windows CMD:         set BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        print("Linux/macOS:         export BOT_TOKEN=123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        # Показать, что именно пришло (маскируем)
        masked = (BOT_TOKEN[:5] + "..." + BOT_TOKEN[-5:]) if BOT_TOKEN and len(BOT_TOKEN) > 12 else (BOT_TOKEN or "<empty>")
        print(f"Текущее значение BOT_TOKEN: {masked}")
        return
    
    masked = BOT_TOKEN[:5] + "..." if len(BOT_TOKEN) > 8 else "***"
    print(f"✅ Найден BOT_TOKEN: {masked}")
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("reset_headers", reset_headers_command))
    application.add_handler(CallbackQueryHandler(settings_callback, pattern=r'^CFG:'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Запускаем бота
    print("🚀 YouTube Video Processor Bot запущен!")
    print("📱 Готов создавать вертикальный контент с субтитрами!")
    print("Нажмите Ctrl+C для остановки.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    import sys
    import codecs
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    if sys.stderr.encoding != 'utf-8':
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    main()