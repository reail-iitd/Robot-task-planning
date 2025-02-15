from src.GNN.oldmodels import *
from src.GNN.action_models import *
from src.GNN.helper import *
from src.utils import *

class DGL_Simple_Likelihood(nn.Module):
    """ 
        The best performing model for the one-step tool prediction task. 
        Separate likelihood prediction of no tool for more robust tool output considering any tool 
        to be used or not as prior. 
    """
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout,
                 embedding,
                 weighted):
        super(DGL_Simple_Likelihood, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "GGCN_Metric_Attn_L_NT_" + ('C_' if 'c' in embedding else '') + ('W_' if weighted else '') + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(3 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.p1  = nn.Linear(2 * n_hidden, n_hidden)
        self.p2  = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_embedding = self.activation(self.attention(attn_embedding))
        attn_weights = F.softmax(self.activation(self.attention2(attn_embedding)), dim=0)
        # print(attn_weights)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        l = []
        tool_embedding = self.activation(self.embed(tool_vec))
        for i in range(NUMTOOLS-1):
            final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
            h = self.activation(self.fc1(final_to_decode))
            h = self.activation(self.fc2(h))
            h = self.activation(self.fc3(h))
            h = self.final(self.fc4(h))
            l.append(h.flatten())
        tools = torch.stack(l)
        probNoTool = self.activation(self.p1(scene_and_goal))
        probNoTool = torch.sigmoid(self.activation(self.p2(probNoTool))).flatten()
        output = torch.cat(((1-probNoTool)*tools.flatten(), probNoTool), dim=0)
        return output

class GGCN(nn.Module):
    """ 
    Baseline model using hetero gated graph convolution to encode world state. 
    Uses goal and world representations to predict tool likelihood estimates.   
    """
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(GGCN, self).__init__()
        self.name = "GGCN_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(GatedHeteroRGCNLayer(in_feats, n_hidden, etypes, activation=activation))
        for i in range(n_layers - 1):
            self.layers.append(GatedHeteroRGCNLayer(n_hidden, n_hidden, etypes, activation=activation))
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_classes)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        for i, layer in enumerate(self.layers):
            h = layer(g, h)
        scene_embedding = torch.sum(h, dim=0).view(1,-1)
        goal_embed = self.activation(self.embed(goalVec))
        h = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        h = self.activation(self.fc1(h))
        h = self.activation(self.fc2(h))
        h = self.final(self.fc3(h))
        return h

class GGCN_Metric(nn.Module):
    """ 
        Uses metric properties of objects as well to incorporate metric dependencies in tool prediction.
        GGCN+Metric
    """
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(GGCN_Metric, self).__init__()
        self.etypes = etypes
        self.name = "GGCN_Metric_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_classes)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        scene_embedding = torch.sum(h, dim=0).view(1,-1)
        goal_embed = self.activation(self.embed(goalVec))
        h = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        h = self.activation(self.fc1(h))
        h = self.activation(self.fc2(h))
        h = self.final(self.fc3(h))
        return h

class GGCN_Metric_Attn(nn.Module):
    """
        Uses goal object conditioned bahdanau style attention for focused 
        representation by diminishing activation of object embeddings not 
        related to the goal objects
        GGCN+Metric+Attention
    """
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(GGCN_Metric_Attn, self).__init__()
        self.etypes = etypes
        self.name = "GGCN_Metric_Attn_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_classes)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_weights = F.softmax(self.activation(self.attention(attn_embedding)), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        h = self.activation(self.fc1(scene_and_goal))
        h = self.activation(self.fc2(h))
        h = self.final(self.fc3(h))
        return h

class GGCN_Metric_Attn_L(nn.Module):
    """ 
        Predicts likelihood of each tool independently using tool embeddings, 
        which are then stacked together for MLP tool
        GGCN+Metric+Attn+L
    """
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(GGCN_Metric_Attn_L, self).__init__()
        self.etypes = etypes
        self.name = "GGCN_Metric_Attn_L_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(3 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_weights = F.softmax(self.activation(self.attention(attn_embedding)), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        l = []
        tool_vec2 = torch.cat((tool_vec, torch.zeros((1, PRETRAINED_VECTOR_SIZE))))
        tool_embedding = self.activation(self.embed(tool_vec2))
        for i in range(NUMTOOLS):
            final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
            h = self.activation(self.fc1(final_to_decode))
            h = self.activation(self.fc2(h))
            h = self.activation(self.fc3(h))
            h = self.final(self.fc4(h))
            l.append(h.flatten())
        tools = torch.stack(l)
        return tools

######################################################################################

# The following models contain the ablation, where the final model has one of the 
# components missing. We show that the model is able to perform much better than 
# any ablated model, and each component is important for the accuracy of the model.

class Final_Metric(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(Final_Metric, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "Final_Metric_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(GatedHeteroRGCNLayer(in_feats, n_hidden, etypes, activation=activation))
        for i in range(n_layers - 1):
            self.layers.append(GatedHeteroRGCNLayer(n_hidden, n_hidden, etypes, activation=activation))
        self.attention = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(3 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.p1  = nn.Linear(2 * n_hidden, n_hidden)
        self.p2  = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        for i, layer in enumerate(self.layers):
            h = layer(g, h)
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_embedding = self.activation(self.attention(attn_embedding))
        attn_weights = F.softmax(self.activation(self.attention2(attn_embedding)), dim=0)
        # print(attn_weights)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        l = []
        tool_embedding = self.activation(self.embed(tool_vec))
        for i in range(NUMTOOLS-1):
            final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
            h = self.activation(self.fc1(final_to_decode))
            h = self.activation(self.fc2(h))
            h = self.activation(self.fc3(h))
            h = self.final(self.fc4(h))
            l.append(h.flatten())
        tools = torch.stack(l)
        probNoTool = self.activation(self.p1(scene_and_goal))
        probNoTool = torch.sigmoid(self.activation(self.p2(probNoTool))).flatten()
        output = torch.cat(((1-probNoTool)*tools.flatten(), probNoTool), dim=0)
        return output

class Final_Attn(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(Final_Attn, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "Final_Attn_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(3 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.p1  = nn.Linear(2 * n_hidden, n_hidden)
        self.p2  = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        scene_embedding = torch.sum(h, dim=0).view(1,-1)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        l = []
        tool_embedding = self.activation(self.embed(tool_vec))
        for i in range(NUMTOOLS-1):
            final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
            h = self.activation(self.fc1(final_to_decode))
            h = self.activation(self.fc2(h))
            h = self.activation(self.fc3(h))
            h = self.final(self.fc4(h))
            l.append(h.flatten())
        tools = torch.stack(l)
        probNoTool = self.activation(self.p1(scene_and_goal))
        probNoTool = torch.sigmoid(self.activation(self.p2(probNoTool))).flatten()
        output = torch.cat(((1-probNoTool)*tools.flatten(), probNoTool), dim=0)
        return output

class Final_L(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(Final_L, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "Final_L_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_classes)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_embedding = self.activation(self.attention(attn_embedding))
        attn_weights = F.softmax(self.activation(self.attention2(attn_embedding)), dim=0)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        h = self.activation(self.fc1(scene_and_goal))
        h = self.activation(self.fc2(h))
        h = self.final(self.fc3(h))
        return h

class Final_NT(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(Final_NT, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "Final_NT_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(3 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_embedding = self.activation(self.attention(attn_embedding))
        attn_weights = F.softmax(self.activation(self.attention2(attn_embedding)), dim=0)
        # print(attn_weights)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        l = []
        tool_vec2 = torch.cat((tool_vec, torch.zeros((1, PRETRAINED_VECTOR_SIZE))))
        tool_embedding = self.activation(self.embed(tool_vec2))
        for i in range(NUMTOOLS):
            final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
            h = self.activation(self.fc1(final_to_decode))
            h = self.activation(self.fc2(h))
            h = self.activation(self.fc3(h))
            h = self.final(self.fc4(h))
            l.append(h.flatten())
        tools = torch.stack(l)
        return tools

class Final_C(nn.Module):
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout):
        super(Final_C, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "Final_C_" + str(n_hidden) + "_" + str(n_layers)
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.attention = nn.Linear(n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(3 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.p1  = nn.Linear(2 * n_hidden, n_hidden)
        self.p2  = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g, goalVec, goalObjectsVec, tool_vec):
        h = g.ndata['feat']
        edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
        edges = torch.cat(edgeMatrices, 1).to_dense()
        h = torch.cat((h, edges), 1)
        for i, layer in enumerate(self.layers):
            h = self.activation(layer(h))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1)], 1)
        attn_embedding = self.activation(self.attention(attn_embedding))
        attn_weights = F.softmax(self.activation(self.attention2(attn_embedding)), dim=0)
        # print(attn_weights)
        scene_embedding = torch.mm(attn_weights.t(), h)
        goal_embed = self.activation(self.embed(goalVec))
        scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1)], 1)
        l = []
        tool_embedding = self.activation(self.embed(tool_vec))
        for i in range(NUMTOOLS-1):
            final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
            h = self.activation(self.fc1(final_to_decode))
            h = self.activation(self.fc2(h))
            h = self.activation(self.fc3(h))
            h = self.final(self.fc4(h))
            l.append(h.flatten())
        tools = torch.stack(l)
        probNoTool = self.activation(self.p1(scene_and_goal))
        probNoTool = torch.sigmoid(self.activation(self.p2(probNoTool))).flatten()
        output = torch.cat(((1-probNoTool)*tools.flatten(), probNoTool), dim=0)
        return output


######################################################################################

# The following models are for tool sequence prediction

class GGCN_Metric_Attn_L_NT_Tseq_C(nn.Module):
    """ 
        The best performing model for the sequential tool prediction task. 
        Separate likelihood prediction of no tool for more robust tool output considering any tool 
        to be used or not as prior. 
    """
    def __init__(self,
                 in_feats,
                 n_objects,
                 n_hidden,
                 n_classes,
                 n_layers,
                 etypes,
                 activation,
                 dropout,
                 embedding,
                 weighted):
        super(GGCN_Metric_Attn_L_NT_Tseq_C, self).__init__()
        self.n_classes = n_classes
        self.etypes = etypes
        self.name = "GGCN_Metric_Attn_L_NT_Tseq_C_" + str(n_hidden) + "_" + str(n_layers)
        self.n_hidden = n_hidden
        self.layers = nn.ModuleList()
        self.layers.append(nn.Linear(in_feats + n_objects*4, n_hidden))
        for i in range(n_layers - 1):
            self.layers.append(nn.Linear(n_hidden, n_hidden))
        self.tool_lstm = nn.LSTM(n_hidden, n_hidden)
        self.attention = nn.Linear(n_hidden + n_hidden + n_hidden, n_hidden)
        self.attention2 = nn.Linear(n_hidden, 1)
        self.embed = nn.Linear(PRETRAINED_VECTOR_SIZE, n_hidden)
        self.fc1 = nn.Linear(4 * n_hidden, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, 1)
        self.p1  = nn.Linear(3 * n_hidden, n_hidden)
        self.p2  = nn.Linear(n_hidden, 1)
        self.final = nn.Sigmoid()
        self.activation = nn.PReLU()

    def forward(self, g_list, goalVec, goalObjectsVec, tool_vec, t_list):
        tool_embedding = self.activation(self.embed(tool_vec))
        t_list = [(tool_embedding[TOOLS.index(i)] if i!='no-tool' else torch.zeros(self.n_hidden)).view(1, -1) for i in t_list]
        lstm_hidden = (torch.randn(1, 1, self.n_hidden), torch.randn(1, 1, self.n_hidden))
        goalObjectsVec = self.activation(self.embed(goalObjectsVec))
        goal_embed = self.activation(self.embed(goalVec))
        predicted_tools = []
        for ind,g in enumerate(g_list):
            h = g.ndata['feat']
            edgeMatrices = [g.adjacency_matrix(etype=t) for t in self.etypes]
            edges = torch.cat(edgeMatrices, 1).to_dense()
            h = torch.cat((h, edges), 1)
            for i, layer in enumerate(self.layers):
                h = self.activation(layer(h))
            if (ind != 0):
                lstm_out, lstm_hidden = self.tool_lstm(t_list[ind-1].view(1,1,-1), lstm_hidden)
            else:
                lstm_out = torch.zeros(1, 1, self.n_hidden)
            lstm_out = lstm_out.view(-1)
            attn_embedding = torch.cat([h, goalObjectsVec.repeat(h.size(0)).view(h.size(0), -1), lstm_out.repeat(h.size(0)).view(h.size(0), -1)], 1)
            attn_embedding = self.activation(self.attention(attn_embedding))
            attn_weights = F.softmax(self.attention2(attn_embedding), dim=0)
            scene_embedding = torch.mm(attn_weights.t(), h)
            scene_and_goal = torch.cat([scene_embedding, goal_embed.view(1,-1), lstm_out.view(1,-1)], 1)
            l = []
            for i in range(NUMTOOLS-1):
                final_to_decode = torch.cat([scene_and_goal, tool_embedding[i].view(1, -1)], 1)
                h = self.activation(self.fc1(final_to_decode))
                h = self.activation(self.fc2(h))
                h = self.activation(self.fc3(h))
                h = self.final(self.fc4(h))
                l.append(h.flatten())
            tools = torch.stack(l)
            probNoTool = self.activation(self.p1(scene_and_goal))
            probNoTool = torch.sigmoid(self.activation(self.p2(probNoTool))).flatten()
            output = torch.cat(((1-probNoTool)*tools.flatten(), probNoTool), dim=0)
            predicted_tools.append(output)
        return predicted_tools