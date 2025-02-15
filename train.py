from src.GNN.CONSTANTS import *
from src.GNN.models import *
from src.GNN.dataset_utils import *
import random
import numpy as np
from os import path, makedirs
from tqdm import tqdm
from sys import argv
import approx
from statistics import stdev

import torch
import torch.nn as nn

import warnings
warnings.simplefilter("ignore")

# To run:
# python train.py $domain $training_type $model_name $exec_type

training = argv[2]  
# can be "gcn", "gcn_seq", "action"

model_name = argv[3] 
# can be "GGCN", "GGCN_Metric", "GGCN_Metric_Attn", "GGCN_Metric_Attn_L", "GGCN_Metric_Attn_L_NT",
# "GGCN_Metric_Attn_L_NT_C", "GGCN_Metric_Attn_L_NT_C_W", "Final_Metric", "Final_Attn", "Final_L",
# "Final_C", "Final_W"

exec_type = argv[4]
# can be "train", "accuracy", "ablation", "generalization", "policy"

# Global constants
globalnode = False # can be True or False
split = "world" # can be "random", "world", "tool"
ignoreNoTool = False # can be True or False
sequence = "seq" in training or "action" in training # can be True or False
weighted = ("_W" in model_name) ^ ("Final" in model_name)
graph_seq_length = 4
num_actions = len(possibleActions)

def load_dataset():
	global TOOLS, NUMTOOLS, globalnode
	if not path.exists(MODEL_SAVE_PATH): makedirs(MODEL_SAVE_PATH)
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

def gen_score(model, testData, verbose = False):
	total_correct = 0
	testcases = (9 if domain == 'home' else 8)
	correct_list = [0] * testcases; total_list = [0] * testcases
	for graph in testData.graphs:
		goal_num, _, test_num, tools, g, tool_vec, _ = graph
		tool_vec = torch.Tensor(tool_vec)
		y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
		y_pred = list(y_pred.reshape(-1))
		if domain == 'home':
			if test_num == 4 and (("Final" in model.name and "_L" in model.name) 
				or ("Final" not in model.name and "_L" not in model.name)): y_pred[TOOLS.index("box")] = 0 
			if test_num == 4 and (("Final" in model.name and "_L" in model.name) 
				or ("Final" not in model.name and "_L" not in model.name)): y_pred[TOOLS.index("stool")] = 0 
			if test_num == 1 and (("Final" in model.name and "_C" not in model.name) 
				or ("Final" not in model.name and "_C" in model.name)): y_pred[-1] = 0
			if test_num == 3 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("mop")] = 0
			if test_num == 5 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("glue")] = 0
			if test_num == 8 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("box")] = 0
			if test_num == 9 and (("Final" in model.name and "_C" not in model.name) 
				or ("Final" not in model.name and "_C" in model.name)): y_pred[-1] = 0
		else:
			if test_num == 1 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("blow_dryer")] = 0
			if test_num == 2 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("brick")] = 0
			if test_num == 5 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("glue")] = 0
			if test_num == 6 and (("Final" in model.name and "_L" not in model.name) 
				or ("Final" not in model.name and "_L" in model.name)): y_pred[TOOLS.index("toolbox")] = 0 
		tool_predicted = TOOLS[y_pred.index(max(y_pred))]
		if tool_predicted in tools: total_correct += 1; correct_list[test_num-1] += 1
		elif verbose:
			print(test_num, goal_num, tool_predicted, tools)
		total_list[test_num-1] += 1
	for i in range(testcases): correct_list[i] = correct_list[i] * 100 / total_list[i]
	print(correct_list)
	return total_correct * 100.0 / len(testData.graphs)

def grammatical_action(action):
	if (action["name"] in ["pushTo", "pickNplaceAonB", "dropTo", "apply", "stick"]):
		if (len(action["args"]) != 2):
			return False
		for i in action["args"]:
			if i not in object2idx:
				return False
	elif action["name"] in ["moveTo", "pick", "climbUp", "climbDown", "clean"]:
		if (len(action["args"]) != 1):
			return False
	elif action["name"] in ["changeState"]:
		if (len(action["args"]) != 2):
			return False
		if action["args"][1] in object2idx:
			return False
	elif action["name"] in noArgumentActions:
		if (len(action["args"]) != 0):
			return False
	return True

