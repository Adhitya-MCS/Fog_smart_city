import contextlib
import copy
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from config.units import engine_topology
from runner.json_population import source_seed,arrival_times
from runner.run_simulation import run_simulation
from runner.search import optimize
from runner.integrity import verify_yafs
from placements.metaheuristic import _common as common
from analysis.constraint_analysis import compute_metrics_for_trace
from analysis.statistik import paired_values,rank_biserial,holm


def fixture(tasks=1,source=0,target=1):
    topology={'entity':[dict(id=0,IPT=2000,RAM=100,type='FOG'),dict(id=1,IPT=2000,RAM=100,type='CLOUD')],
              'link':[dict(s=0,d=1,BW=75000,PR=10)]}
    app=dict(id=0,name='0',deadline=100,module=[],message=[],transmission=[])
    users={'sources':[]};alloc=[]
    for i in range(tasks):
        module=f'0_{i}';act=module+'_ACT';req=f'M.USER.{i}';resp=f'R.{i}'
        app['module'] += [dict(id=i,name=module,RAM=1,instructions=20000,bytes=3000000,output_bytes=0,deadline=100,type='MODULE'),
                          dict(id=100+i,name=act,RAM=0,instructions=0,bytes=0,deadline=100,type='ACTUATOR',source_message=req)]
        app['message'] += [dict(id=2*i,name=req,s='None',d=module,instructions=20000,bytes=3000000),
                           dict(id=2*i+1,name=resp,s=module,d=act,instructions=0,bytes=0)]
        app['transmission'] += [dict(module=module,message_in=req,message_out=resp),dict(module=act,message_in=resp)]
        users['sources'].append(dict(app='0',message=req,id_resource=source,**{'lambda':200}))
        alloc += [dict(app='0',module_name=module,id_resource=target),dict(app='0',module_name=act,id_resource=source)]
    return topology,[app],users,alloc


class YAFSProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def execute(self,data=None,times=None,horizon=100,drain=100):
        topology,apps,users,alloc=data or fixture()
        scenario=self.root/'scenario';scenario.mkdir()
        for name,value in [('networkDefinition.json',topology),('appDefinition.json',apps),('usersDefinition.json',users),('allocDefinitionTest.json',{'initialAllocation':alloc})]:
            (scenario/name).write_text(json.dumps(value))
        result=self.root/'result'
        with warnings.catch_warnings(), contextlib.redirect_stdout(io.StringIO()):
            warnings.simplefilter('ignore')
            with patch('runner.json_population.arrival_times',return_value=[1] if times is None else times):
                run_simulation('TestPlacement',horizon,results_dir=result,scenarios_dir=scenario,drain_time=drain,run_seed=7)
        return result,compute_metrics_for_trace(result/'sim_trace.csv')

    def test_yafs_identity(self):
        self.assertEqual(len(verify_yafs()),12)

    def test_adapter_preserves_input(self):
        topology,*_=fixture();before=copy.deepcopy(topology)
        adapted=engine_topology(topology)
        self.assertEqual(topology,before)
        self.assertEqual(adapted['link'][0]['BW'],0.075)
        with self.assertRaises(ValueError):engine_topology(adapted)

    def test_optimizer_matches_native_roundtrip(self):
        data=fixture();prob=common.build_problem(*data[:3])
        expected=sum(common._calc_times(0,1,prob))*1000
        result,m=self.execute(data)
        self.assertAlmostEqual(expected,70)
        self.assertAlmostEqual(m['mean_completed_response_ms'],expected)
        self.assertAlmostEqual(pd.read_csv(result/'sim_trace_link.csv')['latency'].iloc[0],50)

    def test_native_link_queue_semantics_preserved(self):
        _,m=self.execute(times=[1,2])
        # YAFS queues transmission+propagation: roundtrips 70 and 119 ms.
        self.assertAlmostEqual(m['mean_completed_response_ms'],94.5)
        self.assertAlmostEqual(m['max_observed_response_ms'],119)

    def test_native_per_module_cpu_preserved(self):
        result,m=self.execute(fixture(tasks=2,target=0))
        task=pd.read_csv(result/'sim_trace.csv')
        task=task[~task['module'].str.endswith('_ACT')]
        self.assertEqual(task['time_in'].tolist(),[1,1])
        self.assertEqual(task['time_out'].tolist(),[11,11])
        self.assertEqual(m['completed'],2)

    def test_unfinished_local_emission_counted(self):
        result,m=self.execute(fixture(target=0),horizon=5,drain=0)
        self.assertEqual(m['emitted'],1)
        self.assertEqual(m['unfinished'],1)
        self.assertEqual(m['projected_computations_not_finished'],1)
        self.assertIsNone(m['mean_completed_response_ms'])
        self.assertEqual(m['deadline_pending'],1)

    def test_expired_unfinished_is_deadline_miss(self):
        data=fixture(target=0);data[1][0]['deadline']=2
        _,m=self.execute(data,horizon=5,drain=0)
        self.assertEqual(m['deadline_miss_ratio'],1)
        self.assertEqual(m['ontime_delivery_ratio'],0)
        self.assertIsNone(m['completed_only_slav'])

    def test_drain_completes_request(self):
        _,m=self.execute(fixture(target=0),horizon=5,drain=20)
        self.assertEqual(m['completion_ratio'],1)
        self.assertEqual(m['completion_by_emission_end'],0)

    def test_empty_emissions(self):
        _,m=self.execute(times=[])
        self.assertEqual(m['emitted'],0)
        self.assertIsNone(m['completion_ratio'])

    def test_multihop_matches_native(self):
        topology,apps,users,alloc=fixture()
        topology['entity'].append(dict(id=2,IPT=2000,RAM=100,type='FOG'))
        topology['link']=[dict(s=0,d=2,BW=75000,PR=3),dict(s=2,d=1,BW=37500,PR=7)]
        expected=sum(common._calc_times(0,1,common.build_problem(topology,apps,users)))*1000
        _,m=self.execute((topology,apps,users,alloc),horizon=100,drain=200)
        self.assertAlmostEqual(expected,150)
        self.assertAlmostEqual(m['mean_completed_response_ms'],expected)

    def test_diagnosis_splits_latency_without_queueing(self):
        from analysis.diagnosis import diagnose_instance
        topology,apps,users,alloc=fixture()
        topology['entity'].append(dict(id=2,IPT=2000,RAM=100,type='FOG'))
        topology['link']=[dict(s=0,d=2,BW=75000,PR=3),dict(s=2,d=1,BW=37500,PR=7)]
        result,m=self.execute((topology,apps,users,alloc),horizon=100,drain=200)
        row=diagnose_instance(result)
        self.assertEqual(row['completed'],1)
        self.assertAlmostEqual(row['mean_total_ms'],m['mean_completed_response_ms'])
        self.assertAlmostEqual(row['mean_net_queue_ms'],0.0)
        self.assertAlmostEqual(row['mean_module_wait_ms'],0.0)
        self.assertAlmostEqual(row['mean_proc_ms']+row['mean_ideal_net_ms'],row['mean_total_ms'])

    def test_source_streams(self):
        a=source_seed(1,'0','a',0);b=source_seed(1,'0','b',0)
        self.assertNotEqual(a,b)
        self.assertEqual(arrival_times(200,a,10000),arrival_times(200,a,10000))
        self.assertNotEqual(arrival_times(200,a,10000),arrival_times(200,b,10000))
        self.assertNotEqual(a,source_seed(2,'0','a',0))

    def test_cpu_reservation_not_replaced(self):
        topology,apps,users,_=fixture()
        prob=common.build_problem(topology,apps,users)
        self.assertEqual(prob.service_cpu[0],20000/100)

    def test_budgets_and_capacity(self):
        topology,apps,users,_=fixture(tasks=2)
        for name in ['GA','PSO','GWO','WOA','HHO','SA','Random','Greedy','Nearest','MinLatency']:
            with self.subTest(name=name):
                allocation,info=optimize(name,topology,apps,users,3,budget=70)
                self.assertGreater(info['fitness_evaluations'],0)
                self.assertLessEqual(info['fitness_evaluations'],70)
                self.assertEqual(len(allocation),4)
                self.assertEqual(info['history'],sorted(info['history']))
                values=[v for _,v in info['history']]
                self.assertEqual(values,sorted(values,reverse=True))

    def test_ablation_settings_reset(self):
        data=fixture()
        optimize('SA',*data[:3],3,budget=10,cloud_mode='none',initialization='random')
        self.assertEqual(common.CLOUD_MODE,'adaptive')
        self.assertEqual(common.INITIALIZATION,'mixed')

    def test_missing_run_pairing(self):
        keys,a,b=paired_values({'r1':{'x':1},'r2':{'x':2},'r3':{'x':3}},
                              {'r1':{'x':4},'r3':{'x':6}},'x')
        self.assertEqual(keys,['r1','r3'])
        self.assertEqual(list(a),[1,3]);self.assertEqual(list(b),[4,6])

    def test_signed_effect_with_zero_differences(self):
        self.assertEqual(rank_biserial([1,0,-1],[0,0,0]),0)
        self.assertEqual(rank_biserial([-1,0,0],[0,0,0]),-1)
        self.assertEqual(holm([0.01,0.04,0.03]),[0.03,0.06,0.06])


if __name__=='__main__':unittest.main()
