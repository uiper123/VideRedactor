import os
from pathlib import Path

# Telegram Bot Token (получить у @BotFather)
BOT_TOKEN = os.getenv('BOT_TOKEN', '7850144731:AAHeHudyAVljC2J_CR8NLZznqnDHu8ZgLUw')

# Папка для скачивания видео
DOWNLOAD_DIR = Path('downloads')
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Папка для cookies файла (если есть)
COOKIES_FILE = Path('cookies.txt')

# Максимальный размер файла для отправки в Telegram (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

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