# stocks/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings # ⚡️ 1. settings를 import 합니다.
import random
import string
from django.utils import timezone
from datetime import timedelta

class CustomUser(AbstractUser):
    # ⚡️ AI 리포트 생성을 위한 크레딧 필드 추가
    ai_credit = models.IntegerField(default=10, verbose_name='AI 리포트 크레딧')
    # 구글 프로필 이미지 URL을 저장할 필드
    profile_image_url = models.URLField(max_length=500, blank=True, null=True)
    # 어떤 소셜 계정으로 가입했는지 표시
    provider = models.CharField(max_length=50, blank=True)
    
class Stock(models.Model):
    """주식 종목 정보를 담는 모델 (데이터 로컬화) - 강화 버전"""
    # --- 기본 정보 (기존 유지) ---
    code = models.CharField(max_length=20, unique=True, verbose_name='종목코드', db_index=True)
    short_name = models.CharField(max_length=100, blank=True, null=True, verbose_name='종목명 (단축)', db_index=True)
    long_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='종목명 (전체)', db_index=True)
    market = models.CharField(max_length=50, blank=True, null=True, verbose_name='시장 (e.g., NMS, KOSPI)')
    currency = models.CharField(max_length=10, blank=True, null=True, verbose_name='통화 (e.g., USD, KRW)')
    is_sp500 = models.BooleanField(default=False, verbose_name='S&P 500 포함 여부')

    # --- 실시간 시세 정보 (기존 유지 및 보강) ---
    current_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='현재가')
    previous_close = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='전일 종가')
    market_change = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name="변동액")
    change_percent = models.FloatField(null=True, blank=True, verbose_name='변동률 (%)', db_index=True)
    day_high = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='금일 고가')
    day_low = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='금일 저가')
    volume = models.BigIntegerField(null=True, blank=True, verbose_name='거래량', db_index=True)
    market_cap = models.BigIntegerField(null=True, blank=True, verbose_name='시가총액', db_index=True)

    # --- 기업 프로필 정보 (기존 유지) ---
    sector = models.CharField(max_length=100, blank=True, null=True, verbose_name='섹터', db_index=True)
    industry = models.CharField(max_length=100, blank=True, null=True, verbose_name='산업', db_index=True)
    website = models.URLField(max_length=500, blank=True, null=True, verbose_name='웹사이트')
    long_business_summary = models.TextField(blank=True, null=True, verbose_name='기업 개요')
    full_time_employees = models.PositiveIntegerField(null=True, blank=True, verbose_name='직원 수')
    country = models.CharField(max_length=100, blank=True, null=True, verbose_name='국가')

    # --- 펀더멘탈 분석 강화 (신규 추가) ---
    trailing_eps = models.FloatField(null=True, blank=True, verbose_name='EPS (TTM)', db_index=True)
    forward_eps = models.FloatField(null=True, blank=True, verbose_name='EPS (Forward)', db_index=True)
    trailing_pe = models.FloatField(null=True, blank=True, verbose_name='PER (TTM)', db_index=True)
    forward_pe = models.FloatField(null=True, blank=True, verbose_name='PER (Forward)', db_index=True)
    price_to_book = models.FloatField(null=True, blank=True, verbose_name='PBR', db_index=True)
    price_to_sales = models.FloatField(null=True, blank=True, verbose_name='PSR (TTM)')
    dividend_yield = models.FloatField(null=True, blank=True, verbose_name='배당수익률 (%)', db_index=True)
    payout_ratio = models.FloatField(null=True, blank=True, verbose_name='배당성향 (%)')
    beta = models.FloatField(null=True, blank=True, verbose_name='베타 (시장 민감도)', db_index=True)
    revenue_growth = models.FloatField(null=True, blank=True, verbose_name='매출 성장률 (YoY)')
    earnings_growth = models.FloatField(null=True, blank=True, verbose_name='이익 성장률 (YoY)')
    return_on_equity = models.FloatField(null=True, blank=True, verbose_name='자기자본이익률 (ROE)')
    enterprise_value = models.BigIntegerField(null=True, blank=True, verbose_name='기업가치 (EV)')
    enterprise_to_ebitda = models.FloatField(null=True, blank=True, verbose_name='EV/EBITDA')

    # --- 기술적 분석 지표 (신규 추가) ---
    fifty_two_week_high = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='52주 최고가')
    fifty_two_week_low = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='52주 최저가')
    fifty_day_average = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='50일 이동평균')
    two_hundred_day_average = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='200일 이동평균')
    
    # --- 애널리스트 평가 및 목표가 (신규 추가) ---
    recommendation_key = models.CharField(max_length=50, blank=True, null=True, verbose_name='종합 투자의견 (e.g., buy, hold)')
    target_mean_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='평균 목표주가')
    target_high_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='최고 목표주가')
    target_low_price = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True, verbose_name='최저 목표주가')
    number_of_analyst_opinions = models.PositiveIntegerField(null=True, blank=True, verbose_name='애널리스트 수')

    # --- 지분 및 리스크 정보 (신규 추가) ---
    shares_outstanding = models.BigIntegerField(null=True, blank=True, verbose_name='발행주식수')
    held_percent_insiders = models.FloatField(null=True, blank=True, verbose_name='내부자 지분율 (%)')
    held_percent_institutions = models.FloatField(null=True, blank=True, verbose_name='기관 지분율 (%)')
    short_ratio = models.FloatField(null=True, blank=True, verbose_name='공매도 비율 (Short Ratio)')
    overall_risk = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='종합 리스크 점수')

    # --- 데이터 관리 ---
    last_synced_at = models.DateTimeField(auto_now=True, verbose_name='마지막 동기화 시간')

    def __str__(self):
        return f'{self.long_name or self.short_name} ({self.code})'

    class Meta:
        verbose_name = '주식 정보'
        verbose_name_plural = '주식 정보 목록'
        ordering = ['-market_cap'] # 기본 정렬을 시가총액 순으로

