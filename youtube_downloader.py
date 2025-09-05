import yt_dlp
import os
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

USER_ASSETS_DIR = Path('user_assets')

class YouTubeDownloader:
    def __init__(self, download_dir: Path, cookies_file: Optional[Path] = None):
        self.download_dir = download_dir
        self.cookies_file = cookies_file
        
    def _resolve_cookies_path(self, chat_id: Optional[int]) -> Optional[Path]:
        try:
            if chat_id is not None:
                per_user = USER_ASSETS_DIR / str(chat_id) / 'cookies.txt'
                if per_user.exists():
                    return per_user
        except Exception:
            pass
        return self.cookies_file if self.cookies_file and Path(self.cookies_file).exists() else None
        
    def get_ydl_opts(self, output_path: str, chat_id: Optional[int] = None) -> Dict[str, Any]:
        """Получить настройки yt-dlp для скачивания"""
        opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]',
            'outtmpl': output_path,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': False,
            'no_warnings': False,
            'extractaudio': False,
            'embed_subs': False,
            'writeinfojson': False,
            'writethumbnail': False,
            'merge_output_format': 'mp4',
        }
        
        # Добавляем cookies если файл существует
        cookie_path = self._resolve_cookies_path(chat_id)
        if cookie_path and Path(cookie_path).exists():
            opts['cookiefile'] = str(cookie_path)
            
        return opts
    
    async def get_video_info(self, url: str, chat_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Получить информацию о видео без скачивания"""
        try:
            opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            cookie_path = self._resolve_cookies_path(chat_id)
            if cookie_path and Path(cookie_path).exists():
                opts['cookiefile'] = str(cookie_path)
            
            def extract_info():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            
            # Запускаем в отдельном потоке чтобы не блокировать event loop
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, extract_info)
            
            return info
            
        except Exception as e:
            logger.error(f"Ошибка получения информации о видео: {e}")
            return None
    
    async def download_video(self, url: str, chat_id: int) -> Optional[str]:
        """Скачать видео и вернуть путь к файлу"""
        try:
            # Создаем уникальную папку для каждого чата
            chat_dir = self.download_dir / str(chat_id)
            chat_dir.mkdir(parents=True, exist_ok=True)
            
            # Получаем информацию о видео
            info = await self.get_video_info(url, chat_id)
            if not info:
                return None
            
            # Создаем безопасное имя файла
            title = info.get('title', 'video')
            # Убираем недопустимые символы
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title[:50]  # Ограничиваем длину
            
            output_path = str(chat_dir / f"{safe_title}.%(ext)s")
            
            # Настройки для скачивания
            ydl_opts = self.get_ydl_opts(output_path, chat_id)
            
            def download():
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            
            # Запускаем скачивание в отдельном потоке
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, download)
            
            # Ищем скачанный файл
            for file_path in chat_dir.glob(f"{safe_title}.*"):
                if file_path.suffix in ['.mp4', '.mkv', '.webm', '.avi']:
                    return str(file_path)
            
            return None
            
        except Exception as e:
            logger.error(f"Ошибка скачивания видео: {e}")
            return None
    
    def cleanup_file(self, file_path: str):
        """Удалить файл после отправки"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Файл удален: {file_path}")
        except Exception as e:
            logger.error(f"Ошибка удаления файла {file_path}: {e}")
    
    def get_file_size(self, file_path: str) -> int:
        """Получить размер файла в байтах"""
        try:
            return os.path.getsize(file_path)
        except:
            return 0