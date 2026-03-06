import yfinance as yf
import os
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
# data_utils.py
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler # 추가
import pickle
import os
from .indicators_util import add_technical_indicators # 만약 indicators_util.py에 있다면


def get_stock_data_by_date(ticker, interval="1d", start=None, end=None, period="10y"):
    print(f"Fetching data for {ticker}...")
    stock = yf.Ticker(ticker)
    
    # yfinance는 start, end가 있으면 period를 무시하지 않고 오류를 발생시키므로, start, end가 명시적으로 주어지면 period를 None으로 설정
    if start and end:
        period = None
        
    stock_data = stock.history(period=period, interval=interval, start=start, end=end)
    if interval == "1d":
        stock_data.index = pd.to_datetime(stock_data.index.strftime('%Y-%m-%d'))

        vix_stock = yf.Ticker('^VIX')
        vix_stock_data = vix_stock.history(period=period, interval=interval, start=start, end=end)
        vix_stock_data.index = pd.to_datetime(vix_stock_data.index.strftime('%Y-%m-%d'))

        snp_stock = yf.Ticker('^GSPC')
        snp_stock_data = snp_stock.history(period=period, interval=interval, start=start, end=end)
        snp_stock_data.index = pd.to_datetime(snp_stock_data.index.strftime('%Y-%m-%d'))

        tlt_stock = yf.Ticker('TLT')
        tlt_stock_data = tlt_stock.history(period=period, interval=interval, start=start, end=end)
        tlt_stock_data.index = pd.to_datetime(tlt_stock_data.index.strftime('%Y-%m-%d'))

        coca_stock = yf.Ticker('KO')
        coca_stock_data = coca_stock.history(period=period, interval=interval, start=start, end=end)
        coca_stock_data.index = pd.to_datetime(coca_stock_data.index.strftime('%Y-%m-%d'))
    
    # # stock_data['log_close'] = np.log(stock_data['Close'])
    # stock_data['Vix'] = vix_stock_data['Close']
    # stock_data['Snp'] = snp_stock_data['Close']
    # stock_data['Tlt'] = tlt_stock_data['Close']
    # stock_data['Ko'] = coca_stock_data['Close']
    vix_close = vix_stock_data[['Close']].rename(columns={'Close': 'Vix'})
    snp_close = snp_stock_data[['Close']].rename(columns={'Close': 'Snp'})
    tlt_close = tlt_stock_data[['Close']].rename(columns={'Close': 'Tlt'})

    merged_data = stock_data.join(vix_close, how='left')
    merged_data = merged_data.join(snp_close, how='left')
    merged_data = merged_data.join(tlt_close, how='left')
    merged_data = merged_data.drop(['Capital Gains'], axis=1, errors='ignore')

    # # 3. 병합 후 발생할 수 있는 결측치(NaN) 처리
    # #    ffill()은 이전 날짜의 값으로 채우는 방법으로, 시계열 데이터에 적합
    # merged_data.fillna(method='ffill', inplace=True)
    # # 그럼에도 불구하고 맨 처음에 NaN이 남을 수 있으므로, bfill()로 한번 더 처리하거나 dropna()
    # merged_data.fillna(method='bfill', inplace=True)
    # print(merged_data.columns)
        
    if merged_data.empty:
        print(f"No data found for {ticker}.")
        return None
    # yfinance는 Date를 인덱스로 반환
    return merged_data

def save_episode_trades_to_csv(episode_data, ticker, episode_num, save_dir):
    if not episode_data:
        print(f"  Episode {episode_num}: No trade data to save.")
        return
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    episode_df = pd.DataFrame(episode_data)
    csv_filename = os.path.join(save_dir, f"episode_{episode_num}_trades_{ticker}.csv")
    episode_df.to_csv(csv_filename, index=False)
    # print(f"  Trade data for episode {episode_num} saved to {csv_filename}") # 필요시 주석 해제

