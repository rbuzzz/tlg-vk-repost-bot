from app import config, crud, db, logging_setup, models
from app.tg import client as tg_client
from app.vk import client as vk_client
from app.tasks import celery_app, repost


def test_imports() -> None:
    assert config and crud and db and logging_setup and models
    assert tg_client and vk_client and celery_app and repost
