"""
Created on Mar 1, 2020
Pytorch Implementation of LightGCN in
Xiangnan He et al. LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation

@author: Jianbai Ye (gusye@mail.ustc.edu.cn)

Define models here
"""
import world
import torch
from dataloader import BasicDataset
from torch import nn
import numpy as np
import torch.nn.functional as F


class BasicModel(nn.Module):    
    def __init__(self):
        super(BasicModel, self).__init__()
    
    def getUsersRating(self, users):
        raise NotImplementedError
    
class PairWiseModel(BasicModel):
    def __init__(self):
        super(PairWiseModel, self).__init__()
    def bpr_loss(self, users, pos, neg):
        """
        Parameters:
            users: users list 
            pos: positive items for corresponding users
            neg: negative items for corresponding users
        Return:
            (log-loss, l2-loss)
        """
        raise NotImplementedError
    
class PureMF(BasicModel):
    def __init__(self, 
                 config:dict, 
                 dataset:BasicDataset):
        super(PureMF, self).__init__()
        self.num_users  = dataset.n_users
        self.num_items  = dataset.m_items
        self.latent_dim = config['latent_dim_rec']
        self.f = nn.Sigmoid()
        self.__init_weight()
        
    def __init_weight(self):
        self.embedding_user = torch.nn.Embedding(
            num_embeddings=self.num_users, embedding_dim=self.latent_dim)
        self.embedding_item = torch.nn.Embedding(
            num_embeddings=self.num_items, embedding_dim=self.latent_dim)
        print("using Normal distribution N(0,1) initialization for PureMF")
        
    def getUsersRating(self, users):
        users = users.long()
        users_emb = self.embedding_user(users)
        items_emb = self.embedding_item.weight
        scores = torch.matmul(users_emb, items_emb.t())
        return self.f(scores)
    
    def bpr_loss(self, users, pos, neg):
        users_emb = self.embedding_user(users.long())
        pos_emb   = self.embedding_item(pos.long())
        neg_emb   = self.embedding_item(neg.long())
        pos_scores= torch.sum(users_emb*pos_emb, dim=1)
        neg_scores= torch.sum(users_emb*neg_emb, dim=1)
        loss = torch.mean(nn.functional.softplus(neg_scores - pos_scores))
        reg_loss = (1/2)*(users_emb.norm(2).pow(2) + 
                          pos_emb.norm(2).pow(2) + 
                          neg_emb.norm(2).pow(2))/float(len(users))
        return loss, reg_loss
        
    def forward(self, users, items):
        users = users.long()
        items = items.long()
        users_emb = self.embedding_user(users)
        items_emb = self.embedding_item(items)
        scores = torch.sum(users_emb*items_emb, dim=1)
        return self.f(scores)

class LightGCN(BasicModel):
    def __init__(self, 
                 config:dict, 
                 dataset:BasicDataset):
        super(LightGCN, self).__init__()
        self.config = config
        self.dataset : dataloader.BasicDataset = dataset
        self.__init_weight()

    def __init_weight(self):
        self.num_users  = self.dataset.n_users
        self.num_items  = self.dataset.m_items
        self.latent_dim = self.config['latent_dim_rec']
        self.n_layers = self.config['lightGCN_n_layers']
        self.keep_prob = self.config['keep_prob']
        self.A_split = self.config['A_split']
        self.twohop = self.config['twohop']
        self.embedding_user = torch.nn.Embedding(
            num_embeddings=self.num_users, embedding_dim=self.latent_dim)
        self.embedding_item = torch.nn.Embedding(
            num_embeddings=self.num_items, embedding_dim=self.latent_dim)
        if self.config['pretrain'] == 0:
