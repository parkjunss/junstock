import yfinance as yf
import requests
import json
from django.conf import settings
import numpy as np
import pandas as pd
from .models import FinancialItem, Stock, FinancialStatement, StockPriceHistory, TechnicalIndicator, PredictionLog

import fear_and_greed # 라이브러리 import
from google import genai
from finvizfinance.news import News

from django.db.models import F, Window
from django.db.models.functions import RowNumber
from decimal import Decimal
import mplfinance as mpf
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
import os
from email.mime.image import MIMEImage # ⚡️ MIMEImage import
from django.utils import timezone
from django.db.models import Q, Avg, Max
from datetime import date, timedelta

import logging # 로깅을 위해 추가
import re


logger = logging.getLogger(__name__)


def get_peer_stock_data(stock: Stock, count: int = 4) -> dict:
    """
    주어진 주식과 동일한 '산업(Industry)'에 속하는 경쟁사(peer)들의
    주가 등락률 데이터를 반환합니다. 시가총액이 높은 순서대로 정렬합니다.

    Args:
        stock (Stock): 기준이 되는 Stock 객체
        count (int): 가져올 경쟁사의 수

    Returns:
        dict: {'경쟁사코드': 등락률, ...} 형태의 딕셔너리. 예: {'MSFT': 1.50, 'GOOGL': 1.30}
    """
    if not stock.industry:
        # 산업 정보가 없는 경우 비교가 불가능하므로 빈 딕셔너리 반환
        return {}

    # 1. 동일 산업에 속하는 주식들을 필터링
    # 2. 자기 자신은 경쟁사 목록에서 제외
    # 3. 유효한 등락률 데이터가 있는 종목만 선택
    # 4. 시가총액(market_cap)이 높은 순으로 정렬하여 주요 경쟁사를 우선적으로 선택
    # 5. 지정된 count 만큼만 가져오기
    peers = Stock.objects.filter(
        industry=stock.industry
    ).exclude(
        code=stock.code
    ).filter(
        change_percent__isnull=False
    ).order_by(
        '-market_cap'
    )[:count]

    # { 'MSFT': 1.5, 'GOOGL': 1.3 } 와 같은 형식으로 가공하여 반환
    peer_data = {p.code: p.change_percent for p in peers}
    
    return peer_data




def get_stock_technical_data(stock: Stock) -> dict:
    """
    주어진 주식의 기술적 분석 지표를 계산하여 딕셔너리로 반환합니다.
    - 52주 가격 범위
    - 거래량 비율
    - SMA, RSI, MACD, BBands, ADX
    """
    technicals = {}

    # --- 1. 기본 정보 계산 (DB 직접 접근) ---
    if stock.volume is not None:
        technicals['volume'] = stock.volume

    if all([stock.current_price, stock.fifty_two_week_high, stock.fifty_two_week_low]):
        price_range = stock.fifty_two_week_high - stock.fifty_two_week_low
        if price_range > 0:
            current_position = (stock.current_price - stock.fifty_two_week_low) / price_range * 100
            technicals['52_week_range_percent'] = round(float(current_position), 2)

    # --- 2. 복잡한 지표 계산을 위한 과거 데이터 준비 ---
    #    ADX(14)와 장기 이평선을 위해 넉넉하게 200일치 데이터를 가져옵니다.
    try:
        start_date = date.today() - timedelta(days=200)
        history_qs = StockPriceHistory.objects.filter(
            stock=stock,
            date__gte=start_date
        ).order_by('date')
        
        if history_qs.count() < 50: # 최소 데이터 수 확인
            print(f"Not enough history data for {stock.code} to calculate indicators.")
            return technicals

        # DataFrame으로 변환
        df = pd.DataFrame.from_records(
            history_qs.values('date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume')
        ).rename(columns={
            'open_price': 'Open', 'high_price': 'High', 'low_price': 'Low', 
            'close_price': 'Close', 'volume': 'Volume'
        })
        
        # 숫자 타입으로 변환 (매우 중요)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    except Exception as e:
        print(f"Error preparing data for technical analysis of {stock.code}: {e}")
        return technicals # 데이터 준비 실패 시, 지금까지 계산된 것만 반환

    # --- 3. 순수 Pandas로 기술적 지표 계산 ---
    
    # 3-1. 단순이동평균 (SMA)
    df['SMA_20'] = df['Close'].rolling(window=20).mean()

    # 3-2. 상대강도지수 (RSI)
    delta = df['Close'].diff(1)
    gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    loss = -delta.where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI_14'] = 100 - (100 / (1 + rs))

    # 3-3. MACD
    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    
    # 3-4. 볼린저 밴드 (BBands)
    df['BB_Middle'] = df['SMA_20'] # 20일 이동평균선이 중간선
    std_20 = df['Close'].rolling(window=20).std() # 20일 표준편차
    df['BB_Upper'] = df['BB_Middle'] + (std_20 * 2)
    df['BB_Lower'] = df['BB_Middle'] - (std_20 * 2)

    # 3-5. ADX (Average Directional Index) - 계산이 복잡함
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift(1)).abs()
    low_close = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    
    plus_dm = df['High'].diff().where((df['High'].diff() > df['Low'].diff()) & (df['High'].diff() > 0), 0)
    minus_dm = df['Low'].diff().where((df['Low'].diff() > df['High'].diff()) & (df['Low'].diff() > 0), 0)
    
    plus_di = 100 * (plus_dm.ewm(alpha=1/14, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/14, adjust=False).mean() / atr)
    
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    df['ADX_14'] = dx.ewm(alpha=1/14, adjust=False).mean()


    # --- 4. 계산된 지표의 '가장 마지막 값'을 결과 딕셔너리에 추가 ---
    latest = df.iloc[-1]
    
    # .get()을 사용하여 NaN 값이 추가되는 것을 방지
    technicals['sma_20'] = latest.get('SMA_20')
    technicals['rsi_14'] = latest.get('RSI_14')
    technicals['macd'] = latest.get('MACD')
    technicals['macd_signal'] = latest.get('MACD_Signal')
    technicals['bb_upper'] = latest.get('BB_Upper')
    technicals['bb_lower'] = latest.get('BB_Lower')
    technicals['adx_14'] = latest.get('ADX_14')
    
    # --- 5. 거래량 비율 재계산 (DataFrame 사용) ---
    avg_volume = df['Volume'].rolling(window=30).mean().iloc[-1]
    if stock.volume and pd.notna(avg_volume) and avg_volume > 0:
        technicals['volume_ratio'] = round(stock.volume / avg_volume, 2)

    return technicals


def get_latest_annual_financials(stock: Stock, count: int = 1) -> str:
    """
    주어진 주식의 가장 최근 연간 재무 데이터를 요약하여 문자열로 반환합니다.
    """
    # 가장 최근 데이터가 있는 날짜를 찾음
    latest_date_info = stock.financials.filter(period_type='A').order_by('-date').values('date').first()
    if not latest_date_info:
        return "최신 연간 재무 데이터 없음"
        
    latest_date = latest_date_info['date']

    # 해당 날짜의 모든 재무 데이터를 가져옴
    statements = stock.financials.filter(date=latest_date, period_type='A').select_related('item')

    if not statements.exists():
        return "최신 연간 재무 데이터 없음"

    summary_lines = [f"최근 결산 재무 요약 ({latest_date}):"]
    for stmt in statements:
        # 10억 단위(Billion) 또는 100만 단위(Million)로 보기 좋게 포맷
        value = stmt.value
        if abs(value) >= 1_000_000_000:
            formatted_value = f"{value / 1_000_000_000:.2f}B"
        elif abs(value) >= 1_000_000:
            formatted_value = f"{value / 1_000_000:.2f}M"
        else:
            formatted_value = f"{value:,}"

        summary_lines.append(f"  - {stmt.item.korean_label}: {formatted_value}")
    
    return "\n".join(summary_lines)

