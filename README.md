# YouTube Video Processor Bot

Превращает YouTube‑видео в вертикальные клипы 9:16 с субтитрами, заголовками, фоновой музыкой и баннером. Поддерживает персональные настройки для каждого пользователя и cookies.

## Требования
- Python 3.10+
- FFmpeg установлен в системе (должен быть в PATH)
- Telegram Bot Token

## Установка
1) Клонируйте репозиторий и перейдите в папку проекта

```bash
git clone https://github.com/uiper123/VideRedactor.git
cd VideRedactor
```

2) Установите зависимости
```bash
pip install -r requirements.txt
```

3) Установите FFmpeg
- Windows: скачайте с `https://ffmpeg.org/download.html` и добавьте в PATH
- Ubuntu/Debian:
```bash
sudo apt update && sudo apt install -y ffmpeg
```
- macOS (Homebrew):
```bash
brew install ffmpeg
```

## Конфигурация
- Токен бота задайте в переменной окружения или в `config.py`:
```bash
# Рекомендуется
set BOT_TOKEN=ВАШ_ТОКЕН
# или в Linux/macOS
export BOT_TOKEN=ВАШ_ТОКЕН
```

- Ключевые пути/настройки по умолчанию в `config.py` (шрифты, музыка, баннер, хромакей, масштабы, длительности и т. п.). Эти значения используются как дефолт, а персональные изменения сохраняются в `user_settings/<chat_id>.json`.

## Настройка Google Drive
Бот загружает результат на Google Drive через OAuth. Доступны 2 способа авторизации.

### Вариант A — заранее подготовленный токен (без интерактивного окна)
1) На машине, где можно проходить интерактивный вход в Google, создайте `token.pickle`:
   - Установите зависимости: `pip install google-auth-oauthlib google-api-python-client`
   - Получите `credentials.json` в Google Cloud Console (OAuth client ID, тип Desktop App):
     - Перейдите в Google Cloud Console → APIs & Services → Credentials
     - Create Credentials → OAuth client ID → Desktop App
     - Скачайте `credentials.json` и положите рядом со скриптом
   - Выполните скрипт:
   ```python
   from google_auth_oauthlib.flow import InstalledAppFlow
   import pickle
   SCOPES=['https://www.googleapis.com/auth/drive']
   flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
   creds = flow.run_local_server(port=0)
   with open('token.pickle','wb') as f: pickle.dump(creds, f)
   ```
2) Закодируйте `token.pickle` в base64:
   ```bash
   python - << "PY"
import base64
with open('token.pickle','rb') as f:
    print(base64.b64encode(f.read()).decode())
PY
   ```
3) Скопируйте вывод и задайте переменную окружения на машине бота:
   ```bash
   set GOOGLE_OAUTH_TOKEN_BASE64=<ВАШ_BASE64>
   # или в Linux/macOS
   export GOOGLE_OAUTH_TOKEN_BASE64=<ВАШ_BASE64>
   ```
4) Запустите бота. При старте (или первой загрузке) `token.pickle` будет создан из переменной и использован автоматически.

Примечание: `TOKEN_PICKLE_FILE` задаётся в `config.py` (по умолчанию `token.pickle`).

### Вариант B — интерактивный вход на этой машине
Если переменная `GOOGLE_OAUTH_TOKEN_BASE64` не задана, бот попробует классический интерактивный поток:
1) Положите `credentials.json` рядом со скриптом.
2) При первом обращении к Google Drive откроется окно/ссылка для входа.
3) После успешной авторизации файл `token.pickle` будет сохранён.

### Выбор папки для загрузки
- Бот создаёт (если нет) папку с именем `final_videos_<chat_id>` и загружает файлы туда.
- После загрузки бот делает общий доступ “Anyone with the link (reader)”.

## Запуск
```bash
python bot.py
```
В терминале появится сообщение, что бот запущен. Откройте диалог с ботом в Telegram и отправьте ссылку на YouTube.

## Использование
- Старт: отправьте ссылку на YouTube — бот скачает, нарежет и создаст вертикальные клипы.
- Настройки: команда `/settings` откроет меню с кнопками.
  - Заголовки: тексты, размеры (верх/низ), цвет и контур.
  - Субтитры: размер/цвет/контур/шрифт (в т. ч. загрузка шрифта файлом).
  - Макет: масштаб основного видео.
  - Музыка: ON/OFF, путь, громкость (в т. ч. загрузка аудио файлом).
  - Баннер: ON/OFF, путь, позиция X/Y, chroma color/similarity/blend (в т. ч. загрузка видео файлом).
  - Cookies: загрузка `cookies.txt` файлом или вставка текста.

Все изменения сохраняются для конкретного пользователя и автоматически применяются при следующей обработке.

## Загрузка файлов из чата
- Бот спрашивает файл после нажатия соответствующей кнопки в `/settings`.
- Файлы сохраняются в `user_assets/<chat_id>/` и путь записывается в настройки пользователя.
- Поддерживаемые форматы:
  - Шрифты: `.ttf`, `.otf`
  - Музыка: `.mp3`, `.wav`, `.m4a`, `.aac`
  - Баннер: `.mp4`, `.mov`, `.mkv`, `.webm`

## Cookies (YouTube)
- Для доступа к некоторым роликам нужны cookies.
- Откройте `/settings` → Cookies и:
  - Загрузите `cookies.txt` файлом, или
  - Вставьте текст cookies.
- Бот нормализует формат (Netscape) и сохранит:
  - глобально: `COOKIES_FILE` (из `config.py`),
  - персонально: `user_assets/<chat_id>/cookies.txt`.
- При скачивании сначала используется персональный cookies, затем глобальный.

## Где хранятся данные
- Скачанные видео: `downloads/<chat_id>/`
- Временные файлы рендера: `downloads/temp/<chat_id>/`
- Персональные файлы (шрифты/музыка/баннер/cookies): `user_assets/<chat_id>/`
- Персональные настройки: `user_settings/<chat_id>.json`

## Подсказки
- Если видео длинное — оно режется на чанки и клипы по заданной длительности.
- Если итоговый ZIP > 50MB — бот пришлёт файл со ссылками Google Drive (или прямые ссылки).

## Частые проблемы
- "FFmpeg not found": установите FFmpeg и добавьте в PATH.
- "Message is not modified": Telegram не разрешил редактировать сообщение без изменений — в боте это обрабатывается, просто нажмите кнопку ещё раз.
- yt-dlp предупреждения про cookies: используйте меню Cookies — бот нормализует формат.
- Нет звука/музыки: проверьте путь к аудиофайлу в настройках и громкость.
- Не отображаются шрифты: убедитесь, что загруженный файл шрифта доступен и указан в `subtitles.font_path`.

## Безопасность
- Не публикуйте ваш `BOT_TOKEN`.
- Cookies содержат приватные данные — храните их только у себя и не делитесь.
- `token.pickle` содержит токен доступа к Google Drive — храните его в приватном месте.

## Лицензия
Укажите вашу лицензию здесь.
