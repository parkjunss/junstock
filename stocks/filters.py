# stocks/filters.py

import django_filters
from .models import Stock
from django.db.models import Q

class StockFilter(django_filters.FilterSet):
    # --- 기존 필터들 ---
    market_cap_gt = django_filters.NumberFilter(field_name='market_cap', lookup_expr='gt')
    market_cap_lt = django_filters.NumberFilter(field_name='market_cap', lookup_expr='lt')
    forward_pe_gt = django_filters.NumberFilter(field_name='forward_pe', lookup_expr='gt')
    forward_pe_lt = django_filters.NumberFilter(field_name='forward_pe', lookup_expr='lt')
    price_to_book_lt = django_filters.NumberFilter(field_name='price_to_book', lookup_expr='lt')
    price_to_book_gt = django_filters.NumberFilter(field_name='price_to_book', lookup_expr='gt')
    dividend_yield_gt = django_filters.NumberFilter(field_name='dividend_yield', lookup_expr='gt')
    dividend_yield_lt = django_filters.NumberFilter(field_name='dividend_yield', lookup_expr='lt')

    # --- 새로 추가된 필터들 ---
    sector = django_filters.CharFilter(field_name='sector', lookup_expr='iexact')
    industry = django_filters.CharFilter(field_name='industry', lookup_expr='icontains')
    change_percent_gt = django_filters.NumberFilter(field_name='change_percent', lookup_expr='gt')
    change_percent_lt = django_filters.NumberFilter(field_name='change_percent', lookup_expr='lt')
    volume_gt = django_filters.NumberFilter(field_name='volume', lookup_expr='gt')
    volume_lt = django_filters.NumberFilter(field_name='volume', lookup_expr='lt')

    # --- 검색 및 정렬 필터 ---
    query = django_filters.CharFilter(method='filter_by_name_or_code', label="Search by Name or Code")
    ordering = django_filters.OrderingFilter(
        fields=(
            ('market_cap', 'market_cap'),
            ('change_percent', 'change_percent'),
            ('volume', 'volume'),
            ('forward_pe', 'forward_pe'),
            ('price_to_book', 'price_to_book'),
            ('dividend_yield', 'dividend_yield'),
        ),
        field_labels={
            'market_cap': '시가총액 높은 순',
            '-market_cap': '시가총액 낮은 순',
            'change_percent': '상승률 낮은 순',
            '-change_percent': '상승률 높은 순',
            'volume': '거래량 많은 순',
            '-volume': '거래량 적은 순',
            'forward_pe': 'PER 낮은 순',
            '-forward_pe': 'PER 높은 순',
            'price_to_book': 'PBR 낮은 순',
            '-price_to_book': 'PBR 높은 순',
            'dividend_yield': '배당수익률 높은 순',
            '-dividend_yield': '배당수익률 낮은 순',
        }
    )

    class Meta:
        model = Stock
        fields = ['market', 'sector', 'industry']

    def filter_by_name_or_code(self, queryset, name, value):
        return queryset.filter(
            Q(long_name__icontains=value) | Q(short_name__icontains=value) | Q(code__istartswith=value)
        )
    

    @property
    def qs(self):
        # 1. 부모 클래스의 기본 필터링 로직을 먼저 실행합니다.
        #    이 시점의 queryset은 사용자가 요청한 ?per_lt=15 같은 조건이 모두 적용된 상태입니다.
        queryset = super().qs 

        # 2. 어떤 필터들이 사용되었는지 확인합니다.
        #    self.form.cleaned_data 에는 사용자가 값을 입력한 필터들의 이름이 들어있습니다.
        #    예: {'forward_pe_lt': 15.0, 'dividend_yield_gt': 3.0}
        used_filters = self.form.cleaned_data.keys()

        # 3. 특정 지표 필터가 사용되었다면, 해당 필드의 NULL 값을 결과에서 제외합니다.
        if 'forward_pe_gt' in used_filters or 'forward_pe_lt' in used_filters:
            queryset = queryset.exclude(forward_pe__isnull=True)

        if 'price_to_book_gt' in used_filters or 'price_to_book_lt' in used_filters:
            queryset = queryset.exclude(price_to_book__isnull=True)
            
        if 'dividend_yield_gt' in used_filters or 'dividend_yield_lt' in used_filters:
            queryset = queryset.exclude(dividend_yield__isnull=True)
        
        # ... 다른 지표들에 대해서도 필요하다면 동일한 로직을 추가 ...

        # 4. 최종적으로 필터링된 queryset을 반환합니다.
        return queryset