def create_indices_comparison_chart(period='1mo', filename='indices_chart.png'):
    """주요 지수들의 등락률 추이를 비교하는 라인 차트를 생성합니다."""
    tickers = {'S&P 500': '^GSPC', 'Nasdaq': '^IXIC', 'KOSPI': '^KS11'}
    plt.style.use('seaborn-v0_8-whitegrid') # 깔끔한 스타일 적용
    fig, ax = plt.subplots(figsize=(10, 5)) # 차트 크기 지정

    for name, ticker in tickers.items():
        stock = yf.Ticker(ticker)
        data = stock.history(period=period)['Close']
        # 등락률을 계산하기 위해 첫 날 가격으로 정규화 (모든 차트가 0에서 시작)
        normalized_data = (data / data.iloc[0] - 1) * 100
        ax.plot(normalized_data.index, normalized_data, label=name)

    ax.set_title('주요 지수 등락률 비교 (최근 1개월)')
    ax.set_ylabel('등락률 (%)')
    ax.legend() # 범례 표시
    fig.tight_layout() # 레이아웃 최적화

    save_path = os.path.join(settings.BASE_DIR, 'media', 'charts', filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    fig.savefig(save_path)
    plt.close(fig) # 메모리 해제
    return save_path


def create_sector_performance_heatmap(filename='sector_heatmap.png'):
    """S&P 500 섹터별 평균 등락률을 바 차트(히트맵)로 생성합니다."""
    sp500_stocks = Stock.objects.filter(is_sp500=True).exclude(sector__isnull=True, change_percent__isnull=True)
    
    # Django ORM으로 섹터별 평균 등락률 계산
    sector_performance = sp500_stocks.values('sector').annotate(avg_change=Avg('change_percent')).order_by('avg_change')
    
    if not sector_performance:
        return None

    sectors = [item['sector'] for item in sector_performance]
    avg_changes = [item['avg_change'] for item in sector_performance]
    colors = ['red' if x < 0 else 'green' for x in avg_changes]

    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.barh(sectors, avg_changes, color=colors) # 가로 바 차트
    ax.set_title('S&P 500 섹터별 등락률 현황')
    ax.set_xlabel('평균 등락률 (%)')
    fig.tight_layout()

    save_path = os.path.join(settings.BASE_DIR, 'media', 'charts', filename)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    fig.savefig(save_path)
    plt.close(fig)
    return save_path



def get_stock_news(ticker_symbol: str, count: int = 3) -> list:
    """
    yfinance를 사용해 특정 티커(주식 또는 지수)의 최신 뉴스를 가져와
    안전하게 가공하여 딕셔너리 리스트로 반환합니다.

    :param ticker_symbol: 주식 또는 지수 티커 (예: 'AAPL', '^GSPC')
    :param count: 가져올 최대 뉴스 개수
    :return: [{'title': ..., 'url': ..., 'thumbnail': ..., 'description': ...}, ...] 형태의 리스트
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        news_list = ticker.news
        
        if not news_list:
            return []

        processed_news = []
        
        for item in news_list:
            content = item.get('content')
            # .get()을 연쇄적으로 사용하여 KeyError나 TypeError를 방지합니다.
            
            # 1. 제목과 URL 추출 (필수 항목)
            title = content.get('title')
            url = content.get('canonicalUrl') # 'url'이 아닌 'link' 키를 사용하는 경우가 많음

            # 제목이나 URL이 없는 뉴스는 건너뜁니다.
            if not title or not url:
                continue

            # 2. 썸네일 URL 추출 (선택 항목)
            thumbnail_data = content.get('thumbnail', {})
            thumbnail_url = None
            if thumbnail_data and 'resolutions' in thumbnail_data and thumbnail_data['resolutions']:
                # 여러 해상도 중 마지막(보통 가장 높은 해상도)의 URL을 가져옵니다.
                thumbnail_url = thumbnail_data['resolutions'][-1].get('url')
                
            # 3. 뉴스 요약(description) 추출 (선택 항목)
            #    뉴스 제공사에 따라 'summary', 'description' 등 다른 키를 사용할 수 있음
            description = content.get('summary', content.get('description', '요약 없음'))

            processed_news.append({
                'title': title,
                'description': description,
            })
        
        return processed_news
        
    except Exception as e:
        print(f"Error getting yfinance news for {ticker_symbol}: {e}")
        # 실패 시 빈 리스트를 반환하여, 이 함수를 호출하는 다른 로직이 중단되지 않도록 함
        return []


# --- ⚡️ 재사용을 위한 헬퍼 함수 추가 ⚡️ ---
def convert_decimals_in_list(data_list):
    """리스트 안의 딕셔너리들을 순회하며 Decimal을 float으로 변환하는 함수"""
    if not isinstance(data_list, list):
        return data_list # 리스트가 아니면 그대로 반환
        
    for item in data_list:
        if isinstance(item, dict):
            for key, value in item.items():
                if isinstance(value, Decimal):
                    item[key] = float(value)
    return data_list

def calculate_ema(data, period=20, colume='Close'):
   ema = data[colume].ewm(span=period, adjust=False).mean()
   data[f'EMA_{period}'] = ema
   return data

def calculate_sma(data, period=20, colume='Close'):
   return data[colume].rolling(window=period).mean()

def calculate_rsi(data, period=20, colume='Close'):
   delta = data[colume].diff()
   gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
   loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
   rs = gain / loss
   rsi = 100 - (100 / (1 + rs))
   return rsi

    
def get_fear_and_greed_index():
    """
    fear-and-greed 라이브러리를 사용해 공포 탐욕 지수를 가져옵니다.
    """
    try:
        # 라이브러리 호출
        fng_index = fear_and_greed.get()
        
        # 필요한 정보만 추출하여 딕셔너리로 반환
        return {
            'value': fng_index.value,
            'description': fng_index.description,
            'last_update': fng_index.last_update.isoformat(), # datetime 객체를 ISO 형식 문자열로 변환
        }
    except Exception as e:
        print(f"Error fetching Fear & Greed Index: {e}")
        return None


def get_market_news():
    try:
        tickers = {'SNP500': '^GSPC', 'Nasdaq': '^IXIC', "DOW": '^DJI', 'KOSPI': '^KS11'}
        return_data  = []
        for name, ticker in tickers.items():
            news_data = get_yfinance_stock_news(ticker)
            return_data.append(news_data)
        return return_data

    except Exception as e:
        print(f"Error fetching Market News: {e}")
        return None

# --- yfinance를 이용한 해외 주식 정보 조회 ---
def get_yfinance_stock_info(ticker_symbol):
    """yfinance를 사용해 주식 정보를 가져옵니다."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        
        # 앱에 필요한 정보만 선택적으로 가공
        # yfinance가 주는 정보가 매우 많으므로 필요한 것만 골라야 합니다.
        data = {
            'name': info.get('shortName', ticker_symbol),
            'current_price': info.get('currentPrice'),
            'regularMarketChangePercent' : info.get('regularMarketChangePercent'),
            'market': info.get('exchange'),
            'currency': info.get('currency'),
            'day_high': info.get('dayHigh'),
            'day_low': info.get('dayLow'),
            'change': info.get('regularMarketChange'),
            'change_percent': info.get('regularMarketChangePercent'),
            # --- 주요 통계 지표 추가 ---
            'trailing_eps':info.get('trailingEps'),
            'market_cap': info.get('marketCap'),
            'volume': info.get('regularMarketVolume'),
            'trailing_pe': info.get('trailingPE'),
            'dividend_yield': info.get('dividendYield'),
            'week_52_high': info.get('fiftyTwoWeekHigh'),
            'week_52_low': info.get('fiftyTwoWeekLow'),

            # --- 기업 개요(Profile) 정보 ---
            'long_business_summary': info.get('longBusinessSummary'),
            'website': info.get('website'),
            'sector': info.get('sector'),
            'industry': info.get('industry'),
            'full_time_employees': info.get('fullTimeEmployees'),
            'city': info.get('city'),
            'state': info.get('state'),
            'country': info.get('country'),

        }
        return data
    except Exception as e:
        print(f"Error getting yfinance data for {ticker_symbol}: {e}")
        return None

def get_yfinance_stock_news(ticker_symbol):
    """yfinance를 사용해 관련 뉴스를 가져옵니다."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        news_list = ticker.news

        # 가공된 뉴스 리스트를 담을 빈 리스트 생성
        processed_news = []
        for item in news_list: 
            # 'title'과 'url' 필드가 있는지 확인하고, 있을 경우에만 추가
            # --- ⚡️ .get()을 연쇄적으로 사용하여 안전하게 데이터 추출 ---
            content = item.get('content', {}) # 'content'가 없으면 빈 딕셔너리 {} 반환
            thumbnail = content.get('thumbnail', {}) if content else {} # content가 None이 아닐때만 .get() 시도
            resolutions = thumbnail.get('resolutions', []) if thumbnail else [] # thumbnail이 None이 아닐때만 .get() 시도
            canonicalUrl = content.get('canonicalUrl', {}) if content else {}
            thumbnail_url = None

            if resolutions: # resolutions 리스트가 비어있지 않다면
                # 가장 마지막 해상도의 URL을 가져오되, 그 안에서도 .get()으로 안전하게 접근
                thumbnail_url = resolutions[0].get('url')

            # title이나 url이 없는 뉴스도 있을 수 있으므로 .get()으로 안전하게 처리
            title = content.get('title')
            description = content.get('summary')
            url = canonicalUrl.get('url')
            pub_date = content.get('pubDate')

            # 필수 정보인 title과 url이 있는 경우에만 리스트에 추가
            if title and url:
                processed_news.append({
                    'title': title,
                    'description': description,
                    'url': url,
                    'thumbnail': thumbnail_url,
                    'pub_date': pub_date,
                })

        return processed_news
    except Exception as e:
        print(f"Error getting yfinance news for {ticker_symbol}: {e}")
        return []


def get_stock_history(ticker_symbol, period="1y"):
    """
    yfinance 히스토리 데이터에 이동평균선을 계산하여 추가합니다.
    """
    try:
        calculation_period = "1y"
        fetch_period = period
        print(period)

        # 기간을 일수로 변환하여 비교 (대략적인 계산)
        period_days = {'1mo': 20, '3mo': 61, '6mo': 123, '1y': 250, '5y': 1204}
        if period_days.get(period, 0) < 250:
            # fetch_period = calculation_period
            interval = "1m"

        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period=fetch_period)

        if hist.empty:
            return []
        
        # DataFrame의 인덱스(날짜)를 리셋하여 컬럼으로 만듭니다.
        hist = hist.reset_index()

        # 날짜를 'YYYY-MM-DD' 형식의 문자열로 변환합니다.
        hist['Date'] = hist['Date'].dt.strftime('%Y-%m-%d')
        
        # --- ⚡️ 기술적 지표 계산 ---
        # 20일, 60일, 120일 이동평균선을 계산하여 새로운 컬럼으로 추가
        hist = calculate_ema(hist, 20)
        hist = calculate_ema(hist, 60)
        hist = calculate_ema(hist, 120)

        # 4. ⚡️ 사용자가 보고 싶어하는 기간만큼 데이터의 뒷부분을 잘라냅니다.
        if period in period_days:
            final_hist = hist.tail(period_days[period]) 
        else:
            final_hist = hist

        # 필요한 컬럼만 선택하여 반환
        required_columns = ['Date', 'Close', 'EMA_20', 'EMA_60', 'EMA_120']
        
        return final_hist[required_columns].to_dict('records')
    except Exception as e:
        print(f"Error getting stock history with TA for {ticker_symbol}: {e}")
        return []
    

# --- 한국투자증권 API를 이용한 국내 주식 정보 조회 (구조만 잡아놓기) ---
# KIS API는 토큰 발급 등 과정이 복잡하므로, 우선 함수 구조만 만듭니다.

# 실제 settings.py에 아래와 같이 추가해야 합니다.
# KIS_APP_KEY = '실제_APP_KEY'
# KIS_APP_SECRET = '실제_APP_SECRET'
# KIS_BASE_URL = 'https://openapi.koreainvestment.com:9443'

def get_kis_access_token():
    """한국투자증권 API 접근 토큰 발급 (실제 구현 필요)"""
    # 이 부분은 KIS API 문서를 보고 실제 구현해야 합니다.
    # 지금은 임시로 None을 반환합니다.
    return None

def get_korean_stock_price(stock_code):
    """한국투자증권 API로 국내 주식 현재가 조회 (실제 구현 필요)"""
    # token = get_kis_access_token()
    # if not token:
    #     return None
    #
    # headers = {"Authorization": f"Bearer {token}", ...}
    # params = {"FID_INPUT_ISCD": stock_code, ...}
    # res = requests.get(f"{settings.KIS_BASE_URL}/.../inquire-price", headers=headers, params=params)
    #
    # if res.status_code == 200:
    #     data = res.json()
    #     return {'current_price': data['output']['stck_prpr'], ...}
    
    # 지금은 테스트를 위해 가짜 데이터를 반환합니다.
    print(f"Fetching fake Korean stock data for {stock_code}")
    return {
        'name': '삼성전자(가짜)',
        'current_price': '70000',
        'market': 'KOSPI',
    }


def get_financial_statements(ticker_symbol):
    """
    손익계산서, 재무상태표, 현금흐름표를 모두 합쳐서 효율적으로 처리합니다.
    """
    items_to_fetch = FinancialItem.objects.filter(is_active=True).values('yfinance_name', 'standard_key')
    if not items_to_fetch:
        return {'annual': [], 'quarterly': []}
    
    # DB에서 가져온 정보를 빠르게 조회할 수 있도록 딕셔너리로 변환
    # {'Total Revenue': 'total_revenue', 'Net Income': 'net_income', ...}
    item_mapping = {item['yfinance_name']: item['standard_key'] for item in items_to_fetch}

    try:
        ticker = yf.Ticker(ticker_symbol)

        # 1. 필요한 모든 데이터 소스를 미리 정의합니다.
        data_sources = {
            'annual': [ticker.financials, ticker.balance_sheet, ticker.cashflow],
            'quarterly': [ticker.quarterly_financials, ticker.quarterly_balance_sheet, ticker.quarterly_cashflow]
        }
        
        processed_data = {'annual': [], 'quarterly': []}

        for period_type, df_list in data_sources.items():
            
            # 2. 비어있지 않은 데이터프레임만 모아서 하나로 합칩니다. (매우 효율적)
            valid_dfs = [df for df in df_list if not df.empty]
            if not valid_dfs:
                continue
            
            combined_df = pd.concat(valid_dfs)

            # 3. 합쳐진 데이터프레임에 대해 데이터 클리닝을 한 번만 수행합니다.
            combined_df.replace([np.inf, -np.inf], np.nan, inplace=True)
            df_cleaned = combined_df.where(pd.notnull(combined_df), None)

            # 4. 이제 기존 로직을 거의 그대로 사용합니다.
            for date_col in df_cleaned.columns:
                period_data = {'date': date_col.strftime('%Y-%m-%d')}

                # item_mapping을 순회하며 필요한 값을 찾습니다.
                for yfinance_key, frontend_key in item_mapping.items():
                    value = None
                    if yfinance_key in df_cleaned.index:
                        raw_value = df_cleaned.loc[yfinance_key, date_col]
                        value = raw_value.item() if pd.notna(raw_value) else None
                    
                    # standard_key가 있는 항목만 JSON에 포함
                    if frontend_key:
                        period_data[frontend_key] = value

                processed_data[period_type].append(period_data)
        
        return processed_data
    except Exception as e:
        print(f"Error getting financial statements for {ticker_symbol}: {e}")
        return None
    


def get_market_indexes():
    """
    주요 시장 지수 정보를 yfinance로 가져옵니다.
    """
    # 1. 조회할 지수 티커 목록 정의
    # ^GSPC: S&P 500, ^IXIC: 나스닥, ^DJI: 다우 존스, ^KS11: 코스피
    index_tickers = {
        'S&P 500': '^GSPC',
        'Nasdaq': '^IXIC',
        'Dow Jones': '^DJI',
        'KOSPI': '^KS11',
    }
    
    index_data_list = []

    for name, ticker_code in index_tickers.items():
        try:
            ticker = yf.Ticker(ticker_code)
            # '1d' 기간의 데이터를 가져와 가장 최근 정보를 사용합니다.
            hist = ticker.history(period='1mo') # 한 달치 데이터

            if hist.empty or len(hist) < 2:
                continue

            previous_close = hist['Close'].iloc[-2]
            current_price = hist['Close'].iloc[-1]
            
            change = current_price - previous_close
            change_percent = (change / previous_close) * 100

            # 2. 히스토리 종가 리스트를 추출합니다.
            #    차트를 그리는 데는 숫자 리스트만 있으면 됩니다.
            history_points = hist['Close'].tolist()

            index_data_list.append({
                'name': name,
                'code': ticker_code,
                'price': current_price,
                'change': change,
                'change_percent': change_percent,
                # 3. 응답에 히스토리 데이터 추가
                'history': history_points,
            })

        except Exception as e:
            print(f"Error fetching index {ticker_code}: {e}")
            continue
            
    return index_data_list


def get_exchange_rates():
    """
    주요 환율 정보를 yfinance로 가져옵니다.
    """
    # 1. 조회할 환율 페어 티커 목록 정의
    # KRW=X: USD/KRW, JPY=X: USD/JPY, EURUSD=X: EUR/USD
    rate_tickers = {
        'USD/KRW': 'KRW=X',
        'USD/JPY': 'JPY=X',
        'EUR/USD': 'EURUSD=X',
        'CNY=X': 'CNY=X' # USD/CNY
    }
    
    rate_data_list = []

    for name, ticker_code in rate_tickers.items():
        try:
            ticker = yf.Ticker(ticker_code)
            # 환율은 history보다 info에서 가져오는 것이 더 안정적일 수 있습니다.
            info = ticker.info
            
            current_price = info.get('bid') or info.get('previousClose')
            previous_close = info.get('previousClose')
            
            if not current_price or not previous_close:
                continue

            change = current_price - previous_close
            change_percent = (change / previous_close) * 100

            rate_data_list.append({
                'name': name,
                'code': ticker_code,
                'price': current_price,
                'change': change,
                'change_percent': change_percent,
            })
        except Exception as e:
            print(f"Error fetching exchange rate {ticker_code}: {e}")
            continue
            
    return rate_data_list



def get_commodity_prices():
    """
    주요 원자재 선물 가격 정보를 yfinance로 가져옵니다.
    """
    commodity_tickers = {
        'Crude Oil': 'CL=F',   # WTI 원유
        'Gold': 'GC=F',        # 금
        'Silver': 'SI=F',      # 은
        'Copper': 'HG=F',      # 구리
    }
    
    commodity_data_list = []

    for name, ticker_code in commodity_tickers.items():
        try:
            ticker = yf.Ticker(ticker_code)
            info = ticker.info
            
            current_price = info.get('regularMarketPrice') or info.get('previousClose')
            previous_close = info.get('previousClose')
            
            if not current_price or not previous_close:
                continue

            change = current_price - previous_close
            change_percent = (change / previous_close) * 100

            commodity_data_list.append({
                'name': name,
                'price': current_price,
                'change': change,
                'change_percent': change_percent,
            })
        except Exception as e:
            print(f"Error fetching commodity {ticker_code}: {e}")
            continue
            
    return commodity_data_list

def format_data_for_llm_human_readable(data_list):
    """데이터를 사람이 읽기 쉬운 텍스트 형식으로 변환합니다."""
    
    # 소유권 코드('D', 'I')를 설명하는 텍스트로 변환하기 위한 딕셔너리
    ownership_map = {
        'D': '직접 소유(Direct)',
        'I': '간접 소유(Indirect)'
    }
    
    prompt_parts = []
    for item in data_list:
        # 숫자에 콤마를 추가하여 가독성을 높임
        shares = f"{item['Shares']:,}"
        value = f"${item['Value']:,}"
        
        # 소유권 텍스트를 가져옴 (없는 경우 '알 수 없음' 처리)
        ownership_text = ownership_map.get(item['Ownership'], '알 수 없음')

        # 각 항목을 서술형으로 구성
        text_block = f"""
            --- 거래 내역 ---
            - 내부자: {item['Insider']}
            - 직위: {item['Position']}
            - 거래일: {item['Start Date']}
            - 상세 내용: {item['Text']}
            - 주식 수: {shares} 주
            - 총 거래액: {value}
            - 소유 형태: {ownership_text}
        """
        prompt_parts.append(text_block.strip())
        
    return "\n\n".join(prompt_parts)

def get_insider_transactions(ticker_symbol):
    """
    yfinance를 사용해 내부자 거래 정보를 가져오고 데이터를 정제합니다.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        transactions_df = ticker.insider_transactions
        
        if transactions_df.empty:
            return []

        # --- ⚡️ 여기가 핵심 해결책 ⚡️ ---
        # 1. NaN, Inf, -Inf 값을 numpy의 NaN으로 통일합니다.
        transactions_df = transactions_df[['Shares', 'Value', 'Text', 'Insider', 'Position', 'Transaction', 'Start Date', 'Ownership']]
        transactions_df.replace([np.inf, -np.inf], np.nan, inplace=True)
        # 2. 모든 NaN 값을 파이썬의 None으로 바꿉니다.
        #    이렇게 해야 JSON으로 변환 시 null이 됩니다.
        cleaned_df = transactions_df.where(pd.notnull(transactions_df), None)

        # 날짜 컬럼 포맷팅
        # pd.to_datetime은 NaT (Not a Time) 값을 생성할 수 있으므로, 에러 핸들링 추가
        cleaned_df['Start Date'] = pd.to_datetime(cleaned_df['Start Date'], errors='coerce').dt.strftime('%Y-%m-%d')
        
        required_columns = ['Shares', 'Value', 'Text', 'Insider', 'Position', 'Transaction', 'Start Date', 'Ownership']
        existing_columns = [col for col in required_columns if col in cleaned_df.columns]
        
        # 정제된 cleaned_df를 사용합니다.
        final_df = cleaned_df[existing_columns]
        final_df.fillna(0, inplace=True)
        
        return final_df.to_dict('records')
    except Exception as e:
        print(f"Error fetching insider transactions for {ticker_symbol}: {e}")
        return []
    

def aggregate_dashboard_data(market_indexes, exchange_rates, commodity_prices, fear_and_greed_index, market_news):
    """
    대시보드에 필요한 모든 데이터를 수집하고 가공하여 하나의 딕셔너리로 반환합니다.
    (외부 API 데이터는 인자로 받아서 처리)
    """
    print("Dashboard data aggregation started...")
    from .serializers import StockSerializer

    # --- 기본 쿼리셋 (기존 BaseSP500View.get_queryset) ---
    sp500_stocks = Stock.objects.filter(is_sp500=True, current_price__gt=0, volume__gt=0)

    # --- 시장 등락 현황 (기존 MarketBreadthAPIView) ---
    positive_stocks_count = sp500_stocks.filter(change_percent__gt=0).count()
    negative_stocks_count = sp500_stocks.filter(change_percent__lt=0).count()
    total_count = sp500_stocks.count()
    unchanged_stocks_count = total_count - positive_stocks_count - negative_stocks_count

    # --- 시장 주도주 (기존 MarketMoversAPIView) ---
    top_volume_stocks = sp500_stocks.order_by('-volume')[:5]
    top_gainers_stocks = sp500_stocks.order_by('-change_percent')[:5]
    top_losers_stocks = sp500_stocks.order_by('change_percent')[:5]
    
    # --- 섹터별 히트맵 (기존 StockHeatmapAPIView) ---
    window = Window(
        expression=RowNumber(),
        partition_by=[F('sector')],
        order_by=F('market_cap').desc()
    )
    sp500_heatmap_stocks = Stock.objects.filter(
        is_sp500=True, current_price__gt=0, market_cap__isnull=False
    ).annotate(row_num=window)
    
    heatmap_data_queryset = sp500_heatmap_stocks.values(
        'code', 'short_name', 'sector', 'industry', 'market_cap', 'change_percent', 'market_change', 'volume', 'current_price'
    )

    # --- ⚡️ 여기가 핵심 해결책 ⚡️ ---
    # QuerySet을 순회하면서 Decimal 타입을 float으로 변환
    heatmap_data = []
    for item in heatmap_data_queryset:
        # market_cap, change_percent 등 DecimalField일 가능성이 있는 필드들을 변환
        item['market_cap'] = float(item['market_cap']) if item['market_cap'] is not None else None
        item['change_percent'] = float(item['change_percent']) if item['change_percent'] is not None else None
        item['market_change'] = float(item['market_change']) if item['market_change'] is not None else None
        item['current_price'] = float(item['current_price']) if item['current_price'] is not None else None
        heatmap_data.append(item)
    
    # --- 모든 데이터를 하나의 딕셔너리로 조합 ---
    dashboard_data = {
        # 1. 시장 주요 지표 (인자로 받은 데이터를 사용)
        'market_summary': {
            'market_indexes': market_indexes,
            'exchange_rates': exchange_rates,
            'commodity_prices': commodity_prices,
            'fear_and_greed_index': fear_and_greed_index,
            'market_news': market_news,
        },
        # 2. 시장 등락 현황
        'market_breadth': {
            'positive_stocks_count': positive_stocks_count,
            'negative_stocks_count': negative_stocks_count,
            'unchanged_stocks_count': unchanged_stocks_count,
        },
        # 3. 시장 주도주
        'market_movers': {
            'top_volume': StockSerializer(top_volume_stocks, many=True).data,
            'top_gainers': StockSerializer(top_gainers_stocks, many=True).data,
            'top_losers': StockSerializer(top_losers_stocks, many=True).data,
        },
        # 4. 히트맵 데이터
        'heatmap': list(heatmap_data)

        # 'news_data': list(news_data)
    }
    
    print("Dashboard data aggregation finished.")
    return dashboard_data

def generate_ai_report(stock_code, additional_options=[]):
    """
    종목 정보를 수집하고, Google Gemini를 호출하여 분석 리포트를 생성합니다.
    """
    # --- ⚡️ 추가 분석 항목 프롬프트 생성 ---
    additional_prompt_sections = []
    
    if 'technical_analysis' in additional_options:
        # TODO: 기술적 지표 데이터(RSI, MACD 등)를 가져오는 로직 추가
        additional_prompt_sections.append("### 5. 기술적 분석\n(RSI, 이동평균선 등 현재 차트 상황을 분석해주세요.)")
        
    if 'insider_transactions' in additional_options:
        # TODO: 내부자 거래 데이터를 가져오는 로직 추가
        insider_data = get_insider_transactions(stock_code)
        insider_text = format_data_for_llm_human_readable(insider_data)
        additional_prompt_sections.append(f"### 6. 최근 내부자 거래 동향\n{insider_text}\n(위 내부자 거래가 의미하는 바를 분석해주세요.)")


    # DB에서 해당 키들의 한글 라벨을 가져옴
    items_from_db = FinancialItem.objects.all()
    key_label_map = {item.standard_key: item.korean_label for item in items_from_db}

    stock = yf.Ticker(stock_code)
    info_data = stock.info
    news_data = stock.news
    financials_data = get_financial_statements(stock_code)

    news = [news.get('content') for news in news_data]

    news_text = ""
    news_lines = []

    for item in news:
        line = f"{item.get('title')} : {item.get('summary')}"
        news_lines.append(line)
        news_text = "\n".join(news_lines)

    finnews_text = ""
    finnews_lines = []

    fnews = News()
    all_news = fnews.get_news()
    finviz_general_news = all_news.get('news')
    for row in finviz_general_news.iterrows():
        line = f"{row[1].get('Title')}"
        finnews_lines.append(line)
        finnews_text = "\n".join(news_lines)

    basic_data = {
        'name': info_data.get('shortName', stock_code),
        'current_price': info_data.get('currentPrice'),
        'regularMarketChangePercent' : info_data.get('regularMarketChangePercent'),
        'market': info_data.get('exchange'),
        'currency': info_data.get('currency'),
        'day_high': info_data.get('dayHigh'),
        'day_low': info_data.get('dayLow'),
        'change': info_data.get('regularMarketChange'),
        'change_percent': info_data.get('regularMarketChangePercent'),
        # --- 주요 통계 지표 추가 ---
        'market_cap': info_data.get('marketCap'),
        'volume': info_data.get('regularMarketVolume'),
        'trailing_pe': info_data.get('trailingPE'),
        'dividend_yield': info_data.get('dividendYield'),
        'week_52_high': info_data.get('fiftyTwoWeekHigh'),
        'week_52_low': info_data.get('fiftyTwoWeekLow'),

        # --- 기업 개요(Profile) 정보 ---
        'long_business_summary': info_data.get('longBusinessSummary'),
        'sector': info_data.get('sector'),
        'industry': info_data.get('industry'),
        'full_time_employees': info_data.get('fullTimeEmployees'),
    }
    
    basic_info_text = ""
    infos_lines = []

    for key in basic_data.keys():
        line = f'{key} : {basic_data.get(key)}'
        infos_lines.append(line)
        basic_info_text = "\n".join(infos_lines)
        
    # 2. --- 재무 지표 텍스트 동적 생성 ---
    financials_text = ""
    # DB에 정의된 한글 라벨을 가져오면 더 좋음 (FinancialItem 모델 활용)
    # 지금은 간단하게 standard_key를 사용
    if financials_data and financials_data.get('annual'):
        # 가장 최근 연간 데이터만 사용
        latest_annual_data = financials_data['annual'][0]
        
        lines = []
        for key in key_label_map:
            label = key_label_map.get(key, key) # DB에 라벨이 없으면 그냥 키를 사용
            value = latest_annual_data.get(key)
            if value is not None:
                # 큰 숫자를 읽기 쉽게 포맷팅 (예: 100B, 12.5M)
                formatted_value = f"{value / 1_000_000_000:.2f}B" if abs(value) >= 1_000_000_000 else f"{value / 1_000_000:.2f}M"
                lines.append(f"- {label}: {formatted_value}")
        
        financials_text = "\n".join(lines)
    else:
        financials_text = "N/A"

    final_additional_prompt = "\n\n".join(additional_prompt_sections)


    # 2. 프롬프트 엔지니어링 (Gemini에 맞게 최적화)
    #    OpenAI와 동일한 프롬프트를 사용해도 잘 작동합니다.
    prompt = f"""
    당신은 월스트리트의 유능한 주식 분석가입니다. 다음 데이터를 바탕으로 '{stock_code}' 종목에 대한 투자 분석 리포트를 작성해주세요. Markdown 형식을 사용하여 제목과 목록을 명확하게 구분하고, 각 항목에 대해 긍정적인 면과 부정적인 면을 객관적으로 분석한 뒤, 최종적으로 종합 의견을 제시해주세요. 모든 내용은 한글로 작성해주세요. 분석가의 이름은 LLM모델 이름(예:gemini-2.5-flash)으로 해주세요.
    작성일은 작성하지 말아주세요.
    **[기본 정보]**
    - {basic_info_text}

    **[최신 뉴스 요약]**
    - 개별주 관련 뉴스 : {news_text}
    - 일반 뉴스 : {finnews_text}

    **[핵심 재무 지표]**
    - {financials_text}

    {final_additional_prompt}
    
    **[AI 분석 리포트]**

    ### 1. 기업 개요 및 비즈니스 모델 분석
    (여기에 분석 내용을 작성)

    ### 2. 재무 건전성 평가
    (매출과 순이익 추세를 바탕으로 긍정/부정 요인 분석)

    ### 3. 최근 뉴스 및 시장 동향 분석
    (최신 뉴스가 주가에 미칠 영향 분석)

    ### 4. 종합 투자 의견
    (위 분석을 종합하여, 투자 매력도에 대한 최종 의견 제시)
    """

    # 3. Gemini API 호출
    try:
        # API 키 설정
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        # 사용할 모델 선택 (gemini-pro가 텍스트 생성에 적합)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        # 생성된 텍스트 추출
        report_text = response.text
        
        return {'report': report_text}
    except Exception as e:
        print(f"Gemini API error: {e}")
        # Gemini API는 특정 콘텐츠(유해성 등)에 대해 응답을 차단하고 에러를 낼 수 있음
        # response.prompt_feedback 으로 차단 여부 확인 가능
        return {'report': '리포트를 생성하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'}
    


def create_market_chart_image(ticker='^GSPC', period='1mo', filename='market_chart.png'):
    """주요 지수 차트를 이미지 파일로 생성하고, 파일 경로를 반환합니다."""
    stock = yf.Ticker(ticker)
    data = stock.history(period='1mo')
    charts_dir = os.path.join(settings.BASE_DIR, 'media', 'charts')
    os.makedirs(charts_dir, exist_ok=True) # 폴더가 없으면 생성
    
    # ⚡️ 절대 경로로 저장
    save_path = os.path.join(charts_dir, 'market_chart.png')
    mpf.plot(data, type='candle', style='yahoo',
             title=f'{ticker} Chart ({period})',
             ylabel='Price ($)',
             savefig=save_path)
    return save_path


def send_daily_report_email(user, market_summary, watchlist_data, image_paths):
    """
    데이터를 바탕으로, 이미지가 인라인으로 삽입된 HTML 이메일을 생성하고 발송합니다.
    """
    # 이메일 형식 검증을 위한 정규표현식
    EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    # 1. 이메일 주소 형식 검증 (가드 클로즈)
    if not re.match(EMAIL_REGEX, user.email):
        print(f"Skipping email to '{user.email}' due to invalid format.")
        return

    # 차단할 테스트 도메인 목록
    TEST_DOMAINS = ['@example.com', '@example.net', '@test.com']
    
    normalized_email = user.email.lower()
    # 이메일이 TEST_DOMAINS 중 하나로 끝나는지 확인
    if any(normalized_email.endswith(domain) for domain in TEST_DOMAINS):
        print(f"Skipping email to {user.email} (test address).")
        return
        
    print(f"--- Preparing INLINE-IMAGE email for {user.email} ---")
    today_str = timezone.now().strftime('%Y년 %m월 %d일')
    image_cids = {}
    mime_images = []

    print(image_paths)
    # 각 이미지에 대한 cid 생성 및 MIMEImage 객체 생성
    for key, path in image_paths.items():
        cid = f'{key}_image'
        image_cids[f'{key}_cid'] = cid
        with open(path, 'rb') as f:
            mime_image = MIMEImage(f.read())
            mime_image.add_header('Content-ID', f'<{cid}>')
            mime_images.append(mime_image)

    context = {
        'username': user.username,
        'market_summary': market_summary,
        'watchlist_items': watchlist_data,
        **image_cids, # ⚡️ {'indices_chart_cid': '...', 'sector_heatmap_cid': '...'}
    }
    
    html_content = render_to_string('emails/daily_report.html', context)
    text_content = strip_tags(html_content)

    # 3. EmailMultiAlternatives 객체 생성
    email = EmailMultiAlternatives(
        subject=f"{today_str} 주식 시장 리포트",
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email]
    )
    email.attach_alternative(html_content, "text/html")

    # 모든 이미지 객체 첨부
    for img in mime_images:
        email.attach(img)

    # 5. 이메일 발송
    try:
        email.send(fail_silently=False)
        print(f"Email with inline image sent successfully to {user.email}.")
    except Exception as e:
        print(f"!!! CRITICAL ERROR: Failed to send email: {e}")
        raise


