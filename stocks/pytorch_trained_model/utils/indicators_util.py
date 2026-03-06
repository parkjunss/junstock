import numpy as np
import pandas as pd
from stock_indicators import indicators
from stock_indicators.indicators.common.quote import Quote
# --- 6. 데이터 준비 및 기술적 지표 추가 함수 ---
# --- Function to add indicators using stock-indicators ---
def add_technical_indicators(dataframe_orig, 
                             sma_periods=[5, 30, 60], # SMA 기간 리스트
                             ema_periods=[5, 30, 60],  # EMA 기간 리스트
                             rsi_periods=[14, 30],    # RSI 기간 리스트
                             mfi_periods=[14, 30],
                             macd_fast=5, macd_slow=60, macd_signal=30, # MACD 기본값
                             adx_period=14,           # ADX 기본값
                             atr_period=14,           # ATR 기본값
                             cmo_period=14,           # CMO 기본값
                             bb_period=20, bb_std_dev=2, # Bollinger Bands 기본값
                             stoch_k_period=14, stoch_d_period=3, stoch_slowing=3 # Stochastic 기본값
                            ):
    dataframe = dataframe_orig.copy()

    # --- 1. 날짜 인덱스 처리 및 중복 제거 ---
    if isinstance(dataframe.index, pd.DatetimeIndex):
        dataframe.index = pd.to_datetime(dataframe.index.strftime('%Y-%m-%d'))
    elif 'Date' in dataframe.columns:
        try:
            dataframe['Date'] = pd.to_datetime(dataframe['Date']).dt.normalize()
            dataframe.set_index('Date', inplace=True)
        except Exception as e:
            print(f"Error setting Date index from 'Date' column: {e}")
            return pd.DataFrame()
    elif dataframe.index.name and ('Date' in dataframe.index.name or 'date' in dataframe.index.name.lower()):
        try:
            dataframe.index = pd.to_datetime(dataframe.index).normalize()
        except Exception as e:
            print(f"Error converting existing index to DatetimeIndex: {e}")
            return pd.DataFrame()
    else:
        print("Warning: Date information not found. Cannot proceed.")
        return pd.DataFrame()


    # --- 2. Quote 객체 리스트 생성 ---
    quotes_list = []
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not all(col in dataframe.columns for col in required_cols):
        missing_cols = [col for col in required_cols if col not in dataframe.columns]
        print(f"Error: Missing required columns for stock_indicators: {missing_cols}")
        return pd.DataFrame()

    for date_idx, row in dataframe.iterrows():
        quotes_list.append(
            Quote(date=date_idx, open=row['Open'], high=row['High'], 
                  low=row['Low'], close=row['Close'], volume=row['Volume'])
        )
    
    if not quotes_list:
        print("Warning: No quote data to process for indicators.")
        return pd.DataFrame()

    # # --- 3. 비율(Ratio) 지표 추가 ---
    # # 0으로 나누는 오류 방지를 위해 분모에 작은 값(epsilon) 추가 또는 조건 처리
    # epsilon = 1e-9 
    # # Open 대비 비율
    # dataframe['O/H_Ratio'] = dataframe['Open'] / (dataframe['High'] + epsilon)
    # dataframe['O/L_Ratio'] = dataframe['Open'] / (dataframe['Low'] + epsilon) # Low가 0이 될 수 있으므로 주의
    # dataframe['O/C_Ratio'] = dataframe['Open'] / (dataframe['Close'] + epsilon)
    # dataframe['O/V_Ratio'] = dataframe['Open'] / (dataframe['Volume'] + epsilon) # Volume이 0이 될 수 있으므로 주의

    # # Close 대비 비율 (선택적)
    # dataframe['C/H_Ratio'] = dataframe['Close'] / (dataframe['High'] + epsilon)
    # dataframe['C/L_Ratio'] = dataframe['Close'] / (dataframe['Low'] + epsilon)
    # dataframe['C/O_Ratio'] = dataframe['Close'] / (dataframe['Open'] + epsilon)
    # dataframe['C/V_Ratio'] = dataframe['Close'] / (dataframe['Volume'] + epsilon) # Volume이 0이 될 수 있으므로 주의

    # # High/Low 범위 (선택적)
    # dataframe['H/L_Ratio'] = dataframe['High'] / (dataframe['Low'] + epsilon)
    # dataframe['H/O_Ratio'] = dataframe['High'] / (dataframe['Open'] + epsilon)
    # dataframe['H/C_Ratio'] = dataframe['High'] / (dataframe['Close'] + epsilon)
    # dataframe['H/V_Ratio'] = dataframe['High'] / (dataframe['Volume'] + epsilon) # Volume이 0이 될 수 있으므로 주의

    # # High/Low 범위 (선택적)
    # dataframe['L/H_Ratio'] = dataframe['Low'] / (dataframe['High'] + epsilon)
    # dataframe['L/O_Ratio'] = dataframe['Low'] / (dataframe['Open'] + epsilon)
    # dataframe['L/C_Ratio'] = dataframe['Low'] / (dataframe['Close'] + epsilon)
    # dataframe['L/V_Ratio'] = dataframe['Low'] / (dataframe['Volume'] + epsilon) # Volume이 0이 될 수 있으므로 주의

    # --- 4. 기술적 지표 추가 (stock-indicators 사용) ---
    # 내부 헬퍼 함수: 지표 결과를 DataFrame에 추가
    def _add_indicator_to_df(df, indicator_results, value_attr_name, col_name_prefix):
        if indicator_results:
            # 결과에서 날짜와 값을 추출하여 Series 생성
            dates = [res.date.strftime('%Y-%m-%d') for res in indicator_results if getattr(res, value_attr_name, None) is not None]
            values = [getattr(res, value_attr_name) for res in indicator_results if getattr(res, value_attr_name, None) is not None]
            if dates and values:
                df[col_name_prefix] = pd.Series(values, index=pd.to_datetime(dates)).reindex(dataframe.index)

        return df

    # 기간별 SMA 추가
    for period in sma_periods:
        sma_results = indicators.get_sma(quotes_list, lookback_periods=period)
        dataframe = _add_indicator_to_df(dataframe, sma_results, 'sma', f'SMA{period}')

    # 기간별 EMA 추가
    for period in ema_periods:
        ema_results = indicators.get_ema(quotes_list, lookback_periods=period)
        dataframe = _add_indicator_to_df(dataframe, ema_results, 'ema', f'EMA{period}')

    # 기간별 RSI 추가
    for period in rsi_periods:
        rsi_results = indicators.get_rsi(quotes_list, lookback_periods=period)
        dataframe = _add_indicator_to_df(dataframe, rsi_results, 'rsi', f'RSI{period}')

    for period in mfi_periods:
        mfi_results = indicators.get_mfi(quotes_list, lookback_periods=period)
        dataframe = _add_indicator_to_df(dataframe, mfi_results, 'mfi	', f'MFI{period}')

    # MACD
    macd_results = indicators.get_macd(quotes_list, macd_fast, macd_slow, macd_signal)
    if macd_results:
        dataframe = _add_indicator_to_df(dataframe, macd_results, 'macd', 'MACD')
        dataframe = _add_indicator_to_df(dataframe, macd_results, 'signal', 'MACD_Signal')
        dataframe = _add_indicator_to_df(dataframe, macd_results, 'histogram', 'MACD_Hist')

    # ADX
    adx_results = indicators.get_adx(quotes_list, adx_period)
    if adx_results:
        dataframe = _add_indicator_to_df(dataframe, adx_results, 'adx', 'ADX')
        dataframe = _add_indicator_to_df(dataframe, adx_results, 'pdi', 'DMI_Plus') # +DI
        dataframe = _add_indicator_to_df(dataframe, adx_results, 'mdi', 'DMI_Minus')# -DI

    # ATR
    atr_results = indicators.get_atr(quotes_list, atr_period)
    dataframe = _add_indicator_to_df(dataframe, atr_results, 'atr', f'ATR{atr_period}')
    
    # CMO
    cmo_results = indicators.get_cmo(quotes_list, cmo_period)
    dataframe = _add_indicator_to_df(dataframe, cmo_results, 'cmo', f'CMO{cmo_period}')

    # OBV 
    obv_results = indicators.get_obv(quotes_list)
    dataframe = _add_indicator_to_df(dataframe, obv_results, 'obv', f'OBV')

    don_results = indicators.get_donchian(quotes_list, 20)
    if don_results:
        dataframe = _add_indicator_to_df(dataframe, don_results, 'upper_band', f'DON_CHAIN_upper')
        dataframe = _add_indicator_to_df(dataframe, don_results, 'center_line', f'DON_CHAIN_center_line')
        dataframe = _add_indicator_to_df(dataframe, don_results, 'lower_band', f'DON_CHAIN_lower')
        dataframe = _add_indicator_to_df(dataframe, don_results, 'width', f'DON_CHAIN_width')

    # Bollinger Bands
    bb_results = indicators.get_bollinger_bands(quotes_list, bb_period, bb_std_dev)
    if bb_results:
        dataframe = _add_indicator_to_df(dataframe, bb_results, 'sma', f'BB_SMA{bb_period}')
        dataframe = _add_indicator_to_df(dataframe, bb_results, 'upper_band', f'BB_UPPER{bb_period}')
        dataframe = _add_indicator_to_df(dataframe, bb_results, 'lower_band', f'BB_LOWER{bb_period}')
        dataframe = _add_indicator_to_df(dataframe, bb_results, 'percent_b', f'BB_PERCENT_B{bb_period}')
        # dataframe = _add_indicator_to_df(dataframe, bb_results, 'z_score', f'BB_Z_SCORE{bb_period}') # Z-score는 종종 NaN 많음
        dataframe = _add_indicator_to_df(dataframe, bb_results, 'width', f'BB_WIDTH{bb_period}')

    # Stochastic Oscillator
    stoch_results = indicators.get_stoch(quotes_list, stoch_k_period, stoch_d_period, stoch_slowing)
    if stoch_results:
        dataframe = _add_indicator_to_df(dataframe, stoch_results, 'k', f'STOCH_K{stoch_k_period}') # Oscillator (%K)
        dataframe = _add_indicator_to_df(dataframe, stoch_results, 'd', f'STOCH_D{stoch_d_period}') # Signal (%D)

    # --- 5. 최종 처리 ---
    # 초기 불안정 구간 (모든 지표가 계산되기 시작하는 시점)을 결정하기 위해 사용된 모든 lookback 기간 고려
    all_lookbacks = sma_periods + ema_periods + rsi_periods + \
                    [macd_slow, adx_period, atr_period, cmo_period, bb_period, stoch_k_period + stoch_slowing -1] # Stoch는 계산이 좀 더 복잡
    
    # 가장 긴 lookback 기간 찾기 (MACD의 경우 slow period + signal period를 고려해야 할 수도 있지만, 여기서는 단순화)
    # Stoch의 경우 K를 구하고 D를 구하는 과정에서 lookback이 누적됨
    # (정확한 계산은 각 지표별로 다르므로, 여기서는 대략적인 최대값을 사용하거나,
    #  안전하게 충분히 큰 값을 설정하는 것이 좋음)
    # 예시: 모든 지표가 안정화되려면 대략 (가장 긴 lookback + 몇 일의 여유)가 필요할 수 있음.
    # 여기서는 주어진 모든 기간 값 중 최대값을 사용
    overall_longest_lookback = 0
    if all_lookbacks:
        overall_longest_lookback = max(all_lookbacks)
    dataframe.dropna(inplace=True)
    # print("DataFrame index after dropna:", dataframe.index)

    if dataframe.empty:
        print("Warning: DataFrame became empty after calculating all indicators and dropping NaNs.")

    print(dataframe.head())
    return dataframe

# (선택적) 이 파일이 직접 실행될 때를 위한 테스트 코드 (예시)
if __name__ == '__main__':
    # 간단한 테스트용 DataFrame 생성

    import yfinance as yf

    ticker = "AAPL"
    stock = yf.Ticker(ticker)
    data = stock.history(period='5y', interval="1d")
    print(data.tail())
    print("--- Testing add_technical_indicators ---")
    df_with_indicators = add_technical_indicators(data.copy()) # 테스트를 위해 기간 단순화
    print(df_with_indicators.head())
    print(df_with_indicators.info())