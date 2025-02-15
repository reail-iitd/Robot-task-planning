from src.GNN.CONSTANTS import *
from src.GNN.rl_models import *
from src.GNN.dataset_utils import *
import random
import numpy as np
from os import path
from tqdm import tqdm
import approx
import pandas as pd

import torch
import torch.utils.data
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F
from torch.distributions import Categorical

import warnings
warnings.simplefilter("ignore")

# To run:
# python train.py $domain $training_type $model_name

training = argv[2]  
# can be "action"

model_name = argv[3] 
# can be "GGCN", "GGCN_Metric", "GGCN_Metric_Attn", "GGCN_Metric_Attn_L", "GGCN_Metric_Attn_L_NT",
# "GGCN_Metric_Attn_L_NT_C", "GGCN_Metric_Attn_L_NT_C_W", "Final_Metric", "Final_Attn", "Final_L",
# "Final_C", "Final_W"

# Global constants
globalnode = False # can be True or False
split = "world" # can be "random", "world", "tool"
ignoreNoTool = False # can be True or False
sequence = "seq" in training or "action" in training # can be True or False
weighted = ("_W" in model_name) ^ ("Final" in model_name)
graph_seq_length = 4
num_actions = len(possibleActions)
memory_size = 2000
with open('jsons/embeddings/'+embedding+'.vectors') as handle: e = json.load(handle)
avg = lambda a : sum(a)/len(a)
gamma = 0.98

def test_policy(dset, graphs, model, num_objects = 0, verbose = False):
	with open('jsons/embeddings/'+embedding+'.vectors') as handle: e = json.load(handle)
	correct, incorrect, error = 0, 0, 0
	for graph in tqdm(graphs, desc = "Policy Testing", ncols=80):
		goal_num, world_num, tools, g, t = graph
		actionSeq, graphSeq = g
		g = graphSeq[0]; i = 0; aseq = []
		approx.initPolicy(domain, goal_num, world_num)
		while True:
			possible_actions = []
			for action in all_actions: 
				if approx.checkActionPossible(goal_num, action, e): possible_actions.append(action)
			if 'A2C' in model.name:
				probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions))
				a = np.random.choice(possible_actions, p=probs)
			if 'DQN' in model.name:
				if 'Aseq' not in model.name: probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions).detach().numpy())
				else: probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions, aseq).detach().numpy())
				a = possible_actions[probs.index(max(probs))]; aseq.append(a)
			complete, new_g, err = approx.execAction(goal_num, a, e);
			g = new_g; i += 1; print(a)
			if verbose and err != '': print(goal_num, world_num); print(tool_preds); print(actionSeq, err); print('----------')
			if complete:	correct += 1; break
			elif err == '' and i > 30:	incorrect += 1; break
			elif err != '': error += 1; break
	den = correct + incorrect + error
	print ("Correct, Incorrect, Error: ", (correct*100/den), (incorrect*100/den), (error*100/den))
	return (correct*100/den), (incorrect*100/den), (error*100/den)

def test_policy_training(model, init_graphs, all_actions, num_episodes):
	g, goal_num, world_num = init_graphs[np.random.choice(range(len(init_graphs)))]
	approx.initPolicy(domain, goal_num, world_num); correct = 0; aseq = []
	for _ in tqdm(list(range(num_episodes)), desc = 'Testing on train set', ncols=80):
		for i in range(30):
			possible_actions = []
			for action in all_actions: 
				if approx.checkActionPossible(goal_num, action, e): possible_actions.append(action)
			if 'A2C' in model.name:
				probs = model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions)
				m = Categorical(probs); ai = m.sample()
				a = possible_actions[ai.item()]
			if 'DQN' in model.name:
				if 'Aseq' not in model.name: probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions).detach().numpy())
				else: probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions, aseq).detach().numpy())
				a = possible_actions[probs.index(max(probs))]; aseq.append(a)
			complete, new_g, err = approx.execAction(goal_num, a, e);
			g = new_g; 
			if err != '': print(approx.checkActionPossible(goal_num, a, e)); print(a, err)
			if complete: correct += 1; break
			elif err != '': break
	return correct / num_episodes

def get_all_possible_actions():
	actions = []
	for a in ["moveTo", "pick"]:
		for obj in all_objects:
			if obj != 'husky': actions.append({'name': a, 'args':[obj]})
	actions.extend([{'name': i, 'args': ['stool']} for i in ["climbUp", "climbDown"]])
	actions.append({'name': 'clean', 'args': ['dirt']})
	for a in ["dropTo", "pushTo", "pickNplaceAonB"]:
		for obj in all_objects:
			for obj2 in all_objects:
				if obj != 'husky' and obj2 != 'husky': actions.append({'name': a, 'args':[obj, obj2]})
	for obj in ['glue', 'tape']:
		actions.append({'name': 'apply', 'args':[obj, 'paper']})
	actions.append({'name': 'stick', 'args': ['paper', 'walls']})
	for obj in all_objects_with_states:
		if obj != 'light': actions.extend([{'name': 'changeState', 'args':[obj, i]} for i in ['open', 'close']])
	actions.extend([{'name': 'changeState', 'args':['light', i]} for i in ['off']])
	return actions