def generate_market_summary_llm():
    """
    오늘의 전체 시장 데이터를 수집하고, Gemini를 호출하여 종합 시황 분석을 생성합니다.
    """
    print("Generating daily market summary with LLM...")
    today_str = timezone.now().strftime('%Y년 %m월 %d일')

    # 1. 데이터 수집 (기존 서비스 함수들 재활용)
    market_indexes = get_market_indexes()
    exchange_rates = get_exchange_rates()
    commodity_prices = get_commodity_prices()
    fng_index = get_fear_and_greed_index()

    # --- 프롬프트에 제공할 데이터를 더 명확한 텍스트로 가공 ---
    index_data_text = "\n".join([f"  - {d['name']}: {d['price']:.2f} ({d['change_percent']:+.2f}%)" for d in market_indexes])
    index_data_text_for_evidence = index_data_text.replace('  - ', '').replace('\n', ' | ')

    # S&P 500 기준 시장 동향 데이터
    sp500_stocks = Stock.objects.filter(is_sp500=True, current_price__gt=0)
    top_gainers = sp500_stocks.order_by('-change_percent')[:3]
    top_losers = sp500_stocks.order_by('change_percent')[:3]

    top_gainers_text = ", ".join([f"{s.short_name} ({s.change_percent:+.2f}%)" for s in top_gainers])
    top_losers_text = ", ".join([f"{s.short_name} ({s.change_percent:+.2f}%)" for s in top_losers])

    sp500_news = get_stock_news('^GSPC') # S&P 500 관련 최신 뉴스 3개
    sp500_news_text = "\n".join([f"  - {news['title']}" for news in sp500_news]) if sp500_news else "  - 주요 시장 뉴스 없음"
    sp500_news_for_evidence = sp500_news_text.replace('  - ', '').replace('\n', ' | ')

    # 2. 프롬프트 엔지니어링
    prompt = f"""
    당신은 월스트리트의 데이터 분석가이자 금융 리포트 작성 전문가입니다. 당신의 임무는 제공된 원본 데이터를 바탕으로 두 개의 섹션, 즉 '분석 리포트'와 '분석 근거'를 포함한 완벽한 HTML 리포트를 작성하는 것입니다.

    **[작성 규칙]**
    1. 모든 내용은 한글로 작성합니다.
    2. 제목이나 첫 문장에 오늘 날짜인 '{today_str}'을 반드시 포함해주세요.
    3. 아래에 제공된 출력 형식을 반드시, 정확하게 따라야 합니다.
    4. '분석 리포트' 섹션은 독자가 이해하기 쉬운 서술형 문장으로 작성합니다.
    5. '분석 근거' 섹션은 리포트 작성에 사용된 핵심 데이터를 그대로, 명확하게 나열해야 합니다.
    6. 중요한 키워드나 수치는 `<strong>` 태그로 강조해주세요.
    7. 전체 응답은 유효한 HTML 조각이어야 합니다.
    8. 문단은 `<p>` 태그로 감싸주세요.
    9. 목록을 사용할 경우 `<ul>`과 `<li>` 태그를 사용해주세요.
    10. `<h3>` 태그는 사용하지 마세요. (템플릿에 이미 존재함)
    11. 친절하지만 전문적인 톤을 유지해주세요.

    ---

    **[응답 예시]**
    <p>오늘 시장은 <strong>S&P 500 지수</strong>가 <strong>{market_indexes[0]['change_percent']:+.2f}%</strong> 상승하며 전반적으로 긍정적인 분위기 속에서 마감했습니다.</p>
    <p>특히 다음과 같은 점들이 주목받았습니다:</p>
    <p><strong>{today_str}</strong> 시장은 S&P 500 지수가... (이하 생략)</p>
    <ul>
        <li><strong>NVIDIA:</strong> 새로운 AI 칩 발표로 인해 5.2% 급등하며 기술주 상승을 이끌었습니다.</li>
        <li><strong>유가:</strong> WTI 유가가 <strong>${commodity_prices[0]['price']:.2f}</strong>로 하락하며 인플레이션 우려를 다소 완화시켰습니다.</li>
    </ul>

    **[오늘의 원본 데이터 (기준: {today_str})]**
    *   **주요 지수:**
    {index_data_text_for_evidence}

    *   **주요 시장 뉴스:**
    {sp500_news_for_evidence}

    **[오늘의 주요 데이터]**
    
    *   **주요 지수:**
        - S&P 500: {market_indexes[0]['price']:.2f} ({market_indexes[0]['change_percent']:+.2f}%)
        - Nasdaq: {market_indexes[1]['price']:.2f} ({market_indexes[1]['change_percent']:+.2f}%)
    
    *   **투자 심리:**
        - 공포와 탐욕 지수: {fng_index['value']:.1f} ({fng_index['description']})
        
    *   **주요 경제 지표:**
        - USD/KRW 환율: {exchange_rates[0]['price']:.2f}
        - WTI 유가: ${commodity_prices[0]['price']:.2f}

    *   **시장 주도주 (S&P 500 기준):**
        - 주요 상승주: {', '.join([f"{s.short_name} ({s.change_percent:+.2f}%)" for s in top_gainers])}
        - 주요 하락주: {', '.join([f"{s.short_name} ({s.change_percent:+.2f}%)" for s in top_losers])}

    **[일일 시황 브리핑]**

    ### 1. 시장 요약
    (오늘 시장의 전반적인 흐름을 지수와 투자 심리를 바탕으로 간결하게 요약)

    ### 2. 주목할 만한 움직임
    (오늘 시장을 주도한 상승/하락 종목들의 특징과 그 배경을 간략하게 분석)

    ### 3. 주요 시사점 및 전망
    (환율, 유가 등 거시 지표를 고려하여 투자자들이 내일을 위해 생각해야 할 점을 제시)

    **[출력 형식]** 
    (아래 HTML 구조를 반드시 지켜서 응답을 생성해주세요.)

    <h3>분석 리포트</h3>
    <p><em>({today_str} 기준)</em></p>
    <p>(여기에 오늘 시장에 대한 종합적인 분석을 서술형으로 작성)</p>
    <p>(주요 지수, 투자 심리, 주도주 등을 엮어서 자연스러운 문장으로 분석)</p>
    
    <br>

    (간략하게 요약)
    <h3>분석 근거 (AI 학습 데이터)</h3>
    <p><em>이 AI 리포트는 아래 데이터를 기반으로 생성되었습니다.</em></p>
    <ul>
        <li><strong>주요 시장 뉴스:</strong> {sp500_news_for_evidence}</li>
        <li><strong>주요 지수:</strong> {index_data_text_for_evidence}</li>
        <li><strong>투자 심리:</strong> 공포와 탐욕 지수 <strong>{fng_index['value']:.1f} ({fng_index['description']})</strong></li>
        <li><strong>주요 상승주:</strong> {top_gainers_text}</li>
        <li><strong>주요 하락주:</strong> {top_losers_text}</li>
    </ul>

    ---

    **[최종 결과물 (HTML)]**
    (이제 위 규칙과 형식에 맞춰 실제 리포트를 작성해주세요.)
    """

    # 3. Gemini API 호출
    try:
        # API 키 설정
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        # 사용할 모델 선택 (gemini-pro가 텍스트 생성에 적합)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        # 생성된 텍스트 추출
        report_text = response.text

        return report_text

    except Exception as e:
        logger.error(f"Gemini API error during market summary generation: {e}", exc_info=True)
        return "오늘의 시황 분석을 생성하는 데 실패했습니다."