def gen_policy_score(model, testData, num_objects, verbose = False):
	if verbose: print ("Generalization Testing")
	testcases = (9 if domain == 'home' else 8)
	correct, incorrect, error = 0, 0, 0; total_list = []; 
	for i in range(testcases): total_list.append([0,0,0])
	for graph in tqdm(testData.graphs, desc = "Generalization Testing", ncols=80):
		goal_num, world_num, test_num, _, g, _, e = graph
		actionSeq, graphSeq, object_likelihoods, tool_preds = [], [g], [], []
		approx.initPolicy(domain, goal_num, world_num)
		while True:
			if "Aseq" in model.name:
				if "Tool" in model.name:
					tool_likelihoods = modelEnc(graphSeq[-1], goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
					tool_ls = list(tool_likelihoods.reshape(-1))
					tool_preds.append(TOOLS[tool_ls.index(max(tool_ls))])
					object_likelihoods.append(tool2object_likelihoods(num_objects, tool_likelihoods))
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq, object_likelihoods)
				else:
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq)
				y_pred = y_pred_list[-1]
			else:
				y_pred = model(graphSeq[-1], goal2vec[goal_num], goalObjects2vec[goal_num])
			action_pred = vec2action_grammatical(y_pred, num_objects, len(possibleStates), idx2object) if "Cons" in model.name else vec2action(y_pred, num_objects, len(possibleStates), idx2object)
			if domain == 'home' and test_num == 7 and action_pred['name'] in ['climbUp', 'climbDown'] and action_pred['args'][0] == 'stool': 
				if verbose: print(goal_num, world_num); print(actionSeq, 'Climb up/down headphone'); print('----------')
				error += 1; total_list[test_num-1][2] += 1; break
			if ('_L' not in model.name and domain == 'home' and
				((test_num == 3 and 'mop' in action_pred['args']) or
				 (test_num == 4 and 'box' in action_pred['args']) or
				 (test_num == 5 and 'glue' in action_pred['args']) or
				 (test_num == 8 and 'box' in action_pred['args']) or
				 (test_num == 9 and 'stool' in action_pred['args']))):
				error += 1; total_list[test_num-1][2] += 1; break
			if ('_L' not in model.name and domain == 'factory' and
				((test_num == 1 and 'blow_dryer' in action_pred['args']) or
				 (test_num == 2 and 'brick' in action_pred['args']) or
				 (test_num == 3 and 'lify' in action_pred['args']) or
				 (test_num == 5 and 'glue' in action_pred['args']) or
				 (test_num == 7 and 'coal' in action_pred['args']))):
				error += 1; total_list[test_num-1][2] += 1; break
			res, g, err = approx.execAction(goal_num, action_pred, e)
			actionSeq.append(action_pred); graphSeq.append(g)
			if verbose and err != '': print(goal_num, world_num); print(actionSeq, err); print('----------')
			if res:	correct += 1; total_list[test_num-1][0] += 1; break
			elif err == '' and len(actionSeq) > (30 if domain=='home' else 40):	incorrect += 1; total_list[test_num-1][1] += 1; break
			elif err != '': error += 1; total_list[test_num-1][2] += 1; break
	den = correct + incorrect + error
	print ("Correct, Incorrect, Error: ", (correct*100/den), (incorrect*100/den), (error*100/den))
	for i, tup in enumerate(total_list):
		res = []
		for j in tup: res.append((j * 100 / sum(tup)) if sum(tup) else 0)
		print("Testcase", i+1, res)
	return (correct*100/den), (incorrect*100/den), (error*100/den)

