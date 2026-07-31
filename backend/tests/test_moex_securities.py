"""Список бумаг с MOEX: что запрашиваем, что фильтруем, как падаем.

Сеть не нужна — подменяется `_moex_get`. Проверяется ровно то, что ломалось
на живых данных: запрос без ограничения по режиму торгов возвращал одну и ту
же бумагу трижды, а недоступность биржи выглядела как пустой список.
"""
from types import SimpleNamespace

import pytest
import requests

from app.utils import moex_client
from app.utils.moex_client import MoexUnavailableError, get_moex_securities

_COLUMNS = ["SECID", "BOARDID", "SHORTNAME", "INSTRID", "SECTYPE", "ISIN"]


def _response(rows, columns=None):
    """Ответ ISS в формате {securities: {columns, data}}."""
    payload = {"securities": {"columns": columns or _COLUMNS, "data": rows}}
    return SimpleNamespace(
        status_code=200,
        json=lambda: payload,
        raise_for_status=lambda: None,
    )


@pytest.fixture
def captured_url(monkeypatch):
    """Подменяет сетевой вызов и запоминает URL последнего запроса."""
    box = {}

    def fake_get(url, **kwargs):
        box["url"] = url
        box["timeout"] = kwargs.get("timeout")
        return box["response"]

    monkeypatch.setattr(moex_client, "_moex_get", fake_get)
    box["response"] = _response([])
    return box


def test_request_is_scoped_to_main_board(captured_url):
    """Запрос идёт по TQBR: иначе бумага приходит по строке на каждый режим."""
    get_moex_securities()

    assert "/boards/TQBR/securities.json" in captured_url["url"]
    assert "iss.only=securities" in captured_url["url"]
    assert "iss.meta=off" in captured_url["url"]


def test_only_stocks_are_returned(captured_url):
    """Не-акции отсеиваются по INSTRID / SECTYPE."""
    captured_url["response"] = _response([
        ["SBER", "TQBR", "Сбербанк", "EQIN", "1", "RU0009029540"],
        ["RU000A0JX0J2", "TQBR", "Пай фонда", "EQFD", "3", "RU000A0JX0J2"],
        ["LKOH", "TQBR", "ЛУКОЙЛ", "EQIN", "1", "RU0009024277"],
    ])

    result = get_moex_securities()

    assert [row["secid"] for row in result] == ["SBER", "LKOH"]


def test_columns_are_lowercased_for_schema(captured_url):
    """Схема Security ждёт поля в нижнем регистре."""
    captured_url["response"] = _response([
        ["SBER", "TQBR", "Сбербанк", "EQIN", "1", "RU0009029540"],
    ])

    row = get_moex_securities()[0]

    assert row["shortname"] == "Сбербанк"
    assert row["boardid"] == "TQBR"
    assert "SECID" not in row


def test_sectype_alone_is_enough(captured_url):
    """Если ISS не отдал INSTRID, бумага определяется по SECTYPE='1'."""
    captured_url["response"] = _response(
        [["SBER", "TQBR", "Сбербанк", "1", "RU0009029540"]],
        columns=["SECID", "BOARDID", "SHORTNAME", "SECTYPE", "ISIN"],
    )

    assert len(get_moex_securities()) == 1


def test_network_failure_raises_instead_of_empty_list(monkeypatch):
    """Недоступность биржи — ошибка, а не «бумаг нет»."""
    def boom(url, **kwargs):
        raise requests.exceptions.ReadTimeout("Read timed out")

    monkeypatch.setattr(moex_client, "_moex_get", boom)

    with pytest.raises(MoexUnavailableError):
        get_moex_securities()


def test_empty_board_is_not_an_error(captured_url):
    """Пустой ответ — валидный результат: список бумаг просто пуст."""
    assert get_moex_securities() == []
