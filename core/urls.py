# urls.py (main app urls)
from django.urls import path
from . import views

urlpatterns = [
    path('', views.DashboardPageView.as_view(), name='home'),
    path('screener/', views.ScreenerPageView.as_view(), name='screener'),
    path('<str:stock_code>/', views.StockDetailView.as_view(), name='stock_detail'),
    path('api/kpis/<str:stock_code>/', views.KpiApiView.as_view(), name='api_kpis'),
    path('api/chart/<str:stock_code>/', views.ChartView.as_view(), name='api_chart'),
    path('dashboard/', views.DashboardPageView.as_view(), name='dashboard'),
    path('profile/', views.profile, name='profile'),
    path('watchlist/', views.watchlist, name='watchlist'),
]