def test_policy(dset, graphs, model, modelEnc, num_objects = 0, ignoreNearCons = True, verbose = False):
	assert "action" in training
	with open('jsons/embeddings/'+embedding+'.vectors') as handle: e = json.load(handle)
	if verbose: print ("Policy Testing")
	correct, incorrect, error = 0, 0, 0; buckets = []; lenHuman, lenModel = [], []
	for i in range(30): buckets.append([0, 0, 0])
	for i in range(8): 
		lenHuman.append([]); lenModel.append([])
	for graph in tqdm(graphs, desc = "Policy Testing", ncols=80):
		goal_num, world_num, tools, g, t = graph
		actionSeq, graphSeq = g
		plan_len = len(actionSeq)-1; lenHuman[goal_num-1].append(plan_len)
		actionSeq, graphSeq, object_likelihoods, tool_preds = [], [graphSeq[0]], [], []
		approx.initPolicy(domain, goal_num, world_num)
		while True:
			if "Aseq" in model.name:
				if "Tool" in model.name:
					tool_likelihoods = modelEnc(graphSeq[-1], goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
					tool_ls = list(tool_likelihoods.reshape(-1))
					tool_preds.append(TOOLS[tool_ls.index(max(tool_ls))])
					object_likelihoods.append(tool2object_likelihoods(num_objects, tool_likelihoods))
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq, object_likelihoods)
				else:
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq)
				y_pred = y_pred_list[-1]
			else:
				y_pred = model(graphSeq[-1], goal2vec[goal_num], goalObjects2vec[goal_num])
			action_pred = vec2action_grammatical(y_pred, num_objects, len(possibleStates), idx2object) if "Cons" in model.name else vec2action(y_pred, num_objects, len(possibleStates), idx2object)
			res, g, err = approx.execAction(goal_num, action_pred, e, ignoreNearCons)
			actionSeq.append(action_pred); graphSeq.append(g)
			if verbose and err != '': print(goal_num, world_num); print(tool_preds); print(actionSeq, err); print('----------')
			if res:	correct += 1; buckets[plan_len][0] += 1; lenModel[goal_num-1].append(len(actionSeq)); break
			elif err == '' and len(actionSeq) > (30 if domain=='home' else 40):	incorrect += 1; buckets[plan_len][1] += 1; break
			elif err != '': error += 1; buckets[plan_len][2] += 1; break
	den = correct + incorrect + error; #print(buckets)
	# for i in lenHuman: print(sum(i)/len(i), end=', ')
	# for i in lenHuman: print(stdev(i), end=', ')
	# print()
	# for i in lenModel: print(sum(i)/len(i) if len(i) else 0, end=', ')
	# for i in lenModel: print(stdev(i) if len(i) else 0, end=', ')
	print ("Correct, Incorrect, Error: ", (correct*100/den), (incorrect*100/den), (error*100/den))
	return (correct*100/den), (incorrect*100/den), (error*100/den)