class CompanyOfficer(models.Model):
    """기업 임원 정보를 담는 모델"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='officers', verbose_name='주식')
    name = models.CharField(max_length=255, verbose_name='이름')
    title = models.CharField(max_length=255, blank=True, null=True, verbose_name='직책')
    age = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='나이')
    total_pay = models.BigIntegerField(null=True, blank=True, verbose_name='총 보수')

    def __str__(self):
        return f'{self.name} ({self.stock.code})'
    
    class Meta:
        verbose_name = '기업 임원'
        verbose_name_plural = '기업 임원 목록'
        unique_together = ('stock', 'name') # 한 회사에 동명이인 임원이 있는 경우는 드물므로 중복 방지


class StockPriceHistory(models.Model):
    """
    일별 주가 데이터 (OHLCV)를 저장하는 모델
    """
    # 어떤 주식의 기록인지 연결합니다.
    # Stock이 삭제되면 관련 기록도 함께 삭제됩니다.
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='price_history')
    
    # 기록된 날짜
    date = models.DateField(db_index=True)
    
    # 시가, 고가, 저가, 종가 (정확한 금융 계산을 위해 DecimalField 사용)
    open_price = models.DecimalField(max_digits=20, decimal_places=4)
    high_price = models.DecimalField(max_digits=20, decimal_places=4)
    low_price = models.DecimalField(max_digits=20, decimal_places=4)
    close_price = models.DecimalField(max_digits=20, decimal_places=4)
    
    # 거래량
    volume = models.BigIntegerField()
    
    # 배당, 액면분할 등이 반영된 수정 종가 (분석에 유용)
    adj_close = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)

    class Meta:
        # 한 주식에 대해 하루에 하나의 기록만 있도록 제약
        # models.UniqueConstraint를 사용하는 것이 최신 방식입니다.
        constraints = [
            models.UniqueConstraint(fields=['stock', 'date'], name='unique_stock_date')
        ]
        # 기본 정렬 순서를 최신 날짜부터로 지정
        ordering = ['-date']
        verbose_name_plural = "Stock Price Histories"

    def __str__(self):
        return f'{self.stock.code} on {self.date}'

class Watchlist(models.Model):
    """사용자별 관심종목 리스트 모델"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='watchlist', verbose_name='사용자')
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, verbose_name='주식', related_name='watchlist_items') # related_name 추가
    target_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='목표가')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='등록일')

    class Meta:
        # 한 사용자가 동일한 주식을 여러 번 추가하는 것을 방지
        unique_together = ('user', 'stock')

    def __str__(self):
        return f'{self.user.username} - {self.stock.short_name}'


