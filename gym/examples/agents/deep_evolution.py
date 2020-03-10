import numpy as np
from gym import gym
from collections import deque

import ray

ray.init()

env = gym.make('SPY-Daily-v0')

CONFIG = {
    'env': env,
    # removing time frame, stocks owned and cash in hand
    'state_size': env.state_dim - 3,
    'time_frame': 30,
    'sigma': 0.1,
    'learning_rate': 0.03,
    'population_size': 15
}

def get_state_as_change_percentage(state, next_state):
    open = (next_state[2] - state[2]) / next_state[2]
    high = (next_state[3] - state[3]) / next_state[3]
    low = (next_state[4] - state[4]) / next_state[4]
    close = (next_state[5] - state[5]) / next_state[5]
    volume = (next_state[6] - state[6]) / next_state[6]
    return [open, high, low, close, volume]

@ray.remote
def reward_function(weights):
    time_frame = CONFIG['time_frame']
    state_size = CONFIG['state_size']
    model = Model(time_frame * state_size, 500, 3)
    model.set_weights(weights)
    agent = Agent(model,state_size, time_frame)
    _,_,_,reward = run_agent(agent)
    print('reward: ',reward)
    return reward
    

def run_agent(agent):
    env = CONFIG['env']
    state = env.reset()
    # Removed time element from state
    state = np.delete(state, 2)

    next_state, reward, done, info = env.step([0,0])
    if len(next_state) > agent.state_size:
        next_state = np.delete(next_state, 2)
    state_as_percentages = get_state_as_change_percentage(state,next_state)
    state = next_state

    done = False
    states_buy = []
    states_sell = []
    closes = []

    i = 0
    while not done:
        closes.append(state[5])
        action = agent.act(state_as_percentages)
        print(action)
        next_state, reward, done, info = env.step(action)
        if len(next_state) > agent.state_size:
            next_state = np.delete(next_state, 2)
        if action[0] == 1 and state[1] > next_state[2]:
            states_buy.append(i)
        if action[0] == 2 and state[0] > 0:
            states_sell.append(i)
        state_as_percentages = get_state_as_change_percentage(state, next_state)
        state = next_state
        i+=1
    return closes, states_buy, states_sell, info['cur_val']

class Deep_Evolution_Strategy:
    def __init__(self, weights):
        self.weights = weights
        self.population_size = CONFIG['population_size']
        self.sigma = CONFIG['sigma']
        self.learning_rate = CONFIG['learning_rate']
    
    def _get_weight_from_population(self,weights, population):
        weights_population = []
        for index, i in enumerate(population):
            jittered = self.sigma * i
            weights_population.append(weights[index] + jittered)
        return weights_population
    
    def get_weights(self):
        return self.weights

    def train(self,epoch = 100, print_every=1):
        for i in range(epoch):
            population = []
            rewards = np.zeros(self.population_size)
            for k in range(self.population_size):
                x = []
                for w in self.weights:
                    x.append(np.random.randn(*w.shape))
                population.append(x)
            
            # for k in range(self.population_size):
            #     weights_population = self._get_weight_from_population(self.weights, population[k])
            #     rewards[k] = reward_function(weights_population)
            
            futures = [reward_function.remote(self._get_weight_from_population(self.weights,population[k])) for k in range(self.population_size)]

            rewards = ray.get(futures)
            
            rewards = (rewards - np.mean(rewards)) / np.std(rewards)
            for index, w in enumerate(self.weights):
                A = np.array([p[index] for p in population])
                self.weights[index] = (
                    w + self.learning_rate / (self.population_size * self.sigma) * np.dot(A.T, rewards).T
                )
            
            if (i + 1) % print_every == 0:
                print('iter: {}. standard reward: {}'.format(i+1,ray.get(reward_function.remote((self.weights)))))

class Agent:
    def __init__(self, model, state_size, time_frame):
        self.model = model
        self.time_frame = time_frame
        self.state_size = state_size
        self.state_fifo = deque(maxlen=self.time_frame)
        self.max_shares_to_trade_at_once = 100
        self.des = Deep_Evolution_Strategy(self.model.get_weights())
    
    def act(self,state):
        self.state_fifo.append(state)
        # do nothing for the first time frames until we can start the prediction
        if len(self.state_fifo) < self.time_frame:
            return np.zeros(2)
        
        state = np.array(list(self.state_fifo))
        state = np.reshape(state,(self.state_size*self.time_frame,1))
        #print(state)
        decision, buy = self.model.predict(state.T)
        # print('decision: ', decision)
        # print('buy: ', buy)

        return [np.argmax(decision[0]), int(buy[0])]
    
    def fit(self, iterations, checkpoint):
        self.des.train(iterations, print_every = checkpoint)

class Model:
    def __init__(self, input_size, layer_size, output_size):
        self.weights = [
            np.random.randn(input_size, layer_size),
            np.random.randn(layer_size, output_size),
            np.random.randn(layer_size, 1),
            np.random.randn(1, layer_size)
        ]
        #print('weights shape: ',len(self.weights))
    
    def predict(self, inputs):
        feed = np.dot(inputs, self.weights[0]) + self.weights[-1]
        #print('feed shape: ',feed.shape)
        #print('weights shape: ',len(self.weights))
        decision = np.dot(feed, self.weights[1])
        buy = np.dot(feed, self.weights[2])
        return decision, buy
    
    def get_weights(self):
        return self.weights
    
    def set_weights(self, weights):
        self.weights = weights

if __name__ == '__main__':

    time_frame = CONFIG['time_frame']
    state_size = CONFIG['state_size']
    model = Model(time_frame * state_size, 500, 3)
    agent = Agent(model,state_size, time_frame)
    agent.fit(iterations=500, checkpoint=10)