def accuracy_score(dset, graphs, model, modelEnc, num_objects = 0, verbose = False):
	total_correct = 0
	total_ungrammatical = 0
	denominator = 0
	total_test_loss = 0; l = nn.BCELoss()
	correct, incorrect, error = 0, 0, 0
	stuttering = 0
	if verbose:
		print ("Accuracy score: ")
		action_correct, pred1_correct, pred2_correct, den_pred2 = 0, 0, 0, 0
	for graph in tqdm(graphs, desc = "Accuracy Score", ncols=80):
		goal_num, world_num, tools, g, t = graph
		if 'gcn_seq' in training:
			actionSeq, graphSeq = g; loss = 0; toolSeq = tools
			if 'Tseq' in model.name:
				y_pred = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec, tools)
				for i in range(len(y_pred)):
					y_pred_i = list(y_pred[i].reshape(-1))
					tool_predicted = TOOLS[y_pred_i.index(max(y_pred_i))]
					y_true = torch.zeros(NUMTOOLS)
					y_true[TOOLS.index(toolSeq[i])] = 1
					total_test_loss += l(y_pred[i].view(1,-1), y_true)
					if tool_predicted == toolSeq[i]:
						total_correct += 1
					elif verbose:
						print (goal_num, world_num, tool_predicted, toolSeq[i])
					denominator += 1
			else:
				for i, g in enumerate(graphSeq):
					y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
					y_true = torch.zeros(NUMTOOLS)
					y_true[TOOLS.index(toolSeq[i])] = 1
					total_test_loss += l(y_pred.view(1,-1), y_true)
					y_pred = list(y_pred.reshape(-1))
					# tools_possible = dset.goal_scene_to_tools[(goal_num,world_num)]
					tool_predicted = TOOLS[y_pred.index(max(y_pred))]
					if tool_predicted == toolSeq[i]:
						total_correct += 1
					elif verbose:
						print (goal_num, world_num, tool_predicted, toolSeq[i])
					denominator += 1
			continue
		elif 'gcn' in training:
			y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
			denominator += 1
		elif 'action' in training:
			actionSeq, graphSeq = g
			if "Aseq" in model.name:
				if "Tool" in model.name:
					object_likelihoods = []
					for g in graphSeq:
						tool_likelihoods = modelEnc(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
						object_likelihoods.append(tool2object_likelihoods(num_objects, tool_likelihoods))
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq, object_likelihoods)
				else:
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq)
				plan = []
				for i,y_pred in enumerate(y_pred_list):
					denominator += 1
					action_pred = vec2action_grammatical(y_pred, num_objects, len(possibleStates), idx2object) if "Cons" in model.name else vec2action(y_pred, num_objects, len(possibleStates), idx2object)
					plan.append(action_pred)
					if verbose:
						if "Cons" not in model.name and (not grammatical_action(action_pred)):
							# print (action_pred)
							total_ungrammatical += 1
						if "Cons" not in model.name and (not grammatical_action(actionSeq[i])):
							print (actionSeq[i])
						if (action_pred["name"] == actionSeq[i]["name"]):
							action_correct += 1
						if (len(action_pred["args"]) and len(actionSeq[i]["args"]) and action_pred["args"][0] == actionSeq[i]["args"][0]):
							pred1_correct += 1
						if (len(action_pred["args"]) > 1):
							den_pred2 += 1
							if (len(actionSeq[i]["args"]) > 1 and action_pred["args"][1] == actionSeq[i]["args"][1]):
								pred2_correct += 1
					if (action_pred == actionSeq[i]):
						total_correct += 1
					if (len(action_pred["args"]) == 2 and action_pred["args"][0] == action_pred["args"][1]):
						stuttering += 1
				if False:
					c, i, e, err = approx.testPlan(domain, goal_num, world_num, plan)
					correct += c; incorrect += i; error += e
					if err != '' and False: print(goal_num, world_num); print(plan, err); print('----------')
			else:	
				for i in range(len(graphSeq)):
					if 'list' not in model.name:
						y_pred = model(graphSeq[i], goal2vec[goal_num], goalObjects2vec[goal_num])
					elif model.name == 'sequence_list':
						y_pred = model(graphSeq[max(0,i + 1 - graph_seq_length):i+1], goal2vec[goal_num], goalObjects2vec[goal_num])
					denominator += 1
					action_pred = vec2action_grammatical(y_pred, num_objects, len(possibleStates), idx2object) if "Cons" in model.name else vec2action(y_pred, num_objects, len(possibleStates), idx2object)
					# print ("Prediction: ", action_pred)
					# print ("Target: ", actionSeq[i])
					if verbose:
						if (not grammatical_action(action_pred)):
							# print (action_pred)
							total_ungrammatical += 1
						if (not grammatical_action(actionSeq[i])):
							print (actionSeq[i])
						if (action_pred["name"] == actionSeq[i]["name"]):
							action_correct += 1
						if (len(action_pred["args"]) and len(actionSeq[i]["args"]) and action_pred["args"][0] == actionSeq[i]["args"][0]):
							pred1_correct += 1
						if (len(action_pred["args"]) > 1):
							den_pred2 += 1
							if (len(actionSeq[i]["args"]) > 1 and action_pred["args"][1] == actionSeq[i]["args"][1]):
								pred2_correct += 1
					if (action_pred == actionSeq[i]):
						total_correct += 1
			continue
		tools_possible = dset.goal_scene_to_tools[(goal_num,world_num)]
		y_pred = list(y_pred.reshape(-1))
		tool_predicted = TOOLS[y_pred.index(max(y_pred))]
		if tool_predicted in tools_possible:
			total_correct += 1
		elif verbose:
			print (goal_num, world_num, tool_predicted, tools_possible)
	if (("action" in training) and verbose):
		print ("Total ungrammatical percent is", (total_ungrammatical/denominator) * 100)
		print ("Denominator is", denominator)
		print ("Action accuracy is", (action_correct/denominator) * 100)
		print ("Pred1 accuracy is", (pred1_correct/denominator) * 100)
		print ("Pred2 accuracy is", (pred2_correct/den_pred2) * 100)
		print ("Stuttering count is", stuttering)
	if 'action' in training and False:
		den = correct + incorrect + error
		print ("Correct, Incorrect, Error: ", (correct*100/den), (incorrect*100/den), (error*100/den))
	if training == 'gcn_seq':
		print("Normalized Loss:", total_test_loss.item()/denominator)
	return ((total_correct/denominator)*100)

