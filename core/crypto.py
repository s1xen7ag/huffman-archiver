"""
Шифрування AES-256-GCM з ключем, отриманим з пароля.

Пароль не можна використати як ключ напряму: він короткий і передбачуваний.
Тому ключ (32 байти = 256 біт) отримуємо функцією PBKDF2: вона 600 000 разів
хешує пароль разом із випадковою «сіллю». Це робить підбір пароля дуже повільним.

Формат зашифрованих даних:
    [сіль: 16 байт][nonce: 12 байт][шифротекст][тег автентичності: 16 байт]
"""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

SALT_SIZE = 16
NONCE_SIZE = 12
TAG_SIZE = 16
ITERATIONS = 600_000


class WrongPasswordError(Exception):
    """Неправильний пароль або зашифровані дані пошкоджено."""


def derive_key(password, salt):
    """Перетворює пароль на 256-бітний ключ AES."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def encrypt(data, password):
    salt = os.urandom(SALT_SIZE)    # нова сіль щоразу: той самий пароль дасть інший ключ
    nonce = os.urandom(NONCE_SIZE)  # одноразове число, без нього AES-GCM небезпечний
    key = derive_key(password, salt)
    return salt + nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt(blob, password):
    if len(blob) < SALT_SIZE + NONCE_SIZE + TAG_SIZE:
        raise WrongPasswordError("Зашифровані дані пошкоджено")
    salt = blob[:SALT_SIZE]
    nonce = blob[SALT_SIZE:SALT_SIZE + NONCE_SIZE]
    ciphertext = blob[SALT_SIZE + NONCE_SIZE:]
    key = derive_key(password, salt)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag:
        # GCM перевіряє тег автентичності: якщо ключ не той або дані змінено — помилка.
        raise WrongPasswordError("Неправильний пароль або архів пошкоджено") from None
