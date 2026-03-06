# core/views.py
from django.views.generic import TemplateView, DetailView
import os
from django.conf import settings
from django.shortcuts import render, get_object_or_404
from stocks.models import Dashboard, Stock, StockPriceHistory, FinancialStatement, FinancialItem, IndustryFinancialAverage, PredictionLog
from django.views import View
import json
import math
from django.db.models import Q # Q 객체 임포트
from datetime import date, timedelta, datetime
from django.core.paginator import Paginator
import pandas as pd
import numpy as np
from django.http import JsonResponse
from collections import defaultdict
import time

# 함수 기반 뷰(FBV)를 아래 클래스 기반 뷰(CBV)로 대체합니다.
class StockDetailView(DetailView):
    model = Stock
    template_name = 'core/stock_detail.html'
    slug_field = 'code'
    slug_url_kwarg = 'stock_code'
    context_object_name = 'stock'

    def get(self, request, *args, **kwargs):
        # 요청에 'format=json' 쿼리 파라미터가 있는지 확인
        if request.GET.get('format') == 'json':
            # 있으면 JSON 데이터를 반환하는 로직을 수행
            stock_obj = self.get_object() # 현재 페이지의 stock 객체를 가져옴
            return self.get_price_history_json(request, stock_obj)
        else:
            # 없으면 부모 클래스(DetailView)의 원래 get 메서드를 호출하여
            # 평소처럼 HTML 페이지를 렌더링
            return super().get(request, *args, **kwargs)


    def get_price_history_json(self, request, stock):
        """
        차트 데이터를 JSON으로 만들어 반환하는 헬퍼 메서드
        """
        period = request.GET.get('period', '1y').lower()
        
        end_date = date.today()
        start_date = None
        
        if period == '5d':
            start_date = end_date - timedelta(days=7)
        elif period == '1m':
            start_date = end_date - timedelta(days=31)
        elif period == '1y':
            start_date = end_date - timedelta(days=365)
        elif period == '10y':
            start_date = end_date - timedelta(days=365 * 10)

        queryset = StockPriceHistory.objects.filter(stock=stock).order_by('date')
        if start_date:
            queryset = queryset.filter(date__gte=start_date)

        labels = [pd.to_datetime(p.date, format='mixed', dayfirst=False).strftime('%Y-%m-%d') for p in queryset]
        data_points = [float(p.close_price) for p in queryset]
        
    
        response_data = {
            'labels': labels,
            'data': data_points,
        }
        
        return JsonResponse(response_data)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stock_obj = self.object

        # =================================================================
        # 1. 주가 이력 데이터 준비
        # =================================================================
        one_year_ago = date.today() - timedelta(days=365)
        price_data = StockPriceHistory.objects.filter(stock=stock_obj, date__gte=one_year_ago).order_by('date')
        price_labels = [pd.to_datetime(p.date, format='mixed', dayfirst=False).strftime('%Y-%m-%d') for p in price_data]
        price_values = [float(p.close_price) for p in price_data]

        # =================================================================
        # 2. 모든 재무 데이터를 "한 번만" DB에서 가져오기
        # =================================================================
        all_statements_df = pd.DataFrame() # 초기화
        financial_tables_data = {}         # 초기화
        
        all_statements = FinancialStatement.objects.filter(stock=stock_obj).select_related('item').order_by('item__statement_type', 'item__order')
        if all_statements.exists():
            all_statements_df = pd.DataFrame(list(all_statements.values(
                'date', 'value', 'period_type', 'item__standard_key', 'item__korean_label', 'item__statement_type'
            )))
            financial_tables_data = self.prepare_financial_tables_data(all_statements_df)

        # =================================================================
        # 3. 산업 평균 데이터 조회
        # =================================================================
        industry_avg_map = self.get_industry_avg_map(stock_obj.industry)

        # =================================================================
        # 4. 하단 재무 "차트"용 데이터 가공 (DataFrame 재사용)
        # =================================================================
        metrics_data = {
            'incomeOverviewAnnual': self.get_chart_data(all_statements_df, ['total_revenue', 'operating_income'], 'A', 
                avg_map={
                    'total_revenue': industry_avg_map.get('total_revenue', {}).get('A'),
                    'operating_income': industry_avg_map.get('operating_income', {}).get('A')
                }
            ),
            'incomeOverviewQuarterly': self.get_chart_data(all_statements_df, ['total_revenue', 'operating_income'], 'Q',
                avg_map={
                    'total_revenue': industry_avg_map.get('total_revenue', {}).get('Q'),
                    'operating_income': industry_avg_map.get('operating_income', {}).get('Q')
                }
            ),
            'netIncomeAnnual': self.get_chart_data(all_statements_df, ['net_income'], 'A', avg_map={'net_income': industry_avg_map.get('net_income', {}).get('A')}),
            'netIncomeQuarterly': self.get_chart_data(all_statements_df, ['net_income'], 'Q', avg_map={'net_income': industry_avg_map.get('net_income', {}).get('Q')}),
            'fcfAnnual': self.get_chart_data(all_statements_df, ['free_cash_flow'], 'A', avg_map={'free_cash_flow': industry_avg_map.get('free_cash_flow', {}).get('A')}),
            'fcfQuarterly': self.get_chart_data(all_statements_df, ['free_cash_flow'], 'Q', avg_map={'free_cash_flow': industry_avg_map.get('free_cash_flow', {}).get('Q')}),
        }


        # 1. 먼저 '전체' 평가 완료된 로그 쿼리셋을 만듭니다 (슬라이싱 전)
        base_logs = PredictionLog.objects.filter(
            stock=stock_obj, 
            is_correct__isnull=False
        )

        # 2. 전체를 대상으로 카운트 및 필터링 수행 (오류 발생 안 함)
        total_count = base_logs.count()
        correct_count = base_logs.filter(is_correct=True).count() # 성공한 것만 카운트 [3]
        accuracy = (correct_count / total_count * 100) if total_count > 0 else 0

        # ---------------------------------------------------------
        # [추가 기능 1] 모델 매매 시뮬레이션 수익률 계산 (복리 적용)
        # ---------------------------------------------------------
        cumulative_balance = 1.0  # 초기 자산 1.0 (100%)
        
        for log in base_logs:
            # AI가 '매수' 또는 '강력 매수'라고 했을 때만 진입한다고 가정
            if '매수' in log.predicted_signal:
                # actual_change_percent가 1.5면 1.5% 상승 -> 1.015배
                change_ratio = log.actual_change_percent / 100
                cumulative_balance *= (1 + change_ratio)
        
        # 최종 수익률 (%) : (최종 자산 - 초기 자산) * 100
        model_return_percent = (cumulative_balance - 1) * 100

        # 3. 화면에 표시할 '최근 30개'만 마지막에 슬라이싱
        prediction_logs_for_display = base_logs.order_by('-prediction_date')[:30]

        # 3. 템플릿 전달을 위한 데이터 가공 [4, 5]
        prediction_data = {
            'accuracy': round(accuracy, 1),
            'total_count': total_count,
            'model_return': round(model_return_percent, 2), # [추가] 누적 수익률
            'logs': [
                {
                    'date': log.prediction_date.strftime('%Y-%m-%d'),
                    'signal': log.predicted_signal,
                    'outcome': log.actual_outcome,
                    'change': round(log.actual_change_percent, 2),
                    'is_correct': log.is_correct
                } for log in prediction_logs_for_display
            ]
        }

        
        # =================================================================
        # 5. 최종적으로 템플릿에 전달할 initial_data 구성
        # =================================================================
        initial_data = {
            'price': {
                'labels': price_labels,
                'values': price_values,
                'changePercent': stock_obj.change_percent or 0
            },
            'metrics': metrics_data,
            'financials': financial_tables_data,
            'predictions': prediction_data
        }
        context['initial_data_json'] = json.dumps(initial_data, default=str, ensure_ascii=False)
        # print(context['initial_data_json'])

        return context

    # ------------------- 헬퍼 메서드들 -------------------

    def prepare_financial_tables_data(self, df):
        tables_data = {}
        for stmt_type_code, stmt_type_name in FinancialItem.STATEMENT_TYPE_CHOICES:
            stmt_df = df[df['item__statement_type'] == stmt_type_code]
            if stmt_df.empty:
                continue
            
            annual_df = self.pivot_financial_data(stmt_df, 'A')
            quarterly_df = self.pivot_financial_data(stmt_df, 'Q')
            if not annual_df.empty:
                annual_df.columns = pd.to_datetime(annual_df.columns, format='mixed', dayfirst=False).strftime('%Y-%m-%d')

            if not quarterly_df.empty:
                quarterly_df.columns = pd.to_datetime(quarterly_df.columns, format='mixed', dayfirst=False).strftime('%Y-%m-%d')
            
            tables_data[stmt_type_code] = {
                'name': stmt_type_name,
                'annual': {'dates': sorted(list(annual_df.columns), reverse=True), 'statements': annual_df.to_dict('index')},
                'quarterly': {'dates': sorted(list(quarterly_df.columns), reverse=True), 'statements': quarterly_df.to_dict('index')},
                'items': list(stmt_df[['item__standard_key', 'item__korean_label']].rename(columns={'item__standard_key': 'standard', 'item__korean_label': 'label'}).drop_duplicates().to_dict('records'))
            }
        return tables_data

    def get_industry_avg_map(self, industry):
        if not industry:
            return {}
        
        avg_map = {}
        industry_averages = IndustryFinancialAverage.objects.filter(industry=industry).select_related('item')
        for avg in industry_averages:
            if avg.item.standard_key not in avg_map:
                avg_map[avg.item.standard_key] = {}
            avg_map[avg.item.standard_key][avg.period_type] = avg.average_values
        return avg_map

    def get_chart_data(self, df, standard_keys, period_type, avg_map):
        if df.empty:
            return None
            
        chart_df = df[(df['item__standard_key'].isin(standard_keys)) & (df['period_type'] == period_type)].sort_values('date')
        if chart_df.empty:
            return None
        
        chart_df['date'] = pd.to_datetime(chart_df['date'])
        labels = chart_df['date'].dt.strftime('%Y-%m').unique().tolist()
        sliced_labels = labels[-4:]

        datasets = []
        colors = {'total_revenue': 'rgba(59, 130, 246, 0.8)', 'operating_income': 'rgba(239, 68, 68, 0.8)', 'net_income': 'rgba(16, 185, 129, 0.8)', 'free_cash_flow': 'rgba(234, 179, 8, 0.8)'}

        for key in standard_keys:
            key_df = chart_df[chart_df['item__standard_key'] == key]
            if not key_df.empty:
                data_map = {row['date'].strftime('%Y-%m'): row['value'] for _, row in key_df.iterrows()}
                datasets.append({
                    'label': key_df['item__korean_label'].iloc[0],
                    'data': [data_map.get(label, None) for label in sliced_labels],
                    'backgroundColor': colors.get(key, 'gray'),
                    'type': 'bar', 'barPercentage': 0.5
                })

                # --- 산업 평균 데이터셋 추가 (수정된 로직) ---
                avg_data_full_date = avg_map.get(key, {})
                # print(avg_data_full_date)
                if avg_data_full_date:
                    # 1. 평균 데이터의 날짜 키를 표준 'YYYY-MM' 형식으로 변환합니다.
                    avg_lookup_map = {}
                    for date_str, value in avg_data_full_date.items():
                        company_count = value.get('count')
                        try:
                            # '2021-8-31' 같은 문자열을 datetime 객체로 파싱
                            dt_obj = datetime.strptime(date_str, '%Y-%m-%d')
                            # 'YYYY-MM' 형식의 키로 변환하여 저장
                            standard_key = dt_obj.strftime('%Y-%m')
                            avg_lookup_map[standard_key] = value.get('avg')
                        except ValueError:
                            # 날짜 형식이 다를 경우를 대비한 예외 처리
                            continue

                    datasets.append({
                        'label': f"산업 평균 ({key_df['item__korean_label'].iloc[0]})",
                        'data': [avg_lookup_map.get(label, None) for label in sliced_labels], # avg_data의 키 형식에 맞춰야 함
                        'type': 'line', 'borderColor': colors.get(key, 'gray').replace('0.8', '1'), 'fill': False, 'pointRadius': 0
                    })
        
        return {'data': {'labels': sliced_labels, 'datasets': datasets}} # 이제 딕셔너리를 직접 반환


    def pivot_financial_data(self, df, period_type):
        filtered_df = df[df['period_type'] == period_type]
        if filtered_df.empty:
            return pd.DataFrame()

        # 이제 index를 'item__standard'로 사용합니다.
        pivot_df = filtered_df.pivot_table(
            index='item__standard_key', 
            columns='date', 
            values='value'
        ).fillna(0)
        return pivot_df


