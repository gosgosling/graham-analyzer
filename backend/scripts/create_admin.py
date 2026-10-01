"""Назначить администратора.

    python -m scripts.create_admin                 # спросит почту, имя, пароль
    python -m scripts.create_admin --promote MAIL  # сделать админом уже зарегистрированного
    python -m scripts.create_admin --demote MAIL   # снять роль
    python -m scripts.create_admin --revoke        # закрыть все сессии всех пользователей

Админа нельзя получить через сайт — только этим скриптом на сервере. Пароль
не печатается и не попадает в историю shell: вводится через getpass.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.database import SessionLocal
from app.models.user import ROLE_ADMIN, ROLE_USER, User
from app.services import auth
from app.services.auth import AuthError


def _find(db, email: str) -> User | None:
    return db.query(User).filter(User.email == auth.normalize_email(email)).first()


def _set_role(db, email: str, role: str) -> int:
    user = _find(db, email)
    if user is None:
        print("Такой почты нет.", file=sys.stderr)
        return 1
    if role == ROLE_USER and db.query(User).filter(User.role == ROLE_ADMIN).count() <= 1:
        print("Это единственный администратор — сначала назначьте другого.", file=sys.stderr)
        return 1
    user.role = role
    db.commit()
    # Роль сменилась — пусть войдёт заново.
    auth.end_all_sessions(db, user.id)
    print(f"Готово: пользователь {user.id} теперь {role}.")
    return 0


def _create(db) -> int:
    email = input("Почта: ").strip()
    existing = _find(db, email)
    if existing is not None:
        print("Эта почта уже зарегистрирована — используйте --promote.", file=sys.stderr)
        return 1
    name = input("Имя на сайте: ").strip()
    first = getpass.getpass("Пароль (от 10 символов): ")
    if getpass.getpass("Ещё раз: ") != first:
        print("Пароли не совпали.", file=sys.stderr)
        return 1
    try:
        # Администратор — сам оператор: согласие самому себе не нужно,
        # но поле заполняем, чтобы у всех записей было одинаково.
        user = auth.register(db, email, first, name, consent=True)
    except AuthError as err:
        print(err.message, file=sys.stderr)
        return 1
    user.role = ROLE_ADMIN
    user.email_verified_at = auth._now()
    db.commit()
    print(f"Готово: администратор создан (пользователь {user.id}). Войдите на сайте.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--promote", metavar="EMAIL")
    group.add_argument("--demote", metavar="EMAIL")
    group.add_argument("--revoke", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.revoke:
            print(f"Закрыто сессий: {auth.end_all_sessions(db)}")
            return 0
        if args.promote:
            return _set_role(db, args.promote, ROLE_ADMIN)
        if args.demote:
            return _set_role(db, args.demote, ROLE_USER)
        return _create(db)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
