import pandas as pd
import os
import pickle
from django.conf import settings

# --- ✨ 가장 중요한 부분 ✨ ---
# sac_predictor.py와 같은 레벨에 있는 src, utils 디렉토리에서 import
from .utils.indicators_util import add_technical_indicators
from .src.StockTradingEnv import StockTradingEnv
from .src.Agents import SACAgent
# -----------------------------

from stocks.models import Stock, PredictionLog
from django.utils.dateparse import parse_date
import logging

logger = logging.getLogger(__name__)


# ==============================================================================
#                                  설정 (CONSTANTS)
# ==============================================================================
# 함수 외부에서 상수로 관리
# BASE_LOG_DIR = "pytorch_trained_model/sac_ticker_specific_logs"
BASE_LOG_DIR = os.path.join(settings.BASE_DIR, "stocks", "pytorch_trained_model", "sac_ticker_specific_logs")
BEST_MODEL_SUBDIR = "best_model"
WINDOW_SIZE = 50
ACTION_THRESHOLDS = {
    "strong_buy": 0.8,
    "buy": 0.4,
    "strong_sell": -0.8,
    "sell": -0.4
}
# ==============================================================================

def get_trading_signal_from_sac(ticker_to_predict: str, model_ticker: str) -> dict:
    import torch
    import numpy as np
    from .utils.data_utils import get_stock_data_by_date
    """
    지정된 티커에 대해 훈련된 SAC 모델을 사용하여 트레이딩 시그널을 예측합니다.

    Args:
        ticker_to_predict (str): 예측할 대상 티커 (예: "NVDA")
        model_ticker (str): 사용할 모델의 티커 (예: "NVDA")

    Returns:
        dict: 예측 결과. 성공 시 {'signal': str, 'ratio': float, 'date': str, 'error': None},
              실패 시 {'signal': '오류', 'ratio': None, 'date': None, 'error': str}
    """
    try:
        # --- 1. 경로 설정 ---
        model_path = os.path.join(BASE_LOG_DIR, BEST_MODEL_SUBDIR, model_ticker)
        scaler_path = os.path.join(model_path, f"{model_ticker}_best_scaler.pkl")
        # --- ⬇️ 디버깅 코드 추가 ⬇️ ---
        print("="*60)
        print(f"DEBUG: Checking for paths...")
        print(f"  - BASE_LOG_DIR: {BASE_LOG_DIR}")
        print(f"  - Calculated model_path: {model_path}")
        print(f"  - Calculated scaler_path: {scaler_path}")
        print(f"  - Does model_path exist? -> {os.path.exists(model_path)}")
        print(f"  - Does scaler_path exist? -> {os.path.exists(scaler_path)}")
        print("="*60)
        # --- ⬆️ 디버깅 코드 추가 ⬆️ ---

        if not os.path.exists(model_path) or not os.path.exists(scaler_path):
            raise FileNotFoundError(f"모델 또는 스케일러를 찾을 수 없습니다: {model_ticker}")

        # --- 2. 데이터 준비 및 상태 벡터 생성 ---
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        
        required_data_points = WINDOW_SIZE + 180
        latest_data_raw = get_stock_data_by_date(ticker_to_predict, period=f"{required_data_points}d")
        
        if latest_data_raw is None or len(latest_data_raw) < required_data_points:
             raise ValueError(f"데이터가 충분하지 않습니다 (필요: {required_data_points}, 확보: {len(latest_data_raw) if latest_data_raw is not None else 0}).")

        latest_data_raw = latest_data_raw.drop(columns=['Capital Gains'], errors='ignore')
        data_with_indicators = add_technical_indicators(latest_data_raw.copy())
        data_with_indicators.dropna(inplace=True)

        if len(data_with_indicators) < WINDOW_SIZE:
            raise ValueError("결측치 제거 후 데이터가 윈도우 크기보다 작습니다.")

        latest_window_data = data_with_indicators.tail(WINDOW_SIZE)
        prediction_base_date = latest_window_data.index[-1]
        
        scaled_values = scaler.transform(latest_window_data)
        current_state = scaled_values[-1]

        # --- 3. 에이전트 초기화 및 모델 로드 ---
        temp_df = pd.DataFrame([current_state], columns=latest_window_data.columns)
        temp_env = StockTradingEnv(temp_df)
        agent = SACAgent(temp_env)
        
        if not agent.load_models(model_path, model_type="best"):
            raise FileNotFoundError("모델 로드에 실패했습니다.")
            
        # --- 4. 예측 수행 ---
        action_array = agent.predict(current_state)
        action_ratio = float(action_array[0]) # float 타입으로 변환

        # --- 5. 결과 해석 ---
        if action_ratio > ACTION_THRESHOLDS["strong_buy"]:
            signal = "🟢 강력 매수 (Strong Buy)"
        elif action_ratio > ACTION_THRESHOLDS["buy"]:
            signal = "🟩 매수 (Buy)"
        elif action_ratio < ACTION_THRESHOLDS["strong_sell"]:
            signal = "🔴 강력 매도 (Strong Sell)"
        elif action_ratio < ACTION_THRESHOLDS["sell"]:
            signal = "🟥 매도 (Sell)"
        else:
            signal = "⚪️ 관망 (Hold)"


        # ✨ 예측 결과를 데이터베이스에 저장하는 로직 추가 ✨
        try:
            stock_obj = Stock.objects.get(code=ticker_to_predict)
            pred_date = parse_date(prediction_base_date.strftime('%Y-%m-%d'))

            # get_or_create: 중복 저장을 방지하고, 없으면 생성, 있으면 가져옴
            log, created = PredictionLog.objects.get_or_create(
                stock=stock_obj,
                prediction_date=pred_date,
                model_name=f"SAC_{model_ticker}",
                defaults={
                    'predicted_signal': signal,
                    'predicted_ratio': action_ratio,
                }
            )

            if not created:
                # 이미 로그가 있다면 업데이트 (예: 재실행 시)
                log.predicted_signal = signal
                log.predicted_ratio = action_ratio
                log.save()
            
            logger.info(f"Successfully logged prediction for {ticker_to_predict} on {pred_date}")

        except Stock.DoesNotExist:
            logger.error(f"Stock with code {ticker_to_predict} not found in DB. Prediction not logged.")
        except Exception as e:
            logger.error(f"Failed to log prediction for {ticker_to_predict}: {e}")

        return {
            "signal": signal,
            "ratio": action_ratio,
            "date": prediction_base_date.strftime('%Y-%m-%d'),
            "error": None
        }


    except Exception as e:
        # 에러 발생 시 명확한 실패 결과를 반환
        return {
            "signal": "오류",
            "ratio": None,
            "date": None,
            "error": str(e)
        }