# stocks/management/commands/create_ai_reports.py

from django.core.management.base import BaseCommand
from stocks.models import Stock, AIReport
from stocks.services import generate_ai_report # 이전에 만든 서비스 함수 재활용
from tqdm import tqdm

class Command(BaseCommand):
    help = 'Generates or updates AI reports for specified stocks.'

    # 1. --stocks 옵션 추가: 특정 종목만 지정해서 리포트를 만들 수 있게 함
    def add_arguments(self, parser):
        parser.add_argument(
            '--stocks',
            nargs='+', # 여러 개의 값을 받을 수 있음
            type=str,
            help='A list of stock codes to generate reports for (e.g., AAPL MSFT).',
        )
        parser.add_argument(
            '--sp500',
            action='store_true', # 이 옵션을 쓰면 True가 됨
            help='Generate reports for all S&P 500 stocks.',
        )

    def handle(self, *args, **kwargs):
        stocks_to_process = []
        
        # 2. 옵션에 따라 처리할 주식 목록 결정
        if kwargs['stocks']:
            stocks_to_process = Stock.objects.filter(code__in=kwargs['stocks'])
            self.stdout.write(self.style.SUCCESS(f'Targeting {len(stocks_to_process)} specified stocks.'))
        elif kwargs['sp500']:
            stocks_to_process = Stock.objects.filter(is_sp500=True)
            self.stdout.write(self.style.SUCCESS(f'Targeting all {len(stocks_to_process)} S&P 500 stocks.'))
        else:
            self.stdout.write(self.style.ERROR('Please specify stocks using --stocks or use --sp500 flag.'))
            return

        self.stdout.write('Starting AI report generation...')

        # 3. 각 주식에 대해 리포트 생성 및 저장
        for stock in tqdm(stocks_to_process):
            self.stdout.write(f'\nProcessing {stock.code}...')
            try:
                # 서비스 함수 호출하여 리포트 생성
                report_data = generate_ai_report(stock.code)
                report_text = report_data.get('report')

                if not report_text or '오류가 발생했습니다' in report_text:
                    self.stdout.write(self.style.WARNING(f'  -> Failed to generate report for {stock.code}.'))
                    continue

                # update_or_create로 DB에 저장/업데이트
                report_obj, created = AIReport.objects.update_or_create(
                    stock=stock,
                    defaults={'report_text': report_text}
                )
                
                if created:
                    self.stdout.write(self.style.SUCCESS(f'  -> Successfully CREATED report for {stock.code}.'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'  -> Successfully UPDATED report for {stock.code}.'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  -> An unexpected error occurred for {stock.code}: {e}'))

        self.stdout.write(self.style.SUCCESS('AI report generation process finished.'))