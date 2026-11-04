"""
Формат архіву .huf: створення і розпакування.

Будова файлу:
    "HUFA"                 — «магічні» байти, щоб розпізнати наш формат
    [версія: 1 байт]
    [прапорці: 1 байт]     — біт 0 = вміст зашифровано
    [вміст]                — відкритий або зашифрований (див. crypto.py)

Вміст — записи файлів один за одним:
    [кількість файлів: 4 байти]
    для кожного файлу:
        [довжина імені: 2 байти][ім'я в UTF-8, наприклад "Папка/звіт.docx"]
        [метод: 1 байт — 0 = без стиснення, 1 = Хаффман]
        [розмір оригіналу: 8 байт][розмір даних: 8 байт][CRC32: 4 байти]
        [дані]

Порядок обробки: спершу стискаємо кожен файл, потім шифруємо весь вміст.
Навпаки не можна: зашифровані дані схожі на шум і вже не стискаються.
"""

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from . import crypto, huffman

MAGIC = b"HUFA"
VERSION = 1
FLAG_ENCRYPTED = 1

STORED = 0   # файл записано як є
HUFFMAN = 1  # файл стиснуто алгоритмом Хаффмана

PREFIX = struct.Struct("<4sBB")  # магічні байти, версія, прапорці
COUNT = struct.Struct("<I")
NAME_LEN = struct.Struct("<H")
ENTRY = struct.Struct("<BQQI")   # метод, розмір оригіналу, розмір даних, CRC32


class ArchiveError(Exception):
    """Архів пошкоджено або це не наш формат."""


@dataclass
class Entry:
    name: str           # шлях усередині архіву, через "/"
    method: int         # STORED або HUFFMAN
    original_size: int
    packed_size: int
    crc: int


def collect_files(paths):
    """
    Перетворює вибрані файли й папки на список (повний шлях, ім'я в архіві).
    Для папки беремо всі файли всередині, зберігаючи підпапки: "Фото/2024/a.jpg".
    """
    result = []
    for path in map(Path, paths):
        if path.is_dir():
            for file in sorted(path.rglob("*")):
                if file.is_file():
                    result.append((file, file.relative_to(path.parent).as_posix()))
        elif path.is_file():
            result.append((path, path.name))
    return result


