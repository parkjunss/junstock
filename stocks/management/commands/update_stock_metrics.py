# stocks/management/commands/update_stock_metrics.py

import yfinance as yf
from django.core.management.base import BaseCommand
from stocks.models import Stock
from tqdm import tqdm # 진행 상황을 보여주는 라이브러리 (pip install tqdm)
import math # math 모듈 import

from django.utils import timezone

YFINANCE_TO_MODEL_MAP = {
    # --- 기본 정보 ---
    'shortName': 'short_name',
    'longName': 'long_name',
    'exchange': 'market',
    'currency': 'currency',

    # --- 실시간 시세 정보 (regularMarket* 키 사용 권장) ---
    'regularMarketPrice': 'current_price',
    'regularMarketPreviousClose': 'previous_close',
    'regularMarketChange': 'market_change',
    'regularMarketChangePercent': 'change_percent',
    'regularMarketDayHigh': 'day_high',
    'regularMarketDayLow': 'day_low',
    'regularMarketVolume': 'volume',
    'marketCap': 'market_cap',

    # --- 기업 프로필 정보 ---
    'website': 'website',
    'longBusinessSummary': 'long_business_summary',
    'fullTimeEmployees': 'full_time_employees',
    'country': 'country',

    # --- 펀더멘탈 분석 ---
    'trailingEps': 'trailing_eps',
    'forwardEps': 'forward_eps',
    'trailingPE': 'trailing_pe',
    'forwardPE': 'forward_pe',
    'priceToBook': 'price_to_book',
    'priceToSalesTrailing12Months': 'price_to_sales',
    'dividendYield': 'dividend_yield',
    'payoutRatio': 'payout_ratio',
    'beta': 'beta',
    'revenueGrowth': 'revenue_growth',
    'earningsGrowth': 'earnings_growth',
    'returnOnEquity': 'return_on_equity',
    'enterpriseValue': 'enterprise_value',
    'enterpriseToEbitda': 'enterprise_to_ebitda',

    # --- 기술적 분석 ---
    'fiftyTwoWeekHigh': 'fifty_two_week_high',
    'fiftyTwoWeekLow': 'fifty_two_week_low',
    'fiftyDayAverage': 'fifty_day_average',
    'twoHundredDayAverage': 'two_hundred_day_average',

    # --- 애널리스트 평가 ---
    'recommendationKey': 'recommendation_key',
    'targetMeanPrice': 'target_mean_price',
    'targetHighPrice': 'target_high_price',
    'targetLowPrice': 'target_low_price',
    'numberOfAnalystOpinions': 'number_of_analyst_opinions',

    # --- 지분 및 리스크 ---
    'sharesOutstanding': 'shares_outstanding',
    'heldPercentInsiders': 'held_percent_insiders',
    'heldPercentInstitutions': 'held_percent_institutions',
    'shortRatio': 'short_ratio',
    'overallRisk': 'overall_risk',
}

# CompanyOfficer 모델을 위한 별도 맵
OFFICER_YFINANCE_TO_MODEL_MAP = {
    'name': 'name',
    'title': 'title',
    'age': 'age',
    'totalPay': 'total_pay',
}

class Command(BaseCommand):
    help = 'Updates key financial metrics for all stocks in the database.'
    def handle(self, *args, **kwargs):
        stocks_to_update = Stock.objects.all()
        self.stdout.write(f'Starting to update metrics for {stocks_to_update.count()} stocks...')
        """
        DB에 저장된 모든 주식의 최신 정보를 yfinance에서 효율적으로 가져와 동기화합니다.
        yf.Tickers를 사용하여 단일 API 요청으로 처리합니다.
        """
        print("===== 전체 주식 데이터 동기화 시작 =====")
        
        stocks_to_sync = Stock.objects.all()
        if not stocks_to_sync:
            print("동기화할 주식이 없습니다.")
            return "No stocks to sync."

        stock_codes = [s.code for s in stocks_to_sync]
        
        # 1. yf.Tickers로 모든 주식 정보를 한 번에 가져옵니다. (매우 효율적)
        try:
            tickers = yf.Tickers(stock_codes)
            all_ticker_infos = tickers.tickers 
            print(f"{len(stock_codes)}개 종목 정보 다운로드 완료.")
        except Exception as e:
            print(f"yf.Tickers 정보 다운로드 실패: {e}")
            # 실패 시, 여기서 작업을 중단하고 다음 시도를 기다립니다.
            return "Failed to download ticker info."

        updated_stocks = []
        skipped_count = 0
        try:
            # 2. 각 주식 객체에 다운로드한 정보를 매핑하여 업데이트합니다.
            for stock in stocks_to_sync:
                ticker_info = all_ticker_infos.get(stock.code.upper()).info # yfinance는 대문자 코드를 사용

                # yfinance에서 정보를 가져오지 못했거나(상장 폐지 등), 필수 정보가 없는 경우 건너뜁니다.
                if not ticker_info or ticker_info.get('regularMarketPrice') is None:
                    print(f"경고: {stock.code}의 유효한 정보를 가져오지 못해 건너뜁니다.")
                    skipped_count += 1
                    continue

                # 3. YFINANCE_TO_MODEL_MAP을 사용하여 동적으로 필드를 업데이트합니다.
                for yf_key, model_field in YFINANCE_TO_MODEL_MAP.items():
                    value = ticker_info.get(yf_key)
                    
                    # 모델 필드에 값 설정 (값이 None이 아니거나, 필드가 None을 허용하는 경우)
                    if value is not None:
                        setattr(stock, model_field, value)
                
                stock.last_synced_at = timezone.now()
                updated_stocks.append(stock)
                print(f"성공: {stock} 주식 정보.")
        except:
            print(f"실패: {stock} 주식 정보.")
        # 4. bulk_update를 사용하여 변경된 모든 주식 정보를 DB에 한 번에 저장합니다.
        if updated_stocks:
            # 업데이트할 필드 목록을 맵에서 동적으로 생성 (+ last_synced_at)
            update_fields = list(YFINANCE_TO_MODEL_MAP.values()) + ['last_synced_at']
            
            Stock.objects.bulk_update(updated_stocks, update_fields)
            print(f"성공: {len(updated_stocks)}개 주식 정보 DB 동기화 완료.")
            if skipped_count > 0:
                print(f"실패/건너뜀: {skipped_count}개 주식.")

        print("===== 전체 주식 데이터 동기화 종료 =====")
        return f"Synced {len(updated_stocks)} of {len(stock_codes)} stocks."