def generate_single_stock_analysis_llm(stock):
    """
    개별 주식의 데이터를 바탕으로 오늘의 객관적인 분석을 생성합니다.
    이 함수의 결과는 StockDailyAnalysis 모델에 저장됩니다.
    """
    print(f"Generating single analysis for {stock.code}...")
    
    # 데이터 수집 (뉴스, 주요 지표 등)
    news = get_stock_news(stock.code)
    news_text = "\n- ".join([f"{n['title']} ({n.get('description', '요약 없음')})" for n in news])

    prompt = f"""
    당신은 사실 기반의 데이터 분석가입니다. 다음 주식에 대한 오늘의 동향을 객관적으로 분석해주세요.

    - **종목:** {stock.short_name} ({stock.code})
    - **오늘의 변동률:** {stock.change_percent:+.2f}%
    - **관련 뉴스:**
    - {news_text if news_text else "최신 뉴스 없음"}

    ---
    **[분석 요약]**
    (위 정보를 바탕으로, 오늘 주가 움직임의 핵심 요인을 1~2 문단으로 간결하게 분석해주세요. 추측이나 사적인 의견("매수 추천" 등) 없이, 데이터에 기반한 사실만을 전달해주세요.)
    """
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini API error during single stock analysis for {stock.code}: {e}")
        return f"{stock.short_name}의 분석을 생성하는 중 오류가 발생했습니다."

