import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.distributions import Normal
from collections import deque
import random
import copy
import os

# --- 2. Replay Buffer ---
class ReplayBuffer:
    def __init__(self, capacity):
        self.buffer = deque(maxlen=capacity)

    def store_transition(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size):
        batch = random.sample(self.buffer, batch_size)
        state, action, reward, next_state, done = map(np.stack, zip(*batch))
        return state, action, reward, next_state, done

    def __len__(self):
        return len(self.buffer)

# --- 3. Actor Network ---
class Actor(nn.Module):
    def __init__(self, input_dims, action_dims, hidden_dims=(256, 256), log_std_min=-20, log_std_max=2):
        super(Actor, self).__init__()
        self.log_std_min = log_std_min
        self.log_std_max = log_std_max

        self.fc1 = nn.Linear(input_dims, hidden_dims[0])
        self.fc2 = nn.Linear(hidden_dims[0], hidden_dims[1])
        self.mean_layer = nn.Linear(hidden_dims[1], action_dims)
        self.log_std_layer = nn.Linear(hidden_dims[1], action_dims)



    def forward(self, state):
        x = F.relu(self.fc1(state))
        x = F.relu(self.fc2(x))
        mean = self.mean_layer(x)
        log_std = self.log_std_layer(x)
        log_std = torch.clamp(log_std, self.log_std_min, self.log_std_max)
        return mean, log_std

    def sample_action(self, state, reparameterize=True):
        mean, log_std = self.forward(state)
        std = log_std.exp()
        normal = Normal(mean, std)

        if reparameterize:
            action_sample = normal.rsample()
        else:
            action_sample = normal.sample()

        action = torch.tanh(action_sample) # 행동을 [-1, 1] 범위로 스쿼시
        log_prob = normal.log_prob(action_sample)
        log_prob = log_prob - torch.log(torch.clamp(1 - action.pow(2), min=1e-6)) # tanh 변환에 대한 log_prob 조정
        log_prob = log_prob.sum(axis=-1, keepdim=True)

        return action, log_prob

# --- 4. Critic Network (Q-Network) ---
class Critic(nn.Module):
    def __init__(self, input_dims, action_dims, hidden_dims=(256, 256)):
        super(Critic, self).__init__()
        # Q1
        self.fc1_q1 = nn.Linear(input_dims + action_dims, hidden_dims[0])
        self.fc2_q1 = nn.Linear(hidden_dims[0], hidden_dims[1])
        self.fc3_q1 = nn.Linear(hidden_dims[1], 1)
        # Q2
        self.fc1_q2 = nn.Linear(input_dims + action_dims, hidden_dims[0])
        self.fc2_q2 = nn.Linear(hidden_dims[0], hidden_dims[1])
        self.fc3_q2 = nn.Linear(hidden_dims[1], 1)

    def forward(self, state, action):
        sa = torch.cat([state, action], 1)
        q1 = F.relu(self.fc1_q1(sa))
        q1 = F.relu(self.fc2_q1(q1))
        q1 = self.fc3_q1(q1)
        q2 = F.relu(self.fc1_q2(sa))
        q2 = F.relu(self.fc2_q2(q2))
        q2 = self.fc3_q2(q2)
        return q1, q2

