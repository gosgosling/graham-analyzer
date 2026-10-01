"""Хэш пароля администратора: scrypt из стандартной библиотеки.

scrypt — функция, рассчитанная на подбор: каждая проверка стоит памяти и
времени, и перебор словаря по утёкшему хэшу становится дорогим. Параметры —
рекомендованные OWASP для интерактивного входа (N=2^17, r=8, p=1).
Соль своя у каждого хэша, сравнение — за постоянное время.

Формат строки: scrypt$N$r$p$соль_base64$хэш_base64.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P = 2 ** 17, 8, 1
DKLEN = 32
# NIST SP 800-63B: длина важнее состава. Не требуем «цифру и спецсимвол» —
# это даёт «Password1!», а требуем длину и сверяем со списком слабых.
MIN_LENGTH = 10
MAX_LENGTH = 128

# Самые частые пароли из утечек — короткий список, которого хватает, чтобы
# отсечь очевидное. Сверка без учёта регистра.
COMMON = {
    "1234567890", "12345678910", "123456789a", "qwertyuiop", "1q2w3e4r5t", "1qaz2wsx3edc",
    "password123", "password1234", "passw0rd123", "iloveyou123", "qwerty12345", "qwerty123456",
    "abcdef123456", "0987654321", "1111111111", "0000000000", "aaaaaaaaaa", "zxcvbnm123",
    "123qweasdzxc", "qazwsxedcrfv", "admin12345", "administrator", "welcome123", "letmein123",
    "monkey12345", "dragon12345", "football123", "baseball123", "princess123", "sunshine123",
    "йцукенгшщз", "пароль12345", "1234qwerasdf", "asdfghjkl1", "q1w2e3r4t5", "superman123",
}


def password_problem(password: str, email: str = "", name: str = "") -> str | None:
    """Что не так с паролем — или None. Сообщение показывается пользователю."""
    if len(password) < MIN_LENGTH:
        return f"Пароль короче {MIN_LENGTH} символов"
    if len(password) > MAX_LENGTH:
        return f"Пароль длиннее {MAX_LENGTH} символов"
    lowered = password.lower()
    if lowered in COMMON or len(set(lowered)) < 4:
        return "Слишком простой пароль — такой подбирают первым"
    local = email.split("@")[0].lower()
    if (local and len(local) >= 4 and local in lowered) or (name and len(name) >= 4 and name.lower() in lowered):
        return "Пароль не должен содержать почту или имя"
    return None


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"пароль короче {MIN_LENGTH} символов")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P,
                            dklen=DKLEN, maxmem=256 * 1024 * 1024)
    return "$".join(["scrypt", str(N), str(R), str(P),
                     base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


_dummy: list[str] = []


def dummy_hash() -> str:
    """Хэш-пустышка: при входе с несуществующей почтой проверяем пароль
    против него, чтобы время ответа не выдавало, есть ли такой аккаунт."""
    if not _dummy:
        _dummy.append(hash_password(secrets.token_urlsafe(16)))
    return _dummy[0]


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
                                dklen=len(expected), maxmem=256 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)
