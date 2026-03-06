# config/__init__.py

# 이 코드는 Django가 시작될 때 Celery가 항상 import 되도록 보장합니다.
from .celery import app as celery_app

__all__ = ('celery_app',)