class ScreenerPageView(View):
    full_template_name = 'core/screener.html'
    partial_template_name = 'partials/results_card.html' # 이 템플릿만 사용

    def get_context_data(self, **kwargs):
        """템플릿에 전달할 컨텍스트 데이터를 구성합니다."""

        sort_by = self.request.GET.get('sort', 'market_cap') # 기본 정렬: 시가총액
        order = self.request.GET.get('order', 'desc') # 기본 순서: 내림차순

        # 2. 정렬 순서에 따라 order_by 문자열 생성
        if order == 'asc':
            order_by_field = sort_by
        else:
            order_by_field = f'-{sort_by}'



        # 검색어(q) 가져오기
        query = self.request.GET.get('q')
        # 필터링
        queryset = Stock.objects.all()

        allowed_sort_fields = ['short_name', 'current_price', 'market_cap', 'trailing_pe', 'price_to_book', 'dividend_yield', 'trailing_eps']
        if sort_by in allowed_sort_fields:
            queryset = Stock.objects.order_by(order_by_field)
        else:
            # 허용되지 않은 필드일 경우 기본값으로 정렬
            queryset = Stock.objects.order_by('-market_cap')

        # 검색어 필터링 (Q 객체로 OR 조건 구현)
        if query:
            queryset = queryset.filter(
                Q(short_name__icontains=query) | Q(code__icontains=query)
            )

        try:
            market_cap_min = self.request.GET.get('market_cap_min')
            if market_cap_min:
                queryset = queryset.filter(market_cap__gte=int(market_cap_min))
            
            market_cap_max = self.request.GET.get('market_cap_max')
            if market_cap_max:
                queryset = queryset.filter(market_cap__lte=int(market_cap_max))
        except (ValueError, TypeError):
            pass # 숫자가 아닌 값이 들어오면 무시

        # PER
        try:
            per_min = self.request.GET.get('per_min')
            if per_min:
                queryset = queryset.filter(trailing_pe__gte=float(per_min))
            
            per_max = self.request.GET.get('per_max')
            if per_max:
                queryset = queryset.filter(trailing_pe__lte=float(per_max))
        except (ValueError, TypeError):
            pass

        # PBR
        try:
            pbr_min = self.request.GET.get('pbr_min')
            if pbr_min:
                queryset = queryset.filter(price_to_book__gte=float(pbr_min))
            
            pbr_max = self.request.GET.get('pbr_max')
            if pbr_max:
                queryset = queryset.filter(price_to_book__lte=float(pbr_max))
        except (ValueError, TypeError):
            pass

        # eps
        try:
            eps_min = self.request.GET.get('eps_min')
            if eps_min:
                queryset = queryset.filter(trailing_eps__gte=float(eps_min))
            
            eps_max = self.request.GET.get('eps_max')
            if eps_max:
                queryset = queryset.filter(trailing_eps__lte=float(eps_max))
        except (ValueError, TypeError):
            pass

        # 배당수익률
        try:
            dividend_yield_min = self.request.GET.get('dividend_yield_min')
            if dividend_yield_min:
                queryset = queryset.filter(dividend_yield__gte=float(dividend_yield_min))
            
            dividend_yield_max = self.request.GET.get('dividend_yield_max')
            if dividend_yield_max:
                queryset = queryset.filter(dividend_yield__lte=float(dividend_yield_max))
        except (ValueError, TypeError):
            pass

        # 1. 페이지네이션 객체 생성
        paginator = Paginator(queryset, 20)  # 한 페이지에 20개씩 표시
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        # 2. 커스텀 페이지네이션 로직 추가
        page_block_size = 5  # 한 번에 보여줄 페이지 번호 개수
        current_page = page_obj.number
        total_pages = paginator.num_pages
        
        # 현재 페이지가 속한 블록의 시작과 끝 페이지 계산
        start_block = math.floor((current_page - 1) / page_block_size) * page_block_size
        start_page = start_block + 1
        end_page = min(start_block + page_block_size, total_pages)

        # 5페이지씩 건너뛰기(점프)할 페이지 번호 계산
        jump_prev_page = start_block - page_block_size + 1 if start_block > 0 else None
        jump_next_page = start_block + page_block_size + 1 if end_page < total_pages else None
        

        # 3. 템플릿에 전달할 context
        context = {
            'page_obj': page_obj,
            'request': self.request,
            'custom_page_range': range(start_page, end_page + 1),
            'jump_prev_page': jump_prev_page,
            'jump_next_page': jump_next_page,
            'current_sort': sort_by, # 현재 정렬 기준을 템플릿에 전달
            'current_order': order,   # 현재 정렬 순서를 템플릿에 전달
        }
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if request.htmx:
            return render(request, self.partial_template_name, context)
        return render(request, self.full_template_name, context)

