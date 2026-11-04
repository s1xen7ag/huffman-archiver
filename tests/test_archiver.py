"""Тести логіки архіватора. Запуск з папки програми: py -m unittest -v"""

import os
import tempfile
import unittest
from pathlib import Path

from core import archive, crypto, huffman

TEXT = "Алгоритм Хаффмана стискає дані без втрат. Hello, world! 12345\n".encode("utf-8") * 500


class HuffmanTests(unittest.TestCase):
    def assert_roundtrip(self, data):
        packed = huffman.compress(data)
        self.assertIsNotNone(packed)
        self.assertLess(len(packed), len(data))
        self.assertEqual(huffman.decompress(packed), data)

    def test_text(self):
        self.assert_roundtrip(TEXT)

    def test_single_repeated_byte(self):
        self.assert_roundtrip(b"a" * 1000)

    def test_all_byte_values(self):
        self.assert_roundtrip(bytes(range(256)) * 20 + b"\x00" * 20000)

    def test_deep_tree(self):
        # Частоти Фібоначчі дають максимально глибоке дерево: коди довші за 8 бітів
        fib = [1, 1]
        while len(fib) < 22:
            fib.append(fib[-1] + fib[-2])
        data = b"".join(bytes([symbol]) * count for symbol, count in enumerate(fib))
        self.assert_roundtrip(data)

    def test_random_data_is_not_compressed(self):
        self.assertIsNone(huffman.compress(os.urandom(20000)))

    def test_empty(self):
        self.assertIsNone(huffman.compress(b""))


class CryptoTests(unittest.TestCase):
    def test_roundtrip(self):
        blob = crypto.encrypt(TEXT, "пароль123")
        self.assertNotIn(b"Hello", blob)
        self.assertEqual(crypto.decrypt(blob, "пароль123"), TEXT)

    def test_wrong_password(self):
        blob = crypto.encrypt(TEXT, "right")
        with self.assertRaises(crypto.WrongPasswordError):
            crypto.decrypt(blob, "wrong")


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "Документи"
        (self.src / "вкладена").mkdir(parents=True)
        (self.src / "текст.txt").write_bytes(TEXT)
        (self.src / "вкладена" / "random.bin").write_bytes(os.urandom(5000))
        (self.src / "вкладена" / "порожній.txt").write_bytes(b"")
        self.out = self.root / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def assert_same_tree(self, extracted):
        for original in self.src.rglob("*"):
            if original.is_file():
                copy = extracted / original.relative_to(self.src.parent)
                self.assertEqual(copy.read_bytes(), original.read_bytes(), original.name)

    def test_roundtrip(self):
        path = self.root / "a.huf"
        entries = archive.create_archive(archive.collect_files([self.src]), path)
        methods = {Path(entry.name).name: entry.method for entry in entries}
        self.assertEqual(methods["текст.txt"], archive.HUFFMAN)
        self.assertEqual(methods["random.bin"], archive.STORED)
        self.assertFalse(archive.is_encrypted(path))

        target, _ = archive.extract_archive(path, self.out)
        self.assert_same_tree(target)

    def test_encrypted_roundtrip(self):
        path = self.root / "secret.huf"
        archive.create_archive(archive.collect_files([self.src]), path, password="qwerty")
        self.assertTrue(archive.is_encrypted(path))
        self.assertNotIn("текст".encode("utf-8"), path.read_bytes())  # навіть імена файлів приховано

        with self.assertRaises(crypto.WrongPasswordError):
            archive.extract_archive(path, self.out, password="wrong")
        with self.assertRaises(crypto.WrongPasswordError):
            archive.extract_archive(path, self.out)

        target, _ = archive.extract_archive(path, self.out, password="qwerty")
        self.assert_same_tree(target)

    def test_does_not_overwrite(self):
        path = self.root / "a.huf"
        archive.create_archive(archive.collect_files([self.src]), path)
        first, _ = archive.extract_archive(path, self.out)
        second, _ = archive.extract_archive(path, self.out)
        self.assertEqual(first.name, "a")
        self.assertEqual(second.name, "a (2)")

    def test_rejects_path_traversal(self):
        path = self.root / "evil.huf"
        archive.create_archive([(self.src / "текст.txt", "../../evil.txt")], path)
        with self.assertRaises(archive.ArchiveError):
            archive.extract_archive(path, self.out)
        self.assertFalse((self.root / "evil.txt").exists())
        self.assertEqual(list(self.out.iterdir()), [])  # нічого не записано

    def test_detects_corruption(self):
        path = self.root / "a.huf"
        archive.create_archive([(self.src / "текст.txt", "текст.txt")], path)
        data = bytearray(path.read_bytes())
        data[-10] ^= 0xFF
        path.write_bytes(data)
        with self.assertRaises(archive.ArchiveError):
            archive.extract_archive(path, self.out)

    def test_not_an_archive(self):
        path = self.root / "fake.huf"
        path.write_bytes(b"just some text")
        with self.assertRaises(archive.ArchiveError):
            archive.is_encrypted(path)


if __name__ == "__main__":
    unittest.main()
