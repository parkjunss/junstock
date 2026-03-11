# config/celery.py

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')

# 이 부분이 핵심입니다! 
# 괄호 안에 명시적으로 앱 이름을 적어주거나, 
# 장고가 인식하는 정확한 경로를 찾아야 합니다.
app.autodiscover_tasks(['stocks'])