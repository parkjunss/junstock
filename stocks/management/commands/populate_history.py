# stocks/management/commands/populate_history.py

import yfinance as yf
import pandas as pd
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from stocks.models import Stock, StockPriceHistory
from django.db import transaction
from django.db.models import Avg, Max # Max를 여기에 추가

class Command(BaseCommand):
    help = 'Populates the StockPriceHistory model with historical data from yfinance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tickers',
            nargs='+',
            type=str,
            help='A list of stock tickers to process.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all stocks in the database.',
        )
        # yfinance가 지원하는 기간 문자열을 사용 (예: '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max')
        parser.add_argument(
            '--period',
            type=str,
            default='10y',
            help="Period of historical data to fetch (e.g., '1y', '5y', 'max').",
        )

        # --- 🔽 새로운 옵션을 추가합니다 🔽 ---
        parser.add_argument(
            '--update',
            action='store_true',
            help='Fetch only new data since the last recorded date for each stock.',
        )


    @transaction.atomic
    def handle(self, *args, **options):
        if options['update']:
            # --update 옵션이 사용되면 업데이트 로직 실행
            self.perform_update()
        else:
            # 기존의 전체 데이터 채우기 로직 실행
            self.perform_full_population(*args, **options)

    def perform_full_population(self, *args, **options):
        if not options['tickers'] and not options['all']:
            raise CommandError('You must specify at least one ticker with --tickers or use --all.')

        if options['tickers']:
            tickers_list = options['tickers']
            # DB에 존재하는 Stock 인스턴스만 대상으로 필터링
            stocks_to_process = Stock.objects.filter(code__in=tickers_list)
            if len(tickers_list) != stocks_to_process.count():
                self.stdout.write(self.style.WARNING("Some specified tickers do not exist in the database and will be skipped."))
        else:
            stocks_to_process = Stock.objects.all()

        if not stocks_to_process.exists():
            self.stdout.write(self.style.WARNING("No stocks found to process."))
            return

        # Stock 인스턴스와 티커 목록을 분리하여 준비
        tickers_list = list(stocks_to_process.values_list('code', flat=True))
        stock_map = {stock.code: stock for stock in stocks_to_process}

        period = options['period']
        
        self.stdout.write(f"Fetching data for {len(tickers_list)} tickers for the period: {period}...")

        # 한 번에 모든 종목 데이터 다운로드
        hist_df = yf.download(
            tickers=tickers_list,
            period=period,
            group_by='ticker',
            progress=True, # 진행 상황을 보여주는 것이 좋음
        )

        if hist_df.empty:
            self.stdout.write(self.style.WARNING("No data was returned from yfinance."))
            return

        self.stdout.write("Data download complete. Processing and saving to database...")

        history_objects_to_create = []

        # MultiIndex DataFrame 순회
        # 바깥쪽 레벨(level 0)은 Ticker(예: 'AAPL', 'MSFT')
        for ticker in hist_df.columns.levels[0]:
            # 해당 티커의 데이터만 선택 (Open, High, Low, Close, Volume 등)
            single_stock_df = hist_df[ticker]
            
            # NaN 값이 있는 행은 건너뛰기 (데이터가 없는 날 등)
            single_stock_df = single_stock_df.dropna()

            stock_instance = stock_map.get(ticker)
            if not stock_instance:
                self.stdout.write(self.style.WARNING(f"Ticker {ticker} from yfinance response not found in our DB map. Skipping."))
                continue

            self.stdout.write(f"  - Processing {stock_instance.short_name} ({ticker})...")
            
            for index, row in single_stock_df.iterrows():
                # index는 Pandas Timestamp 객체
                record_date = index.date()
                
                # 데이터가 유효한지 간단히 확인
                if pd.isna(row['Open']) or row['Volume'] == 0:
                    continue

                history_objects_to_create.append(
                    StockPriceHistory(
                        stock=stock_instance,
                        date=record_date,
                        open_price=row['Open'],
                        high_price=row['High'],
                        low_price=row['Low'],
                        close_price=row['Close'],
                        volume=row['Volume'],
                        adj_close=row.get('Adj Close', row['Close'])
                    )
                )

        if not history_objects_to_create:
            self.stdout.write(self.style.WARNING("No valid historical records to save."))
            return

        self.stdout.write(f"Preparing to save {len(history_objects_to_create)} records...")
        
        # bulk_create로 한 번에 효율적으로 데이터 삽입
        # ignore_conflicts=True: 이미 존재하는 (stock, date) 조합은 무시하고 넘어감
        StockPriceHistory.objects.bulk_create(history_objects_to_create, ignore_conflicts=True, batch_size=1000)

        self.stdout.write(self.style.SUCCESS('Historical data population complete.'))


    def perform_update(self):
        """
        DB에 저장된 마지막 날짜 이후의 데이터만 가져와 업데이트합니다.
        """
        self.stdout.write("--- Performing Daily Update ---")
        
        # 1. 업데이트할 모든 주식을 가져옵니다.
        all_stocks = Stock.objects.all()
        stock_map = {stock.id: stock for stock in all_stocks}

        # 2. 각 주식별로 마지막 데이터 날짜를 한 번의 쿼리로 효율적으로 찾습니다.
        latest_dates = StockPriceHistory.objects.values('stock_id').annotate(latest_date=Max('date'))
        
        # {stock_id: latest_date, ...} 형태의 딕셔너리로 변환
        latest_dates_map = {item['stock_id']: item['latest_date'] for item in latest_dates}

        history_objects_to_create = []

        # 3. 각 주식을 순회하며 업데이트가 필요한 데이터를 가져옵니다.
        for stock_id, stock_instance in stock_map.items():
            last_date = latest_dates_map.get(stock_id)

            if last_date:
                # 마지막 날짜가 있으면, 그 다음 날부터 오늘까지의 데이터를 요청합니다.
                start_date = last_date + timedelta(days=1)
                # 만약 오늘 날짜와 같다면, 이미 최신이므로 건너뜁니다.
                if start_date > date.today():
                    self.stdout.write(f"{stock_instance.code}: Already up-to-date.")
                    continue
                
                self.stdout.write(f"Updating {stock_instance.code} from {start_date}...")
            else:
                # 데이터가 아예 없는 신규 종목이면, 최근 1년치 데이터를 가져옵니다.
                start_date = date.today() - timedelta(days=365)
                self.stdout.write(f"No history for {stock_instance.code}. Fetching last 1 year data...")

            try:
                # 개별 종목에 대해 데이터를 다운로드합니다.
                hist_df = yf.download(stock_instance.code, start=start_date, progress=False)

                if hist_df.empty:
                    continue

                for index, row in hist_df.iterrows():
                    # ... (데이터 저장 객체 생성 로직은 동일) ...
                    history_objects_to_create.append(
                        StockPriceHistory(
                            stock=stock_instance,
                            date=index.date(),
                            open_price=row['Open'], 
                            high_price=row['High'], 
                            low_price=row['Low'],
                            close_price=row['Close'], 
                            volume=row['Volume'], 
                            adj_close=row.get('Adj Close')
                        )
                    )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error updating {stock_instance.code}: {e}"))
        
        if not history_objects_to_create:
            self.stdout.write(self.style.SUCCESS("All stocks are already up-to-date. No new records to save."))
            return

        self.stdout.write(f"Saving {len(history_objects_to_create)} new records...")
        StockPriceHistory.objects.bulk_create(history_objects_to_create, ignore_conflicts=True, batch_size=1000)
        self.stdout.write(self.style.SUCCESS("Daily update complete."))