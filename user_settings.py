import json
from pathlib import Path
from typing import Dict, Any, Optional

from config import (
    DEFAULT_TOP_HEADER, DEFAULT_BOTTOM_HEADER,
    FONT_PATH, FONT_SIZE, FONT_COLOR, STROKE_COLOR, STROKE_WIDTH,
    TOP_HEADER_FONT_SIZE, BOTTOM_HEADER_FONT_SIZE, HEADER_FONT_COLOR, HEADER_STROKE_COLOR, HEADER_STROKE_WIDTH,
    MAIN_VIDEO_SCALE,
    BANNER_ENABLED, BANNER_PATH, BANNER_X, BANNER_Y,
    CHROMA_KEY_COLOR, CHROMA_KEY_SIMILARITY, CHROMA_KEY_BLEND,
    BACKGROUND_MUSIC_ENABLED, BACKGROUND_MUSIC_PATH, BACKGROUND_MUSIC_VOLUME,
    CLIP_DURATION_SECONDS
)

SETTINGS_DIR = Path('user_settings')
SETTINGS_DIR.mkdir(exist_ok=True)


def _settings_path(chat_id: int) -> Path:
    return SETTINGS_DIR / f"{chat_id}.json"


def _default_settings() -> Dict[str, Any]:
    return {
        "headers": {
            "top": DEFAULT_TOP_HEADER,
            "bottom": DEFAULT_BOTTOM_HEADER,
            "top_font_size": TOP_HEADER_FONT_SIZE,
            "bottom_font_size": BOTTOM_HEADER_FONT_SIZE,
            "header_font_color": HEADER_FONT_COLOR,
            "header_stroke_color": HEADER_STROKE_COLOR,
            "header_stroke_width": HEADER_STROKE_WIDTH,
        },
        "subtitles": {
            "font_path": FONT_PATH,
            "font_size": FONT_SIZE,
            "font_color": FONT_COLOR,
            "stroke_color": STROKE_COLOR,
            "stroke_width": STROKE_WIDTH,
        },
        "layout": {
            "main_video_scale": MAIN_VIDEO_SCALE,
        },
        "banner": {
            "enabled": BANNER_ENABLED,
            "path": BANNER_PATH,
            "x": BANNER_X,
            "y": BANNER_Y,
            "chroma_key_color": CHROMA_KEY_COLOR,
            "chroma_key_similarity": CHROMA_KEY_SIMILARITY,
            "chroma_key_blend": CHROMA_KEY_BLEND,
        },
        "background_music": {
            "enabled": BACKGROUND_MUSIC_ENABLED,
            "path": BACKGROUND_MUSIC_PATH,
            "volume": BACKGROUND_MUSIC_VOLUME,
        },
        "clips": {
            "duration_seconds": CLIP_DURATION_SECONDS
        }
    }


def load_user_settings(chat_id: int) -> Dict[str, Any]:
    path = _settings_path(chat_id)
    if not path.exists():
        settings = _default_settings()
        save_user_settings(chat_id, settings)
        return settings
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # ensure missing keys are filled from defaults
        def_settings = _default_settings()
        merged = _deep_merge(def_settings, data)
        if merged != data:
            save_user_settings(chat_id, merged)
        return merged
    except Exception:
        # fallback to defaults if corrupted
        settings = _default_settings()
        save_user_settings(chat_id, settings)
        return settings


def save_user_settings(chat_id: int, settings: Dict[str, Any]) -> None:
    path = _settings_path(chat_id)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def update_user_settings(chat_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    current = load_user_settings(chat_id)
    merged = _deep_merge(current, patch)
    save_user_settings(chat_id, merged)
    return merged


def get_value(settings: Dict[str, Any], path: str, default: Optional[Any] = None) -> Any:
    node: Any = settings
    for key in path.split('.'):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)  # type: ignore
        else:
            result[k] = v
    return result 