"""
ИНН / ОГРН / EMITTER_ID эмитента по тикеру с MOEX ISS.

Используется для поиска карточки на e-disclosure.ru (по ИНН в форме поиска).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GrahamAnalyzer/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def get_emitter_info(ticker: str) -> dict[str, Any] | None:
    """
    Возвращает словарь с ключами: emitter_id, inn, ogrn, title (как в MOEX),
    либо None если тикер не найден.
    """
    sec = urllib.parse.quote(ticker, safe="")
    url = f"https://iss.moex.com/iss/securities/{sec}.json?iss.meta=off"
    try:
        data = _fetch_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        logger.debug("MOEX securities %s: %s", ticker, e)
        return None
    except Exception as exc:
        logger.debug("MOEX securities %s: %s", ticker, exc)
        return None

    desc = data.get("description") or {}
    cols = desc.get("columns") or []
    rows = desc.get("data") or []
    emitter_id: str | None = None
    for row in rows:
        z = dict(zip(cols, row))
        if z.get("name") == "EMITTER_ID":
            emitter_id = z.get("value")
            break
    if not emitter_id:
        return None

    try:
        eid = int(emitter_id)
    except (TypeError, ValueError):
        return None

    url2 = f"https://iss.moex.com/iss/emitters/{eid}.json?iss.meta=off"
    try:
        data2 = _fetch_json(url2)
    except Exception as exc:
        logger.debug("MOEX emitters %s: %s", eid, exc)
        return None

    em = data2.get("emitter") or {}
    cols2 = em.get("columns") or []
    row0 = (em.get("data") or [None])[0]
    if not row0:
        return None
    z2 = dict(zip(cols2, row0))
    return {
        "emitter_id": eid,
        "inn": z2.get("INN"),
        "ogrn": z2.get("OGRN"),
        "title": z2.get("TITLE"),
    }
