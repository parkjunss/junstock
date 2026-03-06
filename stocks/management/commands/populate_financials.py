# stocks/management/commands/populate_financials.py

import yfinance as yf
import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from stocks.models import Stock, FinancialItem, FinancialStatement


class Command(BaseCommand):
    help = 'Populates or updates the FinancialStatement model with data from yfinance.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tickers', nargs='+', type=str, help='A list of stock tickers to process.'
        )
        parser.add_argument(
            '--all', action='store_true', help='Process all stocks in the database.'
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Delete all existing financial statements before populating new data.'
        )

    def handle(self, *args, **options):
        if not options['tickers'] and not options['all']:
            raise CommandError('You must specify either --tickers or --all.')

        # --clear + --all 동시 사용 방지 (실수로 전체 데이터 삭제 방지)
        if options['clear'] and options['all']:
            raise CommandError('--clear --all 동시 사용은 위험합니다. --tickers와 함께 사용하세요.')

        if options['clear']:
            self.stdout.write(self.style.WARNING("--- Deleting all existing financial statements... ---"))
            count, _ = FinancialStatement.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f"--- Successfully deleted {count} records. ---"))

        if options['tickers']:
            stocks_to_process = Stock.objects.filter(code__in=options['tickers'])
        else:
            stocks_to_process = Stock.objects.all()

        financial_items = FinancialItem.objects.filter(is_active=True)
        if not financial_items.exists():
            raise CommandError('No active FinancialItem found. Please add financial items to track.')

        item_map = {item.yfinance_name: item for item in financial_items}
        item_names = list(item_map.keys())

        self.stdout.write("--- Starting Financial Data Population ---")

        for stock in stocks_to_process:
            self._process_stock(stock, item_map, item_names)

        self.stdout.write(self.style.SUCCESS("--- Financial Data Population Complete ---"))

    @transaction.atomic
    def _process_stock(self, stock, item_map, item_names):
        """종목 하나에 대한 재무 데이터를 수집하고 저장합니다. (트랜잭션 분리)"""
        self.stdout.write(f"Processing {stock.code}...")
        try:
            ticker = yf.Ticker(stock.code)

            data_sources = {
                'A': [
                    ticker.income_stmt,
                    ticker.balance_sheet,
                    ticker.cashflow,
                ],
                'Q': [
                    ticker.quarterly_income_stmt,
                    ticker.quarterly_balance_sheet,
                    ticker.quarterly_cashflow,
                ]
            }

            statements_to_create = []
            processed_records = set()

            for period_type, df_list in data_sources.items():
                for df in df_list:
                    if df is None or df.empty:
                        continue

                    df_transposed = df.T

                    for date, row in df_transposed.iterrows():
                        for item_name in item_names:
                            if item_name not in row or pd.isna(row[item_name]):
                                continue

                            financial_item = item_map[item_name]

                            # 중복 방지
                            record_key = (stock.id, financial_item.id, date.date(), period_type)
                            if record_key in processed_records:
                                continue

                            try:
                                value = int(float(row[item_name]))  # 소수점 안전 처리
                            except (ValueError, TypeError):
                                self.stdout.write(self.style.WARNING(
                                    f"  > Skipping invalid value for {item_name} on {date.date()}: {row[item_name]}"
                                ))
                                continue

                            statements_to_create.append(
                                FinancialStatement(
                                    stock=stock,
                                    item=financial_item,
                                    date=date.date(),
                                    value=value,
                                    period_type=period_type
                                )
                            )
                            processed_records.add(record_key)

            if statements_to_create:
                FinancialStatement.objects.bulk_create(statements_to_create, ignore_conflicts=True)
                self.stdout.write(self.style.SUCCESS(
                    f"  > Saved {len(statements_to_create)} records for {stock.code}."
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  > No financial data found for {stock.code}."
                ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(
                f"  > Error processing {stock.code}: {e}"
            ))
            raise  # 트랜잭션 롤백을 위해 예외를 다시 던짐