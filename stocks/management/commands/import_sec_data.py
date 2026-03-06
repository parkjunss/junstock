# stocks/management/commands/import_sec_data.py

import os
import json
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from stocks.models import Stock, FinancialItem, FinancialStatement
from tqdm import tqdm

class Command(BaseCommand):
    help = 'Imports financial data from SEC JSON files into the database.'

    def add_arguments(self, parser):
        # JSON 파일들이 있는 폴더 경로를 인자로 받도록 설정
        parser.add_argument('data_folder', type=str, help='The folder path containing the SEC JSON files.')

    def handle(self, *args, **kwargs):
        data_folder = kwargs['data_folder']
        if not os.path.isdir(data_folder):
            self.stdout.write(self.style.ERROR(f"Folder not found: {data_folder}"))
            return

        json_files = [f for f in os.listdir(data_folder) if f.endswith('.json')]
        if not json_files:
            self.stdout.write(self.style.WARNING(f"No JSON files found in {data_folder}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Found {len(json_files)} JSON files. Starting import..."))

        for file_name in tqdm(json_files, desc="Importing Files"):
            file_path = os.path.join(data_folder, file_name)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.stderr.write(self.style.ERROR(f"Error reading or parsing {file_name}: {e}"))
                continue

            # 1. CIK로 Stock 객체 찾기
            # Stock 모델에 cik 필드가 있다고 가정합니다. 없으면 ticker 등으로 찾아야 합니다.
            # CIK는 앞에 0을 채워서 10자리로 만들어야 할 수 있습니다.
            cik_str = str(data.get('cik')).zfill(10)
            try:
                stock = Stock.objects.get(cik=cik_str)
            except Stock.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Stock with CIK {cik_str} not found, skipping {file_name}"))
                continue
            
            facts = data.get('facts', {})
            us_gaap = facts.get('us-gaap', {})

            if not us_gaap:
                continue

            # 2. 파일 내 모든 재무 데이터를 순회하며 처리
            for item_name, item_data in us_gaap.items():
                if 'units' not in item_data or 'USD' not in item_data['units']:
                    continue
                
                # 3. FinancialItem 객체 가져오기 (없으면 생성)
                # SEC 데이터의 키를 yfinance_name 필드와 매칭한다고 가정
                item_obj, created = FinancialItem.objects.get_or_create(
                    yfinance_name=item_name,
                    defaults={'korean_label': item_name} # 초기 한글명은 영문명과 동일하게 설정
                )
                if created:
                    self.stdout.write(f"\nNew FinancialItem created: {item_name}")

                statements_to_create = []
                for point in item_data['units']['USD']:
                    try:
                        # 4. period_type 결정
                        form_type = point.get('form')
                        if form_type == '10-K':
                            period_type = 'A'
                        elif form_type == '10-Q':
                            period_type = 'Q'
                        else:
                            continue # 다른 폼은 건너뛰기

                        # 5. FinancialStatement 객체 생성 준비
                        statement = FinancialStatement(
                            stock=stock,
                            item=item_obj,
                            date=datetime.strptime(point['end'], '%Y-%m-%d').date(),
                            value=point['val'],
                            period_type=period_type
                        )
                        statements_to_create.append(statement)
                    
                    except (ValueError, KeyError) as e:
                        # 날짜 형식이 다르거나 필수 키가 없는 경우
                        self.stderr.write(f"\nSkipping data point for {stock.code} - {item_name} due to error: {e}")
                        continue
                
                # 6. Bulk Create로 한 번에 DB에 저장 (효율성)
                # ignore_conflicts=True: 이미 존재하는 데이터는 무시하고 넘어감 (UniqueConstraint 필요)
                if statements_to_create:
                    FinancialStatement.objects.bulk_create(statements_to_create, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS('Import process finished.'))