def load_dataset():
	global TOOLS, NUMTOOLS, globalnode
	filename = ('dataset/'+ domain + '_'+ 
				("global_" if globalnode else '') + 
				("NoTool_" if not ignoreNoTool else '') + 
				("seq_" if sequence else '') + 
				(embedding) +
				str(AUGMENTATION)+'.pkl')
	print(filename)
	if globalnode: etypes.append("Global")
	if path.exists(filename):
		return pickle.load(open(filename,'rb'))
	data = DGLDataset("dataset/" + domain + "/", 
			augmentation=AUGMENTATION, 
			globalNode=globalnode, 
			ignoreNoTool=ignoreNoTool, 
			sequence=sequence,
			embedding=embedding)
	pickle.dump(data, open(filename, "wb"))
	return data

def load_buffer():
	filename = 'dataset/rl_buffer.pkl'
	print(filename)
	if path.exists(filename):
		return pickle.load(open(filename, 'rb'))
	return pd.DataFrame(columns=['goal_num', 'st', 'at', 'p', 'st+1', 'r'])

def save_buffer(replay_buffer):
	filename = 'dataset/rl_buffer.pkl'
	if replay_buffer.shape[0] < 2000: print("Buffer Size =", replay_buffer.shape[0])
	pickle.dump(replay_buffer, open(filename, "wb"))

def world_split(data):
	test_set = []
	train_set = []
	counter = 0
	for i in data.graphs:
		for j in range(1,9):
			if (i[0],i[1]) == (j,j):
				test_set.append(i)
				break
		else:
			counter +=1 
			train_set.append(i)
	return train_set, test_set

def split_data(data):
	train_set, test_set = world_split(data) if split == 'world' else random_split(data)  if split == 'random' else tool_split(data) 
	print ("Size before split was", len(data.graphs))
	print ("The size of the training set is", len(train_set))
	print ("The size of the test set is", len(test_set))
	return train_set, test_set

def form_initial_dataset():
	data = load_dataset()
	filename = 'dataset/rl_dataset.pkl'
	print(filename)
	if path.exists(filename): 
		with open(filename, 'rb') as f:
			df, init_graphs, test_set = pickle.load(f)
		return data, df, init_graphs, test_set
	train_set, test_set = split_data(data)
	df = pd.DataFrame(columns=['goal_num', 'st', 'at', 'aseq', 'p', 'stv', 'st+1', 'r'])
	init_graphs = []
	for datapoint in tqdm(train_set, ncols=80):
		goal_num, world_num, tools, g, t = datapoint
		actionSeq, graphSeq = g; complete = False
		approx.initPolicy(domain, goal_num, world_num)
		old_graph = graphSeq[0]; init_graphs.append((old_graph, goal_num, world_num)); aseq = []
		for action in actionSeq:
			complete, new_graph, err = approx.execAction(goal_num, action, e); 
			if err == '': 
				df = df.append({'goal_num':goal_num, 'st':old_graph, 'at':action, 'aseq':deepcopy(aseq), 'p':1, 'st+1':new_graph, 'r':gamma**len(actionSeq)}, ignore_index=True)
				old_graph = new_graph; aseq.append(action);
	pickle.dump((df, init_graphs, test_set), open(filename, "wb"))
	return data, df, init_graphs, test_set

def run_new_plan(model, init_graphs, all_actions):
	g, goal_num, world_num = init_graphs[np.random.choice(range(len(init_graphs)))]
	approx.initPolicy(domain, goal_num, world_num)
	old_graphs, actions, p, new_graphs, aseq, i = [], [], [], [], [], 0
	while True:
		possible_actions = []
		for action_check in all_actions: 
			if approx.checkActionPossible(goal_num, action_check, e): possible_actions.append(action_check)
		if 'A2C' in model.name:
			probs = model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions)
			m = Categorical(probs); ai = m.sample()
			a = possible_actions[ai.item()]; p.append(probs[ai])
		if 'DQN' in model.name:
			e_prob = np.random.random(); p.append(1); 
			if e_prob < 0.2: a = np.random.choice(possible_actions)
			else: 
				if 'Aseq' not in model.name: probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions).detach().numpy())
				else: probs = list(model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], possible_actions, actions).detach().numpy())
				a = possible_actions[probs.index(max(probs))]
		complete, new_g, err = approx.execAction(goal_num, a, e);
		old_graphs.append(g); actions.append(a); new_graphs.append(new_g); aseq.append(deepcopy(actions));
		g = new_g; i += 1; #print(i, a)
		if err != '': print(approx.checkActionPossible(goal_num, a, e)); print(a, err)
		if complete: r = [gamma**len(old_graphs)]*len(old_graphs); break
		elif i >= 30: r = [0]*len(old_graphs); break
		if err != '': r = [0]*len(old_graphs); break
	return pd.DataFrame({'goal_num':[goal_num]*len(old_graphs), 'st':old_graphs, 'at':actions, 'aseq':aseq, 'p':p, 'st+1':new_graphs, 'r':r}), r[0]

