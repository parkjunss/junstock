# stocks/tasks.py
import time
import logging
from celery import shared_task, group, chord, chain
from django.utils import timezone
from .models import Watchlist, Dashboard, DailyMarketReport, Stock, StockDailyAnalysis, StockPriceHistory, PredictionLog
from fcm_django.models import FCMDevice
import yfinance as yf
from django.core.management import call_command
from django.core.cache import cache
from django.contrib.auth import get_user_model
import mplfinance as mpf
import matplotlib.pyplot as plt
import os
from django.conf import settings
from django.db.models import Avg
import pandas as pd
from datetime import date, timedelta
from django.core.management import call_command # [4]
from celery import shared_task

from .services import (
    aggregate_dashboard_data,
    get_market_indexes, 
    get_exchange_rates, 
    get_commodity_prices, 
    get_fear_and_greed_index,
    get_market_news,
    get_yfinance_stock_info,
    get_yfinance_stock_news,
    get_stock_history,
    generate_market_summary_llm,
    generate_single_stock_analysis_llm,
    generate_single_stock_analysis_llm_v2,
    create_market_chart_image,
    send_daily_report_email,
    get_stock_news,
    update_stock_history_daily,
    calculate_indicators_for_stock,
)

# 로거 설정: 백그라운드 태스크에서는 print 대신 로깅을 사용하는 것이 좋습니다.
logger = logging.getLogger(__name__)

# yfinance에서 오는 key와 Django 모델 필드를 매핑하는 딕셔너리
# 이렇게 하면 코드가 깔끔해지고 유지보수가 쉬워집니다.
YFINANCE_TO_MODEL_MAP = {
    # --- 기본 정보 ---
    'shortName': 'short_name',
    'longName': 'long_name',
    'exchange': 'market',
    # --- 시세 정보 ---
    'regularMarketPrice': 'current_price', # 'currentPrice' 대신 사용 (더 신뢰성 높음)
    'regularMarketChange': 'market_change',
    'regularMarketChangePercent': 'change_percent',
    'regularMarketDayHigh': 'day_high',
    'regularMarketDayLow': 'day_low',
    'regularMarketVolume': 'volume',
    'marketCap': 'market_cap',
    # --- 기업 프로필 정보 ---
    'sector': 'sector',
    'industry': 'industry',
    'website': 'website',
    'longBusinessSummary': 'long_business_summary',
    'fullTimeEmployees': 'full_time_employees',
    'city': 'city',
    'state': 'state',
    'country': 'country',
    # --- 주요 지표 ---
    'trailingPE': 'trailing_pe',
    'forwardPE': 'forward_pe',
    'priceToBook': 'price_to_book',
    'dividendYield': 'dividend_yield',
    'fiftyTwoWeekHigh': 'fifty_two_week_high',
    'fiftyTwoWeekLow': 'fifty_two_week_low',
}


def is_market_open_on(target_date):
    """
    특정 날짜(target_date)에 시장이 열렸었는지 확인합니다.
    """
    try:
        # 넉넉하게 최근 5일치 데이터를 가져와 마지막 거래일 확인 [1]
        check_data = yf.download('^GSPC', period='5d', progress=False)
        
        if check_data.empty:
            return False
            
        # 데이터의 마지막 인덱스(날짜)가 확인하려는 날짜와 같거나 그 이후인지 비교
        last_trading_date = check_data.index[-1].date()
        return last_trading_date >= target_date
    except Exception as e:
        logger.error(f"휴장 여부 확인 중 오류 발생: {e}")
        return False

@shared_task
def run_collect_financial_items_task():
    """재무 항목 마스터 리스트를 수집하고 업데이트하는 태스크"""
    logger.info("===== 재무 항목 수집 작업 시작 =====")
    try:
        call_command('collect_financial_items') # [2] 명령 실행
        logger.info("===== 재무 항목 수집 작업 완료 =====")
    except Exception as e:
        logger.error(f"재무 항목 수집 중 오류 발생: {e}")

@shared_task
def run_calculate_industry_averages_task():
    """산업별 재무 평균을 계산하여 저장하는 태스크"""
    logger.info("===== 산업 평균 계산 작업 시작 =====")
    try:
        call_command('calculate_industry_averages') # [1] 명령 실행
        logger.info("===== 산업 평균 계산 작업 완료 =====")
    except Exception as e:
        logger.error(f"산업 평균 계산 중 오류 발생: {e}")


