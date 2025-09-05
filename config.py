import os
from pathlib import Path

# Load .env if present so BOT_TOKEN can be provided via a .env file
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
except Exception:
    pass

# Telegram Bot Token (получить у @BotFather)
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# Папка для скачивания видео
DOWNLOAD_DIR = Path('downloads')
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Папка для cookies файла (если есть)
COOKIES_FILE = Path('cookies.txt')

# Максимальный размер файла для отправки в Telegram (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Заголовки для готовых роликов (по умолчанию)
DEFAULT_TOP_HEADER = "Странная часть дружбы"
DEFAULT_BOTTOM_HEADER = "найс"

# Настройки шрифта
FONT_PATH = "Obelix_Pro.ttf"
FONT_SIZE = 42
FONT_COLOR = "white"
STROKE_COLOR = "black"
STROKE_WIDTH = 2

# Настройки шрифта для заголовков
TOP_HEADER_FONT_SIZE = 50
BOTTOM_HEADER_FONT_SIZE = 70
HEADER_FONT_COLOR = "red"
HEADER_STROKE_COLOR = "black"
HEADER_STROKE_WIDTH = 2
# Масштаб основного видео
MAIN_VIDEO_SCALE = 0.70

# Длительность нарезки клипов (в секундах)
CLIP_DURATION_SECONDS = 30

# Длительность нарезки видео на чанки (в секундах)
CHUNK_DURATION_SECONDS = 60

# Настройки баннера
BANNER_ENABLED = True
BANNER_PATH = "0830.mov"
BANNER_X = 0
BANNER_Y = 360
CHROMA_KEY_COLOR = "#000000"
CHROMA_KEY_SIMILARITY = 0.1
CHROMA_KEY_BLEND = 0.2

# Настройки фоновой музыки
BACKGROUND_MUSIC_ENABLED = True
BACKGROUND_MUSIC_PATH = "assets/default_background_music.mp3"
BACKGROUND_MUSIC_VOLUME = 0.1

# Настройки yt-dlp для лучшего качества
YT_DLP_OPTS = {
    'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
    'outtmpl': str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
    'writesubtitles': False,
    'writeautomaticsub': False,
    'ignoreerrors': True,
    'no_warnings': False,
    'extractaudio': False,
    'audioformat': 'mp3',
    'embed_subs': False,
    'writeinfojson': False,
    'writethumbnail': False,
}

# Добавляем cookies если файл существует
if COOKIES_FILE.exists():
    YT_DLP_OPTS['cookiefile'] = str(COOKIES_FILE)

# Google Drive
GOOGLE_OAUTH_TOKEN_BASE64 = os.getenv('GOOGLE_OAUTH_TOKEN_BASE64')
TOKEN_PICKLE_FILE = 'token.pickle'
