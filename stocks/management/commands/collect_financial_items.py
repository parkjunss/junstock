# stocks/management/commands/collect_financial_items.py

import yfinance as yf
from django.core.management.base import BaseCommand
from stocks.models import Stock, FinancialItem
import time

class Command(BaseCommand):
    help = 'Collects and updates financial items, using a master list and then scanning all tickers.'

    def handle(self, *args, **kwargs):
        # ======================================================================
        # 1단계: 대표 종목으로 '마스터 순서'와 '타입'을 설정
        # ======================================================================
        self.stdout.write(self.style.SUCCESS('--- Step 1: Setting master order from a representative ticker (MSFT) ---'))
        try:
            master_ticker = yf.Ticker('MSFT')
            statements_to_process = [
                ('IS', master_ticker.financials),
                ('BS', master_ticker.balance_sheet),
                ('CF', master_ticker.cashflow),
            ]
            
            for stmt_type, df in statements_to_process:
                for order, yfinance_name in enumerate(df.index):
                    # update_or_create로 기준 정보 생성 및 업데이트
                    FinancialItem.objects.update_or_create(
                        yfinance_name=yfinance_name,
                        defaults={'statement_type': stmt_type, 'order': order}
                    )
            self.stdout.write(self.style.SUCCESS('Master items have been set.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Could not set master items: {e}'))
            return

        # ======================================================================
        # 2단계: 모든 종목을 스캔하여 누락된 '특수 계정과목' 추가
        # ======================================================================
        self.stdout.write(self.style.SUCCESS('\n--- Step 2: Scanning all tickers for unique, non-standard items ---'))
        
        tickers_to_scan = Stock.objects.values_list('code', flat=True)
        if not tickers_to_scan:
            self.stdout.write(self.style.ERROR('No stocks found in the database.'))
            return
            
        # 이미 처리된(타입이 있는) 항목들의 이름을 미리 가져옴
        processed_items = set(FinancialItem.objects.filter(statement_type__isnull=False).values_list('yfinance_name', flat=True))

        newly_found_items = {} # 새로 발견된 항목들을 임시 저장할 딕셔너리 {yfinance_name: stmt_type}

        for i, ticker_code in enumerate(tickers_to_scan):
            self.stdout.write(f"\rScanning... [{i+1}/{len(tickers_to_scan)}] {ticker_code}", ending="")
            try:
                stock = yf.Ticker(ticker_code)
                # 각 재무제표를 확인
                for stmt_type, df in [('IS', stock.financials), ('BS', stock.balance_sheet), ('CF', stock.cashflow)]:
                    for yfinance_name in df.index:
                        # 아직 처리되지 않은 새로운 항목인 경우에만 추가
                        if yfinance_name not in processed_items and yfinance_name not in newly_found_items:
                            newly_found_items[yfinance_name] = stmt_type
                            self.stdout.write(f"\n  Found new unique item: '{yfinance_name}' from {ticker_code} (Type: {stmt_type})")
                
                time.sleep(0.1) # API 요청에 약간의 딜레이를 주어 서버 부담 감소
            except Exception:
                continue

        self.stdout.write(self.style.SUCCESS('\nFinished scanning all tickers.'))

        if not newly_found_items:
            self.stdout.write(self.style.SUCCESS('No new items found.'))
            return

        # ======================================================================
        # 3단계: 새로 발견된 항목들을 DB에 저장
        # ======================================================================
        self.stdout.write(self.style.SUCCESS('\n--- Step 3: Saving newly found items to the database ---'))
        
        # 각 타입별로 가장 마지막 order 값을 가져옴
        last_orders = {
            'IS': FinancialItem.objects.filter(statement_type='IS').order_by('-order').first().order if FinancialItem.objects.filter(statement_type='IS').exists() else 0,
            'BS': FinancialItem.objects.filter(statement_type='BS').order_by('-order').first().order if FinancialItem.objects.filter(statement_type='BS').exists() else 0,
            'CF': FinancialItem.objects.filter(statement_type='CF').order_by('-order').first().order if FinancialItem.objects.filter(statement_type='CF').exists() else 0,
        }

        for yfinance_name, stmt_type in newly_found_items.items():
            # 해당 타입의 마지막 순서 다음에 새로운 순서를 할당
            last_orders[stmt_type] += 1
            new_order = last_orders[stmt_type]

            obj, created = FinancialItem.objects.update_or_create(
                yfinance_name=yfinance_name,
                defaults={
                    'statement_type': stmt_type,
                    'order': new_order
                }
            )
            if created:
                self.stdout.write(f"  CREATED: '{yfinance_name}' (Type: {stmt_type}, Order: {new_order})")
            else: # 이미 존재하지만 타입이 없었던 경우
                self.stdout.write(f"  UPDATED: '{yfinance_name}' (Type: {stmt_type}, Order: {new_order})")

        self.stdout.write(self.style.SUCCESS('Process complete.'))