def get_latest_technical_indicators(stock: Stock) -> dict:
    """
    특정 주식의 가장 최근 날짜의 기술적 지표를 딕셔너리로 반환합니다.
    """
    latest_indicator = TechnicalIndicator.objects.filter(
        history__stock=stock
    ).order_by('-history__date').first()
    
    if not latest_indicator:
        return {}
    
    # 모델의 필드들을 딕셔너리로 변환
    data = {
        'rsi_14': latest_indicator.rsi_14,
        'sma_20': latest_indicator.sma_20,
        'sma_60': latest_indicator.sma_60,
        'macd': latest_indicator.macd,
        'macd_signal': latest_indicator.macd_signal,
        'bb_lower': latest_indicator.bb_lower,
        'bb_middle': latest_indicator.bb_middle,
        'bb_upper': latest_indicator.bb_upper,
    }
    return data
    

def generate_single_stock_analysis_llm_v2(stock):
    """
    개별 주식에 대해 시장, 경쟁사, 기술적 데이터를 포함한
    심층적인 분석을 생성합니다.
    """
    print(f"Generating enhanced single analysis for {stock.code}...")

    # 1. 데이터 수집 (기존 + 추가)
    news = get_stock_news(stock.code)
    market_indexes = get_market_indexes()
    peers_data = get_peer_stock_data(stock) 
    technicals_data = get_stock_technical_data(stock)

    # ✨ 예측 결과를 DB에서 조회하는 로직으로 변경 ✨
    sac_signal_text = "오늘의 AI 예측 데이터 없음"
    try:
        # 가장 최신 예측(오늘 날짜 기준)을 가져옴
        latest_prediction = PredictionLog.objects.filter(
            stock=stock
        ).latest('prediction_date') # prediction_date가 가장 최신인 것을 가져옴

        # 가져온 예측이 오늘 예측인지 확인 (선택적이지만 좋은 습관)
        if latest_prediction.prediction_date == date.today():
             sac_signal_text = f"{latest_prediction.predicted_signal} (예측 비율: {latest_prediction.predicted_ratio:.4f})"
        else:
             sac_signal_text = f"과거 예측 데이터만 존재 ({latest_prediction.prediction_date}): {latest_prediction.predicted_signal}"

    except PredictionLog.DoesNotExist:
        logger.warning(f"No prediction log found for {stock.code}")
    except Exception as e:
        logger.error(f"Error fetching prediction log for {stock.code}: {e}")
        sac_signal_text = "예측 데이터 조회 중 오류 발생"


    # --- 프롬프트에 제공할 데이터를 더 명확한 텍스트로 가공 ---
    index_data_text = "\n".join([f"  - {d['name']}: {d['price']:.2f} ({d['change_percent']:+.2f}%)" for d in market_indexes])
    index_data_text_for_evidence = index_data_text.replace('  - ', '').replace('\n', ' | ')

    # 데이터 텍스트로 가공
    news_text = "\n- ".join([f"{n['title']}" for n in news])
    peer_context = ", ".join([f"{ticker}: {change:+.2f}%" for ticker, change in peers_data.items()]) if peers_data else "비교 데이터 없음"

    tech_context_list = []
    # 52주 가격 범위
    if technicals_data.get('52_week_range_percent'):
        tech_context_list.append(f"52주 가격 위치: {technicals_data['52_week_range_percent']:.1f}%")

    # 거래량 비율
    if technicals_data.get('volume_ratio'):
        ratio = technicals_data['volume_ratio']
        volume_signal = "평균 이상" if ratio > 1.1 else "평균 이하" if ratio < 0.9 else "평균 수준"
        tech_context_list.append(f"거래량: 평소 대비 {ratio:.1f}배 ({volume_signal})")

    # RSI
    rsi = technicals_data.get('rsi_14')
    if rsi:
        rsi_signal = "과매수" if rsi > 70 else "과매도" if rsi < 30 else "중립"
        tech_context_list.append(f"RSI(14): {rsi:.1f} ({rsi_signal})")

    # MACD
    macd = technicals_data.get('macd')
    signal = technicals_data.get('macd_signal')
    if macd is not None and signal is not None:
        macd_signal = "상승 신호" if macd > signal else "하락 신호"
        tech_context_list.append(f"MACD: {macd_signal}")

    # 이동평균선
    sma20 = technicals_data.get('sma_20')
    if stock.current_price and sma20:
        price = float(stock.current_price)
        trend_signal = "단기 상승 추세" if price > float(sma20) else "단기 하락 추세"
        tech_context_list.append(f"추세: {trend_signal} (20일선 기준)")

    # 볼린저 밴드
    bb_upper = technicals_data.get('bb_upper')
    bb_lower = technicals_data.get('bb_lower')
    if stock.current_price and bb_upper and bb_lower:
        price = float(stock.current_price)
        if price > float(bb_upper):
            bb_signal = "상단 돌파 (과열 가능성)"
        elif price < float(bb_lower):
            bb_signal = "하단 이탈 (반등 가능성)"
        else:
            bb_signal = "밴드 내 움직임"
        tech_context_list.append(f"볼린저 밴드: {bb_signal}")

    # ADX
    adx = technicals_data.get('adx_14')
    if adx:
        adx_signal = "강한 추세" if adx > 25 else "추세 없음 (횡보)"
        tech_context_list.append(f"추세 강도(ADX): {adx:.1f} ({adx_signal})")
    
    # 최종 기술적 분석 요약 텍스트
    tech_context = ", ".join(tech_context_list) if tech_context_list else "데이터 없음"

    financial_summary = get_latest_annual_financials(stock)

    # 2. 프롬프트 엔지니어링 (대폭 강화)
    prompt = f"""
    당신은 월스트리트의 전문 주식 분석가입니다. 오늘의 주가 움직임의 핵심 원인을 분석하는 것이 당신의 임무입니다.

    **[분석 대상 종목]**
    - 종목명: {stock.short_name} ({stock.code})
    - 오늘의 실제 주가 변동: **{stock.change_percent:+.2f}%**

    **[분석을 위한 컨텍스트 데이터]**
    1.  **시장 전반 상황:** {index_data_text_for_evidence}
    2.  **경쟁사 주가 동향:** {peer_context}
    3.  **오늘의 기술적 지표:** {tech_context}
    4.  **최근 관련 뉴스:**
        - {news_text if news_text else "최신 뉴스 없음"}
    5.  **최신 기업 펀더멘털:**
        {financial_summary}
    # ✨ 수정된 부분: 라벨과 설명 변경 ✨
    6.  **AI 모델의 다음 거래일 예측:** {sac_signal_text} (어제 종가 기준으로 오늘 장을 예측한 신호)
    ---
    **[분석 리포트 작성 가이드]**
    1.  리포트를 명확한 섹션으로 나누어 주세요: **"오늘의 주가 분석"**, **"주요 영향 요인"**, **"종합 전망"** 순서로 구성해주세요.
    2.  **"오늘의 주가 분석"** 섹션에서는 {stock.short_name}의 주가 움직임이 시장 전체 및 경쟁사와 어떻게 다른지 객관적으로 서술해주세요.
    3.  **"주요 영향 요인"** 섹션에서는 제공된 뉴스, 기술적 지표, 펀더멘털 데이터를 종합하여 주가 움직임의 핵심 원인을 논리적으로 추론해주세요.
        -   관련 뉴스가 있다면, **단순히 제목을 나열하지 말고, 내용을 간략히 요약하여 분석에 근거로 활용**해주세요. (예: "웰스파고가 AI 시장 확장을 근거로 NVIDIA를 긍정적으로 평가한 점이 투자 심리에 영향을 준 것으로 보입니다.")
        -   제공된 뉴스는 자연스러운 한국어로 번역하여 설명해주세요.
    4.  **"종합 전망"** 섹션에서는 분석된 내용을 바탕으로 **'긍정적 요인'**과 **'부정적 요인'**을 명확히 요약하고, 이를 바탕으로 **'상승 시나리오'**와 **'하락 시나리오'**를 각각 제시해주세요. 확률적인 표현("~할 가능성이 있습니다", "~할 경우 추가 상승 모멘텀을 얻을 수 있습니다")을 사용해주세요.
    5.  마지막으로, **"AI 모델 시그널"** 섹션을 별도로 만들어 AI 예측 결과와 추천 매매 행동을 명확하게 보여주세요.
    6.  추측이나 매매 추천("매수해야 합니다")은 절대 금물입니다. 데이터에 기반한 객관적인 분석만 제공해주세요.
    7.  중요한 키워드나 수치는 `<strong>` 태그로 강조해주세요.
    8.  전체 응답은 **순수한 HTML 조각(HTML fragment)**이어야 합니다. 문단은 `<p>` 태그, 목록은 `<ul>`과 `<li>`를 사용해주세요.
    9.  친절하지만 전문적인 톤을 유지해주세요. `<h3>` 태그는 사용하지 마세요.
    10. **[중요!] 최종 결과물은 `<p>` 태그로 바로 시작해야 하며, 절대로 응답 전체를 Markdown 코드 블록(```)으로 감싸지 마세요.**
    11. **AI 모델 예측 활용법:** 제공된 'AI 모델의 다음 거래일 예측'은 **어제 데이터를 기반으로 오늘의 주가 방향을 예측한 결과**입니다. 이 정보를 다음과 같이 활용하여 분석의 깊이를 더하세요.
        *   만약 AI 예측('매수')과 오늘의 실제 주가 움직임('상승')이 **일치**했다면, "AI 모델의 예측대로 시장이 긍정적으로 반응했습니다. 이는 [뉴스/기술적 지표] 등의 요인과 일맥상통합니다." 와 같이 분석의 근거로 활용하세요.
        *   만약 AI 예측('매도')과 오늘의 실제 주가 움직임('상승')이 **불일치**했다면, "AI 모델은 하락 리스크를 예측했으나, 시장은 [호재 뉴스/강력한 시장 전반의 매수세]와 같은 다른 요인에 더 크게 반응하며 상승 마감했습니다." 와 같이, 예측과 현실의 차이를 유발한 잠재적 원인을 분석하세요.
        *   **절대로 "모델의 예측이 틀렸다" 또는 "정확도에 대한 검토가 필요하다" 와 같은 평가적인 발언을 하지 마세요.** 당신의 임무는 모델을 평가하는 것이 아니라, 제공된 모든 데이터를 종합하여 오늘의 시장 상황을 설명하는 것입니다.

    **[분석 리포트]**
    """
    
    try:
        # API 키 설정
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        # 사용할 모델 선택 (gemini-pro가 텍스트 생성에 적합)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        # 생성된 텍스트 추출
        report_text = response.text

        return report_text
    except Exception as e:
        logger.error(f"Gemini API error during enhanced analysis for: {stock.code}: {e}", exc_info=True)
        return f"{stock.short_name}의 분석을 생성하는 중 오류가 발생했습니다."




