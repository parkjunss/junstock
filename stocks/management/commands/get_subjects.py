from django.core.management.base import BaseCommand
from stocks.models import Stock, FinancialItem
import pandas as pd
class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        # 모든 종목을 다 돌면 시간이 너무 오래 걸리므로, 대표적인 일부 종목만 샘플링
        # 여기서는 DB에 저장된 주식 중 앞 100개만 사용
        all_items = FinancialItem.objects.all()
        name = []
        standard = []
        label = []
        for i in all_items:
            name.append(i.yfinance_name)
            standard.append(i.standard_key)
            label.append(i.korean_label)
        
        df = pd.DataFrame({'name':name, 'standard':standard, 'label':label})
        df.to_csv("./financial_items.csv")