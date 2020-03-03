import json
from src.GNN.CONSTANTS import *
import numpy as np
import os
import pickle
from src.datapoint import Datapoint
import dgl
import torch

etypes = ["Close", "Inside", "On", "Stuck", "Self-Loop"]

def get_graph_data(pathToDatapoint, args):

	datapoint = pickle.load(open(pathToDatapoint, "rb"))
	
	goal_num = int(datapoint.goal[4])
	world_num = int(datapoint.world[-1])
	# goal_vec = np.zeros(NUM_GOALS)
	# goal_vec[goal_num - 1] = 1

	graph_data = datapoint.getGraph()["graph_0"] #Initial Graph

	#List of the names of the nodes
	if args.global_node:
		node_names = [i["name"] for i in graph_data["nodes"]] + ["global"]
		node_ids = [i["id"] for i in graph_data["nodes"]] + [-1] #-1 is the id of the global node
	else:
		node_names = [i["name"] for i in graph_data["nodes"]]
		#The id may not be the same as the position in the list
		node_ids = [i["id"] for i in graph_data["nodes"]]

	n_nodes = len(node_names)

	# The nodes are ordered here according to the order in which they were put into the list
	node_states = np.zeros([n_nodes, N_STATES], dtype=np.int32)
	for i, node in enumerate(graph_data["nodes"]):
		states = node["states"]
		for state in states:
			idx = state2indx[state]
			node_states[i, idx] = 1

	adjacency_matrix = np.zeros([N_EDGES, n_nodes, n_nodes], dtype=np.bool)
	for edge in graph_data["edges"]:
		edge_type = edge["relation"]
		src_id = edge["from"]
		tgt_id = edge["to"]

		edge_type_idx = edge2idx[edge_type]
		src_idx = node_ids.index(src_id)
		tgt_idx = node_ids.index(tgt_id)

		adjacency_matrix[edge_type_idx, src_idx, tgt_idx] = True
	if args.global_node:
		for i in range(N_EDGES):
			for j in range(n_nodes):
				adjacency_matrix[i,n_nodes-1,j] = True
				adjacency_matrix[i,j,n_nodes-1] = True

	node_vectors = [i["vector"] for i in graph_data["nodes"]]
	if args.global_node:
		node_vectors.append([0]*PRETRAINED_VECTOR_SIZE)
	node_vectors = np.array(node_vectors)

	node_size_and_pos = [list(i["size"]) + list(i["position"][0]) + list(i["position"][1]) for i in graph_data["nodes"]]
	if args.global_node:
		node_size_and_pos.append([0]*10)
	node_size_and_pos = np.array(node_size_and_pos)
	tools = datapoint.getTools()
	if (len(tools) == 0):
		return None
	return (adjacency_matrix, node_states, node_ids, node_names, n_nodes, tools, goal_num, world_num, node_vectors, node_size_and_pos)

class Dataset():

	def __init__(self, program_dir, args):
		self.args = args
		graphs = []
		self.goal_scene_to_tools = {}
		all_files = os.walk(program_dir)
		# self.tools = set()
		for path, dirs, files in all_files:
			if (len(files) > 0):
				for file in files:
					file_path = path + "/" + file
					# print (file_path)
					graph_ret = get_graph_data(file_path, self.args)
					if (graph_ret is None):
						continue
					graphs.append(graph_ret)
					tools = graphs[-1][5]
					goal_num = graphs[-1][6]
					world_num = graphs[-1][7]
					if (goal_num,world_num) not in self.goal_scene_to_tools:
						self.goal_scene_to_tools[(goal_num,world_num)] = []
					for tool in tools:
						if tool not in self.goal_scene_to_tools[(goal_num,world_num)]:
							self.goal_scene_to_tools[(goal_num,world_num)].append(tool)
					# for i in (graphs[-1][-2]):
					# 	self.tools.add(i)
		# print (len(self.tools),self.tools)
		self.graphs = graphs
		# for i in self.goal_scene_to_tools:
		# 	if "no-tool" in self.goal_scene_to_tools[i]:
		# 		if (len(self.goal_scene_to_tools[i]) == 1):
		# 			print (i,self.goal_scene_to_tools[i])


############################ DGL ############################

def getDGLGraph(pathToDatapoint, globalNode):
	datapoint = pickle.load(open(pathToDatapoint, "rb"))
	tools = datapoint.getTools()
	if len(tools) == 0: return None
	goal_num = int(datapoint.goal[4])
	world_num = int(datapoint.world[-1])
	# Initial Graph
	graph_data = datapoint.getGraph()["graph_0"] 
	# Make edge sets
	close, inside, on, stuck = [], [], [], []
	for edge in graph_data["edges"]:
		if edge["relation"] == "Close": close.append((edge["from"], edge["to"]))
		elif edge["relation"] == "Inside": inside.append((edge["from"], edge["to"]))
		elif edge["relation"] == "On": on.append((edge["from"], edge["to"]))
		elif edge["relation"] == "Stuck": stuck.append((edge["from"], edge["to"]))
	edgeDict = {
		('object', 'Close', 'object'): close,
		('object', 'Inside', 'object'): inside,
		('object', 'On', 'object'): on,
		('object', 'Stuck', 'object'): stuck
		}
	if globalNode:
		edgeDict[('object', 'Global', 'object')]: [list(range(len(selfLoops))), len(selfLoops)]
	g = dgl.heterograph(edgeDict)
	# Add node features
	n_nodes = g.number_of_nodes()
	node_states = torch.zeros([n_nodes, N_STATES], dtype=torch.float) # State vector
	node_vectors = torch.zeros([n_nodes, PRETRAINED_VECTOR_SIZE], dtype=torch.float) # Fasttext embedding 
	node_size_and_pos = torch.zeros([n_nodes, 10], dtype=torch.float) # Size and position
	node_in_goal = torch.zeros([n_nodes, 1], dtype=torch.float) # Object in goal
	for i, node in enumerate(graph_data["nodes"]):
		states = node["states"]
		node_id = node["id"]
		for state in states:
			idx = state2indx[state]
			node_states[node_id, idx] = 1
			node_vectors[node_id] = torch.FloatTensor(node["vector"])
			node_size_and_pos[node_id] = torch.FloatTensor(list(node["size"]) + list(node["position"][0]) + list(node["position"][1]))
			node_in_goal[node_id] = 1 if node["name"] in goalObjects[goal_num] else 0

	g.ndata['feat'] = torch.cat((node_vectors, node_states, node_size_and_pos), 1)
	return (goal_num, world_num, datapoint.getTools(), g)


class DGLDataset():
	def __init__(self, program_dir, augmentation=50, globalNode=False):
		global etypes
		if globalNode: etypes.append('Global')
		self.num_objects = 0
		graphs = []
		self.goal_scene_to_tools = {}
		all_files = os.walk(program_dir)
		for path, dirs, files in all_files:
			if (len(files) > 0):
				for file in files:
					file_path = path + "/" + file
					for i in range(augmentation):
						graph = getDGLGraph(file_path, globalNode)
						if graph: graphs.append(graph) 
					tools = graphs[-1][2]
					goal_num = graphs[-1][0]
					world_num = graphs[-1][1]
					if (goal_num,world_num) not in self.goal_scene_to_tools:
						self.goal_scene_to_tools[(goal_num,world_num)] = []
					for tool in tools:
						if tool not in self.goal_scene_to_tools[(goal_num,world_num)]:
							self.goal_scene_to_tools[(goal_num,world_num)].append(tool)
		self.graphs = graphs
		self.features = self.graphs[0][3].ndata['feat'].shape[1]