class DashboardPageView(View):
    template_name = 'core/home.html'

    def get_context_data(self, **kwargs):
        dashboard = get_object_or_404(Dashboard, key='main_dashboard')
        context = dashboard.data.copy()

        if 'heatmap' in context:
            # 1. 히트맵 데이터 가공 (이전과 동일)
            #    여기서는 전체 데이터를 JSON으로 변환합니다.
            sectors_data_dict = self._prepare_heatmap_data_dict(context['heatmap'])
            drilldown_data = self._prepare_drilldown_heatmap_data(context['heatmap'])
            context['heatmap_data_json'] = json.dumps(drilldown_data)

            # 2. 드롭다운용 섹터 목록 추가
            #    가공된 데이터의 키(섹터 이름)들만 추출하여 리스트로 만듭니다.
            context['sector_list'] = list(sectors_data_dict.keys())
        
        return context

    def _prepare_heatmap_data_dict(self, raw_heatmap_data):
        """
        데이터를 섹터 이름(key)과 Highcharts 시리즈 객체(value)의 딕셔너리 형태로 가공합니다.
        (이전의 리스트 형태에서 딕셔너리 형태로 변경)
        """
        sectors = {}
        for stock in raw_heatmap_data:
            sector_name = stock.get("sector")
            if not sector_name: continue

            if sector_name not in sectors:
                sectors[sector_name] = {
                    "id": sector_name, # ID를 섹터 이름으로 단순화
                    "name": sector_name,
                    "data": []
                }
            
            sectors[sector_name]["data"].append({
                "name": stock.get("code"),
                "value": stock.get("market_cap", 0),
                "colorValue": stock.get("change_percent", 0)
            })
        
        return sectors

    def _prepare_drilldown_heatmap_data(self, raw_heatmap_data):
        """
        Highcharts 드릴다운 트리맵 형식에 맞는 데이터를 생성합니다.
        (섹터 정보와 종목 정보를 한 리스트에 담음)
        """
        processed_data = []
        sectors = set() # 중복된 섹터 추가를 방지하기 위해 set 사용

        # 1. 종목 데이터를 먼저 추가
        for stock in raw_heatmap_data:
            sector_name = stock.get("sector")
            if not sector_name: continue

            # 나중에 섹터 정보를 추가하기 위해 이름 저장
            sectors.add(sector_name)
            
            processed_data.append({
                "Symbol": stock.get("code"),
                "Name": stock.get("short_name"),
                "Industry": stock.get("industry"),
                "Sector": stock.get("sector"),
                "Price": stock.get("current_price"),
                "percent_change": stock.get('change_percent', 0), # 부모가 누구인지 명시
                "Market Cap": stock.get("market_cap", 0),
            })

        return processed_data

    def get(self, request, *args, **kwargs):
        context_data = self.get_context_data()
        return render(request, self.template_name, context_data)