class News(models.Model):
    """주식 관련 뉴스 모델"""
    title = models.CharField(max_length=255, verbose_name='뉴스 제목')
    description = models.TextField(unique=False, verbose_name='뉴스 요약', default='')
    url = models.CharField(max_length=500, verbose_name='링크', default='')
    thumbnail = models.CharField(max_length=500, verbose_name='썸네일', default='', null=True, blank=True)
    published_at = models.DateTimeField(verbose_name='발행일')
    # 하나의 뉴스가 여러 종목과 관련될 수 있으므로 ManyToManyField 사용
    related_stocks = models.ManyToManyField(Stock, blank=True, related_name='news', verbose_name='관련 종목')

    def __str__(self):
        return self.title
    

class FinancialItem(models.Model):
    """
    재무제표의 계정과목을 정의하는 모델
    """
    STATEMENT_TYPE_CHOICES = [
        ('IS', 'Income Statement'),      # 손익계산서
        ('BS', 'Balance Sheet'),         # 재무상태표
        ('CF', 'Cash Flow Statement'),   # 현금흐름표
    ]
    # yfinance에서 가져온 원본 이름 (예: 'Total Revenue')
    yfinance_name = models.CharField(max_length=255, unique=True, verbose_name='yfinance 계정과목명')
    # 프론트엔드와 통신할 때 사용할 표준화된 키 (예: 'total_revenue')
    standard_key = models.CharField(max_length=100, blank=True, null=True, verbose_name='표준 키')

    statement_type = models.CharField(
        max_length=2, 
        choices=STATEMENT_TYPE_CHOICES,
        help_text='이 계정과목이 속한 재무제표의 종류',
        blank=True,
        null=True
    )
    # -----------------------

    # 계정과목의 표시 순서를 제어하기 위한 필드 (선택사항이지만 강력 추천)
    order = models.PositiveIntegerField(default=0, help_text='재무제표 내 표시 순서')
    
    # UI에 표시될 한글 이름 (예: '총 매출')
    korean_label = models.CharField(max_length=100, blank=True, verbose_name='한글 라벨')
    is_active = models.BooleanField(default=True, verbose_name='활성화 여부')

    class Meta:
        ordering = ['statement_type', 'order'] # 재무제표 종류별, 그리고 순서별로 정렬

    def __str__(self):
        return f"{self.korean_label} ({self.standard_key}) - [{self.get_statement_type_display()}]"


class FinancialStatement(models.Model):
    """
    개별 주식의 특정 재무 계정과목에 대한 시계열 데이터를 저장하는 모델
    """
    # 어떤 주식의 재무 데이터인지 연결
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='financials')
    
    # 어떤 계정과목에 대한 데이터인지 연결 (만들어두신 FinancialItem 모델 활용)
    item = models.ForeignKey(FinancialItem, on_delete=models.CASCADE, related_name='statements')
    
    # 데이터의 기준 날짜 (재무제표의 발표일 또는 종료일)
    date = models.DateField()
    
    # 실제 값 (매우 큰 숫자를 다룰 수 있도록 BigIntegerField 사용)
    value = models.BigIntegerField()
    
    # 데이터의 종류 (연간: 'A' - Annual, 분기: 'Q' - Quarterly)
    period_type = models.CharField(max_length=1, choices=[('A', 'Annual'), ('Q', 'Quarterly')])

    class Meta:
        # 한 주식의, 한 계정과목에, 한 날짜, 한 종류의 데이터만 존재하도록 제약
        constraints = [
            models.UniqueConstraint(fields=['stock', 'item', 'date', 'period_type'], name='unique_financial_statement')
        ]
        ordering = ['-date'] # 최신순 정렬

    def __str__(self):
        return f"{self.stock.code} - {self.item.yfinance_name} ({self.date}, {self.period_type}): {self.value}"


