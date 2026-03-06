import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
from collections import deque
from ..utils.data_utils import render_episode_trades

# --- 1. Stock Trading Environment (SAC에 맞게 수정 가정) ---
class StockTradingEnv(gym.Env):
    def __init__(self, df, initial_balance=10000, transaction_cost_pct=0.001,
                 # --- Reward Hyperparameters ---
                 reward_scaling_factor=1.0,
                 volatility_penalty_weight=0.1,
                 mdd_target=0.15,
                 mdd_penalty_weight=0.2,
                 # --- New Reward Hyperparameters for requested changes ---
                 successful_trade_bonus=0.05, # 수익 실현(매도) 시 추가 보상
                 mdd_threshold=0.30, # 강력한 페널티가 부과되는 MDD 임계값 (30%)
                 strong_mdd_penalty=0.5): # MDD 임계값 초과 시 가해지는 강력한 페널티
        super(StockTradingEnv, self).__init__()
        self.df = df
        # --- Optimization: Convert DataFrame to NumPy array ---
        self.df_numpy = self.df.to_numpy()
        try:
            self.close_price_index = self.df.columns.get_loc('Close')
        except KeyError:
            print("Error: 'Close' column not found in DataFrame.")
            raise

        self.initial_balance = initial_balance
        self.transaction_cost_pct = transaction_cost_pct

        # --- Reward Shaping Parameters ---
        self.reward_scaling_factor = reward_scaling_factor
        self.volatility_penalty_weight = volatility_penalty_weight
        self.mdd_target = mdd_target
        self.mdd_penalty_weight = mdd_penalty_weight
        self.volatility_lookback_period = 20
        self.step_returns_history = deque(maxlen=self.volatility_lookback_period)
        
        # New parameters from user request
        self.successful_trade_bonus = successful_trade_bonus
        self.mdd_threshold = mdd_threshold
        self.strong_mdd_penalty = strong_mdd_penalty


        # 행동 공간: -1 (최대 매도) ~ +1 (최대 매수) 사이의 투자 비율
        self.action_space = spaces.Box(low=-1, high=1, shape=(1,), dtype=np.float32)

        # 관찰 공간: DataFrame의 컬럼 수
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(len(df.columns),), dtype=np.float32
        )

        # --- 보상 함수 하이퍼파라미터 ---
        # 이 값들은 외부 설정 파일에서 받는 것이 좋습니다.
        self.sharpe_reward_weight = 1.5  # 샤프 지수 개선 보상의 가중치
        self.unrealized_pnl_reward_weight = 1.0 # 미실현 손익 보상의 가중치
        self.transaction_penalty_weight = 1.0 # 거래 비용 페널티 가중치 (기존 수수료와 별개로 행동 제어용)
        self.mdd_penalty_weight = 2.0  # MDD 페널티 가중치

        # --- 상태 추적 변수 ---
        self.previous_sharpe_ratio = 0.0
        self.average_buy_price = 0.0 # 미실현 손익 계산을 위한 평균 매수 단가

        self.reset()

    def reset(self):
        self.balance = self.initial_balance
        self.shares_held = 0
        self.current_step = 0
        self.portfolio_value_history = [self.initial_balance] # 포트폴리오 가치 기록
        self.last_portfolio_value = self.initial_balance # 이전 스텝의 포트폴리오 가치를 저장할 변수
        self.episode_peak_value = self.initial_balance # 에피소드 내 최고 포트폴리오 가치

        self.episode_data = [] # 거래 내역 기록
        self.step_returns_history.clear() # 수익률 기록 초기화
        return self._get_state()

    def _get_state(self):
        return self.df_numpy[self.current_step].astype(np.float32)

    def _calculate_current_portfolio_value(self): # 이름 변경으로 명확화
        if self.current_step >= len(self.df_numpy):
             last_valid_price = self.df_numpy[len(self.df_numpy) - 1, self.close_price_index]
             return self.balance + self.shares_held * last_valid_price
        current_price = self.df_numpy[self.current_step, self.close_price_index]
        return self.balance + self.shares_held * current_price


    def step(self, action_ratio_input):
        action_ratio_scalar = float(action_ratio_input[0])
        previous_portfolio_value_for_reward = self.last_portfolio_value
        current_price = self.df_numpy[self.current_step, self.close_price_index]

        transaction_cost = 0
        shares_traded = 0
        action_type = "Hold"

        MIN_ACTION_THRESHOLD = 0.01
        MAX_INVESTMENT_RATIO_PER_STEP = 0.5
        MAX_SELL_RATIO_PER_STEP = 1.0

        if current_price > 0 and abs(action_ratio_scalar) > MIN_ACTION_THRESHOLD:
            if action_ratio_scalar > 0 and self.balance > 0: # --- 매수 로직 ---
                effective_buy_ratio = min(action_ratio_scalar, MAX_INVESTMENT_RATIO_PER_STEP)
                amount_to_invest = self.balance * effective_buy_ratio
                shares_to_buy_potential = int(amount_to_invest // current_price)
                if shares_to_buy_potential > 0:
                    total_required_cost = (shares_to_buy_potential * current_price) * (1 + self.transaction_cost_pct)
                    if self.balance >= total_required_cost:
                        # --- 평균 매수 단가 업데이트 (중요) ---
                        total_investment_before = self.shares_held * self.average_buy_price
                        total_investment_after = total_investment_before + (shares_to_buy_potential * current_price)
                        
                        self.balance -= total_required_cost
                        self.shares_held += shares_to_buy_potential
                        
                        self.average_buy_price = total_investment_after / self.shares_held if self.shares_held > 0 else 0
                        
                        transaction_cost = total_required_cost - (shares_to_buy_potential * current_price)
                        shares_traded = shares_to_buy_potential
                        action_type = "Buy"

            elif action_ratio_scalar < 0 and self.shares_held > 0: # --- 매도 로직 ---
                effective_sell_ratio = min(abs(action_ratio_scalar), MAX_SELL_RATIO_PER_STEP)
                shares_to_sell_potential = int(self.shares_held * effective_sell_ratio)
                if shares_to_sell_potential > 0:
                    proceeds_before_fee = shares_to_sell_potential * current_price
                    estimated_transaction_cost = proceeds_before_fee * self.transaction_cost_pct
                    self.balance += proceeds_before_fee - estimated_transaction_cost
                    self.shares_held -= shares_to_sell_potential
                    
                    # --- 모든 주식 매도 시 평균 매수 단가 초기화 (중요) ---
                    if self.shares_held == 0:
                        self.average_buy_price = 0.0

                    transaction_cost = estimated_transaction_cost
                    shares_traded = -shares_to_sell_potential
                    action_type = "Sell"

        current_portfolio_value_after_trade = self._calculate_current_portfolio_value()
        self.portfolio_value_history.append(current_portfolio_value_after_trade)
        self.episode_peak_value = max(self.episode_peak_value, current_portfolio_value_after_trade)

        # 스텝별 수익률 기록 (샤프 지수 계산용)
        step_return = (current_portfolio_value_after_trade / previous_portfolio_value_for_reward) - 1 if previous_portfolio_value_for_reward > 0 else 0
        self.step_returns_history.append(step_return)

        # --- 새로운 보상 함수 호출 ---
        final_reward, reward_components = self._calculate_reward(
            previous_portfolio_value_for_reward,
            current_portfolio_value_after_trade,
            transaction_cost
        )

        self.current_step += 1
        done = self.current_step >= len(self.df_numpy) - 1
        next_state = self._get_state() if not done else np.zeros_like(self.observation_space.sample())
        self.last_portfolio_value = current_portfolio_value_after_trade

        # 로깅을 위해 reward_components를 info 딕셔너리에 추가
        info = {
            'step': self.current_step - 1,
            'price': current_price,
            'action_type': action_type,
            'action_ratio': action_ratio_scalar,
            'shares_traded': shares_traded,
            'shares_held_after_trade': self.shares_held,
            'balance_after_trade': self.balance,
            'portfolio_value_before_trade': previous_portfolio_value_for_reward,
            'portfolio_value_after_trade': current_portfolio_value_after_trade,
            'reward': final_reward,
            'transaction_cost': transaction_cost
        }
        info.update(reward_components) # 보상 구성요소들을 info에 추가
        self.episode_data.append(info)

        return next_state, final_reward, done, {} # info를 반환하려면 gym 표준을 따라야 함

    def _calculate_reward(self, previous_value, current_value, transaction_cost_in_step):
        """(수정) 스케일과 가중치를 조정한 보상 함수."""
        
        reward_components = {
            'portfolio_growth_reward': 0.0,
            'sharpe_improvement_reward': 0.0,
            'unrealized_pnl_reward': 0.0,
            'mdd_penalty': 0.0,
            'transaction_penalty': 0.0
        }

        # --- 1. 포트폴리오 성장 보상 (스케일 조정) ---
        # 기본 보상 스케일을 높여 긍정적 신호를 더 강조합니다.
        reward_scaling_factor = 100.0 # 예: 1% 수익이면 +1점 보상
        if previous_value > 0:
            # 로그 수익률 대신 간단한 % 수익률 사용 (해석이 더 직관적)
            simple_return = (current_value / previous_value) - 1
            reward_components['portfolio_growth_reward'] = simple_return * reward_scaling_factor

        # --- 2. 샤프 지수 개선 보상 (스케일 조정) ---
        # 샤프 지수 값 자체가 크지 않으므로 가중치를 적절히 조절
        sharpe_reward_weight = 0.5 # 이전보다 낮춤
        if len(self.step_returns_history) > 10:
            current_sharpe_ratio = self.calculate_sharpe_ratio() 
            sharpe_improvement = current_sharpe_ratio - self.previous_sharpe_ratio
            # 샤프 지수가 개선되었을 때만 보상을 주어 신호를 명확하게 함
            if sharpe_improvement > 0:
                reward_components['sharpe_improvement_reward'] = sharpe_improvement * sharpe_reward_weight
            self.previous_sharpe_ratio = current_sharpe_ratio 

        # --- 3. 미실현 손익 보상 (스케일 조정) ---
        unrealized_pnl_reward_weight = 0.5 # 낮춤
        if self.shares_held > 0 and self.average_buy_price > 0:
            current_price = self.df_numpy[self.current_step, self.close_price_index]
            unrealized_pnl_ratio = (current_price / self.average_buy_price) - 1
            if unrealized_pnl_ratio > 0:
                # 제곱근을 사용하여 수익이 커질수록 보상 증가폭이 완만해지도록 함
                reward_components['unrealized_pnl_reward'] = np.sqrt(unrealized_pnl_ratio) * unrealized_pnl_reward_weight

        # --- 4. MDD 페널티 (매우 부드럽게 수정) ---
        mdd_penalty_weight = 0.1 # 대폭 낮춤
        current_drawdown = (self.episode_peak_value - current_value) / self.episode_peak_value if self.episode_peak_value > 0 else 0
        # MDD 자체를 페널티로 사용하되, 가중치를 낮춰 충격을 완화
        reward_components['mdd_penalty'] = -current_drawdown * mdd_penalty_weight

        # --- 5. 거래 행위 페널티 (작고 고정된 값) ---
        # 거래를 막기보다 신중하게 만들 정도의 작은 페널티
        if transaction_cost_in_step > 0:
            reward_components['transaction_penalty'] = -0.01
            
        # --- 최종 보상 계산 ---
        final_reward = sum(reward_components.values())
        
        return final_reward, reward_components

    def render(self, mode='human', file_path_prefix=None, episode_num=None):
        pass # Implementation not shown for brevity

    def get_portfolio_returns(self):
        if len(self.portfolio_value_history) < 2:
            return pd.Series(dtype=float)
        portfolio_values = pd.Series(self.portfolio_value_history)
        returns = portfolio_values.pct_change().dropna()
        return returns

    def calculate_sharpe_ratio(self, risk_free_rate=0.0, periods_per_year=252):
        portfolio_returns = self.get_portfolio_returns()
        if len(portfolio_returns) < 2:
            return 0.0
        excess_returns = portfolio_returns - (risk_free_rate / periods_per_year)
        mean_excess_return = np.mean(excess_returns)
        std_dev_excess_return = np.std(excess_returns)
        if std_dev_excess_return == 0:
            return 0.0
        annual_sharpe_ratio = mean_excess_return / std_dev_excess_return * np.sqrt(periods_per_year)
        return annual_sharpe_ratio

    def calculate_mdd(self):
        if len(self.portfolio_value_history) < 2:
            return 0.0
        portfolio_values = pd.Series(self.portfolio_value_history)
        cumulative_max = portfolio_values.cummax()
        drawdown = (cumulative_max - portfolio_values) / (cumulative_max.replace(0, np.nan) + 1e-9)
        drawdown = drawdown.fillna(0)
        max_drawdown = drawdown.max()
        return max_drawdown