def update_stock_history_daily():
    """
    DB에 저장된 마지막 날짜 이후의 시세 데이터만 가져와 업데이트합니다.
    """
    print("--- Performing Daily Stock Price History Update ---")
    
    all_stocks = Stock.objects.all()
    if not all_stocks.exists():
        print("No stocks in DB to update.")
        return "No stocks to update."

    stock_map = {stock.id: stock for stock in all_stocks}
    
    # 각 주식별 마지막 데이터 날짜를 한 번의 쿼리로 효율적으로 찾습니다.
    latest_dates_qs = StockPriceHistory.objects.values('stock_id').annotate(latest_date=Max('date'))
    latest_dates_map = {item['stock_id']: item['latest_date'] for item in latest_dates_qs}

    history_objects_to_create = []

    # 각 주식을 순회하며 업데이트가 필요한 데이터를 가져옵니다.
    for stock_id, stock_instance in stock_map.items():
        last_date = latest_dates_map.get(stock_id)
        start_date_str = None # yfinance에 전달할 시작 날짜 문자열

        if last_date:
            start_date = last_date - timedelta(days=2)

            if start_date > date.today():
                print(f"[{stock_instance.code}]: Already up-to-date.")
                continue
            
            start_date_str = start_date.strftime('%Y-%m-%d')
            print(f"Updating [{stock_instance.code}] from {start_date_str}...")
        else:
            # 데이터가 아예 없는 신규 종목이면, 최근 10년치 데이터를 가져옵니다. (초기 설정)
            # start_date = date.today() - timedelta(days=365*10)
            # start_date_str = start_date.strftime('%Y-%m-%d')
            # yfinance는 period='10y'가 더 안정적일 수 있음
            print(f"No history for [{stock_instance.code}]. Skipping daily update. Use populate_history command for initial data.")
            continue # 일일 업데이트에서는 신규 종목을 처리하지 않도록 변경 (더 안전)

        try:
            # 개별 종목에 대해 데이터를 다운로드합니다.
            hist_df = yf.download(stock_instance.code, start=start_date_str, progress=False, auto_adjust=True)

            if hist_df.empty:
                continue

            for index, row in hist_df.iterrows():
                # 데이터가 유효한지 확인
                if row['Open'].empty or row['Volume'].empty:
                    continue

                # --- ⚡️ 여기가 핵심 수정 부분 ---
                # Pandas Series/Numpy 타입을 Python 기본 타입으로 변환
                open_price = float(row.iloc[3])
                high_price = float(row.iloc[1])
                low_price = float(row.iloc[2])
                close_price = float(row.iloc[0])
                volume = int(row.iloc[4])
                # 'Adj Close'는 없을 수도 있으므로 .get()으로 안전하게 접근 후 변환
                adj_close_val = row.get('Adj Close')
                adj_close = float(adj_close_val) if adj_close_val is not None else close_price
                
                history_objects_to_create.append(
                    StockPriceHistory(
                        stock=stock_instance,
                        date=index.date(),
                        open_price=open_price,
                        high_price=high_price,
                        low_price=low_price,
                        close_price=close_price,
                        volume=volume,
                        adj_close=adj_close
                    )
                )
        except Exception as e:
            print(f"!!! ERROR updating [{stock_instance.code}]: {e}")
    
    if not history_objects_to_create:
        print("--- All stocks are already up-to-date. No new records to save. ---")
        return "All stocks up-to-date."

    print(f"Saving {len(history_objects_to_create)} new records...")
    StockPriceHistory.objects.bulk_create(history_objects_to_create, ignore_conflicts=True, batch_size=1000)
    
    final_message = f"Saved {len(history_objects_to_create)} new records."
    print(f"--- Daily Update Complete. {final_message} ---")
    return final_message