# --- 5. SAC Agent ---
class SACAgent:
    def __init__(self, env, actor_lr=1e-4, critic_lr=1e-4, alpha_lr=1e-4,
                 gamma=0.99, tau=0.005, hidden_dims=(256, 256),
                 buffer_capacity=100000, batch_size=256,
                 log_std_min=-20, log_std_max=2, device=None, validation_env=None):
        self.env = env
        self.observation_dim = env.observation_space.shape[0]
        self.action_dim = env.action_space.shape[0]
        # SAC의 액터는 tanh를 통해 [-1,1] 출력을 내므로, 환경의 action_space와 스케일 맞출 필요 없음
        # 환경의 step 함수가 [-1,1] 입력을 해석하도록 설계됨

        self.gamma = gamma
        self.tau = tau
        self.batch_size = batch_size
        self.device = device if device else torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")

        self.actor = Actor(self.observation_dim, self.action_dim, hidden_dims, log_std_min, log_std_max).to(self.device)
        self.critic = Critic(self.observation_dim, self.action_dim, hidden_dims).to(self.device)
        self.critic_target = copy.deepcopy(self.critic)
        self.critic_target.eval()

        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=actor_lr, weight_decay=1e-5) # 예시 값
        self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=critic_lr, weight_decay=1e-5)

        # self.target_entropy = -torch.prod(torch.Tensor(env.action_space.shape).to(self.device)).item()
        self.target_entropy = -1.0 * env.action_space.shape[0] # 수정된 target_entropy (선택적)
        # self.log_alpha = torch.zeros(1, requires_grad=True, device=self.device)
        self.log_alpha = torch.tensor([0.0], requires_grad=True, device=self.device) # 수정된 초기 log_alpha (선택적)
        self.alpha_optimizer = optim.Adam([self.log_alpha], lr=alpha_lr)
        self.alpha = self.log_alpha.exp().item()

        self.replay_buffer = ReplayBuffer(buffer_capacity)

        self.validation_env = validation_env
        self.best_validation_metric = -float('inf') # 예: 샤프 지수 또는 수익률


    def select_action(self, state, evaluate=False):
        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        if evaluate:
            mean, _ = self.actor(state_tensor)
            action_tensor = torch.tanh(mean) # 평균 행동 사용
        else:
            action_tensor, _ = self.actor.sample_action(state_tensor, reparameterize=False)
        # return action_tensor.cpu().detach().numpy() # shape (1, action_dim) -> step에서 [0]으로 추출
        return action_tensor.cpu().detach().flatten().numpy() # 또는 .squeeze().numpy()


    def store_experience(self, state, action, reward, next_state, done):
        self.replay_buffer.store_transition(state, action, reward, next_state, done)

    def _soft_update_target_network(self):
        for target_param, param in zip(self.critic_target.parameters(), self.critic.parameters()):
            target_param.data.copy_(self.tau * param.data + (1.0 - self.tau) * target_param.data)

    def learn(self):
        if len(self.replay_buffer) < self.batch_size:
            return None, None, None

        states, actions, rewards, next_states, dones = self.replay_buffer.sample(self.batch_size)

        states = torch.FloatTensor(states).to(self.device)
        actions = torch.FloatTensor(actions).to(self.device) # action은 이미 (batch_size, action_dim) 형태
        rewards = torch.FloatTensor(rewards).unsqueeze(1).to(self.device)
        next_states = torch.FloatTensor(next_states).to(self.device)
        dones = torch.FloatTensor(dones).unsqueeze(1).to(self.device)

        with torch.no_grad():
            next_actions, next_log_probs = self.actor.sample_action(next_states)
            q1_target_next, q2_target_next = self.critic_target(next_states, next_actions)
            q_target_next = torch.min(q1_target_next, q2_target_next)
            target_q_values = rewards + (1.0 - dones) * self.gamma * (q_target_next - self.alpha * next_log_probs)

        current_q1, current_q2 = self.critic(states, actions)
        critic_loss = F.mse_loss(current_q1, target_q_values) + F.mse_loss(current_q2, target_q_values)

        self.critic_optimizer.zero_grad()
        critic_loss.backward()
        self.critic_optimizer.step()

        new_actions, log_probs = self.actor.sample_action(states)
        q1_new_actions, q2_new_actions = self.critic(states, new_actions)
        q_new_actions = torch.min(q1_new_actions, q2_new_actions)
        actor_loss = (self.alpha * log_probs - q_new_actions).mean()

        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        self.actor_optimizer.step()

        alpha_loss = -(self.log_alpha.exp() * (log_probs + self.target_entropy).detach()).mean()
        self.alpha_optimizer.zero_grad()
        alpha_loss.backward()
        self.alpha_optimizer.step()
        self.alpha = self.log_alpha.exp().item()

        self._soft_update_target_network()
        return critic_loss.item(), actor_loss.item(), alpha_loss.item()

    def predict(self, state):
        """
        주어진 상태에 대해 결정론적인 행동(action_ratio)을 예측합니다.
        모델은 eval 모드여야 합니다.
        """
        self.actor.eval() # 예측 시에는 항상 eval 모드
        # self.critic.eval() # Critic은 예측에 직접 사용되지 않음

        state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        with torch.no_grad(): # 그래디언트 계산 비활성화
            mean, _ = self.actor(state_tensor)
            action_tensor = torch.tanh(mean) # 평균 행동 사용, tanh로 스쿼시

        return action_tensor.cpu().detach().flatten().numpy() # (action_dim,) 형태의 NumPy 배열 반환
    
    def save_best_model(self, current_metric, model_save_dir, model_name_prefix, episode):
        if current_metric > self.best_validation_metric:
            self.best_validation_metric = current_metric
            actor_path = os.path.join(model_save_dir, f"{model_name_prefix}_best_actor.pth")
            critic_path = os.path.join(model_save_dir, f"{model_name_prefix}_best_critic.pth")
            log_alpha_path = os.path.join(model_save_dir, f"{model_name_prefix}_best_log_alpha.pth")
            
            torch.save(self.actor.state_dict(), actor_path)
            torch.save(self.critic.state_dict(), critic_path)
            torch.save(self.log_alpha, log_alpha_path)
            print(f"  New best model saved (Metric: {current_metric:.4f}) at episode {episode} to {model_save_dir}")

    def save_models(self, base_path, model_type="latest", episode=None):
        """ 모델을 지정된 경로에 저장합니다. """
        if not os.path.exists(base_path):
            os.makedirs(base_path)

        # model_type이 "best"인 경우 파일명에 episode 번호를 붙이지 않음
        if model_type == "best":
            file_prefix = "best"
        elif episode is not None:
            file_prefix = f"{episode}_{model_type}"
        else:
            file_prefix = model_type
            
        actor_path = os.path.join(base_path, f"{file_prefix}_actor.pth")
        critic_path = os.path.join(base_path, f"{file_prefix}_critic.pth")
        log_alpha_path = os.path.join(base_path, f"{file_prefix}_log_alpha.pth")
        
        torch.save(self.actor.state_dict(), actor_path)
        torch.save(self.critic.state_dict(), critic_path)
        torch.save(self.log_alpha, log_alpha_path)
        print(f"  Models ({model_type}) saved: \n    {actor_path}\n    {critic_path}\n    {log_alpha_path}")

    def load_models(self, base_path, model_type="best", episode=None):
        """ 지정된 경로에서 모델을 불러옵니다. """
        # episode 번호가 주어지면 해당 번호가 포함된 파일명을 사용
        if episode is not None:
            file_prefix = f"{episode}_{model_type}"
        else:
            file_prefix = model_type

        actor_path = os.path.join(base_path, f"{file_prefix}_actor.pth")
        critic_path = os.path.join(base_path, f"{file_prefix}_critic.pth")
        log_alpha_path = os.path.join(base_path, f"{file_prefix}_log_alpha.pth")

        if not all(os.path.exists(p) for p in [actor_path, critic_path, log_alpha_path]):
            print(f"  No existing {model_type} models found with prefix '{file_prefix}' at {base_path}. Starting from scratch.")
            return False # 모델 로드 실패

        try:
            self.actor.load_state_dict(torch.load(actor_path, map_location=self.device, weights_only=True))
            self.critic.load_state_dict(torch.load(critic_path, map_location=self.device, weights_only=True))

            # 타겟 네트워크도 동기화
            self.critic_target = copy.deepcopy(self.critic)
            self.critic_target.eval()

            # log_alpha는 텐서이므로 그대로 로드 후 값 할당
            loaded_log_alpha = torch.load(log_alpha_path, map_location=self.device)
            if isinstance(loaded_log_alpha, torch.Tensor):
                 self.log_alpha.data.copy_(loaded_log_alpha.data) # 기존 텐서에 값 복사
            else: # 이전 버전에서 단순 float으로 저장했을 경우 (호환성)
                 self.log_alpha = torch.tensor([loaded_log_alpha], requires_grad=True, device=self.device)

            self.alpha = self.log_alpha.exp().item()
            
            # 옵티마이저 상태도 저장하고 불러오면 더 좋지만, 일단은 네트워크 가중치만
            # 만약 학습을 이어서 하려면 옵티마이저 재초기화 또는 상태 로드 필요
            # self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=self.actor_lr) # actor_lr 저장/로드 필요
            # self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=self.critic_lr)
            # self.alpha_optimizer = optim.Adam([self.log_alpha], lr=self.alpha_lr)

            self.actor.train() # 추가 학습을 위해 train 모드로 (evaluate 시에는 eval() 호출)
            self.critic.train()
            print(f"  Models ({model_type}) loaded successfully from {base_path}")
            return True
        except Exception as e:
            print(f"  Error loading {model_type} models from {base_path}: {e}")
            return False

    def save_best_model_on_validation(self, current_metric, model_save_dir_for_ticker, episode):
        """ 검증 성능 기반 최고 모델 저장 """
        if self.validation_env is None: return False # 검증 환경 없으면 실행 안 함

        if current_metric > self.best_validation_metric: # 더 좋은 성능일 때
            print(f"  New best validation metric: {current_metric:.4f} (previously {self.best_validation_metric:.4f})")
            self.best_validation_metric = current_metric
            self.save_models(model_save_dir_for_ticker, model_type="best", episode=episode) # "best" 타입으로 저장
            print(f"  Best model updated at episode {episode}.")
            return True
        return False

    def evaluate_on_validation_set(self, num_eval_episodes=1, risk_free_rate_eval=0.0):
        if self.validation_env is None:
            print("  Validation environment is not set. Skipping validation.")
            return None, None # 메트릭과 에피소드 데이터 모두 None 반환

        all_episode_final_portfolio_values = []
        all_episode_sharpes = []
        all_episode_mdds = []
        all_episode_data_for_validation_runs = [] # 각 실행별 episode_data 리스트를 담을 리스트
        print(f"  Running {num_eval_episodes} validation episodes...")

        for i in range(num_eval_episodes):
            state_eval = self.validation_env.reset() # 여기서 validation_env.episode_data 초기화
            done_eval = False
            # current_eval_episode_data = [] # 현재 평가 에피소드의 데이터를 임시 저장

            while not done_eval:
                action_eval = self.select_action(state_eval, evaluate=False)
                next_state_eval, reward_eval, done_eval, info_eval = self.validation_env.step(action_eval) # info도 받을 수 있음
                # validation_env.episode_data는 step 함수 내에서 채워짐
                # 만약 step 함수가 info에 현재 스텝 데이터를 반환한다면 그것을 사용하거나,
                # validation_env.episode_data의 마지막 항목을 가져올 수 있음.
                # 여기서는 validation_env.episode_data가 step 함수에 의해 직접 채워진다고 가정.
                
                state_eval = next_state_eval
            
            # 평가 에피소드 종료 후 지표 계산
            # validation_env.episode_data는 해당 평가 에피소드의 데이터를 담고 있음
            all_episode_data_for_validation_runs.append(list(self.validation_env.episode_data)) # 깊은 복사로 저장

            all_episode_final_portfolio_values.append(self.validation_env.last_portfolio_value)
            all_episode_sharpes.append(self.validation_env.calculate_sharpe_ratio(risk_free_rate=risk_free_rate_eval))
            all_episode_mdds.append(self.validation_env.calculate_mdd())
            print(f"  Validation Episode {i+1}: Final Portfolio: {self.validation_env.last_portfolio_value:.2f}, "
                  f"Sharpe: {all_episode_sharpes[-1]:.2f}, MDD: {all_episode_mdds[-1]*100:.2f}%")


        avg_final_portfolio = np.mean(all_episode_final_portfolio_values) if all_episode_final_portfolio_values else self.validation_env.initial_balance
        avg_return_rate = avg_final_portfolio / self.validation_env.initial_balance - 1
        avg_sharpe = np.mean(all_episode_sharpes) if all_episode_sharpes else 0.0
        avg_mdd = np.mean(all_episode_mdds) if all_episode_mdds else 0.0

        # 반환할 요약 정보 딕셔너리 생성
        validation_summary_metrics = {
            'avg_return': avg_return_rate,
            'avg_sharpe': avg_sharpe,
            'avg_mdd': avg_mdd,
            'num_eval_episodes': num_eval_episodes # 몇 번 실행한 평균인지도 기록
        }
        
        print(f"  Validation Summary ({num_eval_episodes} episodes): Avg Return: {avg_return_rate*100:.2f}%, "
              f"Avg Sharpe: {avg_sharpe:.2f}, Avg MDD: {avg_mdd*100:.2f}%")
        
        current_metric_for_saving = avg_sharpe 
        
        # 만약 num_eval_episodes가 1이라면, 해당 에피소드의 데이터를 반환
        # 여러 에피소드라면, 마지막 에피소드 데이터 또는 모든 데이터를 리스트로 반환하거나,
        # 대표적인 하나의 에피소드 데이터를 반환하도록 선택 가능.
        # 여기서는 모든 평가 에피소드 데이터를 리스트로 반환.
        return current_metric_for_saving, validation_summary_metrics, all_episode_data_for_validation_runs # 요약 딕셔너리 추가 반환



