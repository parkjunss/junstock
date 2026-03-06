# config/celery.py

import os
from celery import Celery
from celery.schedules import crontab
from django.conf import settings

# Django의 settings 모듈을 Celery의 기본 설정으로 사용하도록 설정
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# ⚡️ Django의 settings.py를 사용하도록 설정
app.config_from_object('django.conf:settings', namespace='CELERY')

# ⚡️ 시간대 설정을 명시적으로 추가 (안전을 위해)
app.conf.enable_utc = False
app.conf.timezone = settings.TIME_ZONE # settings.py의 'Asia/Seoul'을 가져옴

app.autodiscover_tasks()

app.conf.beat_schedule = {
    # 'check-stock-prices-every-5-minutes': {
    #     'task': 'stocks.tasks.check_stock_prices_and_notify',
    #     'schedule': crontab(minute='*/5'),
    # },
    # 'update-metrics-daily': {
    #     'task': 'stocks.tasks.run_update_stock_metrics',
    #     # 매일 새벽 5시 30분(한국 시간 기준)에 실행
    #     'schedule': crontab(minute='30', hour='5'), 
    # },
    # 'update-main-dashboard-every-5-minutes': {
    #     'task': 'stocks.tasks.update_dashboard_task', # 실행할 작업의 경로
    #     'schedule': crontab(minute='*/5'),  # 5분마다 실행
    # },
    # 'schedule-daily-reports-main-task': {
    #     'task': 'stocks.tasks.schedule_all_daily_reports',
    #     'schedule': crontab(minute='0', hour='8'), # 매일 아침 8시에 조율 작업 시작
    # },
}