@shared_task(rate_limit='1/m') # 1분에 1번만 실행되도록 rate limit 설정 (API 남용 방지)
def sync_all_stocks_data():
    """
    DB에 저장된 모든 주식의 최신 정보를 yfinance에서 효율적으로 가져와 동기화합니다.
    yf.Tickers를 사용하여 단일 API 요청으로 처리합니다.
    """
    logger.info("===== 전체 주식 데이터 동기화 시작 =====")
    
    stocks_to_sync = Stock.objects.all()
    if not stocks_to_sync:
        logger.info("동기화할 주식이 없습니다.")
        return "No stocks to sync."

    stock_codes = [s.code for s in stocks_to_sync]
    
    # 1. yf.Tickers로 모든 주식 정보를 한 번에 가져옵니다. (매우 효율적)
    try:
        tickers = yf.Tickers(stock_codes)
        # tickers.info는 각 종목 코드(대문자)를 key로 하는 딕셔너리를 반환합니다.
        # 예: {'MSFT': {...info...}, 'AAPL': {...info...}}
        all_ticker_infos = tickers.tickers 
        logger.info(f"{len(stock_codes)}개 종목 정보 다운로드 완료.")
    except Exception as e:
        logger.info(f"yf.Tickers 정보 다운로드 실패: {e}")
        # 실패 시, 여기서 작업을 중단하고 다음 시도를 기다립니다.
        return "Failed to download ticker info."

    updated_stocks = []
    skipped_count = 0
    
    # 2. 각 주식 객체에 다운로드한 정보를 매핑하여 업데이트합니다.
    for stock in stocks_to_sync:
        ticker_info = all_ticker_infos.get(stock.code.upper()).info # yfinance는 대문자 코드를 사용

        # yfinance에서 정보를 가져오지 못했거나(상장 폐지 등), 필수 정보가 없는 경우 건너뜁니다.
        if not ticker_info or ticker_info.get('regularMarketPrice') is None:
            logger.info(f"경고: {stock.code}의 유효한 정보를 가져오지 못해 건너뜁니다.")
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

    # 4. bulk_update를 사용하여 변경된 모든 주식 정보를 DB에 한 번에 저장합니다.
    if updated_stocks:
        # 업데이트할 필드 목록을 맵에서 동적으로 생성 (+ last_synced_at)
        update_fields = list(YFINANCE_TO_MODEL_MAP.values()) + ['last_synced_at']
        
        Stock.objects.bulk_update(updated_stocks, update_fields)
        logger.info(f"성공: {len(updated_stocks)}개 주식 정보 DB 동기화 완료.")
        if skipped_count > 0:
            logger.info(f"실패/건너뜀: {skipped_count}개 주식.")

    logger.info("===== 전체 주식 데이터 동기화 종료 =====")
    return f"Synced {len(updated_stocks)} of {len(stock_codes)} stocks."


# --- Real-time Data Caching Tasks ---
@shared_task
def task_fetch_and_cache_stock_detail(stock_code):
    """
    yfinance에서 종목의 상세 정보와 뉴스를 가져와 캐시에 저장합니다.
    (StockDetailAPIView를 위함)
    """
    logger.info(f"Fetching and caching detail for {stock_code}...")
    
    # 1. 캐시 키 정의
    info_cache_key = f"stock_info:{stock_code}"
    news_cache_key = f"stock_news:{stock_code}"
    
    # 2. 서비스 함수를 통해 데이터 가져오기
    stock_info = get_yfinance_stock_info(stock_code)
    news_list = get_yfinance_stock_news(stock_code)
    
    # 3. 성공적으로 가져온 데이터를 캐시에 저장
    if stock_info:
        cache.set(info_cache_key, stock_info, timeout=60 * 5) # 5분간 캐시
        logger.info(f"Cached stock info for {stock_code}")

    # 뉴스 데이터는 빈 리스트일 수도 있으므로, None이 아닐 경우에만 캐시
    if news_list is not None:
        cache.set(news_cache_key, news_list, timeout=60 * 15) # 15분간 캐시
        logger.info(f"Cached stock news for {stock_code}")
        
    return f"Successfully fetched and cached detail for {stock_code}"