def calculate_indicators_for_all_stocks(stock_id):
    """
    모든 주식에 대해 최신 시세 데이터를 기반으로 기술적 지표를 계산하고 저장합니다.
    """
    print("--- Starting calculation of technical indicators for all stocks ---")
    history_data = StockPriceHistory.objects.filter(stock=stock_id).order_by('-date')[:200]
    if len(history_data) < 120:
        print(f"Not enough historical data for {stock.code}. Skipping.")
        return
        
    history_df = pd.DataFrame.from_records(
        history_data.values('date', 'open_price', 'high_price', 'low_price', 'close_price', 'volume')
    ).set_index('date').rename(columns={
        'open_price': 'Open', 'high_price': 'High', 'low_price': 'Low', 
        'close_price': 'Close', 'volume': 'Volume'
    }).sort_index()

    # --- ⚡️ 여기가 핵심 수정 부분 ---
    # pandas-ta가 계산하기 전에, 모든 가격/거래량 컬럼을 숫자(float/int) 타입으로 변환합니다.
    # to_numeric을 사용하면 문자열 등도 숫자로 바꿔주어 더 안전합니다.
    cols_to_convert = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in cols_to_convert:
        history_df[col] = pd.to_numeric(history_df[col], errors='coerce')

    # Volume은 정수형으로
    history_df['Volume'] = history_df['Volume'].astype('int64')
    
    # 이제 history_df의 모든 숫자 컬럼은 pandas-ta와 호환되는 타입이 되었습니다.
    calculate_indicators_for_stock(stock, history_df) 

    print("--- Finished calculation of technical indicators. ---")