def printPredictions(model, data=None):
	if not data:
		data = DGLDataset("dataset/" + domain + "/", 
			augmentation=AUGMENTATION, 
			globalNode=globalnode, 
			ignoreNoTool=ignoreNoTool, 
			sequence=sequence)
	total_number = 0
	for graph in data.graphs:
		goal_num, world_num, tools, g, t = graph
		if 'gcn' in training:
			y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
		elif training == 'combined':
			encoding = modelEnc.encode(g)[-1] if globalnode else modelEnc.encode(g)
			y_pred = model(encoding.flatten(), goal2vec[goal_num], goalObjects2vec[goal_num])
		elif 'action' in training:
			actionSeq, graphSeq = g
			if "Aseq" in model.name:
				y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq)
				for i,y_pred in enumerate(y_pred_list):
					denominator += 1
					action_pred = vec2action_grammatical(y_pred, num_objects, len(possibleStates), idx2object)
					if verbose:
						if (not grammatical_action(action_pred)):
							# print (action_pred)
							total_ungrammatical += 1
						if (not grammatical_action(actionSeq[i])):
							print (actionSeq[i])
					if (action_pred == actionSeq[i]):
						total_correct += 1
			else:
				for i in range(len(graphSeq)):
					if 'list' not in training:
						y_pred = model(graphSeq[i], goal2vec[goal_num], goalObjects2vec[goal_num])
					elif training == 'sequence_list':
						y_pred = model(graphSeq[max(0,i + 1 - graph_seq_length):i+1], goal2vec[goal_num], goalObjects2vec[goal_num])
					action_pred = vec2action(y_pred, data.num_objects, len(possibleStates), idx2object)
					# if (action_pred != actionSeq[i]):
					# 	print ("Prediction: ", action_pred)
					# 	print ("Target: ", actionSeq[i])
					total_number += 1
				continue
		tools_possible = data.goal_scene_to_tools[(goal_num,world_num)]
		y_pred = list(y_pred.reshape(-1))
		# y_pred[TOOLS.index("box")] = 0
		tool_predicted = TOOLS[y_pred.index(max(y_pred))]
		# if tool_predicted == "tray" or tool_predicted == "tray2":
		print(goal_num, world_num, tool_predicted, tools_possible)
		# print(tool_predicted, "\t\t", tools_possible)
	print ("Total number of states is", total_number)

def backprop(data, optimizer, graphs, model, num_objects, modelEnc=None, batch_size = 1):
	total_loss = 0.0
	l = nn.BCELoss()
	batch_loss = 0.0
	for iter_num, graph in tqdm(list(enumerate(graphs)), ncols=80):
		goal_num, world_num, tools, g, t = graph
		if 'gcn_seq' in training:
			actionSeq, graphSeq = g; loss = 0
			if 'Tseq' in model.name:
				y_pred = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec, tools)
				for i in range(len(y_pred)):
					y_true = torch.zeros(NUMTOOLS)
					y_true[TOOLS.index(tools[i])] = 1
					loss += l(y_pred[i].view(1,-1), y_true)
			else:
				for i,g in enumerate(graphSeq):
					y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
					y_true = torch.zeros(NUMTOOLS)
					y_true[TOOLS.index(tools[i])] = 1
					loss += l(y_pred.view(1,-1), y_true)
			if weighted: loss *= (1 if t == data.min_time[(goal_num, world_num)] else 0.5)
			batch_loss += loss
		elif 'gcn' in training:
			y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
			y_true = torch.zeros(NUMTOOLS)
			for tool in tools: y_true[TOOLS.index(tool)] = 1
			loss = l(y_pred, y_true)
			if weighted: loss *= (1 if t == data.min_time[(goal_num, world_num)] else 0.5)
			batch_loss += loss
		elif 'action' in training:
			actionSeq, graphSeq = g; loss = 0
			if "Aseq" in model.name:
				if "Tool" in model.name:
					object_likelihoods = []
					for g in graphSeq:
						tool_likelihoods = modelEnc(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
						object_likelihoods.append(tool2object_likelihoods(num_objects, tool_likelihoods))
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq, object_likelihoods)
				else:
					y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq)
				for i,y_pred in enumerate(y_pred_list):
					y_true = action2vec_cons(actionSeq[i], num_objects, len(possibleStates)) if "Cons" in model.name else action2vec(actionSeq[i], num_objects, len(possibleStates))
					loss += l(y_pred, y_true)
			else:
				for i in range(len(graphSeq)):
					if 'list' not in model.name:
						y_pred = model(graphSeq[i], goal2vec[goal_num], goalObjects2vec[goal_num])
					elif model.name == 'sequence_list':
						y_pred = model(graphSeq[max(0,i + 1 - graph_seq_length):i + 1], goal2vec[goal_num], goalObjects2vec[goal_num])
					y_true = action2vec_cons(actionSeq[i], num_objects, len(possibleStates)) if "Cons" in model.name else action2vec(actionSeq[i], num_objects, len(possibleStates))
					loss += l(y_pred, y_true)
			batch_loss += loss
		total_loss += loss
		if ((iter_num + 1) % batch_size == 0):
			optimizer.zero_grad()
			batch_loss.backward()
			optimizer.step()
			batch_loss = 0
	return (total_loss.item()/len(graphs))