@shared_task
def task_fetch_and_cache_stock_chart(stock_code, period):
    """
    yfinance에서 종목의 차트 데이터를 가져와 캐시에 저장합니다.
    (StockChartAPIView를 위함)
    """
    logger.info(f"Fetching and caching chart for {stock_code} ({period})...")
    
    # 1. 캐시 키 정의
    chart_cache_key = f"stock_chart:{stock_code}:{period}"
    
    # 2. 서비스 함수를 통해 데이터 가져오기
    chart_data = get_stock_history(stock_code, period)
    
    # 3. 성공적으로 가져온 데이터를 캐시에 저장
    if chart_data:
        cache.set(chart_cache_key, chart_data, timeout=60 * 5) # 5분간 캐시
        logger.info(f"Cached stock chart for {stock_code} ({period})")
        
    return f"Successfully fetched and cached chart for {stock_code} ({period})"


# --- 1. 개별 데이터 Fetching "일꾼" 태스크들 ---
# services.py의 함수를 단순히 감싸는 역할만 합니다.
@shared_task(name='fetch.market_indexes')
def get_market_indexes_task():
    return get_market_indexes()

@shared_task(name='fetch.exchange_rates')
def get_exchange_rates_task():
    return get_exchange_rates()

@shared_task(name='fetch.commodity_prices')
def get_commodity_prices_task():
    return get_commodity_prices()

@shared_task(name='fetch.fear_and_greed_index')
def get_fear_and_greed_index_task():
    return get_fear_and_greed_index()

@shared_task(name='fetch.market_news')
def get_market_news_task():
    return get_market_news()

# --- 2. 취합된 데이터를 받아 최종적으로 집계하고 저장하는 태스크 ---
@shared_task(name='aggregate.save_dashboard_data')
def aggregate_and_save_task(results):
    """
    병렬로 실행된 태스크들의 결과(results)를 받아서 데이터를 집계하고 저장합니다.
    """
    logger.info("All fetch tasks completed. Aggregating and saving data...")
    start_time = time.time()
    
    # group의 결과는 리스트 형태로 전달됩니다. 순서는 group에 넣은 순서와 같습니다.
    market_indexes, exchange_rates, commodity_prices, fear_and_greed_index, market_news = results
    
    try:
        # 서비스 함수를 호출하여 최종 데이터 구조 생성
        fresh_data = aggregate_dashboard_data(
            market_indexes, exchange_rates, commodity_prices, fear_and_greed_index, market_news
        )
        
        # Dashboard 모델에 데이터 저장
        _, created = Dashboard.objects.update_or_create(
            key='main_dashboard',
            defaults={'data': fresh_data}
        )
        
        duration = time.time() - start_time
        message = f"Successfully {'created' if created else 'updated'} dashboard data in {duration:.2f} seconds."
        logger.info(message)
        return message

    except Exception as e:
        logger.error(f'Error during final aggregation and save: {e}')
        raise e

# --- 3. 전체 워크플로우를 실행시키는 "지휘자" 태스크 ---
@shared_task
def update_dashboard_task():
    """
    대시보드 업데이트 워크플로우를 시작시키는 메인 태스크입니다.
    이 태스크를 Celery Beat나 Management Command에서 호출합니다.
    """
    logger.info("Initiating dashboard update workflow.")
    
    # 1. 병렬로 실행할 태스크들을 group으로 묶습니다.
    # .s()는 태스크를 즉시 실행하지 않고 '시그니처(signature)'로 만듭니다.
    fetch_tasks = group(
        get_market_indexes_task.s(),
        get_exchange_rates_task.s(),
        get_commodity_prices_task.s(),
        get_fear_and_greed_index_task.s(),
        get_market_news_task.s()
    )
    
    # 2. chain을 사용하여 'group 실행' -> '집계 및 저장' 순서로 워크플로우를 정의합니다.
    # fetch_tasks(group)의 결과가 aggregate_and_save_task의 인자로 전달됩니다.
    workflow = chain(fetch_tasks | aggregate_and_save_task.s())
    
    # 3. 정의된 워크플로우를 비동기적으로 실행합니다.
    workflow.delay()
    
    return "Dashboard update workflow has been successfully triggered."


