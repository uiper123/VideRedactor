import os
import zipfile
from faster_whisper import WhisperModel
import ffmpeg
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging
import asyncio
import json
import math
import subprocess
import tempfile
import re
from tqdm import tqdm
import threading
import time

from google_drive_uploader import upload_to_drive

from config import (
    FONT_PATH, FONT_SIZE, FONT_COLOR, STROKE_COLOR, STROKE_WIDTH, 
    TOP_HEADER_FONT_SIZE, BOTTOM_HEADER_FONT_SIZE, HEADER_FONT_COLOR, HEADER_STROKE_COLOR, HEADER_STROKE_WIDTH, 
    MAIN_VIDEO_SCALE,
    BANNER_ENABLED, BANNER_PATH, BANNER_X, BANNER_Y, 
    CHROMA_KEY_COLOR, CHROMA_KEY_SIMILARITY, CHROMA_KEY_BLEND,
    BACKGROUND_MUSIC_ENABLED, BACKGROUND_MUSIC_PATH, BACKGROUND_MUSIC_VOLUME,
    CHUNK_DURATION_SECONDS, CLIP_DURATION_SECONDS
)

from PIL import Image
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class FastVideoProcessor:
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(exist_ok=True)
        
        try:
            self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            logger.info("Модель Faster-Whisper 'base' успешно загружена (CPU, int8)")
        except Exception as e:
            logger.error(f"Ошибка загрузки Faster-Whisper: {e}")
            self.whisper_model = None

    async def process_video(self, video_path: str, chat_id: int, top_header: str = None, bottom_header: str = None, background_music_path: Optional[str] = None, segment_duration: Optional[int] = None, settings: Optional[Dict] = None) -> Optional[str]:
        """Основная функция обработки видео"""
        try:
            chat_dir = self.temp_dir / str(chat_id)
            chat_dir.mkdir(exist_ok=True)
            
            video_info = await self.get_video_info(video_path)
            duration = video_info.get('duration', 0)
            
            logger.info(f"Обрабатываем видео длительностью {duration} секунд")
            
            if duration > 300:
                chunks = await self.split_video_into_chunks(video_path, chat_dir)
            else:
                chunks = [video_path]
            
            processed_videos = []
            for i, chunk_path in enumerate(chunks):
                logger.info(f"Обрабатываем чанк {i+1}/{len(chunks)}")
                subtitles = await self.generate_subtitles(chunk_path)
                vertical_video = await self.create_vertical_video_fast(
                    chunk_path, subtitles, chat_dir, i, background_music_path, chat_id, top_header, bottom_header, settings=settings
                )
                if vertical_video:
                    processed_videos.append(vertical_video)
            
            if processed_videos:
                upload_result = await self.cut_and_upload_to_drive(processed_videos, chat_id, clip_duration=segment_duration)
                return upload_result
            
            return None
        except Exception as e:
            logger.error(f"Ошибка обработки видео: {e}")
            return None

    async def cut_and_upload_to_drive(self, video_paths: List[str], chat_id: int, clip_duration: Optional[int] = None) -> Optional[str]:
        """Нарезает видео на сегменты, загружает их на Google Drive и возвращает путь к файлу со ссылками."""
        try:
            chat_dir = self.temp_dir / str(chat_id)
            final_clips_dir = chat_dir / "final_clips"
            final_clips_dir.mkdir(exist_ok=True)
            
            folder_name = f"final_videos_{chat_id}"
            
            # Выбор длительности клипа: параметр пользователя или значение по умолчанию из конфигурации
            actual_clip_duration = clip_duration if clip_duration and clip_duration > 0 else CLIP_DURATION_SECONDS
            
            clip_paths = []
            for i, video_path in enumerate(video_paths):
                video_info = await self.get_video_info(video_path)
                total_duration = video_info['duration']
                num_segments = math.ceil(total_duration / actual_clip_duration)
                
                for j in range(num_segments):
                    start_time = j * actual_clip_duration
                    output_path = final_clips_dir / f"clip_{i}_{j}.mp4"
                    
                    (
                        ffmpeg.input(video_path, ss=start_time, t=actual_clip_duration)
                        .output(str(output_path), avoid_negative_ts='make_zero')
                        .overwrite_output()
                        .run(quiet=True)
                    )
                    clip_paths.append(output_path)

            uploaded_links = []
            loop = asyncio.get_event_loop()
            for clip_path in clip_paths:
                link = await loop.run_in_executor(None, upload_to_drive, str(clip_path), folder_name)
                if link:
                    direct_link = self.to_drive_direct_download(link)
                    uploaded_links.append(direct_link)
            
            links_file_path = chat_dir / "uploaded_links.txt"
            with open(links_file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(uploaded_links))

            return str(links_file_path)
        except Exception as e:
            logger.error(f"Ошибка нарезки и загрузки на Google Drive: {e}")
            return None

    async def get_video_info(self, video_path: str) -> Dict:
        """Получить информацию о видео"""
        try:
            def get_info():
                probe = ffmpeg.probe(video_path)
                video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
                return {
                    'duration': float(probe['format']['duration']),
                    'width': int(video_stream['width']),
                    'height': int(video_stream['height']),
                    'fps': eval(video_stream['r_frame_rate'])
                }
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, get_info)
        except Exception as e:
            logger.error(f"Ошибка получения информации о видео: {e}")
            return {'duration': 0, 'width': 1920, 'height': 1080, 'fps': 30}

    async def split_video_into_chunks(self, video_path: str, output_dir: Path) -> List[str]:
        """Нарезка видео на чанки по 5 минут"""
        try:
            video_info = await self.get_video_info(video_path)
            total_duration = video_info['duration']
            chunk_count = math.ceil(total_duration / CHUNK_DURATION_SECONDS)
            chunks = []

            logger.info(f"✂️ Нарезаем видео на {chunk_count} чанков...")
            with tqdm(total=chunk_count, desc="✂️ Нарезка видео", unit="чанк") as pbar:
                for i in range(chunk_count):
                    start_time = i * CHUNK_DURATION_SECONDS
                    output_path = output_dir / f"chunk_{i:03d}.mp4"
                    (ffmpeg.input(video_path, ss=start_time, t=CHUNK_DURATION_SECONDS).output(str(output_path), c='copy', avoid_negative_ts='make_zero').overwrite_output().run(quiet=True))
                    chunks.append(str(output_path))
                    pbar.update(1)
            
            logger.info(f"Видео нарезано на {len(chunks)} чанков")
            return chunks
        except Exception as e:
            logger.error(f"Ошибка нарезки видео: {e}")
            return [video_path]

    async def generate_subtitles(self, video_path: str) -> List[Dict]:
        """Генерация субтитров через Faster-Whisper"""
        try:
            if not self.whisper_model:
                logger.error("Модель Faster-Whisper не загружена")
                return []
            def transcribe():
                logger.info("🤖 Генерируем субтитры через Faster-Whisper AI...")
                segments, info = self.whisper_model.transcribe(video_path, word_timestamps=True, language='ru', beam_size=5)
                subtitles = []
                total_segments = info.duration
                with tqdm(total=total_segments, desc="🎤 Обработка речи", unit="сек") as pbar:
                    for segment in segments:
                        if segment.words:
                            for word in segment.words:
                                subtitles.append({'start': word.start, 'end': word.end, 'text': word.word.strip(), 'confidence': word.probability})
                        pbar.update(segment.end - segment.start)
                logger.info(f"Обнаружен язык: {info.language} (вероятность: {info.language_probability:.2f})")
                return subtitles
            loop = asyncio.get_event_loop()
            subtitles = await loop.run_in_executor(None, transcribe)
            logger.info(f"Сгенерировано {len(subtitles)} субтитров")
            return subtitles
        except Exception as e:
            logger.error(f"Ошибка генерации субтитров: {e}")
            return []

    async def create_vertical_video_fast(
        self, video_path: str, subtitles: List[Dict], output_dir: Path, chunk_index: int,
        background_music_path: Optional[str] = None, chat_id: int = None,
        top_header: str = None, bottom_header: str = None, settings: Optional[Dict] = None
    ) -> Optional[str]:
        """Быстрое создание вертикального видео через FFmpeg"""
        output_path = output_dir / f"vertical_{chunk_index:03d}.mp4"
        srt_path = output_dir / f"subtitles_{chunk_index:03d}.srt"
        
        # Resolve settings with fallbacks to global config
        s = settings or {}
        main_video_scale = s.get('layout', {}).get('main_video_scale', MAIN_VIDEO_SCALE)
        music_enabled = s.get('background_music', {}).get('enabled', BACKGROUND_MUSIC_ENABLED)
        music_path_cfg = s.get('background_music', {}).get('path', BACKGROUND_MUSIC_PATH)
        music_volume = s.get('background_music', {}).get('volume', BACKGROUND_MUSIC_VOLUME)
        banner_enabled = s.get('banner', {}).get('enabled', BANNER_ENABLED)
        banner_path = s.get('banner', {}).get('path', BANNER_PATH)
        banner_x = s.get('banner', {}).get('x', BANNER_X)
        banner_y = s.get('banner', {}).get('y', BANNER_Y)
        chroma_color = s.get('banner', {}).get('chroma_key_color', CHROMA_KEY_COLOR)
        chroma_similarity = s.get('banner', {}).get('chroma_key_similarity', CHROMA_KEY_SIMILARITY)
        chroma_blend = s.get('banner', {}).get('chroma_key_blend', CHROMA_KEY_BLEND)
        subs_font_path = (Path(__file__).parent / s.get('subtitles', {}).get('font_path', FONT_PATH)).as_posix()
        subs_font_size = int(s.get('subtitles', {}).get('font_size', FONT_SIZE) * 1.5)
        subs_font_color = s.get('subtitles', {}).get('font_color', FONT_COLOR)
        subs_stroke_color = s.get('subtitles', {}).get('stroke_color', STROKE_COLOR)
        subs_stroke_width = s.get('subtitles', {}).get('stroke_width', STROKE_WIDTH)
        header_font_color = s.get('headers', {}).get('header_font_color', HEADER_FONT_COLOR)
        header_stroke_color = s.get('headers', {}).get('header_stroke_color', HEADER_STROKE_COLOR)
        header_stroke_width = s.get('headers', {}).get('header_stroke_width', HEADER_STROKE_WIDTH)
        top_font_size = s.get('headers', {}).get('top_font_size', TOP_HEADER_FONT_SIZE)
        bottom_font_size = s.get('headers', {}).get('bottom_font_size', BOTTOM_HEADER_FONT_SIZE)

        try:
            def create_vertical():
                
                logger.info("Создаем вертикальное видео через FFmpeg...")
                probe = ffmpeg.probe(video_path)
                video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
                width, height = int(video_stream['width']), int(video_stream['height'])
                target_width, target_height = 1080, 1920
                self.create_srt_file(subtitles, srt_path)

                # Новая логика для основного видео: делаем его больше и обрезаем по бокам
                # Устанавливаем ширину на 100%, а высоту оставляем на 70%
                main_video_height_on_canvas = int(target_height * main_video_scale)
                main_video_width_on_canvas = target_width

                # Соотношение сторон для основного видео (3:4)
                new_aspect_ratio = main_video_width_on_canvas / main_video_height_on_canvas

                # Определяем, как кропать: по ширине или по высоте
                if (width / height) > new_aspect_ratio:
                    # Видео шире, чем нужно -> кропаем ширину
                    new_width = int(height * new_aspect_ratio)
                    crop_x = (width - new_width) // 2
                    crop_y = 0
                    crop_width = new_width
                    crop_height = height
                else:
                    # Видео выше, чем нужно -> кропаем высоту
                    new_height = int(width / new_aspect_ratio)
                    crop_x = 0
                    crop_y = (height - new_height) // 2
                    crop_width = width
                    crop_height = new_height
                
                input_video = ffmpeg.input(video_path, **{'noautorotate': None})
                background = input_video.filter('scale', target_width, target_height).filter('gblur', sigma=20)
                
                # Обрезаем и масштабируем основное видео
                main_video = input_video.crop(crop_x, crop_y, crop_width, crop_height)
                main_video = main_video.filter('scale', main_video_width_on_canvas, main_video_height_on_canvas)

                # Центрируем основное видео
                x_offset = (target_width - main_video_width_on_canvas) // 2
                y_offset = (target_height - main_video_height_on_canvas) // 2
                composed = ffmpeg.overlay(background, main_video, x=x_offset, y=y_offset).filter('setdar', '9/16')
                duration = float(probe['format']['duration'])

                
                
                audio = input_video.audio
                if music_enabled:
                    music_path_to_use = background_music_path or self.get_custom_background_music(chat_id) or music_path_cfg
                    if music_path_to_use and os.path.exists(music_path_to_use):
                        audio = self.add_background_music(audio, music_path_to_use, duration, music_volume)

                if subtitles:
                    composed = self.add_animated_subtitles(composed, subtitles, target_width, target_height, subs_font_path, subs_font_size, subs_font_color, subs_stroke_color, subs_stroke_width)

                if top_header:
                    composed = self.add_header(composed, top_header, target_width, target_height, 'top', top_font_size, header_font_color, header_stroke_color, header_stroke_width)
                if bottom_header:
                    composed = self.add_header(composed, bottom_header, target_width, target_height, 'bottom', bottom_font_size, header_font_color, header_stroke_color, header_stroke_width)

                if banner_enabled and os.path.exists(banner_path):
                    composed = self.add_ivideo_banner(composed, banner_path, duration, chroma_color, chroma_similarity, chroma_blend, banner_x, banner_y)

                if audio:
                    output_args = ffmpeg.output(composed, audio, str(output_path), vcodec='libx264', acodec='aac', preset='fast', crf=18, pix_fmt='yuv420p', movflags='faststart').overwrite_output()
                else:
                    output_args = ffmpeg.output(composed, str(output_path), vcodec='libx264', preset='fast', crf=23, pix_fmt='yuv420p', movflags='faststart').overwrite_output()
                
                cmd_args = ffmpeg.compile(output_args)
                logger.info("Начинаем рендеринг вертикального видео...")
                success = self.run_ffmpeg_with_progress(cmd_args, duration, f"🎬 Создание вертикального видео {chunk_index+1}")
                
                if not success:
                    logger.warning("Прогресс-бар не сработал, запускаем FFmpeg обычным способом...")
                    try:
                        output_args.run(quiet=True, overwrite_output=True)
                        success = True
                    except ffmpeg.Error as e:
                        logger.error(f"FFmpeg ошибка: {e.stderr.decode('utf-8', errors='ignore')}")
                        return None
                
                if not success:
                    return None
                return str(output_path)

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, create_vertical)
            logger.info(f"Создано вертикальное видео: {result}")
            return result
        except Exception as e:
            logger.error(f"Ошибка создания вертикального видео: {e}")
            return None
        finally:
            # Очистка временных файлов
            if srt_path.exists(): srt_path.unlink() 
            

    def create_srt_file(self, subtitles: List[Dict], srt_path: Path):
        try:
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.seconds_to_srt_time(subtitle['start'])
                    end_time = self.seconds_to_srt_time(subtitle['end'])
                    f.write(f"{i}\n{start_time} --> {end_time}\n{subtitle['text']}\n\n")
        except Exception as e: logger.error(f"Ошибка создания SRT файла: {e}")

    def seconds_to_srt_time(self, seconds: float) -> str:
        hours, rem = divmod(seconds, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d},{int((seconds % 1) * 1000):03d}"

    def cleanup_temp_files(self, chat_id: int):
        try:
            chat_dir = self.temp_dir / str(chat_id)
            if chat_dir.exists():
                import shutil
                shutil.rmtree(chat_dir)
                logger.info(f"Временные файлы для чата {chat_id} удалены")
        except Exception as e: logger.error(f"Ошибка очистки временных файлов: {e}")

    def run_ffmpeg_with_progress(self, cmd_args: List[str], duration: float, description: str = "Processing"):
        try:
            process = subprocess.Popen(cmd_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='ignore')
            with tqdm(total=100, desc=description, unit='%', bar_format='{l_bar}{bar}| {n:.1f}% [{elapsed}<{remaining}]') as pbar:
                stderr_lines = []
                for line in process.stderr:
                    stderr_lines.append(line.strip())
                    time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                    if time_match:
                        h, m, s = map(float, time_match.groups())
                        current_time = h * 3600 + m * 60 + s
                        progress = min((current_time / duration) * 100, 100)
                        pbar.n = progress
                        pbar.refresh()
            return_code = process.wait(timeout=3600) # Увеличиваем таймаут до 1 часа
            if return_code != 0:
                logger.error(f"FFmpeg завершился с кодом {return_code}")
                logger.error("Последние 10 строк вывода FFmpeg:")
                for line in stderr_lines[-10:]:
                    logger.error(f"  {line}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error("FFmpeg процесс был убит по таймауту (1 час)")
            process.kill()
            return False
        except Exception as e:
            logger.error(f"Ошибка запуска FFmpeg с прогрессом: {e}")
            return False

    def add_animated_subtitles(self, video_stream, subtitles: List[Dict], width: int, height: int, font_path: str, font_size: int, font_color: str, stroke_color: str, stroke_width: int):
        try:
            if not subtitles:
                return video_stream

            for sub in subtitles:
                text = sub['text'].replace("'", "’").replace('"', '”').strip()
                if not text:
                    continue

                # Настройки шрифта и положения
                base_font_size = int(font_size)
                y_pos = int(height * 0.67)
                
                # Fade-in animation
                fade_duration = 0.2
                alpha_expr = f"if(lt(t,{sub['start']}),0,if(lt(t,{sub['start']}+{fade_duration}),(t-{sub['start']})/{fade_duration},1))"

                video_stream = video_stream.filter(
                    'drawtext',
                    text=text,
                    fontfile=font_path,
                    fontsize=base_font_size,
                    fontcolor=f"{font_color}",
                    bordercolor=f"{stroke_color}",
                    borderw=stroke_width,
                    x='(w-text_w)/2',
                    y=y_pos,
                    enable=f'between(t,{sub["start"]},{sub["end"]})',
                    alpha=alpha_expr
                )
            return video_stream
        except Exception as e: 
            logger.error(f"Ошибка добавления анимированных субтитров: {e}")
            return video_stream

    def get_file_size(self, file_path: str) -> int:
        try: return os.path.getsize(file_path)
        except: return 0

    def to_drive_direct_download(self, link: str) -> str:
        """Конвертирует ссылку Google Drive в прямую для скачивания."""
        try:
            # Поддерживаем форматы:
            # - https://drive.google.com/file/d/<FILE_ID>/view?usp=sharing
            # - https://drive.google.com/open?id=<FILE_ID>
            # - https://drive.google.com/uc?id=<FILE_ID>&export=download
            # - https://drive.google.com/uc?export=download&id=<FILE_ID>
            patterns = [
                r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)/",
                r"https?://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)",
                r"https?://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)",
                r"https?://drive\.google\.com/uc\?export=download&id=([a-zA-Z0-9_-]+)"
            ]
            file_id = None
            for pat in patterns:
                m = re.search(pat, link)
                if m:
                    file_id = m.group(1)
                    break
            if not file_id:
                return link
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        except Exception:
            return link

    def upload_custom_background_music(self, music_file_path: str, chat_id: int) -> Optional[str]:
        try:
            chat_dir = self.temp_dir / str(chat_id)
            chat_dir.mkdir(exist_ok=True)
            import shutil
            custom_music_path = chat_dir / f"custom_music_{chat_id}.mp3"
            shutil.copy2(music_file_path, custom_music_path)
            logger.info(f"Пользовательская музыка загружена: {custom_music_path}")
            return str(custom_music_path)
        except Exception as e: logger.error(f"Ошибка загрузки пользовательской музыки: {e}")
        return None

    def get_custom_background_music(self, chat_id: int) -> Optional[str]:
        try:
            custom_music_path = self.temp_dir / str(chat_id) / f"custom_music_{chat_id}.mp3"
            if custom_music_path.exists(): return str(custom_music_path)
            return None
        except Exception as e: logger.error(f"Ошибка получения пользовательской музыки: {e}")
        return None

    def add_background_music(self, original_audio, music_path: str, video_duration: float, volume: float = 0.1):
        try:
            if not os.path.exists(music_path): return original_audio
            music_stream = ffmpeg.input(music_path).filter('aloop', loop=-1, size=0).filter('atrim', duration=video_duration).filter('volume', volume)
            if original_audio:
                return ffmpeg.filter([original_audio, music_stream], 'amix', inputs=2, duration='first')
            return music_stream
        except Exception as e: logger.error(f"Ошибка добавления фоновой музыки: {e}")
        return original_audio

    def get_default_background_music(self) -> Optional[str]:
        try:
            default_music_path = Path(__file__).parent / "assets" / "default_background_music.mp3"
            if default_music_path.exists(): return str(default_music_path)
            alt_music_path = self.temp_dir / "default_background_music.mp3"
            if alt_music_path.exists(): return str(alt_music_path)
            return None
        except Exception as e: logger.error(f"Ошибка поиска музыки по умолчанию: {e}")
        return None

    def add_header(self, video_stream, header_text: str, width: int, height: int, position: str = 'top', font_size: int = 60, font_color: str = HEADER_FONT_COLOR, stroke_color: str = HEADER_STROKE_COLOR, stroke_width: int = HEADER_STROKE_WIDTH):
        try:
            if not header_text: return video_stream
            text = header_text.replace("'", "").replace('"', "").replace('\\', '').strip()
            if not text: return video_stream
            y_pos = int(height * 0.05) if position == 'top' else int(height * 0.12)
            font_path = (Path(__file__).parent / FONT_PATH).as_posix()
            return video_stream.filter('drawtext', text=text, fontfile=font_path, fontsize=font_size, fontcolor=font_color, bordercolor=stroke_color, borderw=stroke_width, x='(w-text_w)/2', y=y_pos, enable='gte(t,0)')
        except Exception as e: logger.error(f"Ошибка добавления заголовка {position}: {e}")
        return video_stream

    def add_ivideo_banner(self, video_stream, banner_path: str, duration: float, chroma_key_color: str, similarity: float, blend: float, x: int, y: int):
        try:
            banner = ffmpeg.input(banner_path, stream_loop=-1).filter('colorkey', color=chroma_key_color, similarity=similarity, blend=blend)
            return ffmpeg.overlay(video_stream, banner, x=x, y=y, eof_action='pass').filter('trim', duration=duration)
        except Exception as e: logger.error(f"Ошибка добавления iVideo баннера: {e}")
        return video_stream