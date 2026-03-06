# stocks/management/commands/calculate_industry_averages.py
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count
from stocks.models import Stock, FinancialItem, FinancialStatement, IndustryFinancialAverage
from tqdm import tqdm

class Command(BaseCommand):
    help = 'Calculates and saves industry-wide financial statement averages.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('Starting industry average calculation...'))

        industries = Stock.objects.exclude(industry__isnull=True).exclude(industry='').values_list('industry', flat=True).distinct()
        
        objects_to_update = []
        objects_to_create = []
        
        # 기존 데이터를 미리 메모리에 로드하여 DB 조회를 최소화
        existing_averages = {
            (avg.industry, avg.item_id, avg.period_type): avg
            for avg in IndustryFinancialAverage.objects.all()
        }

        all_items = list(FinancialItem.objects.all())  # 루프 밖으로

        for industry in tqdm(industries, desc="Processing Industries"):
            # 여기서 stocks_in_industry 조회 (industry 루프 안에 있어야 함)
            stocks_in_industry = Stock.objects.filter(industry=industry).values_list('id', flat=True)

            for item in all_items:
                for period in ['A', 'Q']:
                    averages = FinancialStatement.objects.filter(
                        stock_id__in=stocks_in_industry,
                        item=item,
                        period_type=period
                    ).values('date').annotate(
                        average_value=Avg('value'),
                        company_count=Count('stock', distinct=True)
                    ).order_by('date')

                    if not averages:
                        continue

                    average_values_dict = {
                        avg['date'].strftime('%Y-%m-%d'): {
                            'avg': avg['average_value'],
                            'count': avg['company_count']
                        }
                        for avg in averages
                    }

                    key = (industry, item.id, period)
                    if key in existing_averages:
                        obj = existing_averages[key]
                        obj.average_values = average_values_dict
                        objects_to_update.append(obj)
                    else:
                        objects_to_create.append(
                            IndustryFinancialAverage(
                                industry=industry,
                                item=item,
                                period_type=period,
                                average_values=average_values_dict
                            )
                        )
        
        self.stdout.write(f"\nFound {len(objects_to_create)} new records to create.")
        self.stdout.write(f"Found {len(objects_to_update)} records to update.")

        if objects_to_create:
            IndustryFinancialAverage.objects.bulk_create(
                objects_to_create, 
                batch_size=500, 
                ignore_conflicts=True
            )
            self.stdout.write(self.style.SUCCESS('Bulk created new records.'))

        if objects_to_update:
            IndustryFinancialAverage.objects.bulk_update(objects_to_update, ['average_values'], batch_size=500)
            self.stdout.write(self.style.SUCCESS('Bulk updated existing records.'))
            
        self.stdout.write(self.style.SUCCESS('Successfully calculated and saved all industry averages.'))