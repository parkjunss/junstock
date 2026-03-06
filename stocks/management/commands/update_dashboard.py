# your_app/management/commands/update_dashboard.py

import time
from django.core.management.base import BaseCommand, CommandError
from stocks.models import Dashboard
from stocks.services import aggregate_dashboard_data
from stocks.services import (
    aggregate_dashboard_data,
    get_market_indexes, 
    get_exchange_rates, 
    get_commodity_prices, 
    get_fear_and_greed_index,
    get_stock_history
)

class Command(BaseCommand):
    # 이 커맨드에 대한 도움말. `python manage.py update_dashboard --help` 실행 시 보입니다.
    help = 'Aggregates all necessary data for the main dashboard and saves it to the Dashboard model.'

    def handle(self, *args, **options):
        """
        커맨드의 메인 로직을 담당하는 메서드입니다.
        `python manage.py update_dashboard`를 실행하면 이 메서드가 호출됩니다.
        """
        self.stdout.write(self.style.SUCCESS('Starting dashboard data aggregation...'))
        start_time = time.time()

        try:
            # 1. 서비스 함수를 호출하여 최신 데이터를 가져옵니다.
            #    (Celery Task에서 사용했던 로직과 동일합니다)
            index = get_market_indexes, 
            exchange = get_exchange_rates, 
            commodity = get_commodity_prices, 
            fear_and_greed = get_fear_and_greed_index,

            fresh_data = aggregate_dashboard_data(index, exchange, commodity, fear_and_greed)

            # 2. `update_or_create`를 사용하여 데이터를 갱신합니다.
            dashboard_obj, created = Dashboard.objects.update_or_create(
                key='main_dashboard',
                defaults={'data': fresh_data}
            )

            end_time = time.time()
            duration = end_time - start_time

            if created:
                self.stdout.write(self.style.SUCCESS(
                    f'Successfully created new dashboard data entry in {duration:.2f} seconds.'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'Successfully updated existing dashboard data in {duration:.2f} seconds.'
                ))

        except Exception as e:
            # 에러 발생 시 CommandError를 발생시키면 Django가 처리해줍니다.
            raise CommandError(f'An error occurred during dashboard data aggregation: {e}')