@shared_task
def check_stock_prices_and_notify():
    """
    모든 관심종목의 현재가를 확인하고, 목표가에 도달하면 알림을 보냅니다.
    (yf.download을 사용하여 API 호출을 최소화)
    """
    logger.info("===== 주가 확인 작업 시작 =====")

    # 1. 목표가가 설정된 모든 Watchlist 항목을 가져옵니다. (select_related로 stock 정보 함께 로드)
    watchlists_with_target = Watchlist.objects.filter(target_price__isnull=False).select_related('stock', 'user')

    if not watchlists_with_target:
        logger.info("알림 보낼 관심종목이 없습니다.")
        logger.info("===== 주가 확인 작업 종료 =====")
        return

    # 2. 모든 종목 코드를 리스트로 만듭니다.
    stock_codes = [item.stock.code for item in watchlists_with_target]
    
    try:
        # 3. yf.download으로 모든 종목의 최신 가격 정보를 한 번에 가져옵니다.
        #    - period='2d'로 최소한의 데이터만 요청합니다.
        #    - progress=False로 다운로드 진행바를 숨깁니다.
        data = yf.download(stock_codes, period='2d', progress=False)
        
        if data.empty:
            logger.info("yf.download로부터 데이터를 가져오지 못했습니다.")
            logger.info("===== 주가 확인 작업 종료 =====")
            return

        # 4. 각 종목별로 목표가 도달 여부를 확인합니다.
        for item in watchlists_with_target:
            user = item.user
            stock = item.stock
            target_price = item.target_price

            try:
                # yf.download는 컬럼 레벨이 여러 개일 수 있습니다. ('Close', 'AAPL'), ('Open', 'AAPL')
                # 따라서 ['Close'][stock.code] 형태로 접근합니다.
                current_price = data['Close'][stock.code].iloc[-1]

                logger.info(f"[{stock.code}] 현재가: {current_price:.2f}, 목표가: {target_price}")

                if current_price >= target_price:
                    devices = FCMDevice.objects.filter(user=user, active=True)
                    
                    # 알림 본문 생성
                    body = f"{stock.name}({stock.code})의 주가가 목표가({target_price})를 돌파했습니다! 현재가: {current_price:.2f}"
                    
                    # 각 기기로 알림 발송
                    for device in devices:
                        device.send_message(
                            title="🚀 목표가 도달 알림",
                            body=body,
                            data={"stock_code": stock.code, "current_price": f"{current_price:.2f}"}
                        )
                    logger.info(f"알림 발송 완료: {user.username} - {stock.name}")
                    
                    # 중복 발송 방지를 위해 목표가 초기화
                    item.target_price = None
                    item.save(update_fields=['target_price'])

            except KeyError:
                logger.info(f"오류: {stock.code}의 가격 정보를 찾을 수 없습니다. API 응답에 종목이 누락되었을 수 있습니다.")
                continue
            except Exception as e:
                logger.info(f"오류 발생 ({stock.code}): {e}")
                continue

    except Exception as e:
        logger.info(f"yf.download API 호출 중 심각한 오류 발생: {e}")

    logger.info("===== 주가 확인 작업 종료 =====")


@shared_task
def run_update_stock_metrics():
    """
    'update_stock_metrics' 관리자 명령어를 호출하는 Celery 작업
    """
    logger.info("===== 주식 지표 업데이트 작업 시작 =====")
    try:
        call_command('update_stock_metrics')
        logger.info("===== 주식 지표 업데이트 작업 성공적으로 완료 =====")
    except Exception as e:
        logger.info(f"주식 지표 업데이트 작업 중 오류 발생: {e}")


# ==================================================================================
# ↓↓↓ 아래는 Celery가 직접 실행하는 '@shared_task' 들입니다. ↓↓↓
# ==================================================================================

@shared_task
def generate_daily_market_report_task():
    """TASK: 오늘의 종합 시황 리포트를 생성하고 DB에 저장"""
    today = timezone.now().date()
    if DailyMarketReport.objects.filter(date=today).exists():
        print(f"Market report for {today} already exists.")
        return
    summary_text = generate_market_summary_llm()
    DailyMarketReport.objects.create(date=today, summary_text=summary_text)
    print(f"Successfully created market report for {today}.")


@shared_task
def generate_analysis_for_stock_task(stock_id):
    """TASK: 특정 주식 하나에 대한 일일 분석을 생성하고 DB에 저장"""
    today = timezone.now().date()
    stock = Stock.objects.get(id=stock_id)
    if StockDailyAnalysis.objects.filter(stock=stock, date=today).exists():
        print(f"Analysis for {stock.code} on {today} already exists.")
        return
    # analysis_text = generate_single_stock_analysis_llm(stock)
    analysis_text = generate_single_stock_analysis_llm_v2(stock)
    StockDailyAnalysis.objects.create(stock=stock, date=today, analysis_text=analysis_text)
    print(f"Successfully created analysis for {stock.code} on {today}.")



