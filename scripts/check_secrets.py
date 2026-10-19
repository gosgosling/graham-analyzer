#!/usr/bin/env python3
"""Поиск секретов во всей истории git: каждый блоб всех веток.

Печатает тип находки, число разных значений и путь — сами значения никогда.
Код возврата 1, если что-то найдено.

    python3 scripts/check_secrets.py [путь-к-репозиторию]

Шаблоны те же, что убирает scripts/clean_history.sh, плюс общие (ключи AWS,
GitHub, Telegram, закрытые ключи). Пароль локальной базы из docker-compose.yml
секретом не считается: база слушает только 127.0.0.1, в проде пароль свой.
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict

PATTERNS = {
    "токен T-Invest": re.compile(rb"\bt\.[A-Za-z0-9_-]{60,}"),
    "ключ Alibaba": re.compile(rb"LTAI[A-Za-z0-9]{12,}"),
    "ключ вида sk-": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "ключ AWS": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "токен GitHub": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "токен Telegram": re.compile(rb"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}"),
    "закрытый ключ": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "хэш пароля": re.compile(rb"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}|\$argon2id?\$v=\d+\$"),
}
FORBIDDEN_PATHS = re.compile(r"(^|/)\.env$|\.edisclosure_storage_state\.json$")


def main(repo: str) -> int:
    objects = subprocess.run(
        ["git", "-C", repo, "rev-list", "--all", "--objects"],
        capture_output=True, check=True,
    ).stdout.decode().splitlines()
    paths: dict[str, str] = {}
    for line in objects:
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, path)

    found: dict[tuple[str, str], set[int]] = defaultdict(set)
    for path in sorted(set(paths.values())):
        if FORBIDDEN_PATHS.search(path):
            found[("файл с секретами", path)].add(0)

    batch = subprocess.Popen(
        ["git", "-C", repo, "cat-file", "--batch"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    )
    assert batch.stdin and batch.stdout
    for sha, path in paths.items():
        batch.stdin.write(sha.encode() + b"\n")
        batch.stdin.flush()
        header = batch.stdout.readline().split()
        data = batch.stdout.read(int(header[2]))
        batch.stdout.read(1)
        if header[1] != b"blob" or path.endswith(".dump"):
            continue
        for name, rx in PATTERNS.items():
            for match in rx.finditer(data):
                found[(name, path)].add(hash(match.group(0)))
    batch.stdin.close()
    batch.wait()

    for (name, path), values in sorted(found.items()):
        print(f"{name:18} {len(values):3}  {path}")
    print(f"Проверено объектов: {len(paths)}; находок: {len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