def backpropGD(data, optimizer, graphs, model, num_objects, modelEnc=None):
	total_loss = 0.0
	l = nn.BCELoss()
	for iter_num, graph in enumerate(graphs):
		goal_num, world_num, tools, g, t = graph
		if 'gcn' in training:
			y_pred = model(g, goal2vec[goal_num], goalObjects2vec[goal_num], tool_vec)
			y_true = torch.zeros(NUMTOOLS)
			for tool in tools: y_true[TOOLS.index(tool)] = 1
			loss = l(y_pred, y_true)
			if weighted: loss *= (1 if t == data.min_time[(goal_num, world_num)] else 0.5)
		elif 'action' in training:
			actionSeq, graphSeq = g; loss = 0
			if "aseq" in training:
				y_pred_list = model(graphSeq, goal2vec[goal_num], goalObjects2vec[goal_num], actionSeq)
				for i,y_pred in enumerate(y_pred_list):
					y_true = action2vec(actionSeq[i], num_objects, len(possibleStates))
					loss += l(y_pred, y_true)
			else:
				for i in range(len(graphSeq)):
					if 'list' not in training:
						y_pred = model(graphSeq[i], goal2vec[goal_num], goalObjects2vec[goal_num])
					elif training == 'sequence_list':
						y_pred = model(graphSeq[max(0,i + 1 - graph_seq_length):i + 1], goal2vec[goal_num], goalObjects2vec[goal_num])
					y_true = action2vec(actionSeq[i], num_objects, len(possibleStates))
					loss += l(y_pred, y_true)
					# loss += torch.sum((y_pred - y_true)** 2)
		total_loss += loss
	optimizer.zero_grad()
	total_loss.backward()
	optimizer.step()
	return (total_loss.item()/len(graphs))

def random_split(data):
	test_size = int(0.1 * len(data.graphs))
	random.shuffle(data.graphs)
	test_set = data.graphs[:test_size]
	train_set = data.graphs[test_size:]
	return train_set, test_set

def world_split(data):
	test_set = []
	train_set = []
	counter = 0
	for i in data.graphs:
		for j in range(1,9):
			if (i[0],i[1]) == (j,(j if domain=='home' else j-1)):
				test_set.append(i)
				break
		else:
			counter +=1 
			train_set.append(i)
	return train_set, test_set

def tool_split(data):
	train_set, test_set = world_split(data)
	tool_set, notool_set = [], []
	for graph in train_set:
		if 'no-tool' in graph[2]: notool_set.append(graph)
		else: tool_set.append(graph)
	new_set = []
	for i in range(len(tool_set)-len(notool_set)):
		new_set.append(random.choice(notool_set))
	train_set = tool_set + notool_set + new_set
	return train_set, test_set

def split_data(data):
	train_set, test_set = world_split(data) if split == 'world' else random_split(data)  if split == 'random' else tool_split(data) 
	print ("Size before split was", len(data.graphs))
	print ("The size of the training set is", len(train_set))
	print ("The size of the test set is", len(test_set))
	return train_set, test_set

