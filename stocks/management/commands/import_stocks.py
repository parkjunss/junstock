# stocks/management/commands/import_stocks.py

import csv
from django.core.management.base import BaseCommand
from stocks.models import Stock
from django.conf import settings
import os
import pandas as pd

class Command(BaseCommand):
    help = 'Imports stock data from a companies.csv file'

    def handle(self, *args, **kwargs):
        # CSV 파일의 경로를 프로젝트의 루트 디렉토리 기준으로 설정합니다.
        # settings.BASE_DIR는 manage.py 파일이 있는 위치를 가리킵니다.
        csv_file_path = os.path.join(settings.BASE_DIR, 'companies.csv')
        
        self.stdout.write(f'Starting to import stocks from {csv_file_path}')

        # 기존 Stock 데이터를 모두 삭제 (선택 사항, 중복을 피하기 위해)
        Stock.objects.all().delete()
        # self.stdout.write(self.style.SUCCESS('Successfully deleted all existing stocks.'))
        df = pd.read_csv(csv_file_path)
        print(df.head())
        stocks_to_create=[]
        try:
            for idx, row in df.iterrows():
                # CSV의 'ticker'와 'name' 컬럼을 사용합니다.
                # 다른 컬럼이 필요하다면 row['column_name']으로 접근 가능합니다.
                ticker = row['Symbol']
                long_name = row['Name']
                short_name = long_name.split(' ')[0]
                print(long_name, short_name)
                current_price = row['Last Sale']
                net_change = row['Net Change']
                change_percent = row['% Change']
                volume = row['Volume']
                industry = row['Industry']
                sector = row['Sector']
                market_cap = row['Market Cap']
                

                if not ticker or not long_name:
                    self.stdout.write(self.style.WARNING(f'Skipping row due to missing ticker or name: {row}'))
                    continue
                    
                # Stock 객체를 메모리에만 생성 (아직 DB에 저장 안함)
                stocks_to_create.append(
                    Stock(
                        code=ticker,
                        long_name=long_name,
                        short_name=short_name,
                        current_price=current_price.strip('$') or current_price,
                        market_change=net_change,
                        change_percent=change_percent.strip('%') or change_percent,
                        volume=volume,
                        market_cap=market_cap,
                        industry=industry,
                        sector=sector,
                    )
                )
            
            # bulk_create를 사용해 모든 Stock 객체를 한 번의 쿼리로 DB에 삽입 (매우 효율적)
            if stocks_to_create:
                Stock.objects.bulk_create(stocks_to_create, ignore_conflicts=True)
                self.stdout.write(self.style.SUCCESS(f'Successfully imported {len(stocks_to_create)} stocks.'))
            else:
                self.stdout.write(self.style.WARNING('No stocks to import.'))

        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File not found at {csv_file_path}. Make sure the file is in the root directory.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'An error occurred: {e}'))