def render_episode_trades(episode_data, initial_balance, ticker, episode_num, save_dir_prefix):
    if not episode_data:
        print(f"  Episode {episode_num}: No data to render chart.")
        return
    
    save_dir, base_filename = os.path.split(save_dir_prefix)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    df_episode = pd.DataFrame(episode_data)
    if df_episode.empty:
        print(f"Episode {episode_num}: DataFrame is empty, cannot render.")
        return

    fig, axes = plt.subplots(4, 1, figsize=(15, 12), sharex=True)
    fig.suptitle(f"Trading Activity - {ticker} - Episode {episode_num}", fontsize=16)

    # 1. Price and Trades
    axes[0].plot(df_episode['step'], df_episode['price'], label='Price', color='skyblue', linewidth=2)
    buy_points = df_episode[df_episode['action_type'] == "Buy"]
    sell_points = df_episode[df_episode['action_type'] == "Sell"]
    if not buy_points.empty:
        axes[0].scatter(buy_points['step'], buy_points['price'], marker='^', color='green', label='Buy', s=100, alpha=0.8, edgecolors='k')
    if not sell_points.empty:
        axes[0].scatter(sell_points['step'], sell_points['price'], marker='v', color='red', label='Sell', s=100, alpha=0.8, edgecolors='k')
    axes[0].set_ylabel("Price")
    axes[0].legend()
    axes[0].grid(True, linestyle='--', alpha=0.7)

    # 2. Portfolio Value
    axes[1].plot(df_episode['step'], df_episode['portfolio_value_after_trade'], label='Portfolio Value', color='orange', linewidth=2)
    axes[1].axhline(y=initial_balance, color='r', linestyle='--', label=f'Initial Balance ({initial_balance})')
    axes[1].set_ylabel("Portfolio Value")
    axes[1].legend()
    axes[1].grid(True, linestyle='--', alpha=0.7)

    # 3. Shares Held
    axes[2].plot(df_episode['step'], df_episode['shares_held_after_trade'], label='Shares Held', color='purple', linewidth=2, drawstyle='steps-post')
    axes[2].set_ylabel("Shares Held")
    axes[2].legend()
    axes[2].grid(True, linestyle='--', alpha=0.7)
    
    # 4. Action Ratio
    axes[3].plot(df_episode['step'], df_episode['action_ratio'], label='Action Ratio (-1 to 1)', color='brown', alpha=0.7, drawstyle='steps-post')
    axes[3].axhline(y=0, color='k', linestyle=':', linewidth=0.8)
    axes[3].set_ylabel("Action Ratio")
    axes[3].set_xlabel("Step")
    axes[3].legend()
    axes[3].grid(True, linestyle='--', alpha=0.7)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    
    render_filename = f"{save_dir_prefix}_episode_{episode_num}_render.png"
    plt.savefig(render_filename)
    # print(f"  Rendered chart for episode {episode_num} saved to {render_filename}") # 필요시 주석 해제
    plt.close(fig)

def plot_training_summary(episode_rewards, episode_portfolio_values, 
                          episode_critic_losses, episode_actor_losses, episode_alpha_values, # 손실 및 알파 값 리스트 추가
                          initial_balance, ticker, save_path):
    num_plots = 5 # 총 그래프 수
    plt.figure(figsize=(15, num_plots * 4)) # 세로 길이 조절

    plt.subplot(num_plots, 1, 1)
    plt.plot(episode_rewards)
    plt.title(f"{ticker} - Episode Cumulative Rewards")
    plt.xlabel("Episode")
    plt.ylabel("Cumulative Reward")
    plt.grid(True)

    plt.subplot(num_plots, 1, 2)
    plt.plot(episode_portfolio_values)
    plt.title(f"{ticker} - Episode Final Portfolio Value")
    plt.xlabel("Episode")
    plt.ylabel("Portfolio Value")
    plt.axhline(y=initial_balance, color='r', linestyle='--', label=f'Initial Balance ({initial_balance})')
    plt.legend()
    plt.grid(True)

    plt.subplot(num_plots, 1, 3)
    plt.plot(episode_critic_losses, label='Critic Loss', color='orange')
    plt.title(f"{ticker} - Average Critic Loss per Episode")
    plt.xlabel("Episode")
    plt.ylabel("Loss")
    plt.legend()
    plt.grid(True)

    plt.subplot(num_plots, 1, 4)
    plt.plot(episode_actor_losses, label='Actor Loss', color='green')
    plt.title(f"{ticker} - Average Actor Loss per Episode")
    plt.xlabel("Episode")
    plt.ylabel("Loss")
    plt.legend()
    plt.grid(True)

    plt.subplot(num_plots, 1, 5)
    plt.plot(episode_alpha_values, label='Alpha Value', color='purple') # Alpha Loss 대신 Alpha 값 자체를 플롯
    plt.title(f"{ticker} - Alpha Value per Episode")
    plt.xlabel("Episode")
    plt.ylabel("Alpha")
    plt.legend()
    plt.grid(True)

    plt.tight_layout()
    plt.savefig(save_path)
    print(f"Extended training summary plot saved to {save_path}")
    plt.close()