class IndustryFinancialAverage(models.Model):
    """
    산업(Industry)별, 재무 항목(FinancialItem)별 평균 시계열 데이터를 저장하는 모델
    """
    industry = models.CharField(max_length=100, db_index=True)
    item = models.ForeignKey(FinancialItem, on_delete=models.CASCADE)
    period_type = models.CharField(max_length=1, choices=[('A', 'Annual'), ('Q', 'Quarterly')])
    
    # { "2022-12-31": 12345.67, "2021-12-31": 11111.89, ... } 형태의 데이터를 저장
    average_values = models.JSONField(default=dict)

    class Meta:
        # 이 조합은 유일해야 함
        unique_together = ('industry', 'item', 'period_type')
        verbose_name = "산업별 재무 평균"
        verbose_name_plural = "산업별 재무 평균"

    def __str__(self):
        return f"Average for {self.industry} - {self.item.korean_label} ({self.period_type})"

        
class AIReport(models.Model):
    # 어떤 주식에 대한 리포트인지 연결 (1:1 관계)
    stock = models.OneToOneField(Stock, on_delete=models.CASCADE, related_name='ai_report')

    # 생성된 리포트 텍스트
    report_text = models.TextField(verbose_name='AI 리포트 내용')
    
    # 이 리포트가 언제 생성되었는지
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    
    # 이 리포트가 언제 마지막으로 업데이트되었는지
    updated_at = models.DateTimeField(auto_now=True, verbose_name='최종 업데이트일')

    def __str__(self):
        return f"AI Report for {self.stock.short_name}"


class Dashboard(models.Model):
    """
    미리 계산된 대시보드 데이터를 저장하는 모델.
    전체 대시보드 데이터를 하나의 JSON 객체로 저장합니다.
    """
    # 나중에 다른 대시보드가 추가될 경우를 대비해 key 필드를 둘 수 있습니다.
    key = models.CharField(max_length=50, primary_key=True, default='main_dashboard')
    
    # 대시보드에 필요한 모든 데이터를 이 필드에 저장합니다.
    data = models.JSONField(default=dict)
    
    # 데이터가 언제 업데이트되었는지 추적합니다.
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Dashboard Data ({self.key}) updated at {self.updated_at}"

    class Meta:
        verbose_name = "대시보드 데이터"
        verbose_name_plural = "대시보드 데이터"


class UserReportViewLog(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    
    # 이 사용자가 이 리포트를 마지막으로 조회(결제)한 시간
    last_viewed_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        # 한 사용자는 한 주식에 대해 하나의 조회 기록만 가짐
        unique_together = ('user', 'stock')

    def __str__(self):
        return f"{self.user.username} viewed {self.stock.code} report at {self.last_viewed_at}"


def generate_reset_code():
    """6자리 숫자 인증 코드를 생성합니다."""
    return ''.join(random.choices(string.digits, k=6))

class PasswordResetCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    code = models.CharField(max_length=6, default=generate_reset_code)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        """인증 코드 유효기간(예: 10분)이 지났는지 확인합니다."""
        return timezone.now() > self.created_at + timedelta(minutes=10)



class DailyMarketReport(models.Model):
    """하루 한 번 생성되는 전체 시황 리포트"""
    date = models.DateField(unique=True, default=timezone.now)
    summary_text = models.TextField(verbose_name="종합 시황 분석 텍스트")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Market Report for {self.date}"

class StockDailyAnalysis(models.Model):
    """종목별 일일 AI 분석 리포트"""
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE)
    date = models.DateField(default=timezone.now)
    analysis_text = models.TextField(verbose_name="종목 분석 텍스트")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 특정 날짜에 특정 주식에 대한 분석은 하나만 존재
        unique_together = ('stock', 'date')

    def __str__(self):
        return f"Analysis for {self.stock.code} on {self.date}"