def profile(request):
    """프로필 페이지"""
    context = {
        'page_title': 'Profile'
    }
    return render(request, 'core/profile.html', context)

def watchlist(request):
    """관심종목 페이지"""
    context = {
        'page_title': 'Watchlist',
        'watchlist_stocks': [
            {'symbol': 'TSLA', 'name': 'Tesla', 'price': 361.23, 'change': 36.32},
            {'symbol': 'AAPL', 'name': 'Apple', 'price': 185.92, 'change': -2.15},
            {'symbol': 'MSFT', 'name': 'Microsoft', 'price': 412.78, 'change': 8.43},
            {'symbol': 'GOOGL', 'name': 'Alphabet', 'price': 142.56, 'change': 3.21},
        ]
    }
    return render(request, 'core/watchlist.html', context)



class KpiApiView(View):
    
    # --- 1. 필요한 재무 항목의 standard_key 목록 정의 ---
    # 이 목록을 클래스 변수로 빼두면 재사용 및 관리가 용이합니다.
    REQUIRED_KEYS = [
        'total_revenue', 'gross_profit', 'operating_income', 'net_income',
        'total_assets', 'total_liabilities_net_minority_interest', 'stockholders_equity',
        'current_assets', 'current_liabilities',
        'interest_expense', 'operating_expense',
        # 더 필요한 항목이 있다면 여기에 추가
    ]

    def get(self, request, *args, **kwargs):
        stock_code = kwargs.get('stock_code')
        stock = get_object_or_404(Stock, code=stock_code)
        
        # --- 2. 최근 5개년 연간(Annual) 재무 데이터 조회 ---
        # 5년치 데이터를 가져오기 위해 6년 전 데이터부터 조회 (성장률 계산을 위해)
        statements = FinancialStatement.objects.filter(
            stock=stock,
            period_type='A',
            item__standard_key__in=self.REQUIRED_KEYS
        ).select_related('item').order_by('-date')[:6 * len(self.REQUIRED_KEYS)] # 넉넉하게 조회

        if not statements:
            return JsonResponse({'error': 'Financial data not found'}, status=404)

        # --- 3. 데이터를 pandas를 이용해 연도별 딕셔너리로 재구성 ---
        df = pd.DataFrame(list(statements.values('date', 'value', 'item__standard_key')))
        # pivot을 사용하여 각 날짜(연도)를 컬럼으로, 항목을 인덱스로 만듦
        try:
            pivot_df = df.pivot_table(
                index='item__standard_key', 
                columns='date', 
                values='value',
                aggfunc='last' # 중복 발생 시 마지막 값을 사용 (또는 'mean')
            )
        except Exception as e:
            # pivot_table도 실패하는 예외적인 경우를 대비한 로깅
            print(f"Error pivoting data for {stock_code}: {e}")
            return JsonResponse({'error': 'Data processing error'}, status=500)

        # 최신 5개년 데이터만 사용하도록 슬라이싱
        pivot_df = pivot_df.reindex(sorted(pivot_df.columns, reverse=True), axis=1).iloc[:, :5]

        # --- 4. KPI 계산 ---
        # defaultdict를 사용하면 키가 없을 때 에러 없이 빈 딕셔너리를 반환
        kpis = defaultdict(dict)

        # 각 연도(컬럼)를 순회하며 KPI 계산
        for year_date in pivot_df.columns:
            year_str = str(year_date.year)
            series = pivot_df[year_date] # 해당 연도의 데이터 시리즈

            # 수익성 (Profitability)
            kpis['profitability'][year_str] = self.calculate_profitability(series)
            
            # 안정성 (Stability)
            kpis['stability'][year_str] = self.calculate_stability(series)

        # 성장성 (Growth) - 연도별 비교가 필요하므로 별도 계산
        kpis['growth'] = self.calculate_growth(pivot_df)

        def nan_to_none(obj):
            if isinstance(obj, dict):
                return {k: nan_to_none(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [nan_to_none(elem) for elem in obj]
            # pandas/numpy의 NaN은 float 타입일 수 있음
            elif isinstance(obj, float) and np.isnan(obj):
                return None
            return obj

        # kpis 딕셔너리에 재귀 함수 적용
        cleaned_kpis = nan_to_none(kpis)

        return JsonResponse(cleaned_kpis)


    # --- 5. KPI 계산을 위한 헬퍼 메서드들 ---
    
    def calculate_profitability(self, series):
        """특정 연도의 데이터(series)를 받아 수익성 지표를 계산"""
        total_revenue = series.get('total_revenue')
        gross_profit = series.get('gross_profit')
        operating_income = series.get('operating_income')
        net_income = series.get('net_income')
        equity = series.get('stockholders_equity')
        assets = series.get('total_assets')

        # 'total_revenue'가 0이거나 None이면 계산 불가
        if not total_revenue:
            return {}

        return {
            'gross_margin': (gross_profit / total_revenue) * 100 if gross_profit is not None else None,
            'operating_margin': (operating_income / total_revenue) * 100 if operating_income is not None else None,
            'net_profit_margin': (net_income / total_revenue) * 100 if net_income is not None else None,
            'roe': (net_income / equity) * 100 if net_income is not None and equity else None,
            'roa': (net_income / assets) * 100 if net_income is not None and assets else None,
        }

    def calculate_stability(self, series):
        """특정 연도의 데이터(series)를 받아 안정성 지표를 계산"""
        total_liabilities = series.get('total_liabilities_net_minority_interest')
        equity = series.get('stockholders_equity')
        current_assets = series.get('current_assets')
        current_liabilities = series.get('current_liabilities')
        
        return {
            'debt_to_equity': (total_liabilities / equity) * 100 if total_liabilities is not None and equity else None,
            'current_ratio': (current_assets / current_liabilities) if current_assets is not None and current_liabilities else None,
        }

    def calculate_growth(self, df):
        """전체 기간 데이터(DataFrame)를 받아 성장률 지표를 계산"""
        growth_kpis = defaultdict(dict)
        # pct_change()는 이전 기간 대비 변화율을 쉽게 계산해줌. axis=1은 행(가로) 방향으로 계산
        growth_df = df.T.sort_index().pct_change().T * 100 

        for year_date in growth_df.columns:
            year_str = str(year_date.year)
            series = growth_df[year_date]
            growth_kpis[year_str] = {
                'revenue_growth_yoy': series.get('total_revenue'),
                'operating_income_growth_yoy': series.get('operating_income'),
                'net_income_growth_yoy': series.get('net_income'),
            }
        return growth_kpis


class ChartView(View):
    def get(self, request, stock_code):
        """
        Provides the data for the chart for a specific stock.
        """
        try:
            # Use the stock_code from the URL to get the correct stock
            stock = get_object_or_404(Stock, code=stock_code)
            period = self.request.GET.get('period', '1y').lower()
            
            end_date = date.today()
            start_date = None
            
            if period == '5d':
                start_date = end_date - timedelta(days=7)
            elif period == '1m':
                start_date = end_date - timedelta(days=31)
            elif period == '6m':
                start_date = end_date - timedelta(days=180)
            elif period == '1y':
                start_date = end_date - timedelta(days=365)
            elif period == '10y':
                start_date = end_date - timedelta(days=365 * 10)
            elif period == 'max':
                start_date = end_date - timedelta(days=365 * 50)

            # Filter the price history for that stock
            price_history = StockPriceHistory.objects.filter(stock=stock, date__gte=start_date).order_by('date')
            # Format the data for the charting library
            data = []
            for record in price_history:
                timestamp = int(time.mktime(record.date.timetuple())) * 1000
                data.append({
                    'timestamp': timestamp,
                    'open': float(record.open_price),
                    'high': float(record.high_price),
                    'low': float(record.low_price),
                    'close': float(record.close_price),
                    'volume': record.volume
                })
            return JsonResponse(data, safe=False)
        except Stock.DoesNotExist:
            return JsonResponse({"error": f"Stock with code '{stock_code}' not found."}, status=4404)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)