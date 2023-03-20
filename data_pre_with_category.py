"""
Task:   在原有的data_netual基础上，加入地点的属性信息，并生成四类图谱三元组
"""

from __future__ import print_function
from __future__ import division

import time
import datetime
import argparse
import numpy as np
import pickle as pickle
from collections import Counter
import collections
from math import radians, cos, sin, asin, sqrt
from tqdm import tqdm
import os

from numpy.lib.function_base import select


class DataFoursquare(object):
    def __init__(self, trace_min=10, global_visit=10, hour_gap=48, min_gap=10, session_min=3, session_max=10,
                 sessions_min=3, train_split=0.8, time_split=3600, distance_split=0.06):
        tmp_path = "../data/"
        # TODO
        # self.TWITTER_PATH = tmp_path + 'dataset_TSMC2014_NYC.txt'
        self.TWITTER_PATH = tmp_path + 'Foursquare.txt'
        # self.TWITTER_PATH = tmp_path + 'Gowalla.txt'
        self.SAVE_PATH = tmp_path
        # self.save_name = 'foursquare_NYC_4input'
        self.save_name = 'Foursquare'
        # self.save_name = 'Gowalla'

        self.trace_len_min = trace_min
        self.location_global_visit_min = global_visit
        self.hour_gap = hour_gap
        self.min_gap = min_gap
        self.session_max = session_max
        self.filter_short_session = session_min
        self.sessions_count_min = sessions_min
        self.time_split = time_split
        self.distance_split = distance_split

        self.train_split = train_split

        self.data = {}
        self.venues = {}
        self.data_filter = {}
        self.user_filter3 = None
        self.uid_list = {}
        self.vid_list = {'unk': [0, -1]}
        self.vid_list_lookup = {}
        self.vid_lookup = {}
        self.tim_gap_list = {}
        self.dis_gap_list = {}
        self.pid_loc_lat = {}
        self.data_neural = {}
        self.data_temp = {}
        self.temp_dis_dict = {}
        self.kg = {'utp': {}, 'ptp': {}}
        self.triple_utp, self.triple_ptp = [], []
        self.tim, self.tim_rel, self.dis_rel, self.tim_dis_rel = [], [], [], []
        self.train_utp, self.train_ptp = [], []
        self.test_utp, self.test_ptp = [], []
        self.check_in_num = 0
        self.sessions_num = 0
        self.tim_max = 0
        self.dis_max = 0

        self.min_lon = 0x3f3f3f3f
        self.max_lon = 0
        self.min_lat = 0x3f3f3f3f
        self.max_lat = 0
        self.n1 = 100
        self.n2 = 100
        self.add = {}
        self.raw_data = []
        self.triple_prg = []
        self.category_lookup = {}
        self.pid_category_lookup = {}
        self.uid_pid = {}  # all of the pid which is considered of every user
        self.user_uid = {}
        self.data_category = {}  # added
        self.word2wid_list = {}  # word: wid
        self.wid2word_list = {}  # wid: word

        self.session_max_length = 100

    # ############# 1. read trajectory data from file
    def load_trajectory_from_tweets(self):
        with open(self.TWITTER_PATH, 'rb') as fid:
            for line in fid:
                line = line.decode("utf8", "ignore")
                uid, pid, category_id, category_name, lat, lon, non, UTC_time = line.strip('\n').split('\t')
                uid = int(uid)
                pid = int(pid)
                category_id = int(category_id)
                non = int(non)

                # print(uid, pid, category_id, category_name, lat, lon, non, UTC_time)
                # print(type(uid), type(pid), type(category_id), type(category_name), type(lat), type(lon), type(non), type(UTC_time))
                self.raw_data.append([uid, pid, category_id, category_name, lat, lon, non, UTC_time])
                # time = datetime.datetime.strptime(UTC_time, "%a %b %d %H:%M:%S %z %Y")  # 获取时间
                # tim = time.strftime("%Y-%m-%d %H:%M:%S")  # 转化时间格式
                tim = UTC_time.strip('\r')
                if uid not in self.data:  # [u1]={[loc1, time1],[loc2,time2]}
                    self.data[uid] = [[pid, tim]]
                    self.data_category[uid] = [[pid, tim, category_name]]
                else:
                    self.data[uid].append([pid, tim])
                    self.data_category[uid].append([pid, tim, category_name])
                if pid not in self.venues:  # 统计loc被访问的频次
                    self.venues[pid] = 1
                else:
                    self.venues[pid] += 1

                # read lon and lat
                self.pid_loc_lat[pid] = [float(lon), float(lat)]

    # ########### 2.0 basically filter users based on visit length and other statistics
    def filter_users_by_length(self):  # self.data:[uid]={[loc,time]}
        # TODO: 改成了LSTPM的代码
        uid_3 = [x for x in self.data if len(self.data[x]) > 0]
        pick3 = sorted([(x, len(self.data[x])) for x in uid_3], key=lambda x: x[1], reverse=True)
        pid_3 = [x for x in self.venues if self.venues[x] > 0]
        pid_pic3 = sorted([(x, self.venues[x]) for x in pid_3], key=lambda x: x[1], reverse=True)  # (loc,loc_len)
        pid_3 = dict(pid_pic3)  # 储存loc被user访问的频次的字典

        # uid_3 = [x for x in self.data if len(self.data[x]) >= self.trace_len_min]  # 保留用户访问的序列大于trace_len_min的用户
        # pick3 = sorted([(x, len(self.data[x])) for x in uid_3], key=lambda x: x[1], reverse=True)  # (user, user_len)
        # pid_3 = [x for x in self.venues if self.venues[x] >= self.location_global_visit_min]  # 保留被用户访问大于loc的最小值的loc
        # pid_pic3 = sorted([(x, self.venues[x]) for x in pid_3], key=lambda x: x[1], reverse=True)  # (loc,loc_len)
        # pid_3 = dict(pid_pic3)  # 储存loc被user访问的频次的字典

        session_len_list = []
        for u in pick3:  # 开始为每个用户划分session
            uid = u[0]
            # info = self.data[uid]
            info = self.data_category[uid]  # [pid, tim, category_name]
            topk = Counter([x[0] for x in info]).most_common()  # 列表储存每一个用户访问loc的频次
            topk1 = [x[0] for x in topk if x[1] > 1]  # 储存loc,过滤一个用户访问至少访问同一个地点两次
            sessions = {}
            sessions_with_category = {}

            ##############################################################
            ##############################################################
            ##############################################################
            # TODO: 按照LSTPM的代码修改
            for i in range(len(info) - 1):
                sessions[i] = self.data[uid][:i + 2]
                sessions_with_category[i] = info[:i + 2]
                if len(sessions[i]) > self.session_max_length:
                    sessions[i] = sessions[i][-self.session_max_length:]
                    sessions_with_category[i] = sessions_with_category[i][-self.session_max_length:]
            ##############################################################
            ##############################################################
            ##############################################################
            # for i, record in enumerate(info):  # record储存[loc,tim]
            #     poi, tmd, word = record
            #     record = [poi, tmd]
            #     record_category = [poi, tmd, word]
            #     try:
            #         tid = int(time.mktime(time.strptime(tmd, "%Y-%m-%d %H:%M:%S")))  # 将时间格式转换成时间戳
            #     except Exception as e:
            #         print('error:{}'.format(e))
            #         continue
            #     sid = len(sessions)
            #     if poi not in pid_3 and poi not in topk1:  # 过滤掉被访问频次低的loc
            #         # if poi not in topk1:
            #         continue
            #     if i == 0 or len(sessions) == 0:  # session[user]={[loc1,tim1],[loc2,tim2]}
            #         sessions[sid] = [record]
            #         sessions_with_category[sid] = [record_category]
            #     else:
            #         if (tid - last_tid) / 3600 > self.hour_gap or len(
            #                 sessions[sid - 1]) > self.session_max:  # 大于24h或者每一个session的长度大于10
            #             sessions[sid] = [record]
            #             sessions_with_category[sid] = [record_category]
            #         elif (tid - last_tid) / 60 > self.min_gap:  # 大于10分钟
            #             sessions[sid - 1].append(record)
            #             sessions_with_category[sid - 1].append(record_category)
            #         else:
            #             pass
            #     last_tid = tid
            ##############################################################
            ##############################################################
            ##############################################################

            sessions_filter = {}
            sessions_filter_category = {}
            for s, s_c in zip(sessions, sessions_with_category):
                if len(sessions[s]) >= 0:
                    # if len(sessions[s]) >= self.filter_short_session:
                    sessions_filter[len(sessions_filter)] = sessions[s]
                    sessions_filter_category[len(sessions_filter_category)] = sessions_with_category[s_c]
                    session_len_list.append(len(sessions[s]))  # session长度
            if len(sessions_filter) >= 0:
                # if len(sessions_filter) >= self.sessions_count_min:  #
                self.data_filter[uid] = {'sessions_count': len(sessions_filter), 'topk_count': len(topk), 'topk': topk,
                                         'sessions': sessions_filter, 'sessions_category': sessions_filter_category,
                                         'raw_sessions': sessions, 'raw_sessions_category': sessions_with_category}

        self.user_filter3 = [x for x in self.data_filter if
                             self.data_filter[x]['sessions_count'] >= 0]
        # self.user_filter3 = [x for x in self.data_filter if
        #                      self.data_filter[x]['sessions_count'] >= self.sessions_count_min]

    # ########### 3. build dictionary for users and location
    def build_users_locations_dict(self):  # loc->loc_id
        for u in self.user_filter3:  # 获取用户
            sessions = self.data_filter[u]['sessions']
            if u not in self.uid_list:
                self.uid_list[u] = [len(self.uid_list),
                                    len(sessions)]  # 存储user字典，[user:[len(user_id),len(user_session)]]
            for sid in sessions:  # 用户的每个session
                poi = [p[0] for p in sessions[sid]]  # loc
                for p in poi:
                    if p not in self.vid_list:
                        self.vid_list_lookup[len(self.vid_list)] = p  # loc->loc_id
                        self.vid_list[p] = [len(self.vid_list), 1]  # 字典类型，[loc:[loc_id,loc_num]]
                    else:
                        self.vid_list[p][1] += 1

    # ########### 4. remap lon and lat
    def venues_lookup(self):  # vid=lon_lat
        for vid in self.vid_list_lookup:
            pid = self.vid_list_lookup[vid]
            lon_lat = self.pid_loc_lat[pid]
            self.vid_lookup[vid] = lon_lat

    # ########## 5.0 prepare training data for neural network
    @staticmethod
    def tid_list(tmd):
        tm = time.strptime(tmd, "%Y-%m-%d %H:%M:%S")
        tid = tm.tm_wday * 24 + tm.tm_hour
        return tid

    @staticmethod
    def tid_list_48(tmd):
        tm = time.strptime(tmd, "%Y-%m-%d %H:%M:%S")
        if tm.tm_wday in [0, 1, 2, 3, 4]:
            tid = tm.tm_hour
        else:
            tid = tm.tm_hour + 24
        return tid

    @staticmethod
    def distance(lng1, lat1, lng2, lat2):
        lng1, lat1, lng2, lat2 = map(radians, [float(lng1), float(lat1), float(lng2), float(lat2)])
        dlon = lng2 - lng1
        dlat = lat2 - lat1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        distance = 2 * asin(sqrt(a)) * 6371 * 1000
        distance = round(distance / 1000, 3)
        return distance

    @staticmethod
    def ptp_dict(tim_dis_rel):
        tim_dis = {}
        count = 0
        for id in tim_dis_rel:
            if tuple(id) not in tim_dis.keys():
                tim_dis[tuple(id)] = count
                count = count + 1
        return tim_dis

    @staticmethod
    def filtering_triple(triple):
        triple1 = []
        count = 0
        for tri in triple:
            count += 1
            print(count)
            if tri not in triple1:
                triple1.append(tri)
        return triple1

    def prepare_neural_data(self):
        num = 0
        for u in tqdm(self.uid_list):
            uid = self.uid_list[u][0]
            sessions = self.data_filter[u]['sessions']  # [pid, tim]
            sessions_word = self.data_filter[u]['sessions_category']  # [pid, tim, category_name]
            sessions_check = {}
            sessions_check_word = {}
            sessions_trans = {}
            sessions_id = []
            sessions_utp = {}
            self.sessions_num += len(sessions)
            num += 1
            for sid in sessions:  # step1: 获取用户的session
                trans = []
                gap_list = []
                for i in range(len(sessions[sid]) - 1):  # step2: 获取每个序列的时间和地理距离间隔
                    # build triple (user, tim, loc)
                    j = i + 1
                    self.check_in_num += 1
                    # 计算每个序列之间的时间和地理距离
                    pid = self.vid_list[sessions[sid][i][0]][0]
                    ti_pre = int(time.mktime(time.strptime(sessions[sid][i][1], "%Y-%m-%d %H:%M:%S")))
                    lat_pre = float(self.vid_lookup[pid][0])
                    lon_pre = float(self.vid_lookup[pid][1])

                    pid_next = self.vid_list[sessions[sid][j][0]][0]
                    ti_next = int(time.mktime(time.strptime(sessions[sid][j][1], "%Y-%m-%d %H:%M:%S")))
                    lat_next = float(self.vid_lookup[pid_next][0])
                    lon_next = float(self.vid_lookup[pid_next][1])

                    t_gap = ti_next - ti_pre
                    d_gap = self.distance(lon_pre, lat_pre, lon_next, lat_next)
                    t = int(float(t_gap) / self.time_split)
                    d = int(float(d_gap) / self.distance_split)
                    self.tim_max = max(self.tim_max, t)
                    self.dis_max = max(self.dis_max, d)
                    gap_list.append([t, d])
                    pid_gap = tuple([pid, pid_next])
                    if pid_gap not in self.temp_dis_dict:
                        self.temp_dis_dict[pid_gap] = [[t, d]]
                    else:
                        self.temp_dis_dict[pid_gap].append([t, d])
                    trans.append([pid, tuple([t, d]), pid_next])  # POI之间的转移三元组
                # 保存所需的数据，check-in data， transfer data
                sessions_check[sid] = [[self.vid_list[p[0]][0], self.tid_list_48(p[1])] for p in
                                       sessions[sid]]  # 映射loc->loc_id
                sessions_check_word[sid] = [[self.vid_list[p[0]][0], self.tid_list_48(p[1]), self.word2wid_list[p[2]]]
                                            for p in sessions_word[sid]]
                sessions_utp[sid] = [[uid, self.tid_list_48(p[1]), self.vid_list[p[0]][0]] for p in
                                     sessions[sid]]  # 映射loc->loc_id
                t_list = [self.tid_list_48(p[1]) for p in sessions[sid]]
                self.tim.extend(t_list)
                self.tim_rel.extend([k[0] for k in gap_list])
                self.dis_rel.extend([k[1] for k in gap_list])
                self.tim_dis_rel.extend(gap_list)  # 在列表最后追加列表
                self.triple_utp.extend(sessions_utp[sid])
                self.triple_ptp.extend(trans)
                sessions_trans[sid] = trans
                sessions_id.append(sid)  # 存储用户访问的session

            # # 根据每个用户按照8:1:1（或6:2:2）划分训练集，验证集和测试集
            # split_train_id = int(np.floor(self.train_split * len(sessions_id)))
            # split_vaild_id = int(np.float(0.9 * len(sessions_id)))
            # train_id = sessions_id[:split_train_id]  # session中前80%做train
            # vaild_id = sessions_id[split_train_id:split_vaild_id]
            # test_id = sessions_id[split_vaild_id:]  # session后10%做test
            # TODO: 这里改成STAN的划分形式
            train_id = sessions_id[:-2]
            vaild_id = sessions_id[-2:-1]
            test_id = sessions_id[-1:]

            self.user_uid[u] = self.uid_list[u][0]
            self.data_neural[self.uid_list[u][0]] = {'sessions': sessions_check,
                                                     'sessions_with_word': sessions_check_word, 'train': train_id,
                                                     'test': test_id, 'vaild': vaild_id,
                                                     'sessions_trans': sessions_trans}
            self.data_temp[self.uid_list[u][0]] = {'sessions_utp': sessions_utp, 'sessions_id': sessions_id}

    def construct_data(self, n_tim_rel, tim_dis_dict):
        # train_kg_ptp, train_kg_upt, train_kg = [], [], []
        train_kg_dict, train_kg = collections.defaultdict(list), collections.defaultdict(list)
        n_locs = len(self.vid_list)
        # get utp-triple 
        head_upt = [(triple[0] + n_locs) for triple in self.train_utp]
        rel_upt = [triple[1] for triple in self.train_utp]
        tail_upt = [triple[2] for triple in self.train_utp]
        # get ptp-triple
        head_ptp = [triple[0] for triple in self.train_ptp]
        rel_ptp = [int(tim_dis_dict[tuple(triple[1])] + n_tim_rel) for triple in self.train_ptp]
        tail_ptp = [triple[2] for triple in self.train_ptp]
        print("---------start utp------------")
        upt_mat = np.array((head_upt, rel_upt, tail_upt))  # 3 * n
        upt_mat = upt_mat.T  # n * 3
        temp = list(set([tuple(t) for t in upt_mat]))  # 去重
        temp = [list(v) for v in temp]  # tuple->list
        train_kg['utp'] = temp
        for i in range(len(temp)):
            train_kg_dict[temp[i][0]].append((temp[i][2], temp[i][1]))
        # TODO: 修改了代码，原先的代码跑的太慢了
        # for i in tqdm(range(len(head_upt))):
        #     if [head_upt[i], rel_upt[i], tail_upt[i]] not in train_kg['utp']:
        #         train_kg_dict[head_upt[i]].append((tail_upt[i], rel_upt[i]))
        #         train_kg['utp'].append([head_upt[i], rel_upt[i], tail_upt[i]])

        print("---------start ptp------------")
        ptp_mat = np.array((head_ptp, rel_ptp, tail_ptp))  # 3 * n
        ptp_mat = ptp_mat.T  # n * 3
        temp = list(set([tuple(t) for t in ptp_mat]))  # 去重
        temp = [list(v) for v in temp]  # tuple->list
        train_kg['ptp'] = temp
        for i in range(len(temp)):
            train_kg_dict[temp[i][0]].append((temp[i][2], temp[i][1]))
        # for j in tqdm(range(len(head_ptp))):
        #     if [head_ptp[j], rel_ptp[j], tail_ptp[j]] not in train_kg['ptp']:
        #         train_kg_dict[head_ptp[j]].append((tail_ptp[j], rel_ptp[j]))
        #         train_kg['ptp'].append([head_ptp[j], rel_ptp[j], tail_ptp[j]])
        print('load KG data.')
        return train_kg_dict, train_kg

    def prepare_kg_data(self):
        for u in self.data_neural:
            for k in self.data_neural[u]['train']:
                self.train_utp.extend([p for p in self.data_temp[u]['sessions_utp'][k]])
                self.train_ptp.extend([q for q in self.data_neural[u]['sessions_trans'][k]])
        utp_triple, ptp_triple = self.triple_utp, self.triple_ptp
        n_tim_rel = len(list(set(self.tim)))
        tim_dis_dict = self.ptp_dict(self.tim_dis_rel)
        train_kg_dict, train_kg = self.construct_data(n_tim_rel, tim_dis_dict)

        # store kg data
        # self.kg['utp'] = self.filtering_triple(utp_triple)  
        # self.kg['ptp'] = self.filtering_triple(ptp_triple)
        self.kg['ptp_dict'] = tim_dis_dict
        self.kg['poi_trans'] = self.temp_dis_dict
        self.kg['timining_rel'] = list(set(self.tim))
        self.kg['tim_rel'] = list(set(self.tim_rel))
        self.kg['dis_rel'] = list(set(self.dis_rel))
        self.kg['train_kg'] = np.concatenate([train_kg['utp'], train_kg['ptp']])
        self.kg['train_kg_dict'] = train_kg_dict
        # self.kg['train_utp'] = self.train_utp
        # self.kg['train_ptp'] = self.train_ptp
        self.kg['max_dis_tim'] = [self.tim_max, self.dis_max]

    # add for triple3
    # ############# 用来生成word字典
    def prepare_category_dict(self):
        index = 0
        for user in self.data_filter:
            sessions_with_category = self.data_filter[user]['sessions_category']
            for i, records in enumerate(sessions_with_category.values()):
                for record in records:
                    word = record[2]
                    if word not in self.word2wid_list:
                        self.word2wid_list[word] = index
                        self.wid2word_list[index] = word
                        index += 1

    def calculate_grid_id(self, lon, lat):
        if lon < self.min_lon or lon > self.max_lon or lat < self.min_lat or lat > self.max_lat:
            print('Error in calculation grid ID.')
            return -1
        row_interval = (self.max_lat - self.min_lat) / self.n2
        col_interval = (self.max_lon - self.min_lon) / self.n1
        ID = int((lon - self.min_lon) / col_interval) + 1 + int((lat - self.min_lat) / row_interval) * self.n1
        return ID

    def add_id(self):
        # unify entity id
        self.add['pid'] = 0
        self.add['uid'] = len(self.vid_list)
        self.add['category_name_id'] = len(self.vid_list) + len(self.uid_list) - 1 + 1
        self.add['grid_id'] = len(self.vid_list) + len(self.uid_list) - 1 + 1 + len(self.category_lookup) - 1
        # unify relation id
        self.add['time'] = 0
        self.add['ptp_relation'] = 48 + 1
        self.add['category_relation'] = len(self.kg['ptp_dict']) + 49
        # self.add['loc_relation'] = len(self.kg['ptp_dict']) + 49 + len(self.category_lookup)
        self.add['loc_relation'] = len(self.kg['ptp_dict']) + 49 + 1

    def prepare_category_data(self):
        # form category_lookup Rid: relation and pid_category_lookup pid: Rid
        # and calculate the interval of coordinates
        relation2pid = {}  # relation : pid
        for vid in tqdm(self.vid_lookup):
            lon, lat = self.vid_lookup[vid]
            self.max_lon = max(lon, self.max_lon)
            self.min_lon = min(lon, self.min_lon)
            self.max_lat = max(lat, self.max_lat)
            self.min_lat = min(lat, self.min_lat)

            loc = self.vid_list_lookup[vid]
            relation = []
            for line in self.raw_data:
                if loc == line[1]:
                    relation = [0, line[3]]  # 这里不允许出现重复的category name,所以不考虑category id了
                    break
            relation = tuple(relation)
            if relation not in self.category_lookup.values():
                self.pid_category_lookup[vid] = len(self.category_lookup)
                relation2pid[relation] = len(self.category_lookup)
                self.category_lookup[len(self.category_lookup)] = relation
            else:
                self.pid_category_lookup[vid] = relation2pid[relation]

        # form category_triple in data_neural and triple_prg
        for usr in self.data_filter:
            uid = self.user_uid[usr]
            for session in self.data_neural[uid]['sessions'].values():
                pid_list = [pid[0] for pid in session]
                if uid not in self.uid_pid:
                    self.uid_pid[uid] = pid_list
                else:
                    self.uid_pid[uid] = self.uid_pid[uid] + pid_list
            self.uid_pid[uid] = list(set(self.uid_pid[uid]))

        for uid in tqdm(self.data_neural):
            self.data_neural[uid]['category_triple'] = []
            for pid in self.uid_pid[uid]:
                lon, lat = self.vid_lookup[pid]
                grid_id = self.calculate_grid_id(lon, lat)
                r_id = self.pid_category_lookup[pid]
                triple = [pid, r_id, grid_id]
                if triple not in self.triple_prg:
                    self.triple_prg.append(triple)
                if triple not in self.data_neural[uid]['category_triple']:
                    self.data_neural[uid]['category_triple'].append(triple)

    # ############# 6. save variables
    def get_parameters(self):
        parameters = {}
        parameters['TWITTER_PATH'] = self.TWITTER_PATH
        parameters['SAVE_PATH'] = self.SAVE_PATH
        parameters['trace_len_min'] = self.trace_len_min
        parameters['location_global_visit_min'] = self.location_global_visit_min
        parameters['hour_gap'] = self.hour_gap
        parameters['min_gap'] = self.min_gap
        parameters['session_max'] = self.session_max
        parameters['filter_short_session'] = self.filter_short_session
        parameters['sessions_min'] = self.sessions_count_min
        parameters['train_split'] = self.train_split

        return parameters

    def save_variables(self):
        foursquare_dataset = {'data_neural': self.data_neural, 'wid2word_list': self.wid2word_list,
                              'vid_list': self.vid_list, 'uid_list': self.uid_list,
                              'parameters': self.get_parameters(), 'data_filter': self.data_filter,
                              'vid_lookup': self.vid_lookup, 'KG': self.kg}
        pickle.dump(foursquare_dataset, open(self.SAVE_PATH + self.save_name + '.pkl', 'wb'))

    # ############# 7. save files
    def writee(self):
        # entity
        with open("../data/entity_user_dict.txt", "w") as f:
            for user in self.uid_list:
                uid = self.uid_list[user][0] + self.add['uid']
                f.write(str(uid) + '\t' + str(user) + '\n')

        with open("../data/entity_loc_dict.txt", "w") as f:
            for loc in self.vid_list:
                if loc == 'unk':
                    continue
                pid = self.vid_list[loc][0] + self.add['pid']
                f.write(str(pid) + '\t' + str(loc) + '\n')

        with open("../data/entity_category_name_id.txt", "w") as f:
            for cid in self.category_lookup:
                name = self.category_lookup[cid][1]
                cid = cid + self.add['category_name_id']
                f.write(str(cid) + '\t' + str(name) + '\n')

        with open("../data/entity_grid_id.txt", "w") as f:
            for i in range(100):
                f.write(str(i + 1 + self.add['grid_id']) + '\t' + str(i + 1) + '\n')
        # relation
        with open("../data/relation_time_id.txt", "w") as f:
            for i in range(49):
                f.write(str(i + self.add['time']) + '\t' + str(i) + '\n')

        with open("../data/relation_td_id.txt", "w") as f:
            for tuplee in self.kg['ptp_dict']:
                idd = self.kg['ptp_dict'][tuplee] + self.add['ptp_relation']
                f.write(str(idd) + '\t' + str(tuplee) + '\n')

        with open("../data/relation_category_id.txt", "w") as f:
            true_cid = int(list(self.category_lookup.keys())[0]) + self.add['category_relation']
            f.write(str(true_cid) + '\t' + 'belong to')

        with open("../data/relation_loc_id.txt", "w") as f:
            f.write(str(self.add['loc_relation']) + '\t' + 'locate')

        # triple
        with open("../data/triple_utp.txt", "w") as f:
            for triple in self.triple_utp:
                uid = triple[0] + self.add['uid']
                timee = triple[1] + self.add['time']
                pid = triple[2] + self.add['pid']
                f.write(str(uid) + '\t' + str(timee) + '\t' + str(pid) + '\n')

        with open("../data/triple_ptp.txt", "w") as f:
            for triple in self.triple_ptp:
                pid1 = triple[0] + self.add['pid']
                pid2 = triple[2] + self.add['pid']
                relation = self.kg['ptp_dict'][triple[1]] + self.add['ptp_relation']
                f.write(str(pid1) + '\t' + str(relation) + '\t' + str(pid2) + '\n')

        with open("../data/triple_pc.txt", "w") as f:
            true_cid = int(list(self.category_lookup.keys())[0]) + self.add['category_relation']
            for triple in self.triple_prg:
                pid = triple[0] + self.add['pid']
                # relation = triple[1] + self.add['category_relation']
                name = triple[1] + self.add['category_name_id']
                f.write(str(pid) + '\t' + str(true_cid) + '\t' + str(name) + '\n')

        with open("../data/triple_plg.txt", "w") as f:
            for triple in self.triple_prg:
                pid = triple[0] + self.add['pid']
                relation = self.add['loc_relation']
                grid_id = triple[2] + self.add['grid_id']
                f.write(str(pid) + '\t' + str(relation) + '\t' + str(grid_id) + '\n')


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace_min', type=int, default=10, help="raw trace length filter threshold")
    parser.add_argument('--global_visit', type=int, default=10, help="location global visit threshold")
    parser.add_argument('--hour_gap', type=int, default=24, help="maximum interval of two trajectory points")
    parser.add_argument('--min_gap', type=int, default=10, help="minimum interval of two trajectory points")
    parser.add_argument('--session_max', type=int, default=10, help="control the length of session not too long")
    parser.add_argument('--session_min', type=int, default=3, help="control the length of session not too short")
    parser.add_argument('--sessions_min', type=int, default=5, help="the minimum amount of the good user's sessions")
    parser.add_argument('--train_split', type=float, default=0.8, help="train/test ratio")
    parser.add_argument('--time_gap', type=float, default=3600, help="time gap")
    parser.add_argument('--distance_gap', type=float, default=0.06, help="distance_gap")
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    data_generator = DataFoursquare(trace_min=args.trace_min, global_visit=args.global_visit,
                                    hour_gap=args.hour_gap, min_gap=args.min_gap,
                                    session_min=args.session_min, session_max=args.session_max,
                                    sessions_min=args.sessions_min, train_split=args.train_split,
                                    time_split=args.time_gap, distance_split=args.distance_gap)
    parameters = data_generator.get_parameters()
    print('############PARAMETER SETTINGS:\n' + '\n'.join([p + ':' + str(parameters[p]) for p in parameters]))
    print('############START PROCESSING:')
    print('load trajectory from {}'.format(data_generator.TWITTER_PATH))
    data_generator.load_trajectory_from_tweets()
    print('filter users')
    data_generator.filter_users_by_length()
    print('build users/locations dictionary')
    data_generator.build_users_locations_dict()
    # data_generator.load_venues()
    data_generator.venues_lookup()  # 映射loc->loc_id
    data_generator.prepare_category_dict()
    print('prepare data for neural network')
    data_generator.prepare_neural_data()
    data_generator.prepare_kg_data()
    print('prepare triple3 for neural network:')
    data_generator.prepare_category_data()
    data_generator.add_id()
    print('save prepared data')
    data_generator.save_variables()
    data_generator.writee()
    print('raw users:{} raw locations:{}'.format(
        len(data_generator.data), len(data_generator.venues)))
    print('final users:{} final locations:{} '.format(
        len(data_generator.data_neural), len(data_generator.vid_list)))
    print('check_in num:{} sessions length:{} '.format(
        data_generator.check_in_num, data_generator.sessions_num))
    print('triple num:{} '.format(
        len(data_generator.kg['utp']) + len(data_generator.kg['ptp'])))