def calculate_indicators_for_stock(stock_instance, history_df):
    """
    주어진 DataFrame에 대해, 정의된 설정에 따라 기술적 지표를 계산하고 저장합니다.
    """
    if history_df.empty:
        return

    # --- ⚡️ 1. 계산할 지표와 파라미터를 딕셔너리로 정의 ---
    indicator_settings = {
        'sma': [{'length': 20}, {'length': 60}, {'length': 120}],
        'ema': [{'length': 20}],
        'rsi': [{'length': 14}],
        'macd': [{'fast': 12, 'slow': 26, 'signal': 9}],
        'bbands': [{'length': 20, 'std': 2}],
    }

    # --- 2. 설정을 바탕으로 동적으로 지표 계산 ---
    for indicator_name, params_list in indicator_settings.items():
        for params in params_list:
            # getattr(history_df.ta, 'sma')는 history_df.ta.sma와 같음
            indicator_function = getattr(history_df.ta, indicator_name)
            # **params는 {'length': 20}을 length=20으로 풀어줌
            indicator_function(**params, append=True)

# def calculate_and_save_indicators(stock_instance, history_df):
#     """
#     주어진 DataFrame에 대해 기술적 지표를 계산하고,
#     TechnicalIndicator 모델에 bulk_update/create 합니다.
#     """
#     if history_df.empty:
#         return

#     # 1. pandas-ta를 사용하여 지표 계산
#     history_df.ta.sma(length=20, append=True) # SMA_20
#     history_df.ta.ema(length=20, append=True) # EMA_20
#     history_df.ta.rsi(length=14, append=True) # RSI_14
#     history_df.ta.macd(append=True)           # MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
#     history_df.ta.bbands(length=20, append=True) # BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
    
#     # NaN 값을 None으로 변환
#     history_df.replace([np.inf, -np.inf], np.nan, inplace=True)
#     history_df_cleaned = history_df.where(pd.notnull(history_df), None)

#     # 2. DB에 저장된 StockPriceHistory 객체들을 가져옴
#     dates = history_df_cleaned.index.date
#     history_objects = StockPriceHistory.objects.filter(stock=stock_instance, date__in=dates)
#     history_map = {h.date: h for h in history_objects}

#     indicator_objects_to_update = []
    
#     # 3. 계산된 지표를 TechnicalIndicator 객체에 매핑
#     for index, row in history_df_cleaned.iterrows():
#         history_obj = history_map.get(index.date())
#         if not history_obj:
#             continue
            
#         indicator_objects_to_update.append(
#             TechnicalIndicator(
#                 history=history_obj, # OneToOneField는 history 객체 자체를 할당
#                 sma_20=row.get('SMA_20'),
#                 ema_20=row.get('EMA_20'),
#                 rsi_14=row.get('RSI_14'),
#                 macd=row.get('MACD_12_26_9'),
#                 macd_signal=row.get('MACDs_12_26_9'),
#                 macd_hist=row.get('MACDh_12_26_9'),
#                 bb_upper=row.get('BBU_20_2.0'),
#                 bb_middle=row.get('BBM_20_2.0'),
#                 bb_lower=row.get('BBL_20_2.0'),
#             )
#         )
    
#     if not indicator_objects_to_update:
#         return

#     # 4. bulk_create 또는 update_or_create로 저장
#     #    primary_key=True를 사용했으므로, ignore_conflicts=True로 update/insert 동시 처리
#     TechnicalIndicator.objects.bulk_create(
#         indicator_objects_to_update,
#         ignore_conflicts=True,
#         batch_size=1000
#     )
#     print(f"Saved/Updated {len(indicator_objects_to_update)} indicator records for {stock_instance.code}.")


def run_backtesting_simulation(stock_code: str, start_date: str, end_date: str, initial_capital: float = 10000.0):
    """
    특정 주식에 대해 AI 모델 예측 기반의 가상 매매 시뮬레이션을 실행합니다.
    
    Args:
        stock_code (str): 백테스팅할 주식 티커
        start_date (str): 시작 날짜 (YYYY-MM-DD)
        end_date (str): 종료 날짜 (YYYY-MM-DD)
        initial_capital (float): 초기 자본금

    Returns:
        dict: 날짜별 수익률 데이터가 포함된 딕셔너리
    """
    # 1. 필요한 데이터 가져오기
    # 모델 예측 로그
    logs = PredictionLog.objects.filter(
        stock__code=stock_code,
        prediction_date__range=[start_date, end_date]
    ).order_by('prediction_date').values('prediction_date', 'predicted_signal')

    if not logs:
        return {"error": "해당 기간에 대한 예측 데이터가 없습니다."}

    prediction_df = pd.DataFrame(list(logs))
    prediction_df['prediction_date'] = pd.to_datetime(prediction_df['prediction_date'])
    prediction_df.set_index('prediction_date', inplace=True)

    # 실제 주가 데이터 (하루 더 여유있게 가져옴)
    price_start_date = pd.to_datetime(start_date) - timedelta(days=1)
    price_end_date = pd.to_datetime(end_date) + timedelta(days=1)
    price_data = yf.download(stock_code, start=price_start_date, end=price_end_date)
    
    if price_data.empty:
        return {"error": "주가 데이터를 가져올 수 없습니다."}

    # 2. 시뮬레이션 준비
    # 주가 데이터에 예측 시그널을 합침 (예측일 기준 다음날 매매)
    price_data['signal'] = prediction_df['predicted_signal'].shift(1) # 시그널을 하루 뒤로 밀어서 매매일에 맞춤
    
    # 포트폴리오 상태 변수
    cash = initial_capital
    shares = 0
    portfolio_values = []
    
    # 3. 매매 시뮬레이션 실행 (날짜별 반복)
    for index, row in price_data.iterrows():
        current_price = row['Close']
        current_date = index.strftime('%Y-%m-%d')
        
        # 시그널에 따른 행동 결정 (매수/매도/관망)
        signal = row['signal']
        
        # '매수' 시그널이 있고 현금이 있으면 전량 매수 (간단한 전략)
        if '매수' in str(signal) and cash > 0:
            shares_to_buy = cash / current_price
            shares += shares_to_buy
            cash = 0
            
        # '매도' 시그널이 있고 주식이 있으면 전량 매도
        elif '매도' in str(signal) and shares > 0:
            cash += shares * current_price
            shares = 0
        
        # '관망' 또는 시그널 없으면 아무것도 안 함
        
        # 일별 포트폴리오 가치 계산 및 기록
        current_portfolio_value = cash + (shares * current_price)
        portfolio_values.append({
            "date": current_date,
            "value": current_portfolio_value
        })

    # 4. 결과 데이터프레임 생성 및 수익률 계산
    portfolio_df = pd.DataFrame(portfolio_values)
    portfolio_df['date'] = pd.to_datetime(portfolio_df['date'])
    portfolio_df.set_index('date', inplace=True)
    
    # 모델 누적 수익률
    portfolio_df['model_returns'] = portfolio_df['value'].pct_change().fillna(0)
    portfolio_df['model_cumulative_returns'] = (1 + portfolio_df['model_returns']).cumprod() - 1

    # Buy and Hold (단순 보유) 전략 수익률 계산
    buy_and_hold_returns = price_data['Close'].pct_change().fillna(0)
    buy_and_hold_cumulative_returns = (1 + buy_and_hold_returns).cumprod() - 1
    
    # 최종 결과 데이터 합치기
    result_df = pd.DataFrame({
        'model_cumulative_returns': portfolio_df['model_cumulative_returns'],
        'buy_and_hold_cumulative_returns': buy_and_hold_cumulative_returns
    })
    
    # 시뮬레이션 기간에 맞게 데이터 자르기
    result_df = result_df[start_date:end_date]
    
    # Chart.js가 사용할 수 있는 형식으로 변환
    result_json = {
        "labels": result_df.index.strftime('%Y-%m-%d').tolist(),
        "model_performance": (result_df['model_cumulative_returns'] * 100).round(2).tolist(),
        "buy_and_hold_performance": (result_df['buy_and_hold_cumulative_returns'] * 100).round(2).tolist(),
    }

    return result_json