@shared_task
def send_single_user_report_task(user_id, image_paths_dict):
    """
    TASK: 특정 사용자 한 명에게 DB 데이터를 조합하여 이메일 발송 (안정성 강화 버전)
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        print(f"User with ID {user_id} not found. Skipping email.")
        return

    today = timezone.now().date()
    
    # 1. 공용 시황 리포트 가져오기
    try:
        market_report = DailyMarketReport.objects.get(date=today)
        market_summary_text = market_report.summary_text
    except DailyMarketReport.DoesNotExist:
        market_summary_text = "오늘의 시황 분석이 아직 준비되지 않았습니다."

    # 2. 관심종목 및 관련 분석 데이터 준비
    watchlist_items_qs = user.watchlist.select_related('stock').all()

    # ⚡️ 1. 템플릿에 전달할 최종 데이터 리스트를 만듭니다.
    watchlist_data_for_template = []
    if watchlist_items_qs:
        stock_ids = [item.stock.id for item in watchlist_items_qs]
        analyses = StockDailyAnalysis.objects.filter(stock_id__in=stock_ids, date=today)
        analysis_map = {analysis.stock.id: analysis.analysis_text for analysis in analyses}
        
        for item in watchlist_items_qs:
            # 각 항목을 딕셔너리로 구성
            watchlist_data_for_template.append({
                'stock': item.stock, # Stock 객체 자체를 전달
                'analysis': analysis_map.get(item.stock.id, "오늘의 분석 정보가 없습니다."),
                'news': get_stock_news(item.stock.code, count=2) # 뉴스 데이터도 함께 전달
            })

    # 3. 최종 이메일 발송
    try:
        send_daily_report_email(user, market_summary_text, watchlist_data_for_template, image_paths_dict)
    except Exception as e:
        # 이메일 발송 자체에서 에러가 날 경우를 대비
        print(f"CRITICAL: Failed during the final email sending process for {user.email}: {e}")

@shared_task
def dispatch_email_tasks(results, user_ids):
    image_paths = [res for res in results if isinstance(res, str) and res.endswith('.png')]
    indices_path = next((p for p in image_paths if 'indices' in p), None)
    sector_path = next((p for p in image_paths if 'sector' in p), None)

    # 2. ⚡️ 추출한 경로들로 '딕셔너리'를 만듭니다.
    image_paths_dict = {
        'indices_chart': indices_path,
        'sector_heatmap': sector_path,
    }

    email_tasks = group(
        send_single_user_report_task.s(user_id, image_paths_dict) for user_id in user_ids
    )
    email_tasks.apply_async()
    print(f">>> Queued {len(user_ids)} email sending tasks.")

@shared_task
def create_indices_comparison_chart_task(period='1mo', filename='indices_chart.png'):
    today = timezone.now().date()
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

    ax.set_title('Major Index Change (1 Month)')
    ax.set_ylabel('Change (%)')
    ax.legend() # 범례 표시
    fig.tight_layout() # 레이아웃 최적화

    save_path = os.path.join(settings.BASE_DIR, 'media', 'charts', f'{today}_{filename}')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    fig.savefig(save_path)
    plt.close(fig) # 메모리 해제
    return save_path

@shared_task
def create_sector_performance_heatmap_task(filename='sector_heatmap.png'):
    today = timezone.now().date()

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
    ax.set_title('S&P 500 Sectors')
    ax.set_xlabel('Avg (%)')
    fig.tight_layout()

    save_path = os.path.join(settings.BASE_DIR, 'media', 'charts', f'{today}_{filename}')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    fig.savefig(save_path)
    plt.close(fig)
    return save_path

@shared_task
def schedule_all_daily_reports():
    """MAIN TASK: 실제 장이 열렸던 날인지 날짜를 대조한 후 리포팅 실행"""
    
    # 분석 대상 날짜는 '어제' (화~토 아침 실행 기준) [5]
    target_date = date.today() - timedelta(days=1)
    
    # 함수를 호출하여 휴장 여부 확인
    if not is_market_open_on(target_date):
        print(f">>> {target_date}는 휴장일이었습니다. 리포트 생성을 취소합니다.")
        return
    print(f">>> {target_date} 장 데이터가 확인되었습니다. 리포트 생성을 시작합니다.")

    print(">>> Main scheduling task started...")
    
    active_stock_ids = list(Watchlist.objects.values_list('stock_id', flat=True).distinct())
    user_ids = list(get_user_model().objects.filter(is_active=True).values_list('id', flat=True))

    if not user_ids:
        print("No active users to send reports to. Exiting.")
        return

    # --- ⚡️ 1. 모든 병렬 작업을 '하나의 리스트'로 준비합니다. ---
    header_tasks = []

    # 고정된 작업들 추가
    # header_tasks.append(calculate_indicators_for_watchlist_stocks_task.s())
    header_tasks.append(generate_daily_market_report_task.s())
    header_tasks.append(create_indices_comparison_chart_task.s())
    header_tasks.append(create_sector_performance_heatmap_task.s())

    # 동적으로 생성되는 작업들 추가 (리스트 + 리스트)
    analysis_tasks = [generate_analysis_for_stock_task.s(stock_id) for stock_id in active_stock_ids]
    header_tasks.extend(analysis_tasks) # .extend()를 사용하여 리스트를 합침

    # --- 2. 완성된 리스트로 group을 생성합니다. ---
    prepare_data_header = group(header_tasks)

    # 3. Body (Callback) 작업 준비
    callback_task = dispatch_email_tasks.s(user_ids=user_ids)

    # 4. Chord 실행
    chord(prepare_data_header)(callback_task)
    
    print(f">>> Chord queued with {len(header_tasks)} tasks in header.")


@shared_task
def update_stock_history_daily_task():
    """
    Celery Task: 모든 주식의 일일 시세 데이터를 업데이트합니다.
    """
    print("--- Starting Celery task: update_stock_history_daily_task ---")
    result = update_stock_history_daily()
    print(f"--- Finished Celery task: update_stock_history_daily_task. Result: {result} ---")
    return result

@shared_task
def calculate_indicators_for_watchlist_stocks_task():
    """TASK: '모든' 관심종목에 등록된 주식들의 기술적 지표를 계산합니다."""
    print("--- Celery task: Calculating indicators for all watchlist stocks ---")
    
    # 1. 관심종목에 등록된 모든 주식 ID를 중복 없이 가져옵니다.
    watchlist_stock_ids = Watchlist.objects.values_list('stock_id', flat=True).distinct()
    
    # 2. 각 주식에 대해 개별 지표 계산 Task를 '병렬로' 실행시킵니다.
    tasks_to_run = [
        calculate_single_stock_indicators_task.s(stock_id) for stock_id in watchlist_stock_ids
    ]
    
    # 3. 리스트를 group으로 묶어서 실행
    if tasks_to_run:
        group(tasks_to_run).apply_async()
        print(f"Queued indicator calculation for {len(tasks_to_run)} watchlist stocks.")
    else:
        print("No watchlist stocks to calculate indicators for.")



@shared_task
def calculate_single_stock_indicators_task(stock_id):
    """TASK: '단일' 주식의 기술적 지표를 계산합니다."""
    try:
        stock = Stock.objects.get(id=stock_id)
        # ... (이전에 만든 calculate_indicators_for_stock 서비스 함수 호출) ...
        # 1. DB에서 해당 stock의 history 데이터 가져오기
        # 2. DataFrame으로 변환
        # 3. pandas-ta로 지표 계산
        # 4. DB에 저장
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
        calculate_indicators_for_stock(stock, history_df)
        print(f"Successfully calculated indicators for {stock.code}")
    except Stock.DoesNotExist:
        print(f"Stock with id {stock_id} does not exist. Skipping.")
    except Exception as e:
        print(f"Error calculating indicators for stock_id {stock_id}: {e}")


@shared_task
def evaluate_predictions():
    """
    어제 예측된 결과에 대해 오늘의 실제 주가 변동을 비교하여 성능을 평가합니다.
    매일 새벽에 실행되도록 Celery Beat에 등록합니다.
    """
    # 평가 대상 날짜는 어제
    target_date = date.today() - timedelta(days=1)
    
    # 휴장 확인 로직 적용
    if not is_market_open_on(target_date):
        print(f">>> {target_date}는 휴장일입니다. 평가는 다음 영업일에 진행합니다.")
        return

    # 아직 평가되지 않은 어제의 예측 로그들을 가져옴
    logs_to_evaluate = PredictionLog.objects.filter(
        prediction_date=target_date,
        is_correct__isnull=True
    )

    if not logs_to_evaluate.exists():
        print(f"No predictions to evaluate for {target_date}.")
        return

    print(f"Evaluating {logs_to_evaluate.count()} predictions for {target_date}...")

    for log in logs_to_evaluate:
        try:
            # yfinance를 사용하여 다음 거래일의 데이터를 가져옴
            # prediction_date가 금요일이면, 실제 결과는 월요일에 나옴
            # yfinance는 주말을 자동으로 건너뛰고 다음 거래일 데이터를 가져옴
            start_date = log.prediction_date
            end_date = start_date + timedelta(days=4) # 주말을 고려하여 넉넉하게
            
            # yfinance는 start를 포함하므로, 예측일 다음날 데이터를 원함
            data = yf.download(log.stock.code, start=start_date, end=end_date, progress=False)
            
            if len(data) < 2:
                print(f"Not enough data to evaluate {log.stock.code} for {target_date}")
                continue

            # 예측일(t)과 그 다음 거래일(t+1)의 종가
            price_t = data['Close'].iloc[0]
            price_t1 = data['Close'].iloc[1]
            
            actual_change = (price_t1 - price_t) / price_t * 100
            
            # 실제 결과 정의
            if actual_change > 0.5: # 0.5% 이상 상승 시 '상승'
                actual_outcome = "상승"
            elif actual_change < -0.5: # -0.5% 이하 하락 시 '하락'
                actual_outcome = "하락"
            else:
                actual_outcome = "보합"

            # 예측 성공 여부 판단
            is_correct = False
            predicted_signal = log.predicted_signal
            
            # '매수' 계열 예측은 '상승' 또는 '보합'을 맞춘 것으로 간주 (손실 회피)
            if ('매수' in predicted_signal and actual_outcome in ["상승", "보합"]):
                is_correct = True
            # '매도' 계열 예측은 '하락' 또는 '보합'을 맞춘 것으로 간주
            elif ('매도' in predicted_signal and actual_outcome in ["하락", "보합"]):
                is_correct = True
            # '관망' 예측은 '보합'일 때 맞춘 것으로 간주
            elif ('관망' in predicted_signal and actual_outcome == "보합"):
                is_correct = True

            # 결과 업데이트
            log.actual_outcome = actual_outcome
            log.actual_change_percent = actual_change
            log.is_correct = is_correct
            log.evaluated_at = timezone.now()
            log.save()

            print(f"Evaluated {log.stock.code}: Predicted {predicted_signal}, Actual {actual_outcome} ({actual_change:.2f}%) -> {'Correct' if is_correct else 'Incorrect'}")

        except Exception as e:
            print(f"Error evaluating prediction for {log.stock.code}: {e}")

    print("Prediction evaluation finished.")


@shared_task(queue='pytorch-tasks')
def run_daily_predictions():
    from .pytorch_trained_model.sac_predictor import get_trading_signal_from_sac

    """
    관심 목록에 있는 모든 주식에 대해 AI 예측을 실행하고 DB에 저장합니다.
    이 작업은 리포트 생성 작업보다 먼저 실행되어야 합니다.
    """
    # 중복을 제거한 모든 관심 주식 목록 가져오기
    active_stock_codes = Watchlist.objects.values_list('stock__code', flat=True).distinct()

    if not active_stock_codes:
        print("No stocks in watchlist to predict.")
        return

    print(f"Starting daily predictions for {len(active_stock_codes)} stocks...")

    for code in active_stock_codes:
        print(f"Predicting for {code}...")
        try:
            # 예측 함수 호출 (이 함수는 내부적으로 DB에 결과를 저장합니다)
            # 모델 티커와 예측 티커가 동일하다고 가정
            get_trading_signal_from_sac(ticker_to_predict=code, model_ticker=code)
        except Exception as e:
            # 개별 주식 예측 실패가 전체 작업을 중단시키지 않도록 처리
            print(f"Failed to predict for {code}: {e}")
            
    print("Daily prediction task finished.")

@shared_task
def backfill_prediction_evaluations():
    """evaluate_predictions를 재사용"""
    evaluate_predictions()