# 여기에 get_stock_data_by_date, add_technical_indicators 함수 정의 또는 import

def load_and_preprocess_data_for_window(ticker, start_date, end_date, scaler_obj, feature_columns, indicator_params, is_training_window=True, existing_scaler_path=None):
    """ 특정 윈도우 기간의 데이터를 로드, 지표 추가, 스케일링합니다. """
    raw_df = get_stock_data_by_date(ticker, start_date, end_date)
    if raw_df is None or raw_df.empty:
        return None, None, None # scaled_df, unscaled_df, scaler

    processed_df_unscaled = add_technical_indicators(raw_df.copy(), **indicator_params)
    if processed_df_unscaled.empty or processed_df_unscaled.isnull().values.any():
        return None, None, None

    # 스케일러 처리
    current_scaler = None
    if is_training_window: # 훈련 윈도우면 스케일러 새로 fit 또는 로드
        if existing_scaler_path and os.path.exists(existing_scaler_path): # 티커별 고정 스케일러
            with open(existing_scaler_path, 'rb') as f:
                current_scaler = pickle.load(f)
            print(f"  Loaded existing scaler for window from {existing_scaler_path}")
            scaled_values = current_scaler.transform(processed_df_unscaled[feature_columns])
        else: # 롤링/확장 윈도우의 첫 훈련이거나, 고정 스케일러가 없을 때
            if config.SCALER_TYPE == "MinMaxScaler":
                current_scaler = MinMaxScaler(feature_range=config.MINMAX_SCALER_RANGE)
            elif config.SCALER_TYPE == "RobustScaler":
                current_scaler = RobustScaler()
            else: # StandardScaler 기본
                current_scaler = StandardScaler()
            
            scaled_values = current_scaler.fit_transform(processed_df_unscaled[feature_columns])
            if existing_scaler_path: # 티커별 고정 스케일러 경로가 있다면 저장
                 with open(existing_scaler_path, 'wb') as f:
                    pickle.dump(current_scaler, f)
                 print(f"  New scaler for window created and saved to {existing_scaler_path}")
    else: # 검증/테스트 윈도우면 전달받은 scaler_obj 사용
        if scaler_obj is None:
            print("  Error: Scaler object is None for non-training window.")
            return None, None, None
        current_scaler = scaler_obj
        try:
            processed_df_to_scale = processed_df_unscaled[feature_columns] # 컬럼 순서 맞추기
            scaled_values = current_scaler.transform(processed_df_to_scale)
        except KeyError as e:
            print(f"  KeyError during scaling non-training window: {e}. Columns might not match.")
            return None, None, None
        except ValueError as e: # fit 안 된 스케일러로 transform 시도 등
            print(f"  ValueError during scaling non-training window: {e}")
            return None, None, None


    processed_df_scaled = pd.DataFrame(scaled_values, columns=feature_columns, index=processed_df_unscaled.index)
    return processed_df_scaled, processed_df_unscaled[feature_columns], current_scaler