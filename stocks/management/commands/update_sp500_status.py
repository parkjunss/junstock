# stocks/management/commands/update_sp500_status.py

import pandas as pd
from django.core.management.base import BaseCommand
from stocks.models import Stock

class Command(BaseCommand):
    help = 'Updates the is_sp500 flag for stocks based on the Wikipedia list.'

    def handle(self, *args, **kwargs):
        # 1. 위키피디아에서 S&P 500 목록 테이블을 읽어옵니다.
        # pandas.read_html은 페이지의 모든 <table>을 찾아 리스트로 반환합니다.
        try:
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            # 첫 번째 테이블이 바로 S&P 500 구성 종목 테이블입니다.
            sp500_df = pd.read_html(url)[0] 
            
            # 테이블에서 티커(Symbol) 컬럼만 추출하여 set으로 만듭니다. (빠른 조회를 위해)
            sp500_tickers = set(sp500_df['Symbol'].tolist())
            self.stdout.write(self.style.SUCCESS(f'Successfully fetched {len(sp500_tickers)} S&P 500 tickers from Wikipedia.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to fetch S&P 500 list: {e}'))
            return

        # 2. DB의 모든 주식에 대해 is_sp500 플래그를 업데이트합니다.
        updated_count = 0
        
        # 먼저 모든 종목의 플래그를 False로 초기화 (S&P 500에서 제외된 종목 처리)
        Stock.objects.all().update(is_sp500=False)
        self.stdout.write('Reset all is_sp500 flags to False.')

        # S&P 500 티커 목록에 있는 종목들만 is_sp500 플래그를 True로 설정
        # bulk_update를 사용하면 더 효율적이지만, 여기서는 update()로도 충분합니다.
        queryset_to_update = Stock.objects.filter(code__in=sp500_tickers)
        updated_count = queryset_to_update.update(is_sp500=True)
        
        self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} stocks as S&P 500 components.'))