# stocks/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StockSearchAPIView, PopularStockListAPIView, StockDetailAPIView, 
    StockChartAPIView, FinancialsAPIView, StockScreenerView, 
    AIReportAPIView, InsiderTransactionsAPIView, AddCreditAPIView, WatchlistViewSet, PasswordResetRequestAPIView, PasswordResetConfirmAPIView, backtesting_performance_api
)
from .dashboard_views import MainDashboardAPIView

# ViewSet을 위한 라우터 설정
router = DefaultRouter()
# /api/stocks/watchlist/ 경로로 WatchlistViewSet을 연결
router.register(r'watchlist', WatchlistViewSet, basename='watchlist')

urlpatterns = [
    path('search/', StockSearchAPIView.as_view(), name='stock-search'),
    path('popular/', PopularStockListAPIView.as_view(), name='popular-stock-list'),
    path('detail/<str:stock_code>/', StockDetailAPIView.as_view(), name='stock-detail'),
    path('chart/<str:stock_code>/', StockChartAPIView.as_view(), name='stock-chart'),
    path('financials/<str:stock_code>/', FinancialsAPIView.as_view(), name='stock-financials'),
    path('screener/', StockScreenerView.as_view(), name='stock-screener'),
    # 1. 주요 시장 지표 (인덱스, 환율 등)
    path('dashboard/', MainDashboardAPIView.as_view(), name='dashboard'),
    path('ai-report/<str:stock_code>/', AIReportAPIView.as_view(), name='ai-report'),
    path('insider-transactions/<str:stock_code>/', InsiderTransactionsAPIView.as_view(), name='insider-transactions'),
    path('user/add-credit/', AddCreditAPIView.as_view(), name='add-credit'),
    path('password-reset/request/', PasswordResetRequestAPIView.as_view(), name='password-reset-request'),
    path('password-reset/confirm/', PasswordResetConfirmAPIView.as_view(), name='password-reset-confirm'),
    path('api/backtesting/<str:stock_code>/', backtesting_performance_api, name='backtesting-api'),

]

# 라우터가 생성한 URL들을 기존 urlpatterns에 추가
urlpatterns += router.urls