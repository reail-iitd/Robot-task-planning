from src.GNN.helper import *
from src.GNN.CONSTANTS import *
from src.utils import *
from src.GNN.oldmodels import *
from src.GNN.action_models import *
torch.manual_seed(1)

class A2C(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_states,
                 n_layers,
                 etypes,
                 activation):
        super(A2C, self).__init__()
        self.name = "A2C_" + str(n_hidden) + "_" + str(n_layers)
        self.activation = nn.PReLU()
        self.layers, self.metric = nn.ModuleList(), nn.ModuleList()
        self.layers.append(GatedHeteroRGCNLayer(in_feats, n_hidden, etypes, activation=activation))
        self.metric.append(nn.Linear(in_feats, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(GatedHeteroRGCNLayer(n_hidden, n_hidden, etypes, activation=activation))
            self.metric.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Sequential(nn.Linear(n_hidden + n_hidden + n_hidden + 1, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.embed = nn.Sequential(nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation)
        self.critic = nn.Sequential(nn.Linear(3*n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.actor = nn.Sequential(nn.Linear(5*n_hidden + len(possibleActions) + n_states, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.n_hidden = n_hidden; self.n_objects = n_objects; self.n_layers = n_layers; self.n_states = n_states

    def graph(self, g, goalVec, goalObjectsVec):
        goalObjectsVec = self.embed(torch.Tensor(goalObjectsVec))
        goal_embed = self.embed(torch.Tensor(goalVec.reshape(1, -1)))
        semantic_part, metric_part = g.ndata['feat'], g.ndata['feat']
        for i in range(self.n_layers):
            semantic_part = self.activation(self.layers[i](g, semantic_part))
            metric_part = self.activation(self.metric[i](metric_part))
        h = torch.cat([semantic_part, metric_part], dim = 1)
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1), g.ndata['close']], 1)
        attn_weights = F.softmax(self.attention(attn_embedding), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        final_to_decode = torch.cat([scene_embedding, goal_embed], 1)
        return final_to_decode

    def value(self, g, goalVec, goalObjectsVec):
    	final_to_decode = self.graph(g, goalVec, goalObjectsVec)
    	value = torch.sigmoid(self.critic(final_to_decode))
    	return value

    def policy(self, g, goalVec, goalObjectsVec, a_list):
    	a_list = torch.stack([action2vec_lstm(i, self.n_objects, self.n_states, self.n_hidden, self.embed) for i in a_list])
    	final_to_decode = self.graph(g, goalVec, goalObjectsVec)
    	actor_input = torch.cat([final_to_decode.view(-1).repeat(len(a_list)).view(len(a_list), -1), a_list], 1)
    	probs = F.softmax(self.actor(actor_input).view(1,-1), dim=1)
    	return probs.view(-1)

class DQN(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_states,
                 n_layers,
                 etypes,
                 activation):
        super(DQN, self).__init__()
        self.name = "DQN_" + str(n_hidden) + "_" + str(n_layers)
        self.activation = nn.PReLU()
        self.layers, self.metric = nn.ModuleList(), nn.ModuleList()
        self.layers.append(GatedHeteroRGCNLayer(in_feats, n_hidden, etypes, activation=activation))
        self.metric.append(nn.Linear(in_feats, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(GatedHeteroRGCNLayer(n_hidden, n_hidden, etypes, activation=activation))
            self.metric.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Sequential(nn.Linear(n_hidden + n_hidden + n_hidden + 1, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.embed = nn.Sequential(nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation)
        self.critic = nn.Sequential(nn.Linear(3*n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.actor = nn.Sequential(nn.Linear(5*n_hidden + len(possibleActions) + n_states, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.n_hidden = n_hidden; self.n_objects = n_objects; self.n_layers = n_layers; self.n_states = n_states

    def graph(self, g, goalVec, goalObjectsVec):
        goalObjectsVec = self.embed(torch.Tensor(goalObjectsVec))
        goal_embed = self.embed(torch.Tensor(goalVec.reshape(1, -1)))
        semantic_part, metric_part = g.ndata['feat'], g.ndata['feat']
        for i in range(self.n_layers):
            semantic_part = self.activation(self.layers[i](g, semantic_part))
            metric_part = self.activation(self.metric[i](metric_part))
        h = torch.cat([semantic_part, metric_part], dim = 1)
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1), g.ndata['close']], 1)
        attn_weights = F.softmax(self.attention(attn_embedding), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        final_to_decode = torch.cat([scene_embedding, goal_embed], 1)
        return final_to_decode

    def policy(self, g, goalVec, goalObjectsVec, a_list):
        a_list = torch.stack([action2vec_lstm(i, self.n_objects, self.n_states, self.n_hidden, self.embed) for i in a_list])
        final_to_decode = self.graph(g, goalVec, goalObjectsVec)
        actor_input = torch.cat([final_to_decode.view(-1).repeat(len(a_list)).view(len(a_list), -1), a_list], 1)
        probs = torch.sigmoid(self.actor(actor_input).view(1,-1))
        return probs.view(-1)

class DQN_Aseq(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_states,
                 n_layers,
                 etypes,
                 activation):
        super(DQN_Aseq, self).__init__()
        self.name = "DQN_Aseq_" + str(n_hidden) + "_" + str(n_layers)
        self.activation = nn.PReLU()
        self.layers, self.metric = nn.ModuleList(), nn.ModuleList()
        self.layers.append(GatedHeteroRGCNLayer(in_feats, n_hidden, etypes, activation=activation))
        self.metric.append(nn.Linear(in_feats, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(GatedHeteroRGCNLayer(n_hidden, n_hidden, etypes, activation=activation))
            self.metric.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Sequential(nn.Linear(n_hidden + n_hidden + n_hidden + 1, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.embed = nn.Sequential(nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation)
        self.actor = nn.Sequential(nn.Linear(7*n_hidden + len(possibleActions) + n_states, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.action_lstm = nn.LSTM(len(possibleActions) + n_hidden + n_hidden + n_states, 2*n_hidden)
        self.n_hidden = n_hidden; self.n_objects = n_objects; self.n_layers = n_layers; self.n_states = n_states

    def graph(self, g, goalVec, goalObjectsVec, a_hist):
        goalObjectsVec = self.embed(torch.Tensor(goalObjectsVec))
        goal_embed = self.embed(torch.Tensor(goalVec.reshape(1, -1)))
        lstm_hidden = (torch.randn(1, 1, 2*self.n_hidden),torch.randn(1, 1, 2*self.n_hidden))
        lstm_out = torch.zeros(1, 1, 2*self.n_hidden)
        a_hist = [action2vec_lstm(i, self.n_objects, self.n_states, self.n_hidden, self.embed) for i in a_hist]
        for prev_action in a_hist:
            lstm_out, lstm_hidden = self.action_lstm(prev_action.view(1,1,-1), lstm_hidden)
        semantic_part, metric_part = g.ndata['feat'], g.ndata['feat']
        for i in range(self.n_layers):
            semantic_part = self.activation(self.layers[i](g, semantic_part))
            metric_part = self.activation(self.metric[i](metric_part))
        h = torch.cat([semantic_part, metric_part], dim = 1)
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1), g.ndata['close']], 1)
        attn_weights = F.softmax(self.attention(attn_embedding), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        final_to_decode = torch.cat([scene_embedding, goal_embed, lstm_out.view(1,-1)], 1)
        return final_to_decode

    def policy(self, g, goalVec, goalObjectsVec, a_list, a_hist):
        final_to_decode = self.graph(g, goalVec, goalObjectsVec, a_hist)
        a_list = torch.stack([action2vec_lstm(i, self.n_objects, self.n_states, self.n_hidden, self.embed) for i in a_list])
        actor_input = torch.cat([final_to_decode.view(-1).repeat(len(a_list)).view(len(a_list), -1), a_list], 1)
        probs = torch.sigmoid(self.actor(actor_input).view(1,-1))
        return probs.view(-1)


class DQN2(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_states,
                 n_layers,
                 etypes,
                 activation):
        super(DQN2, self).__init__()
        self.etypes = etypes
        self.name = "DQN2_" + str(n_hidden) + "_" + str(n_layers)
        self.activation = nn.PReLU()
        self.metric = nn.ModuleList()
        self.metric.append(nn.Linear(in_feats + n_objects*4, 2*n_hidden))
        for i in range(n_layers + 1):
            self.metric.append(nn.Linear(2*n_hidden, 2*n_hidden))
        self.attention = nn.Sequential(nn.Linear(n_hidden + n_hidden + n_hidden + 1, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.embed = nn.Sequential(nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation)
        self.critic = nn.Sequential(nn.Linear(3*n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.actor = nn.Sequential(nn.Linear(5*n_hidden + len(possibleActions) + n_states, n_hidden), self.activation, nn.Linear(n_hidden, n_hidden), self.activation, nn.Linear(n_hidden, 1))
        self.n_hidden = n_hidden; self.n_objects = n_objects; self.n_layers = n_layers; self.n_states = n_states

    def graph(self, g, goalVec, goalObjectsVec):
        goalObjectsVec = self.embed(torch.Tensor(goalObjectsVec))
        goal_embed = self.embed(torch.Tensor(goalVec.reshape(1, -1)))
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i in range(self.n_layers):
            h = self.activation(self.metric[i](h))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1), g.ndata['close']], 1)
        attn_weights = F.softmax(self.attention(attn_embedding), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        final_to_decode = torch.cat([scene_embedding, goal_embed], 1)
        return final_to_decode

    def policy(self, g, goalVec, goalObjectsVec, a_list):
        a_list = torch.stack([action2vec_lstm(i, self.n_objects, self.n_states, self.n_hidden, self.embed) for i in a_list])
        final_to_decode = self.graph(g, goalVec, goalObjectsVec)
        actor_input = torch.cat([final_to_decode.view(-1).repeat(len(a_list)).view(len(a_list), -1), a_list], 1)
        probs = torch.sigmoid(self.actor(actor_input).view(1,-1))
        return probs.view(-1)

