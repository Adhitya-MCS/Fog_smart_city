"""Experiment-owned Population and replay distribution; YAFS stays unchanged."""
import hashlib
import math
import numpy as np
from yafs.population import Population
from yafs.distribution import Distribution


def source_seed(run_seed, app, message, node):
    digest=hashlib.sha256(f'{run_seed}|{app}|{message}|{node}'.encode()).digest()
    return int.from_bytes(digest[:4],'big')


def arrival_times(mean_ms, seed, horizon):
    if not math.isfinite(mean_ms) or mean_ms<=0:
        raise ValueError('Inter-arrival mean must be positive and finite')
    rng=np.random.RandomState(seed)
    times=[]
    now=0
    while True:
        # Retain native YAFS exponentialDistribution integer/minimum-one semantics.
        now+=max(1,int(rng.exponential(mean_ms)))
        if now>=horizon:return times
        times.append(now)


def periodic_times(start_ms, period_ms, horizon):
    if not (math.isfinite(period_ms) and period_ms>0 and math.isfinite(start_ms) and start_ms>=0):
        raise ValueError('Period must be positive and start non-negative')
    times=[]
    k=0
    while True:
        t=max(1,int(round(start_ms+k*period_ms)))
        if t>=horizon:return times
        if not times or t>times[-1]:times.append(t)
        k+=1


class ReplayDistribution(Distribution):
    def __init__(self, sim, times, descriptor, ledger, observation_end):
        super().__init__(name='IndependentReplay')
        self.sim=sim
        self.times=times
        self.descriptor=descriptor
        self.ledger=ledger
        self.observation_end=observation_end
        self.index=0
        self.pending=None
        self.source_des=None

    def next(self):
        # Native source loop calls next() again immediately AFTER emitting the
        # previous message. Record that acknowledged emission, not a planned one.
        if self.pending is not None:
            if self.sim.env.now!=self.pending:
                raise RuntimeError('Source replay deviated from scheduled emission')
            self.ledger.append({**self.descriptor,'source_des':self.source_des,
                                'time_emit':self.sim.env.now,'sequence':self.index-1})
            self.pending=None
        if self.index==len(self.times):
            return max(1,self.observation_end-self.sim.env.now+1)
        target=self.times[self.index]
        self.index+=1
        self.pending=target
        return target-self.sim.env.now


class JSONPopulation(Population):
    def __init__(self,name,json_data,iteration=1,run_seed=None,emission_end=10000,
                 observation_end=20000,ledger=None,planned=None,**kwargs):
        super().__init__(name=name,**kwargs)
        self.data=json_data
        self.seed=iteration if run_seed is None else run_seed
        self.emission_end=emission_end
        self.observation_end=observation_end
        self.ledger=ledger if ledger is not None else []
        self.planned=planned if planned is not None else []

    def initial_allocation(self,sim,app_name):
        for item in self.data.get('sources',[]):
            if str(item['app'])!=str(app_name):continue
            msg=sim.apps[app_name].get_message(item['message'])
            seed=source_seed(self.seed,app_name,item['message'],item['id_resource'])
            if 'period_ms' in item:times=periodic_times(float(item['start_ms']),float(item['period_ms']),self.emission_end)
            else:times=arrival_times(float(item['lambda']),seed,self.emission_end)
            descriptor=dict(app=str(app_name),module=msg.dst,message=msg.name,
                            source_node=item['id_resource'],source_seed=seed)
            dist=ReplayDistribution(sim,times,descriptor,self.ledger,self.observation_end)
            dist.source_des=sim.deploy_source(app_name,id_node=item['id_resource'],msg=msg,distribution=dist)
            self.planned.append({**descriptor,'source_des':dist.source_des,'times':times})
