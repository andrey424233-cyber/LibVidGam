import io
import os
import re
import zipfile
from typing import List

import rarfile
from PIL import Image


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
ZIP_EXTENSIONS = {'.zip', '.cbz'}
RAR_EXTENSIONS = {'.rar', '.cbr'}


def _natural_key(name: str):
    """Натуральная сортировка: page2 < page10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


class OpenedArchive:
    """Держит архив открытым. Один экземпляр на файл — быстрое чтение страниц."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.ext = os.path.splitext(file_path)[1].lower()
        if self.ext in ZIP_EXTENSIONS:
            self._handle = zipfile.ZipFile(file_path, 'r')
        elif self.ext in RAR_EXTENSIONS:
            self._handle = rarfile.RarFile(file_path)
        else:
            raise ValueError(f"Неподдерживаемый формат: {self.ext}")

        self.files = sorted(
            [f for f in self._handle.namelist()
             if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS],
            key=_natural_key
        )

    def page_count(self) -> int:
        return len(self.files)

    def read_page(self, index: int) -> Image.Image:
        if not 0 <= index < len(self.files):
            raise IndexError(f"Страница {index} не существует")
        data = self._handle.read(self.files[index])
        img = Image.open(io.BytesIO(data))
        img.load()
        return img

    def close(self):
        try:
            self._handle.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class ArchiveReader:
    """Backward-compatible API. Открывает архив каждый раз — использовать, если
    OpenedArchive по каким-то причинам недоступен."""

    SUPPORTED_FORMATS = ['.zip', '.rar', '.cbz', '.cbr']

    @staticmethod
    def is_supported(file_path: str) -> bool:
        return os.path.splitext(file_path)[1].lower() in ArchiveReader.SUPPORTED_FORMATS

    @staticmethod
    def get_file_list(file_path: str) -> List[str]:
        try:
            with OpenedArchive(file_path) as arc:
                return list(arc.files)
        except Exception as e:
            print(f"Ошибка чтения архива {file_path}: {e}")
            return []

    @staticmethod
    def get_page_count(file_path: str) -> int:
        return len(ArchiveReader.get_file_list(file_path))

    @staticmethod
    def extract_page(file_path: str, page_index: int) -> Image.Image:
        try:
            with OpenedArchive(file_path) as arc:
                return arc.read_page(page_index)
        except Exception as e:
            print(f"Ошибка извлечения страницы: {e}")
            raise