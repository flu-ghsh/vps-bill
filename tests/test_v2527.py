import asyncio
from types import SimpleNamespace

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from app.main import AdminOnlyMiddleware
from app.notifier import Notifier


def test_expired_callback_is_suppressed(capsys):
    mw = AdminOnlyMiddleware(frozenset({1}))
    event = SimpleNamespace(from_user=SimpleNamespace(id=1), data="upcoming")
    # isinstance check requires genuine CallbackQuery.
    q = CallbackQuery(id="x", from_user={"id":1,"is_bot":False,"first_name":"Test"}, chat_instance="1", data="upcoming")
    async def handler(event, data):
        raise TelegramBadRequest(method="answerCallbackQuery", message="query is too old and response timeout expired or query ID is invalid")
    assert asyncio.run(mw(handler,q,{})) is None
    assert "Устаревший callback" in capsys.readouterr().out


def test_other_callback_error_propagates():
    mw=AdminOnlyMiddleware(frozenset({1}))
    q = CallbackQuery(id="x", from_user={"id":1,"is_bot":False,"first_name":"Test"}, chat_instance="1", data="upcoming")
    async def handler(event,data):
        raise TelegramBadRequest(method="answerCallbackQuery",message="other failure")
    import pytest
    with pytest.raises(TelegramBadRequest):
        asyncio.run(mw(handler,q,{}))
