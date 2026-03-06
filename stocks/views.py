from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets, permissions, generics
from .models import *
from .serializers import *
from .services import *

from .filters import StockFilter
from django.db.models import Count, Q, F, Window
from django.db.models.functions import RowNumber

from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404 
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from django.shortcuts import render
from django.http import JsonResponse
from .models import Stock, StockPriceHistory, PredictionLog
import time

from rest_framework.decorators import api_view
from .services import run_backtesting_simulation # 위에서 만든 함수 import


# stocks/views.py
from django.core.mail import send_mail
# --- API Views (Refactored with Data Localization) ---

class StockDetailAPIView(APIView):
    """
    DB에 저장된 주식의 상세 정보를 반환하는 API (매우 빠름)
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, stock_code):
        stock_code = stock_code.upper()
        
        # 1. 로컬 DB에서 주식 정보를 직접 조회합니다.
        stock_obj = get_object_or_404(Stock, code=stock_code)
        
        # 2. Serializer를 통해 응답 데이터를 만듭니다.
        #    (주의: StockDetailSerializer를 새로 만들어야 합니다)
        serializer = StockDetailSerializer(stock_obj, context={'request': request})
        return Response(serializer.data)

class StockChartAPIView(APIView):
    """
    쿼리 파라미터로 기간을 받아 해당 종목의 히스토리 데이터를 반환하는 API
    (데이터는 외부 API를 통해 가져오지만, 캐싱 적용)
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, stock_code):
        stock_code = stock_code.upper()
        period = request.query_params.get('period', '1y')
        allowed_periods = ['1mo', '3mo', '6mo', '1y', '5y', 'max']
        if period not in allowed_periods:
            period = '1y'

        # 차트 데이터는 DB에 저장하지 않으므로, 이전의 캐싱/비동기 로직을 유지하거나
        # 단순하게 직접 호출할 수 있습니다. 여기서는 단순성을 위해 직접 호출합니다.
        chart_data = get_stock_history(stock_code, period)
        
        if not chart_data:
            return Response({"error": "Chart data not found"}, status=status.HTTP_404_NOT_FOUND)
            
        return Response(chart_data)

# --- 기존 Views (일부 수정 또는 유지) ---

class StockListAPIView(APIView):
    """
    DB에 저장된 주식 목록을 보여주는 API
    """
    def get(self, request):
        stocks = Stock.objects.all()
        serializer = StockSerializer(stocks, many=True)
        return Response(serializer.data)

@method_decorator(cache_page(60 * 60), name='dispatch')
class PopularStockListAPIView(APIView):
    """
    미리 정의된 인기 종목 목록을 반환하는 API
    """
    def get(self, request):
        popular_stocks = [
            {'code': 'AAPL', 'short_name': 'Apple Inc.'},
            {'code': 'GOOGL', 'short_name': 'Alphabet Inc. (Google)'},
            {'code': 'MSFT', 'short_name': 'Microsoft Corp.'},
            {'code': '005930.KS', 'short_name': '삼성전자'},
            {'code': '035420.KS', 'short_name': 'NAVER'},
            {'code': '035720.KS', 'short_name': '카카오'},
        ]
        return Response(popular_stocks)

class WatchlistViewSet(viewsets.ModelViewSet):
    serializer_class = WatchlistSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Watchlist.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        stock = serializer.validated_data.get('stock')
        exists = Watchlist.objects.filter(user=self.request.user, stock=stock).exists()
        if exists:
            raise ValidationError('This stock is already in the watchlist.')
        serializer.save(user=self.request.user)

class StockSearchAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = request.query_params.get('query', None)
        if not query:
            return Response([], status=200)

        search_results = Stock.objects.filter(
            Q(short_name__icontains=query) | Q(code__istartswith=query) | Q(long_name__istartswith=query)
        )[:20]

        context = {'request': request}
        serializer = StockSearchSerializer(search_results, many=True, context=context)
        return Response(serializer.data, status=200)

@method_decorator(cache_page(60 * 60), name='dispatch')
class FinancialsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, stock_code):
        financials_data = get_financial_statements(stock_code)
        if not financials_data:
            return Response({"error": "Financial data not found"}, status=404)
        return Response(financials_data)

from rest_framework.pagination import PageNumberPagination

class StandardResultsSetPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class StockScreenerView(generics.ListAPIView):
    queryset = Stock.objects.filter(market_cap__isnull=False).order_by('-market_cap')
    serializer_class = StockSerializer
    permission_classes = [permissions.AllowAny]
    filterset_class = StockFilter
    pagination_class = StandardResultsSetPagination

class AIReportAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, stock_code):
        user = request.user
        additional_options = request.data.get('options', [])
        stock = get_object_or_404(Stock, code=stock_code.upper())

        try:
            report_obj = stock.ai_report
        except AIReport.DoesNotExist:
            report_text_data = generate_ai_report(stock.code, additional_options)
            report_text = report_text_data.get('report')
            if not report_text or '오류가 발생했습니다' in report_text:
                return Response({"error": "AI 리포트 생성에 실패했습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            report_obj = AIReport.objects.create(stock=stock, report_text=report_text)
        
        if not report_obj:
            return Response({"error": "리포트를 처리하는 중 문제가 발생했습니다."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        view_log, created_log = UserReportViewLog.objects.get_or_create(user=user, stock=stock)
        validity_period = timedelta(days=3)
        is_still_valid = not created_log and (timezone.now() - view_log.last_viewed_at < validity_period)

        if not is_still_valid:
            if user.ai_credit <= 0:
                return Response(
                    {"error": "크레딧이 부족합니다.", "code": "INSUFFICIENT_CREDIT"},
                    status=status.HTTP_402_PAYMENT_REQUIRED
                )
            user.ai_credit -= 1
            user.save(update_fields=['ai_credit'])
            view_log.save()

        return Response({
            'report': report_obj.report_text,
            'remaining_credits': user.ai_credit,
            'valid_until': (view_log.last_viewed_at + validity_period).isoformat()
        })

@method_decorator(cache_page(60 * 15), name='dispatch')
class InsiderTransactionsAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, stock_code):
        transactions = get_insider_transactions(stock_code)
        return Response(transactions)

class AddCreditAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        user.ai_credit += 1
        user.save(update_fields=['ai_credit'])
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)




# 1. 비밀번호 재설정 '요청' API (인증 코드 발송)
class PasswordResetRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        User = get_user_model()
        try:
            user = User.objects.get(email=email)
            
            # 기존 코드가 있다면 삭제하고 새로 생성
            PasswordResetCode.objects.filter(user=user).delete()
            reset_code = PasswordResetCode.objects.create(user=user)
            
            # 이메일 발송
            send_mail(
                subject='[Your App Name] 비밀번호 재설정 인증 코드',
                message=f'안녕하세요, {user.username}님.\n\n비밀번호 재설정을 위한 인증 코드는 다음과 같습니다:\n\n{reset_code.code}\n\n이 코드는 10분간 유효합니다.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
            )
            return Response({"message": "인증 코드가 이메일로 발송되었습니다."}, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response({"error": "해당 이메일을 가진 사용자가 없습니다."}, status=status.HTTP_404_NOT_FOUND)

# 2. 비밀번호 재설정 '확인' API (코드 검증 및 비밀번호 변경)
class PasswordResetConfirmAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email')
        code = request.data.get('code')
        password = request.data.get('password')
        
        try:
            user = get_user_model().objects.get(email=email)
            reset_code_entry = PasswordResetCode.objects.get(user=user, code=code)

            if reset_code_entry.is_expired():
                return Response({"error": "인증 코드가 만료되었습니다."}, status=status.HTTP_400_BAD_REQUEST)
            
            # 비밀번호 변경
            user.set_password(password)
            user.save()
            
            # 사용된 인증 코드 삭제
            reset_code_entry.delete()
            
            return Response({"message": "비밀번호가 성공적으로 변경되었습니다."}, status=status.HTTP_200_OK)
            
        except (get_user_model().DoesNotExist, PasswordResetCode.DoesNotExist):
            return Response({"error": "이메일 또는 인증 코드가 올바르지 않습니다."}, status=status.HTTP_400_BAD_REQUEST)



def get_model_performance_stats():
    # 평가가 완료된 로그만 필터링
    evaluated_logs = PredictionLog.objects.filter(is_correct__isnull=False)
    
    total_predictions = evaluated_logs.count()
    if total_predictions == 0:
        return {"accuracy": 0}

    correct_predictions = evaluated_logs.filter(is_correct=True).count()
    
    # 전체 정확도
    overall_accuracy = (correct_predictions / total_predictions) * 100

    # 시그널별 정확도
    signal_stats = evaluated_logs.values('predicted_signal').annotate(
        total=Count('id'),
        correct=Count('id', filter=Q(is_correct=True))
    ).order_by('predicted_signal')

    stats = {
        "overall_accuracy": f"{overall_accuracy:.2f}%",
        "total_predictions": total_predictions,
        "signal_details": list(signal_stats)
    }
    return stats




@api_view(['GET'])
def backtesting_performance_api(request, stock_code):
    """
    특정 주식에 대한 백테스팅 결과를 JSON으로 반환하는 API
    """
    # URL 쿼리 파라미터에서 기간 가져오기 (예: ?start_date=2023-01-01&end_date=2023-12-31)
    start_date = request.query_params.get('start_date', '2023-01-01') # 기본값 설정
    end_date = request.query_params.get('end_date', '2024-01-01')
    
    data = run_backtesting_simulation(stock_code, start_date, end_date)
    
    if "error" in data:
        return Response(data, status=400)
        
    return Response(data)