import os
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

logger = logging.getLogger(__name__)

class FastVideoProcessor:
    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(exist_ok=True)
        
        # Загружаем модель Faster-Whisper
        try:
            # Для процессора AMD int8 - хороший баланс скорости и качества.
            self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            logger.info("Модель Faster-Whisper 'base' успешно загружена (CPU, int8)")
        except Exception as e:
            logger.error(f"Ошибка загрузки Faster-Whisper: {e}")
            self.whisper_model = None
    
    async def process_video(self, video_path: str, chat_id: int) -> List[str]:
        """Основная функция обработки видео"""
        try:
            # Создаем папку для чата
            chat_dir = self.temp_dir / str(chat_id)
            chat_dir.mkdir(exist_ok=True)
            
            # Получаем информацию о видео
            video_info = await self.get_video_info(video_path)
            duration = video_info.get('duration', 0)
            
            logger.info(f"Обрабатываем видео длительностью {duration} секунд")
            
            # Если видео длиннее 5 минут, нарезаем на чанки
            if duration > 300:  # 5 минут
                chunks = await self.split_video_into_chunks(video_path, chat_dir)
            else:
                chunks = [video_path]
            
            processed_videos = []
            
            for i, chunk_path in enumerate(chunks):
                logger.info(f"Обрабатываем чанк {i+1}/{len(chunks)}")
                
                # Генерируем субтитры
                subtitles = await self.generate_subtitles(chunk_path)
                
                # Создаем вертикальное видео с субтитрами через FFmpeg
                vertical_video = await self.create_vertical_video_fast(
                    chunk_path, subtitles, chat_dir, i
                )
                
                if vertical_video:
                    processed_videos.append(vertical_video)
            
            return processed_videos
            
        except Exception as e:
            logger.error(f"Ошибка обработки видео: {e}")
            return []
    
    async def get_video_info(self, video_path: str) -> Dict:
        """Получить информацию о видео"""
        try:
            def get_info():
                probe = ffmpeg.probe(video_path)
                video_stream = next((stream for stream in probe['streams'] 
                                   if stream['codec_type'] == 'video'), None)
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
            chunk_duration = 300  # 5 минут
            video_info = await self.get_video_info(video_path)
            total_duration = video_info['duration']
            
            chunks = []
            chunk_count = math.ceil(total_duration / chunk_duration)
            
            def split_chunk(i):
                start_time = i * chunk_duration
                output_path = output_dir / f"chunk_{i:03d}.mp4"
                
                # Используем ffmpeg для быстрой нарезки без перекодирования
                (
                    ffmpeg
                    .input(video_path, ss=start_time, t=chunk_duration)
                    .output(str(output_path), c='copy', avoid_negative_ts='make_zero')
                    .overwrite_output()
                    .run(quiet=True)
                )
                
                return str(output_path)
            
            # Нарезаем чанки параллельно с прогресс-баром
            logger.info(f"✂️ Нарезаем видео на {chunk_count} чанков...")
            loop = asyncio.get_event_loop()
            tasks = []
            
            with tqdm(total=chunk_count, desc="✂️ Нарезка видео", unit="чанк") as pbar:
                for i in range(chunk_count):
                    task = loop.run_in_executor(None, split_chunk, i)
                    tasks.append(task)
                
                # Ждем завершения всех задач с обновлением прогресса
                chunks = []
                for task in asyncio.as_completed(tasks):
                    chunk = await task
                    chunks.append(chunk)
                    pbar.update(1)
            
            # Сортируем чанки по порядку
            chunks.sort()
            
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
                
                # faster-whisper может работать напрямую с путем к видео
                segments, info = self.whisper_model.transcribe(
                    video_path,
                    word_timestamps=True,
                    language='ru',
                    beam_size=5
                )

                subtitles = []
                # tqdm для отслеживания прогресса по сегментам
                total_segments = info.duration
                with tqdm(total=total_segments, desc="🎤 Обработка речи", unit="сек") as pbar:
                    for segment in segments:
                        if segment.words:
                            for word in segment.words:
                                subtitles.append({
                                    'start': word.start,
                                    'end': word.end,
                                    'text': word.word.strip(),
                                    'confidence': word.probability
                                })
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
        self, 
        video_path: str, 
        subtitles: List[Dict], 
        output_dir: Path, 
        chunk_index: int
    ) -> Optional[str]:
        """Быстрое создание вертикального видео через FFmpeg"""
        try:
            output_path = output_dir / f"vertical_{chunk_index:03d}.mp4"
            
            def create_vertical():
                logger.info("Создаем вертикальное видео через FFmpeg...")
                
                # Получаем информацию о видео
                probe = ffmpeg.probe(video_path)
                video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
                width = int(video_stream['width'])
                height = int(video_stream['height'])
                
                # Целевые размеры 9:16
                target_width = 1080
                target_height = 1920
                
                # SRT файлы больше не нужны - используем прямые drawtext фильтры
                
                # Вычисляем размеры для основного видео (занимает 70% высоты)
                main_height = int(target_height * 0.7)
                # Вычисляем ширину с сохранением пропорций
                original_ratio = width / height
                main_width = int(main_height * original_ratio)
                
                # Позиция основного видео по центру вертикально
                x_offset = (target_width - main_width) // 2
                y_offset = int(target_height * 0.15)  # 15% отступ сверху (больше места для субтитров)
                
                # Создаем фильтр для композиции
                input_video = ffmpeg.input(video_path)
                
                # Создаем размытый фон (растягиваем и размываем)
                background = (
                    input_video
                    .filter('scale', target_width, target_height)
                    .filter('gblur', sigma=20)
                )
                
                # Масштабируем основное видео на всю ширину экрана
                # Всегда делаем видео шириной во весь экран, обрезаем по высоте если нужно
                scale_width = target_width
                scale_height = int(target_width * height / width)
                
                if scale_height > main_height:
                    # Если получается слишком высокое, обрезаем по высоте
                    main_video = (
                        input_video
                        .filter('scale', scale_width, scale_height)
                        .filter('crop', target_width, main_height, 0, (scale_height - main_height) // 2)
                    )
                else:
                    # Масштабируем до нужной высоты на всю ширину
                    main_video = (
                        input_video
                        .filter('scale', target_width, main_height)
                    )
                
                x_offset = 0  # Видео занимает всю ширину
                
                # Накладываем основное видео на фон
                composed = ffmpeg.overlay(background, main_video, x=x_offset, y=y_offset)
                
                # Получаем аудио поток отдельно
                audio = input_video.audio
                
                # Добавляем баннер с хромакеем
                banner_path = Path("banner1.mp4")
                if banner_path.exists():
                    logger.info("Добавляем баннер с хромакеем...")
                    composed = self.add_banner_with_chromakey(composed, str(banner_path), target_width, target_height)
                
                # Добавляем анимированные субтитры вместо SRT
                if subtitles:
                    logger.info("Добавляем анимированные субтитры...")
                    composed = self.add_animated_subtitles(composed, subtitles, target_width, target_height)
                
                # Получаем длительность видео для прогресс-бара
                duration = float(probe['format']['duration'])
                
                # Строим команду FFmpeg с аудио
                output_args = ffmpeg.output(
                    composed, audio,  # Добавляем и видео, и аудио потоки
                    str(output_path),
                    vcodec='libx264',
                    acodec='aac',
                    preset='fast',
                    crf=23,
                    pix_fmt='yuv420p',
                    movflags='faststart'
                ).overwrite_output()
                
                # Получаем аргументы командной строки
                cmd_args = ffmpeg.compile(output_args)
                
                # Запускаем с прогресс-баром
                logger.info("Начинаем рендеринг вертикального видео...")
                success = self.run_ffmpeg_with_progress(
                    cmd_args, 
                    duration, 
                    f"🎬 Создание вертикального видео {chunk_index+1}"
                )
                
                # Если прогресс-бар не сработал, запускаем обычным способом
                if not success:
                    logger.warning("Прогресс-бар не сработал, запускаем FFmpeg обычным способом...")
                    try:
                        output_args.run(quiet=True, overwrite_output=True)
                        success = True
                        logger.info("FFmpeg завершился успешно (без прогресс-бара)")
                    except ffmpeg.Error as e:
                        logger.error(f"FFmpeg ошибка: {e.stderr.decode('utf-8', errors='ignore')}")
                        return None
                
                if not success:
                    logger.error("Ошибка при рендеринге видео")
                    return None
                
                # SRT файлы больше не используются
                
                logger.info("Вертикальное видео создано успешно")
                return str(output_path)
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, create_vertical)
            
            logger.info(f"Создано вертикальное видео: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Ошибка создания вертикального видео: {e}")
            return None
    
    def create_srt_file(self, subtitles: List[Dict], srt_path: Path):
        """Создание SRT файла с субтитрами"""
        try:
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, subtitle in enumerate(subtitles, 1):
                    start_time = self.seconds_to_srt_time(subtitle['start'])
                    end_time = self.seconds_to_srt_time(subtitle['end'])
                    
                    f.write(f"{i}\n")
                    f.write(f"{start_time} --> {end_time}\n")
                    f.write(f"{subtitle['text']}\n\n")
            
            logger.info(f"SRT файл создан: {srt_path}")
            
        except Exception as e:
            logger.error(f"Ошибка создания SRT файла: {e}")
    
    def seconds_to_srt_time(self, seconds: float) -> str:
        """Конвертация секунд в формат времени SRT"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millisecs:03d}"
    
    def cleanup_temp_files(self, chat_id: int):
        """Очистка временных файлов"""
        try:
            chat_dir = self.temp_dir / str(chat_id)
            if chat_dir.exists():
                import shutil
                shutil.rmtree(chat_dir)
                logger.info(f"Временные файлы для чата {chat_id} удалены")
        except Exception as e:
            logger.error(f"Ошибка очистки временных файлов: {e}")
    
    def run_ffmpeg_with_progress(self, cmd_args: List[str], duration: float, description: str = "Processing"):
        """Запуск FFmpeg с отображением прогресса"""
        try:
            # Создаем процесс FFmpeg с правильной кодировкой для Windows
            process = subprocess.Popen(
                cmd_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
                encoding='utf-8',
                errors='ignore'  # Игнорируем ошибки кодировки
            )
            
            # Создаем прогресс-бар
            pbar = tqdm(
                total=100,
                desc=description,
                unit='%',
                bar_format='{l_bar}{bar}| {n:.1f}% [{elapsed}<{remaining}]'
            )
            
            stderr_lines = []
            
            # Читаем вывод FFmpeg
            while True:
                try:
                    output = process.stderr.readline()
                    if output == '' and process.poll() is not None:
                        break
                    
                    if output:
                        stderr_lines.append(output.strip())
                        
                        # Ищем информацию о времени обработки
                        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', output)
                        if time_match:
                            hours = int(time_match.group(1))
                            minutes = int(time_match.group(2))
                            seconds = float(time_match.group(3))
                            
                            current_time = hours * 3600 + minutes * 60 + seconds
                            progress = min((current_time / duration) * 100, 100)
                            
                            pbar.n = progress
                            pbar.refresh()
                        
                        # Проверяем на завершение процесса
                        if process.poll() is not None:
                            break
                            
                except UnicodeDecodeError:
                    # Пропускаем строки с ошибками кодировки
                    continue
                except Exception as e:
                    logger.warning(f"Ошибка чтения вывода FFmpeg: {e}")
                    break
            
            pbar.close()
            
            # Ждем завершения процесса с таймаутом
            try:
                return_code = process.wait(timeout=30)  # Максимум 30 секунд ожидания
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg не завершился за 30 секунд, принудительно завершаем...")
                process.terminate()
                try:
                    return_code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.error("Принудительное завершение FFmpeg...")
                    process.kill()
                    return_code = process.wait()
            
            if return_code != 0:
                logger.error(f"FFmpeg завершился с кодом {return_code}")
                # Выводим последние строки stderr для диагностики
                if stderr_lines:
                    logger.error("Последние строки вывода FFmpeg:")
                    for line in stderr_lines[-10:]:  # Последние 10 строк
                        logger.error(f"  {line}")
                return False
            
            logger.info("FFmpeg успешно завершен")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка запуска FFmpeg с прогрессом: {e}")
            return False
    
    def add_animated_subtitles(self, video_stream, subtitles: List[Dict], width: int, height: int):
        """Добавляет анимированные субтитры к видео потоку"""
        try:
            if not subtitles:
                return video_stream
            
            # Применяем каждый субтитр как отдельный drawtext фильтр
            current_stream = video_stream
            
            for subtitle in subtitles:
                start_time = subtitle['start']
                end_time = subtitle['end']
                
                # Очищаем текст от специальных символов
                text = subtitle['text'].replace("'", "").replace('"', '').replace('\\', '').strip()
                
                if not text:  # Пропускаем пустые тексты
                    continue
                
                # Позиция субтитров (накладываются на нижнюю часть центрального видео)
                y_pos = int(height * 0.78)  # 78% от верха
                
                # Добавляем каждое слово как отдельный drawtext фильтр
                current_stream = current_stream.filter(
                    'drawtext',
                    text=text,
                    fontfile='Robloxian-UltraBold.ttf',  # Используем шрифт из папки
                    fontsize=120,  # Увеличенный размер шрифта
                    fontcolor='white',
                    bordercolor='black',
                    borderw=8,  # Увеличенная черная рамка
                    x='(w-text_w)/2',
                    y=y_pos,
                    enable=f'between(t,{start_time},{end_time})'
                )
            
            return current_stream
            
        except Exception as e:
            logger.error(f"Ошибка добавления анимированных субтитров: {e}")
            # Fallback - простые субтитры без анимации
            return self.add_simple_subtitles(video_stream, subtitles, width, height)
    
    def add_simple_subtitles(self, video_stream, subtitles: List[Dict], width: int, height: int):
        """Добавляет простые субтитры без анимации (fallback)"""
        try:
            if not subtitles:
                return video_stream
            
            current_stream = video_stream
            
            for subtitle in subtitles:
                start_time = subtitle['start']
                end_time = subtitle['end']
                text = subtitle['text'].replace("'", "").replace('"', '').replace('\\', '').strip()
                
                if not text:
                    continue
                
                # Позиция субтитров (накладываются на нижнюю часть центрального видео)
                y_pos = int(height * 0.78)
                
                current_stream = current_stream.filter(
                    'drawtext',
                    text=text,
                    fontfile='Robloxian-UltraBold.ttf',  # Используем шрифт из папки
                    fontsize=120,  # Увеличенный размер шрифта
                    fontcolor='white',
                    bordercolor='black',
                    borderw=8,  # Увеличенная черная рамка
                    x='(w-text_w)/2',
                    y=y_pos,
                    enable=f'between(t,{start_time},{end_time})'
                )
            
            return current_stream
            
        except Exception as e:
            logger.error(f"Ошибка добавления простых субтитров: {e}")
            return video_stream
    
    def create_subtitle_overlay(self, subtitles: List[Dict], width: int, height: int, duration: float):
        """Создает overlay с анимированными субтитрами"""
        try:
            # Создаем прозрачный фон для субтитров
            subtitle_bg = ffmpeg.input('color=c=black@0.0:s={}x{}:d={}'.format(width, height, duration), f='lavfi')
            
            # Добавляем каждое слово как отдельный текстовый элемент
            current_overlay = subtitle_bg
            
            for subtitle in subtitles:
                start_time = subtitle['start']
                end_time = subtitle['end']
                text = subtitle['text'].replace("'", "\\'").replace('"', '\\"')
                
                # Позиция субтитров
                y_pos = int(height * 0.85)
                
                # Добавляем текст с анимацией
                current_overlay = current_overlay.filter(
                    'drawtext',
                    text=text,
                    fontfile='C:/Windows/Fonts/arial.ttf',
                    fontsize=48,
                    fontcolor='white',
                    bordercolor='black',
                    borderw=3,
                    x='(w-text_w)/2',
                    y=y_pos,
                    enable=f'between(t,{start_time},{end_time})'
                )
            
            return current_overlay
            
        except Exception as e:
            logger.error(f"Ошибка создания overlay субтитров: {e}")
            return None
    
    def add_banner_with_chromakey(self, video_stream, banner_path: str, width: int, height: int):
        """Добавляет баннер с удалением фиолетового хромакея"""
        try:
            # Загружаем баннер
            banner = ffmpeg.input(banner_path, stream_loop=-1)  # Зацикливаем баннер
            
            # Удаляем фиолетовый хромакей (цвет #800080 или похожие оттенки)
            # Используем colorkey фильтр для удаления фиолетового цвета
            banner_keyed = banner.filter(
                'colorkey',
                color='0x800080',  # Фиолетовый цвет в hex
                similarity=0.3,    # Допуск по цвету (0.0-1.0)
                blend=0.1          # Смягчение краев
            )
            
            # Масштабируем баннер под размер экрана (если нужно)
            banner_scaled = banner_keyed.filter('scale', width, height)
            
            # Накладываем баннер поверх основного видео
            # Баннер будет всегда виден поверх всего контента
            composed = ffmpeg.overlay(video_stream, banner_scaled, x=0, y=0)
            
            logger.info("Баннер с хромакеем успешно добавлен")
            return composed
            
        except Exception as e:
            logger.error(f"Ошибка добавления баннера с хромакеем: {e}")
            return video_stream
    
    def get_file_size(self, file_path: str) -> int:
        """Получить размер файла в байтах"""
        try:
            return os.path.getsize(file_path)
        except:
            return 0