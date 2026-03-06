import torch
import numpy as np
import pandas as pd
import os
import pickle

# --- 이 부분은 실제 파일 구조에 맞게 수정해야 합니다 ---
from utils.indicators_util import add_technical_indicators
from utils.data_utils import get_stock_data_by_date
from src.StockTradingEnv import StockTradingEnv
from src.Agents import SACAgent

# ==============================================================================
#                                  설정 (CONFIGURATION)
# ==============================================================================
# 이 부분만 원하는 대로 수정하시면 됩니다.
TICKER_TO_PREDICT = "NVDA"  # 예측할 대상 티커
MODEL_TICKER = "NVDA"       # 훈련에 사용했던 모델의 티커

BASE_LOG_DIR = "pytorch_trained_model/sac_ticker_specific_logs"
BEST_MODEL_SUBDIR = "best_model" # best 모델이 저장된 하위 폴더 이름

# 훈련 시 사용했던 윈도우 크기
WINDOW_SIZE = 50

# 시그널 해석 임계값
ACTION_THRESHOLDS = {
    "strong_buy": 0.6,
    "buy": 0.2,
    "strong_sell": -0.6,
    "sell": -0.2
}
# ==============================================================================

def main():
    """메인 예측 로직을 실행하는 함수"""
    try:
        # --- 1. 경로 설정 ---
        model_path = os.path.join(BASE_LOG_DIR, BEST_MODEL_SUBDIR, MODEL_TICKER)
        scaler_path = os.path.join(model_path, f"{MODEL_TICKER}_best_scaler.pkl")

        if not os.path.exists(model_path) or not os.path.exists(scaler_path):
            raise FileNotFoundError(f"모델 또는 스케일러 경로를 찾을 수 없습니다: {model_path}")
        
        print(f"--- 로딩 경로 설정 완료 ---")
        print(f"  - 모델 경로: {model_path}")
        print(f"  - 스케일러 경로: {scaler_path}")
        
        # --- 2. 데이터 준비 및 상태 벡터 생성 ---
        print(f"\n--- 최신 데이터로 상태 벡터 생성 ({TICKER_TO_PREDICT}) ---")

        # 2-1. 스케일러 먼저 로드
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        
        # 2-2. 충분한 양의 최신 데이터 가져오기
        required_data_points = WINDOW_SIZE + 180 # 기술적 지표 계산을 위한 여유분
        latest_data_raw = get_stock_data_by_date(TICKER_TO_PREDICT, period=f"{required_data_points}d")
        
        if latest_data_raw is None or len(latest_data_raw) < required_data_points:
             raise ValueError(f"상태 생성을 위한 데이터가 충분하지 않습니다.")

        # 2-3. 불필요한 컬럼 제거 (안전장치)
        latest_data_raw = latest_data_raw.drop(columns=['Capital Gains'], errors='ignore')

        # 2-4. 기술적 지표 추가
        data_with_indicators = add_technical_indicators(latest_data_raw.copy())
        
        # 2-5. 결측치 제거
        data_with_indicators.dropna(inplace=True)
        if len(data_with_indicators) < WINDOW_SIZE:
            raise ValueError("결측치 제거 후 데이터가 윈도우 크기보다 작습니다.")

        # 2-6. 가장 최근 window_size 만큼의 데이터 선택
        latest_window_data = data_with_indicators.tail(WINDOW_SIZE)
        
        prediction_base_date = latest_window_data.index[-1]
        
        # 2-7. 로드된 스케일러로 데이터 변환
        scaled_values = scaler.transform(latest_window_data)
        
        # ==============================================================================
        # ✨ 수정된 부분: (50, 38) 배열 전체를 펼치는 대신, 마지막 날의 데이터만 선택
        # ==============================================================================
        # 기존 코드: current_state = scaled_values.flatten() -> shape (1900,)
        current_state = scaled_values[-1] # -> shape (38,)
        
        print(f"✅ 최신 상태 벡터 생성 성공 (Shape: {current_state.shape})")

        # --- 3. 에이전트 초기화 및 모델 로드 ---
        print("\n--- 에이전트 초기화 및 모델 로드 ---")
        
        # 임시 환경은 실제 컬럼 이름을 가진 데이터프레임으로 생성해야 함
        # state 생성 방식이 바뀌었으므로 임시 환경의 데이터도 단일 행으로 구성 가능
        temp_df = pd.DataFrame([current_state], columns=latest_window_data.columns)
        temp_env = StockTradingEnv(temp_df)
        
        agent = SACAgent(temp_env)
        
        model_loaded = agent.load_models(model_path, model_type="best")
        if not model_loaded:
            raise FileNotFoundError("모델 로드에 실패했습니다.")
            
        print("✅ 최고 성능 모델 로드 성공")
        
        # --- 4. 예측 수행 ---
        action_array = agent.predict(current_state) # predict 메서드는 내부적으로 eval() 모드 사용
        action_ratio = action_array[0]

        # --- 5. 결과 해석 및 출력 ---
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

        print("\n" + "="*50)
        print("          AI 트레이딩 어시스턴트 분석 결과")
        print("="*50)
        print(f"  - 분석 대상 티커: {TICKER_TO_PREDICT}")
        print(f"  - 사용된 모델: {MODEL_TICKER} 훈련 모델")
        print(f"  - 예측 기준 날짜: {prediction_base_date.strftime('%Y-%m-%d')} (이 날짜 종가 기준)")
        print(f"  - 분석 실행 시간: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 50)
        print(f"  - 예측된 행동 비율 (Action Ratio): {action_ratio:.4f}")
        print(f"  - 최종 트레이딩 시그널: {signal}")
        print("="*50)
        print("\n*주의: 이 결과는 과거 데이터 기반의 확률적 예측이며, 실제 수익을 보장하지 않습니다.")
        print("*해석: 위 시그널은 예측 기준 날짜의 장 마감 정보를 바탕으로 다음 거래일에 취할 행동을 제안합니다.")

    except (FileNotFoundError, ValueError, Exception) as e:
        print(f"\n❌ 스크립트 실행 중 오류가 발생했습니다: {e}")


if __name__ == "__main__":
    main()