#             nn.init.xavier_uniform_(self.embedding_user.weight, gain=1)
#             nn.init.xavier_uniform_(self.embedding_item.weight, gain=1)
#             print('use xavier initilizer')
# random normal init seems to be a better choice when lightGCN actually don't use any non-linear activation function
            nn.init.normal_(self.embedding_user.weight, std=0.1)
            nn.init.normal_(self.embedding_item.weight, std=0.1)
            world.cprint('use NORMAL distribution initilizer')
        else:
            self.embedding_user.weight.data.copy_(torch.from_numpy(self.config['user_emb']))
            self.embedding_item.weight.data.copy_(torch.from_numpy(self.config['item_emb']))
            print('use pretarined data')
        self.f = nn.Sigmoid()
        self.Graph_user, self.Graph_item, self.Graph_uu, self.Graph_vv, self.Graph_du, self.Graph_dv = self.dataset.getSparseGraph()
        print(f"lgn is already to go(dropout:{self.config['dropout']})")

        # print("save_txt")
    def __dropout_x(self, x, keep_prob):
        size = x.size()
        index = x.indices().t()
        values = x.values()
        random_index = torch.rand(len(values)) + keep_prob
        random_index = random_index.int().bool()
        index = index[random_index]
        values = values[random_index]/keep_prob
        g = torch.sparse.FloatTensor(index.t(), values, size)
        return g
    
    def __dropout(self, keep_prob):
        if self.A_split:
            graph_user, graph_item, graph_uu, graph_vv, graph_du, graph_dv = [], [], [], [], [], []
            for g in self.Graph_user:
                graph_user.append(self.__dropout_x(g, keep_prob))
            for g in self.Graph_item:
                graph_item.append(self.__dropout_x(g, keep_prob))
            for g in self.Graph_uu:
                graph_uu.append(self.__dropout_x(g, keep_prob))
            for g in self.Graph_vv:
                graph_vv.append(self.__dropout_x(g, keep_prob))
            for g in self.Graph_du:
                graph_du.append(self.__dropout_x(g, keep_prob))
            for g in self.Graph_dv:
                graph_dv.append(self.__dropout_x(g, keep_prob))
        else:
            graph_user = self.__dropout_x(self.Graph_user, keep_prob)
            graph_item = self.__dropout_x(self.Graph_item, keep_prob)
            graph_uu = self.__dropout_x(self.Graph_uu, keep_prob)
            graph_vv = self.__dropout_x(self.Graph_vv, keep_prob)
            graph_du = self.__dropout_x(self.Graph_du, keep_prob)
            graph_dv = self.__dropout_x(self.Graph_dv, keep_prob)
        return graph_user, graph_item, graph_uu, graph_vv, graph_du, graph_dv
    
    def computer(self):
        """
        propagate methods for lightGCN
        """       
        users_emb = users_org = self.embedding_user.weight
        items_emb = items_org = self.embedding_item.weight
        # all_emb = torch.cat([users_emb, items_emb])
        #   torch.split(all_emb , [self.num_users, self.num_items])
        embs_user, embs_item = [users_emb], [items_emb]
        if self.config['dropout']:
            if self.training:
                print("droping")
                g_droped_user, g_droped_item, g_droped_uu, g_droped_vv = self.__dropout(self.keep_prob)
            else:
                g_droped_user, g_droped_item, g_droped_uu, g_droped_vv, g_droped_du, g_droped_dv = self.Graph_user, self.Graph_item, self.Graph_uu, self.Graph_vv, self.Graph_du, self.Graph_dv
        else:
            g_droped_user, g_droped_item, g_droped_uu, g_droped_vv, g_droped_du, g_droped_dv = self.Graph_user, self.Graph_item, self.Graph_uu, self.Graph_vv, self.Graph_du, self.Graph_dv
        
        #du_org = torch.sparse.mm(g_droped_du, users_org)
        #dv_org = torch.sparse.mm(g_droped_dv, items_org)
        du_org = g_droped_du * users_org
        dv_org = g_droped_dv * items_org
        for layer in range(self.n_layers):
            '''if self.A_split:
                temp_emb_user, temp_emb_item = [], []
                for f in range(len(g_droped_user)):
                    temp_emb_user.append(torch.sparse.mm(g_droped_user[f], users_emb))
                users_emb = torch.cat(temp_emb_user, dim=0)
                for f in range(len(g_droped_item)):
                    temp_emb_item.append(torch.sparse.mm(g_droped_item[f], items_emb))
                items_emb = torch.cat(temp_emb_item, dim=0)
            else:
                items_emb = torch.sparse.mm(g_droped_user, users_emb) + torch.sparse.mm(g_droped_vv, items_emb)
                users_emb = torch.sparse.mm(g_droped_item, items_emb) + torch.sparse.mm(g_droped_uu, users_emb)'''
            users_emb = users_emb + du_org
            items_emb = items_emb + dv_org
            uv_emb = torch.sparse.mm(g_droped_item, items_emb)
            uu_emb = torch.sparse.mm(g_droped_uu, users_emb)
            users_emb = uu_emb + uv_emb
            vu_emb = torch.sparse.mm(g_droped_user, users_emb)
            vv_emb = torch.sparse.mm(g_droped_vv, items_emb)
            items_emb = vv_emb + vu_emb
            #embs_user.append(uu_emb)
            #embs_user.append(uv_emb)
            #embs_item.append(vv_emb)
            #embs_item.append(vu_emb)
            embs_user.append(users_emb)
            embs_item.append(items_emb)
        users = torch.mean(torch.stack(embs_user, dim=1), dim=1)
        items = torch.mean(torch.stack(embs_item, dim=1), dim=1)
        #print(embs.size())
        # light_out = torch.mean(embs, dim=1)
        # users, items = torch.split(light_out, [self.num_users, self.num_items])
        return users, items
    
    def getUsersRating(self, users):
        all_users, all_items = self.computer()
        users_emb = all_users[users.long()]
        items_emb = all_items
        rating = self.f(torch.matmul(users_emb, items_emb.t()))
        return rating
    
    def getEmbedding(self, users, pos_items, neg_items):
        all_users, all_items = self.computer()
        users_emb = all_users[users]
        pos_emb = all_items[pos_items]
        neg_emb = all_items[neg_items]
        users_emb_ego = self.embedding_user(users)
        pos_emb_ego = self.embedding_item(pos_items)
        neg_emb_ego = self.embedding_item(neg_items)
        return users_emb, pos_emb, neg_emb, users_emb_ego, pos_emb_ego, neg_emb_ego
    
    def bpr_loss(self, users, pos, neg):
        (users_emb, pos_emb, neg_emb, 
        userEmb0,  posEmb0, negEmb0) = self.getEmbedding(users.long(), pos.long(), neg.long())
        reg_loss = (1/2)*(userEmb0.norm(2).pow(2) + 
                         posEmb0.norm(2).pow(2)  +
                         negEmb0.norm(2).pow(2))/float(len(users))
        pos_scores = torch.mul(users_emb, pos_emb)
        pos_scores = torch.sum(pos_scores, dim=1)
        neg_scores = torch.mul(users_emb, neg_emb)
        neg_scores = torch.sum(neg_scores, dim=1)
        
        loss = torch.mean(torch.nn.functional.softplus(neg_scores - pos_scores))
        #bipartite_loss = torch.mean(torch.square(userEmb0 - posEmb0)) + torch.mean(torch.square(userEmb0 - negEmb0))
        # ue = F.softmax(userEmb0, dim=-1)
        # pve = F.softmax(posEmb0, dim=-1)
        # nve = F.softmax(negEmb0, dim=-1)
        # bipartite_loss = torch.mean(ue * torch.log(pve)) + torch.mean(ue * torch.log(nve)) + torch.mean(pve * torch.log(ue)) + torch.mean(nve * torch.log(ue))
        # loss += self.config['ceweight'] * bipartite_loss
        
        return loss, reg_loss
       
    def forward(self, users, items):
        # compute embedding
        all_users, all_items = self.computer()
        # print('forward')
        #all_users, all_items = self.computer()
        users_emb = all_users[users]
        items_emb = all_items[items]
        inner_pro = torch.mul(users_emb, items_emb)
        gamma     = torch.sum(inner_pro, dim=1)
        return gamma