def create_archive(sources, archive_path, password="", on_progress=None):
    """
    Створює архів з файлів sources = [(шлях, ім'я в архіві), ...].
    Якщо задано пароль, вміст шифрується AES-256.
    on_progress(частка, повідомлення) — для прогрес-бару.
    Повертає список Entry (для таблиці й статистики).
    Оригінальні файли тільки читаються і ніяк не змінюються.
    """
    report = on_progress or (lambda fraction, message: None)
    total = sum(path.stat().st_size for path, _ in sources) or 1
    done = 0
    payload = bytearray(COUNT.pack(len(sources)))
    entries = []

    for path, name in sources:
        data = path.read_bytes()
        message = f"Стиснення: {name}"
        packed = huffman.compress(data, lambda f: report((done + f * len(data)) / total, message))
        method = HUFFMAN
        if packed is None:  # стиснення не допоможе — зберігаємо як є
            packed, method = data, STORED

        entry = Entry(name, method, len(data), len(packed), zlib.crc32(data))
        name_bytes = name.encode("utf-8")
        payload += NAME_LEN.pack(len(name_bytes)) + name_bytes
        payload += ENTRY.pack(entry.method, entry.original_size, entry.packed_size, entry.crc)
        payload += packed
        entries.append(entry)

        done += len(data)
        report(done / total, message)

    flags = 0
    if password:
        report(1.0, "Шифрування")
        payload = crypto.encrypt(bytes(payload), password)
        flags |= FLAG_ENCRYPTED

    # Пишемо спершу в тимчасовий файл і лише потім перейменовуємо:
    # якщо станеться збій, наполовину записаного архіву не залишиться.
    archive_path = Path(archive_path)
    temp_path = archive_path.with_name(archive_path.name + ".tmp")
    try:
        with open(temp_path, "wb") as file:
            file.write(PREFIX.pack(MAGIC, VERSION, flags))
            file.write(payload)
        os.replace(temp_path, archive_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return entries


def is_encrypted(archive_path):
    with open(archive_path, "rb") as file:
        flags = _check_prefix(file.read(PREFIX.size))
    return bool(flags & FLAG_ENCRYPTED)


def extract_archive(archive_path, out_dir, password="", on_progress=None):
    """
    Розпаковує архів у нову папку всередині out_dir (з назвою архіву).
    Нічого не перезаписує: якщо така папка вже є, створить "назва (2)".
    Повертає (папка з результатом, список Entry).
    """
    report = on_progress or (lambda fraction, message: None)
    report(0.0, "Читання архіву")
    raw = Path(archive_path).read_bytes()
    flags = _check_prefix(raw[:PREFIX.size])
    payload = raw[PREFIX.size:]
    if flags & FLAG_ENCRYPTED:
        if not password:
            raise crypto.WrongPasswordError("Архів зашифровано — введіть пароль")
        report(0.0, "Розшифрування")
        payload = crypto.decrypt(payload, password)

    items = _read_entries(payload)
    target_dir = _unique_path(Path(out_dir) / Path(archive_path).stem)
    root = target_dir.resolve()
    # Перевіряємо всі імена ДО того, як щось записати на диск.
    targets = [_safe_target(root, entry.name) for entry, _ in items]

    total = sum(entry.original_size for entry, _ in items) or 1
    done = 0
    target_dir.mkdir(parents=True)
    for (entry, packed), target in zip(items, targets):
        message = f"Розпакування: {entry.name}"
        data = _unpack_data(entry, packed, lambda f: report((done + f * entry.original_size) / total, message))
        target.parent.mkdir(parents=True, exist_ok=True)
        _unique_path(target).write_bytes(data)
        done += entry.original_size
        report(done / total, message)

    return target_dir, [entry for entry, _ in items]


def _check_prefix(prefix):
    """Перевіряє заголовок файлу і повертає прапорці."""
    if len(prefix) < PREFIX.size:
        raise ArchiveError("Це не архів .huf")
    magic, version, flags = PREFIX.unpack(prefix)
    if magic != MAGIC:
        raise ArchiveError("Це не архів .huf")
    if version != VERSION:
        raise ArchiveError(f"Непідтримувана версія архіву: {version}")
    return flags


def _read_entries(payload):
    """Розбирає вміст архіву на список (Entry, стиснені дані)."""
    items = []
    try:
        (count,) = COUNT.unpack_from(payload, 0)
        pos = COUNT.size
        for _ in range(count):
            (name_len,) = NAME_LEN.unpack_from(payload, pos)
            pos += NAME_LEN.size
            name = payload[pos:pos + name_len].decode("utf-8")
            pos += name_len
            method, original_size, packed_size, crc = ENTRY.unpack_from(payload, pos)
            pos += ENTRY.size
            data = payload[pos:pos + packed_size]
            pos += packed_size
            if len(data) != packed_size:
                raise ArchiveError("Архів обрізаний або пошкоджений")
            items.append((Entry(name, method, original_size, packed_size, crc), data))
    except (struct.error, UnicodeDecodeError) as error:
        raise ArchiveError("Архів пошкоджено") from error
    return items


def _unpack_data(entry, packed, on_progress):
    """Розпаковує один файл і перевіряє контрольну суму."""
    if entry.method == STORED:
        data = packed
    elif entry.method == HUFFMAN:
        try:
            data = huffman.decompress(packed, on_progress)
        except (ValueError, IndexError, struct.error) as error:
            raise ArchiveError(f"Файл {entry.name} пошкоджено") from error
    else:
        raise ArchiveError(f"Невідомий метод стиснення у файлі {entry.name}")

    if len(data) != entry.original_size or zlib.crc32(data) != entry.crc:
        raise ArchiveError(f"Файл {entry.name} пошкоджено (не збігається контрольна сума)")
    return data


def _safe_target(root, name):
    """
    Захист від шкідливих архівів: ім'я на кшталт "../../Windows/x.dll" або "C:/x"
    могло б записати файл поза папкою розпакування. Такі імена відхиляємо.
    """
    target = (root / name).resolve()
    if target == root or not target.is_relative_to(root):
        raise ArchiveError(f"Небезпечне ім'я файлу в архіві: {name}")
    return target


def _unique_path(path):
    """Повертає шлях, якого ще не існує: "звіт.txt" -> "звіт (2).txt", якщо перший зайнятий."""
    if not path.exists():
        return path
    number = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
        number += 1