# ⚡️ 새로운 기술적 분석 지표 모델
class TechnicalIndicator(models.Model):
    """
    각 날짜의 주가 기록에 대한 기술적 분석 지표들을 저장합니다.
    StockPriceHistory와 1:1 관계를 가집니다.
    """
    # 어떤 주가 기록에 대한 지표인지 연결
    history = models.OneToOneField(
        StockPriceHistory, 
        on_delete=models.CASCADE, 
        related_name='indicators', # history.indicators 로 접근 가능
        primary_key=True # ⚡️ 성능 최적화를 위해 history 필드를 기본 키로 사용
    )

    # --- 이동평균 (Moving Averages) ---
    sma_20 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='20일 단순이동평균')
    sma_60 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='60일 단순이동평균')
    sma_120 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='120일 단순이동평균')
    ema_20 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='20일 지수이동평균')
    ema_60 = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='60일 지수이동평균')

    # --- 모멘텀 지표 (Momentum Indicators) ---
    rsi_14 = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True, verbose_name='RSI (14일)')
    
    # MACD는 세 개의 값(MACD, Signal, Histogram)으로 구성됨
    macd = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='MACD')
    macd_signal = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='MACD Signal Line')
    macd_hist = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='MACD Histogram')

    # --- 변동성 지표 (Volatility Indicators) ---
    bb_upper = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='볼린저밴드 상단')
    bb_middle = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='볼린저밴드 중간')
    bb_lower = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name='볼린저밴드 하단')

    # 마지막 업데이트 시간
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Indicators for {self.history.stock.code} on {self.history.date}"



class PredictionLog(models.Model):
    """
    강화학습 모델의 일일 예측 결과를 기록하고 성능을 추적하는 모델
    """
    # 예측 정보
    stock = models.ForeignKey(Stock, on_delete=models.CASCADE, related_name='prediction_logs', verbose_name="주식")
    model_name = models.CharField(max_length=50, default="SAC_v1", verbose_name="사용 모델")
    prediction_date = models.DateField(verbose_name="예측 기준일") # 예측이 이루어진 날짜 (데이터 기준)
    predicted_signal = models.CharField(max_length=50, verbose_name="예측 시그널") # "강력 매수", "매도" 등
    predicted_ratio = models.FloatField(verbose_name="예측 비율") # -1 ~ 1 사이의 값
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="기록 시간")

    # 성능 평가 정보 (초기에는 Null)
    actual_outcome = models.CharField(max_length=20, null=True, blank=True, verbose_name="실제 결과") # "상승", "하락", "보합"
    actual_change_percent = models.FloatField(null=True, blank=True, verbose_name="실제 등락률 (%)")
    is_correct = models.BooleanField(null=True, blank=True, verbose_name="예측 성공 여부")
    evaluated_at = models.DateTimeField(null=True, blank=True, verbose_name="평가 시간")

    class Meta:
        verbose_name = "AI 예측 로그"
        verbose_name_plural = "AI 예측 로그"
        # 특정 주식에 대해 같은 날짜에 예측이 중복되지 않도록 설정
        unique_together = ('stock', 'prediction_date', 'model_name')
        ordering = ['-prediction_date', 'stock']

    def __str__(self):
        return f"[{self.prediction_date}] {self.stock.code}: {self.predicted_signal}"