def get_model(model_name):
	import src.GNN.models
	if training == 'gcn' or training == 'gcn_seq':
		size, layers = (4, 5) if training == 'gcn' else (2, 3)
		modelEnc = None
		if "Tseq" in model_name:
			model_class = getattr(src.GNN.models, "GGCN_Metric_Attn_L_NT_Tseq_C")
			model = model_class(data.features, data.num_objects, size * GRAPH_HIDDEN, NUMTOOLS, layers, etypes, torch.tanh, 0.5, embedding, weighted)
		elif ("Final" not in model_name and "_NT" in model_name) or "Final_W" in model_name:
			model_class = getattr(src.GNN.models, "DGL_Simple_Likelihood")
			model = model_class(data.features, data.num_objects, size * GRAPH_HIDDEN, NUMTOOLS, layers, etypes, torch.tanh, 0.5, embedding, weighted)
		else:
			model_class = getattr(src.GNN.models, model_name)
			model = model_class(data.features, data.num_objects, size * GRAPH_HIDDEN, NUMTOOLS, layers, etypes, torch.tanh, 0.5)
	elif training == 'action':
		model_class = getattr(src.GNN.models, model_name)
		model = model_class(data.features, data.num_objects, 2 * GRAPH_HIDDEN, len(possibleStates), 3, etypes, torch.tanh, 0.5)
		modelEnc = DGL_Simple_Likelihood(data.features, data.num_objects, 2 * GRAPH_HIDDEN, NUMTOOLS, 3, etypes, torch.tanh, 0.5, embedding, weighted) if 'Tool' in model.name else None 
	return model, modelEnc

def load_model(filename, model, modelEnc):
	lr = 0.0005 if 'action' in training else 0.00005
	if training == 'gcn_seq': lr = 0.0005
	optimizer = torch.optim.Adam(model.parameters() , lr=lr, weight_decay=1e-5)
	file_path = MODEL_SAVE_PATH + "/" + filename + ".ckpt"
	if path.exists(file_path):
		print(color.GREEN+"Loading pre-trained model: "+filename+color.ENDC)
		checkpoint = torch.load(file_path)
		model.load_state_dict(checkpoint['model_state_dict'])
		optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
		epoch = checkpoint['epoch']
		accuracy_list = checkpoint['accuracy_list']
	else:
		if "train" not in exec_type: print("File '%s' not found!" % filename); exit()
		epoch = -1; accuracy_list = []
		print(color.GREEN+"Creating new model: "+model.name+color.ENDC)
	if "action" in training:
		if "Tool" in model.name:
			enc_path = MODEL_SAVE_PATH + "/Seq_GGCN_Metric_Attn_L_NT_C_128_3_Trained.ckpt"
			assert(path.exists(enc_path))
			checkpoint_enc = torch.load(enc_path)
			modelEnc.load_state_dict(checkpoint_enc['model_state_dict'])
			modelEnc.eval()
			for p in modelEnc.parameters(): p.requires_grad = False
	return model, modelEnc, optimizer, epoch, accuracy_list

def save_model(model, optimizer, epoch, accuracy_list, file_path = None):
	seqTool = 'Seq_' if training == 'gcn_seq' else ''
	if file_path == None:
		file_path = MODEL_SAVE_PATH + "/" + seqTool + model.name + "_" + str(epoch) + ".ckpt"
	torch.save({
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'accuracy_list': accuracy_list}, file_path)

def eval_accuracy(data, train_set, test_set, model, modelEnc, verbose=False):
	t1, t2 = accuracy_score(data, train_set, model, modelEnc, data.num_objects, verbose), accuracy_score(data, test_set, model, modelEnc, data.num_objects, verbose)
	print ("Accuracy on training set is ", t1)
	print ("Accuracy on test set is ", t2)
	return t1, t2

def convert_model(filename, training_type):
	global training
	file_path = MODEL_SAVE_PATH + "/" + filename + ".pt"
	assert(path.exists(file_path))
	model = torch.load(file_path)
	flag = False
	if str(type(model)) == "<class 'collections.OrderedDict'>": # If only model state dict is saved
		flag = True
		model, modelEnc = get_model(model_name)
		model.load_state_dict(torch.load(file_path))
	lr = 0.0005 if 'action' in training_type else 0.00005
	if training_type == 'gcn_seq': lr = 0.0005
	optimizer = torch.optim.Adam(model.parameters() , lr=lr)
	training = training_type
	if flag:
		save_model(model, optimizer, 0, [], file_path = file_path)		
	else:
		save_model(model, optimizer, 0, [])

