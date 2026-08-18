"""Хранение файлов дела на диске.

Раскладка повторяет то, как юристы держат бумажные дела:

    data/cases/2026/Петров_2026-001/01_Договор/Петров_2026-001_ДДУ_15.05.2021.pdf

Имена файлов приводятся к безопасному виду: кириллица транслитерируется,
всё остальное вычищается. Путь всегда проверяется на выход за пределы
папки дела — имя файла приходит от пользователя и доверять ему нельзя.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import BinaryIO, Optional

from .types import FOLDERS, type_title

MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".rtf", ".txt", ".odt",
    ".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff",
    ".xls", ".xlsx", ".csv", ".zip", ".rar", ".7z",
}
# Исполняемое и активный HTML не принимаем ни под каким видом.
FORBIDDEN_SUFFIXES = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".sh",
    ".js", ".vbs", ".jar", ".apk", ".dll", ".lnk", ".html", ".htm", ".svg",
}

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
    "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


class StorageError(Exception):
    """Файл принять нельзя."""


def translit(value: str) -> str:
    result = []
    for char in (value or "").replace("ё", "е").replace("Ё", "Е"):
        lower = char.lower()
        if lower in TRANSLIT:
            replacement = TRANSLIT[lower]
            result.append(replacement.capitalize() if char.isupper() else replacement)
        else:
            result.append(char)
    return "".join(result)


def safe_name(value: str, fallback: str = "file") -> str:
    """Имя, пригодное для файловой системы на любой ОС."""
    text = unicodedata.normalize("NFKD", translit(value or ""))
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    text = re.sub(r"_{2,}", "_", text)
    return text[:80] or fallback


def check_upload(filename: str, size: int) -> str:
    """Проверяет расширение и размер, возвращает нормализованное расширение."""
    suffix = Path(filename or "").suffix.lower()
    if not suffix:
        raise StorageError("У файла нет расширения — непонятно, что это.")
    if suffix in FORBIDDEN_SUFFIXES:
        raise StorageError(f"Файлы {suffix} не принимаются.")
    if suffix not in ALLOWED_SUFFIXES:
        raise StorageError(f"Формат {suffix} не поддерживается.")
    if size <= 0:
        raise StorageError("Файл пустой.")
    if size > MAX_FILE_BYTES:
        raise StorageError(
            f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ. Сожмите или разделите его."
        )
    return suffix


def case_folder(root: Path, case_number: str, client_name: str, created: date) -> Path:
    """Папка дела: data/cases/2026/Петров_2026-001"""
    surname = safe_name((client_name or "").split()[0] if client_name else "", "Klient")
    return Path(root) / "cases" / str(created.year) / f"{surname}_{safe_name(case_number)}"


def build_filename(
    case_number: str, client_name: str, doc_type: str, doc_date: Optional[date], suffix: str
) -> str:
    """Фамилия_НомерДела_ТипДокумента_Дата.pdf"""
    surname = safe_name((client_name or "").split()[0] if client_name else "", "Klient")
    parts = [surname, safe_name(case_number), safe_name(type_title(doc_type), "dokument")]
    if doc_date:
        parts.append(doc_date.strftime("%d.%m.%Y"))
    return "_".join(part for part in parts if part) + suffix


def resolve_target(base: Path, folder: str, filename: str) -> Path:
    """Итоговый путь с защитой от выхода за пределы папки дела.

    Названия папок берутся из нашего же справочника, поэтому остаются
    кириллическими — юристу разбирать «01_Договор» проще, чем
    «01_Dogovor». Всё, что пришло со стороны, обезвреживается.
    """
    base = Path(base).resolve()
    folder_name = folder if folder in FOLDERS else safe_name(folder, "99_Prochee")
    target = (base / folder_name / safe_name(filename)).resolve()
    if base not in target.parents:
        raise StorageError("Недопустимый путь к файлу.")
    return target


def unique_path(path: Path) -> Path:
    """Не затираем одноимённый файл: второй становится ..._2."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 100):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise StorageError("Слишком много файлов с одинаковым именем.")


def save_stream(source: BinaryIO, target: Path, max_bytes: int = MAX_FILE_BYTES) -> tuple[int, str]:
    """Пишет файл на диск, считая размер и контрольную сумму.

    Файл, превысивший лимит, удаляется: иначе на диске остаётся мусор
    от прерванной загрузки.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0

    try:
        with target.open("wb") as handle:
            while True:
                chunk = source.read(1024 * 256)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise StorageError(f"Файл больше {max_bytes // (1024 * 1024)} МБ.")
                digest.update(chunk)
                handle.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    if written == 0:
        target.unlink(missing_ok=True)
        raise StorageError("Файл пустой.")

    return written, digest.hexdigest()