def updateBuffer(model, init_graphs, all_actions, replay_buffer, num_runs):
	dataframes = []; rewards = []
	for run in tqdm(list(range(num_runs)), desc = 'Running episodes', ncols=80):
		plan_df, plan_r = run_new_plan(model, init_graphs, all_actions)
		dataframes.append(plan_df); rewards.append(plan_r)
	replay_buffer = pd.concat([replay_buffer]+dataframes, ignore_index=True)
	if replay_buffer.shape[0] > memory_size: replay_buffer = replay_buffer[-1*memory_size:]
	return replay_buffer, avg(rewards)

def get_training_data(replay_buffer, crowdsource_df, sample_size):
	total_data = pd.concat([replay_buffer, crowdsource_df], ignore_index=True)
	positive_data = total_data[total_data.r > 0].sample(sample_size)
	try: negative_data = total_data[total_data.r == 0].sample(sample_size)
	except: print('Insufficient negative examples'); negative_data = total_data[total_data.r > 0].sample(sample_size)
	return pd.concat([positive_data, negative_data], ignore_index=True)

def get_model(name):
	import src.GNN.rl_models
	model_class = getattr(src.GNN.rl_models, name)
	model = model_class(data.features, data.num_objects, 2 * GRAPH_HIDDEN, 4, 3, etypes, torch.tanh)
	return model

def load_model(filename, model):
	optimizer = torch.optim.Adam(model.parameters(), lr=0.0001, weight_decay=0.00001)
	file_path = MODEL_SAVE_PATH + "/" + filename + ".ckpt"
	if path.exists(file_path):
		print(color.GREEN+"Loading pre-trained model: "+filename+color.ENDC)
		checkpoint = torch.load(file_path)
		model.load_state_dict(checkpoint['model_state_dict'])
		optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
		epoch = checkpoint['epoch']
		accuracy_list = checkpoint['accuracy_list']
	else:
		epoch = -1; accuracy_list = []
		print(color.GREEN+"Creating new model: "+model.name+color.ENDC)
	return model, optimizer, epoch, accuracy_list

def save_model(model, optimizer, epoch, accuracy_list, file_path = None):
	if file_path == None:
		file_path = MODEL_SAVE_PATH + "/" + model.name + "_" + str(epoch) + ".ckpt"
	torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'accuracy_list': accuracy_list}, file_path)

if __name__ == '__main__':
	all_actions = get_all_possible_actions()
	data, crowdsource_df, init_graphs, test_set = form_initial_dataset()
	replay_buffer = load_buffer()
	model = get_model('DQN_Aseq')
	model, optimizer, epoch, accuracy_list = load_model(model.name + "_Trained", model)

	for num_epochs in range(epoch+1, epoch+NUM_EPOCHS+1):
		print("EPOCH ", num_epochs)
		replay_buffer, avg_r = updateBuffer(model, init_graphs, all_actions, replay_buffer, 5 if num_epochs == epoch+1 else 1)
		save_buffer(replay_buffer)
		global_loss = []
		for _ in tqdm(range(100), desc = 'Training', ncols=80):
			val_loss, total_loss, p_loss = [], [], []
			dataset = get_training_data(replay_buffer, crowdsource_df, 50)
			for ind in dataset.index:
				goal_num, g, a, aseq, p, r = dataset['goal_num'][ind], dataset['st'][ind], dataset['at'][ind], dataset['aseq'][ind], dataset['p'][ind], dataset['r'][ind]
				if 'A2C' in model.name:
					pred_val = model.value(g, goal2vec[goal_num], goalObjects2vec[goal_num])
					if p != 1:
						p_loss.append(r * -torch.log(torch.tensor([p], dtype=torch.float)) - (1-r) * torch.log(torch.tensor([1-p], dtype=torch.float)))
					val_loss.append(F.smooth_l1_loss(torch.Tensor([r]), pred_val))
				if 'DQN' in model.name:
					if 'Aseq' not in model.name: pred_val = model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], [a])
					else: pred_val = model.policy(g, goal2vec[goal_num], goalObjects2vec[goal_num], [a], aseq)
					# print(r, pred_val)
					val_loss.append(F.smooth_l1_loss(torch.Tensor([r]), pred_val))
			loss = torch.stack(val_loss).sum()
			if 'A2C' in model.name: loss += torch.stack(p_loss).sum()
			optimizer.zero_grad()
			loss.backward()
			optimizer.step()
			# if 'A2C' in model.name: print("Loss =", loss.item(), " Value Loss =", avg(val_loss).item(), " Policy Loss =", avg(p_loss).item())
			# else: print("Value Loss =", avg(val_loss).item())
			global_loss.append(loss.item())
		print('Avg loss of epoch', avg(global_loss))
		avg_r = test_policy_training(model, init_graphs, all_actions, 5)
		print("Average reward ", avg_r)
		accuracy_list.append((avg_r, avg(global_loss)))
		save_model(model, optimizer, num_epochs, accuracy_list)
	print ("The maximum avg return on train set is ", str(max(accuracy_list)), " at epoch ", accuracy_list.index(max(accuracy_list)))
	test_policy(data, test_set, model, data.num_objects, False)