if __name__ == '__main__':
	data = load_dataset()
	model, modelEnc = get_model(model_name)
	seqTool = 'Seq_' if training == 'gcn_seq' else ''
	# model, modelEnc, optimizer, epoch, accuracy_list = load_model("GGCN_Metric_Attn_Aseq_L_Auto_Cons_C_5_Action_128_3_13", model, modelEnc)
	model, modelEnc, optimizer, epoch, accuracy_list = load_model(seqTool + model.name + "_Trained", model, modelEnc)
	# model, modelEnc, optimizer, epoch, accuracy_list = load_model("checkpoints/baseline_metric_att_aseq_auto_c_best_69_64", model, modelEnc)
	train_set, test_set = split_data(data)

	if exec_type == "train":
		print ("Training " + model.name + " with " + embedding)
		for num_epochs in range(epoch+1, epoch+NUM_EPOCHS+1):
			random.shuffle(train_set)
			print ("EPOCH " + str(num_epochs))
			loss = backprop(data, optimizer, train_set, model, data.num_objects, modelEnc, batch_size = 1)
			print(loss)
			t1, t2 = eval_accuracy(data, train_set, test_set, model, modelEnc)
			if 'action' in training:
				c, i, e = test_policy(data, test_set, model, modelEnc, data.num_objects, False, False)
				accuracy_list.append((t2, t1, loss, c, i, e))
			else: 
				accuracy_list.append((t2, t1))
			save_model(model, optimizer, num_epochs, accuracy_list)
		print ("The maximum accuracy on test set is ", str(max(accuracy_list)), " at epoch ", accuracy_list.index(max(accuracy_list)))
		if 'action' in training:
			policy_acc = [i[3] for i in accuracy_list]
			print("The maximum policy on test set is ", str(max(policy_acc)), " at epoch ", policy_acc.index(max(policy_acc)))

	elif exec_type == "accuracy":
		print ("Evaluating " + model.name)
		model.eval()
		eval_accuracy(data, train_set, test_set, model, modelEnc, True)
		if training != 'gcn': exit()
		genTest = TestDataset("dataset/test/" + domain + "/" + embedding + "/")
		print("Generalization accuracy is ", gen_score(model, genTest))

	elif exec_type == "generalization" and "Action" not in model.name:
		testConcept = TestDataset("dataset/test/" + domain + "/conceptnet/")
		testFast = TestDataset("dataset/test/" + domain + "/fasttext/")
		embeddings, object2vec, object2idx, idx2object, tool_vec, goal2vec, goalObjects2vec = compute_constants("fasttext")
		for i in ["GGCN_256_5_0", "GGCN_Metric_256_5_Trained", "GGCN_Metric_Attn_256_5_Trained",\
					"GGCN_Metric_Attn_L_256_5_Trained", "GGCN_Metric_Attn_L_NT_256_5_Trained"]:
			model, _ = get_model('_'.join(i.split("_")[:-3]))
			model, _, _, _, _ = load_model(i, model, None)
			print(i, gen_score(model, testFast))
		embeddings, object2vec, object2idx, idx2object, tool_vec, goal2vec, goalObjects2vec = compute_constants("conceptnet")
		for i in ["GGCN_Metric_Attn_L_NT_C_256_5_Trained", "GGCN_Metric_Attn_L_NT_C_W_256_5_Trained"]:
			model, _ = get_model('_'.join(i.split("_")[:-3]))
			model, _, _, _, _ = load_model(i, model, None)
			print(i, gen_score(model, testConcept))

	elif exec_type == "generalization" and "Action" in model.name:
		genTestSet = TestDataset("dataset/test/" + domain + "/" + embedding + "/")
		gen_policy_score(model, genTestSet, data.num_objects)

	elif exec_type == "ablation":
		testConcept = TestDataset("dataset/test/" + domain + "/conceptnet/")
		testFast = TestDataset("dataset/test/" + domain + "/fasttext/")
		embeddings, object2vec, object2idx, idx2object, tool_vec, goal2vec, goalObjects2vec = compute_constants("fasttext")
		for i in ["Final_C_256_5_Trained"]:
			model, _ = get_model('_'.join(i.split("_")[:-3]))
			model, _, _, _, _ = load_model(i, model, None)
			print(i, gen_score(model, testFast))
		embeddings, object2vec, object2idx, idx2object, tool_vec, goal2vec, goalObjects2vec = compute_constants("conceptnet")
		for i in ["Final_Attn_256_5_Trained", "Final_L_256_5_Trained", "Final_Metric_256_5_Trained",\
					"Final_NT_256_5_Trained"]:
			model, _ = get_model('_'.join(i.split("_")[:-3]))
			model, _, _, _, _ = load_model(i, model, None)
			print(i, gen_score(model, testFast))

	elif exec_type == "policy":
		assert "action" in training and "Action" in model.name
		# test_policy(data, train_set, model, modelEnc, data.num_objects)
		test_policy(data, test_set, model, modelEnc, data.num_objects, verbose = False)