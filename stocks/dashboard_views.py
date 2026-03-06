
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework import permissions, status
from django.db.models import F, Window
from django.db.models.functions import RowNumber

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from .models import Dashboard

from .models import Stock
from .serializers import StockSerializer

from .tasks import update_dashboard_task

# --- 공통 쿼리셋을 위한 기본 뷰 ---
class BaseSP500View(APIView):
    """S&P 500 종목 중 유효한 데이터를 필터링하는 기본 뷰"""
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        # 여러 뷰에서 공통으로 사용하는 S&P 500 기본 쿼리셋
        return Stock.objects.filter(is_sp500=True, current_price__gt=0, volume__gt=0)
    
class MainDashboardAPIView(APIView):
    """
    미리 생성된 대시보드 데이터를 제공하는 초고속 API.
    모든 데이터는 백그라운드에서 주기적으로 업데이트됩니다.
    """
    permission_classes = [permissions.AllowAny]
    # 이 뷰는 DB 조회만 하므로 캐싱이 덜 중요하지만,
    # DB 부하를 줄이기 위해 짧은 캐시를 적용할 수 있습니다.
    def get(self, request, *args, **kwargs):
        try:
            # 미리 계산된 대시보드 데이터를 가져옵니다.
            try:
                dashboard = Dashboard.objects.get(key='main_dashboard')
            except:
                update_dashboard_task
                dashboard = Dashboard.objects.get(key='main_dashboard')
            return Response(dashboard.data)
        except Dashboard.DoesNotExist:
            # 아직 백그라운드 작업이 한 번도 실행되지 않은 경우
            return Response(
                {"error": "데이터를 준비 중입니다. 잠시 후 다시 시도해주세요."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )