# stocks/admin.py

from django.contrib import admin
from .models import Stock, Watchlist, PredictionLog, News, FinancialItem, AIReport, CustomUser, Dashboard, UserReportViewLog, DailyMarketReport, StockDailyAnalysis, FinancialStatement, StockPriceHistory, TechnicalIndicator
# 아래 클래스들을 추가하여 모델을 관리자 페이지에 등록합니다.


@admin.register(PredictionLog)
class PredictionLogAdmin(admin.ModelAdmin):
    list_display = ('prediction_date', 'stock', 'predicted_signal', 'is_correct', 'actual_change_percent')
    list_filter = ('is_correct', 'predicted_signal', 'stock__code', 'prediction_date')
    search_fields = ('stock__code', 'stock__short_name')
    
@admin.register(TechnicalIndicator)
class TechnicalIndicatorAdmin(admin.ModelAdmin):
    # ⚡️ 1. 쉼표(,)를 추가하여 항목이 하나인 튜플로 만듭니다.
    list_display = ('get_stock_code', 'get_date') # ⚡️ 2. 함수를 사용하는 것이 더 좋습니다.
    
    # ⚡️ list_display에서 ForeignKey를 건너갈 때, 정렬을 위해 함수를 사용하면 더 안정적입니다.
    @admin.display(description='Stock Code', ordering='history__stock__code')
    def get_stock_code(self, obj):
        # obj는 TechnicalIndicator 인스턴스
        return obj.history.stock.code

    @admin.display(description='Date', ordering='-history__date')
    def get_date(self, obj):
        return obj.history.date

    # 검색과 필터는 문자열 경로로도 잘 작동합니다.
    search_fields = ('history__stock__code', 'history__stock__name')
    list_filter = ('history__date',)

@admin.register(StockPriceHistory)
class StockPriceHistoryAdmin(admin.ModelAdmin):
    list_display = ('stock', 'date')
    # ⚡️ list_filter에서도 ForeignKey의 특정 필드를 사용하는 것이 더 좋습니다.
    #    (예: 'stock__code' - 하지만 기본 필터도 잘 작동합니다.)
    list_filter = ('stock', 'date')
    ordering = ('-date', 'stock__code')

    # --- ⚡️ 여기가 핵심 수정 부분 ---
    # 'stock' 대신, stock 객체의 'code' 필드와 'name' 필드를 검색하도록 명시합니다.
    search_fields = ('stock__code', 'stock__short_name')

@admin.register(FinancialStatement)
class FinancialStatementAdmin(admin.ModelAdmin):
    list_display = ('stock', 'item')
    search_fields = ('stock__code', 'stock__short_name', 'item')

@admin.register(UserReportViewLog)
class UserReportViewLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock')

@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ('key', 'updated_at')

@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = (
        'username',
        'email',
        'date_joined',
    )

    list_display_links = (
        'username',
        'email',
    )

@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('code', 'short_name', 'market_cap')
    search_fields = ('short_name', 'code', 'market_cap', 'industry')

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'stock', 'target_price', 'created_at')
    list_filter = ('user',)

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'published_at')
    search_fields = ('title',)
    filter_horizontal = ('related_stocks',) # ManyToManyField를 좀 더 편하게 관리


@admin.register(FinancialItem)
class FinancialItemAdmin(admin.ModelAdmin):
    list_display = ('yfinance_name', 'standard_key', 'korean_label', 'is_active')
    list_editable = ('standard_key', 'korean_label', 'is_active')
    search_fields = ('yfinance_name', 'standard_key', 'korean_label')


@admin.register(AIReport)
class AIReportAdmin(admin.ModelAdmin):
    list_display = ('stock', 'created_at', 'updated_at')


@admin.register(DailyMarketReport)
class DailyMarketReportAdmin(admin.ModelAdmin):
    # 목록 화면에 어떤 필드를 보여줄지 설정
    list_display = ('date', 'created_at')
    # 날짜를 기준으로 필터링할 수 있는 옵션 추가
    list_filter = ('date',)
    # 날짜 내림차순으로 정렬
    ordering = ('-date',)

@admin.register(StockDailyAnalysis)
class StockDailyAnalysisAdmin(admin.ModelAdmin):
    # 목록 화면에 보여줄 필드 설정
    list_display = ('stock', 'date', 'created_at')
    # 종목과 날짜로 필터링 옵션 추가
    list_filter = ('stock', 'date')
    # 날짜 내림차순, 그 다음 종목 코드 순으로 정렬
    ordering = ('-date', 'stock__code')
    # 종목 코드로 검색 기능 추가
    search_fields = ('stock__code', 'stock__short_name')