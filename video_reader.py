"""Утилиты для работы с видео: длительность, превью-кадр. Использует OpenCV."""
import os

import cv2
from PyQt5.QtGui import QImage


VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v'}


def is_supported(file_path: str) -> bool:
    return os.path.splitext(file_path)[1].lower() in VIDEO_EXTENSIONS


def get_duration(file_path: str) -> int:
    """Длительность в секундах или 0, если не удалось."""
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return 0
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps > 0 and frames > 0:
            return int(frames / fps)
        return 0
    finally:
        cap.release()


def extract_thumbnail(file_path: str, target=(480, 270)):
    """Возвращает QImage с кадром из начала видео или None."""
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = frames / fps if fps > 0 else 0

        seek_sec = min(2.0, duration * 0.1) if duration > 0 else 0
        cap.set(cv2.CAP_PROP_POS_MSEC, seek_sec * 1000)
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
        if not ret:
            return None

        h, w = frame.shape[:2]
        if w == 0 or h == 0:
            return None

        scale = min(target[0] / w, target[1] / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        h, w, ch = frame.shape
        bytes_per_line = ch * w
        img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return img.copy()
    except Exception:
        return None
    finally:
        cap.release()


def format_duration(seconds: int) -> str:
    if not seconds or seconds < 0:
        return "0:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"