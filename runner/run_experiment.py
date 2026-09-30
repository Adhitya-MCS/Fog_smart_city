"""Corrected experiment harness using the UNCHANGED vendored YAFS engine."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import platform
import sys
from pathlib import Path

_project_root=Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:sys.path.insert(0,str(_project_root))
from generator.generate_scenario import generate_topology,generate_applications,generate_users
from runner.run_simulation import run_simulation
from runner.search import optimize,STRATEGIES
from runner.integrity import verify_yafs
from analysis.constraint_analysis import compute_metrics_for_trace


def stable_seed(*parts):
    return int.from_bytes(hashlib.sha256('|'.join(map(str,parts)).encode()).digest()[:4],'big')


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New result/scenario directory; never overwrite')
    p.add_argument('--app-counts',default='25,50,75,100,125,150,175,200,225,250')
    p.add_argument('--topology-size',type=int,default=100)
    p.add_argument('--topology-seed',type=int,default=42)
    p.add_argument('--seed',type=int,default=20260909)
    p.add_argument('--runs',type=int,default=30)
    p.add_argument('--algorithms',default='Greedy,GA,PSO,GWO,WOA,HHO,SA,Random')
    p.add_argument('--budget',type=int,default=3000)
    p.add_argument('--duration',type=float,default=10000,help='Emission window, ms')
    p.add_argument('--drain-time',type=float,default=10000)
    p.add_argument('--alpha',type=float,default=1/3)
    p.add_argument('--beta',type=float,default=1/3)
    p.add_argument('--gamma',type=float,default=1/3)
    p.add_argument('--cloud-mode',choices=['adaptive','constant','none'],default='adaptive')
    p.add_argument('--initialization',choices=['mixed','random'],default='mixed')
    args=p.parse_args()
    counts=[int(x) for x in args.app_counts.split(',')]
    algorithms=args.algorithms.split(',')
    if len(set(counts))!=len(counts) or len(set(algorithms))!=len(algorithms):p.error('Duplicate tier or algorithm')
    if not set(algorithms)<=set(['Greedy',*STRATEGIES]):p.error('Unknown algorithm')
    weights=(args.alpha,args.beta,args.gamma)
    if min(counts)<1 or args.runs<1 or args.budget<1 or args.topology_size<3:p.error('Invalid size, runs, or budget')
    if any(not math.isfinite(x) for x in [*weights,args.duration,args.drain_time]) or min(weights)<0 or sum(weights)<=0 or args.duration<=0 or args.drain_time<0:p.error('Invalid weights or observation windows')
    yafs_hashes=verify_yafs()
    args.output.mkdir(parents=True,exist_ok=False)
    write_json(args.output/'manifest.json',{**vars(args),'output':str(args.output),
        'engine':'unchanged local YAFS source','yafs_sha256':yafs_hashes,
        'python':platform.python_version(),'packages':{k:importlib.metadata.version(k) for k in ['simpy','networkx','numpy','pandas','scipy']},
        'experiment_sha256':{str(f.relative_to(_project_root)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ['config','generator','placements','runner','analysis'] for f in (_project_root/d).rglob('*.py')},
        'units':'canonical bytes/ms, engine BW divided by 1e6, simulation clock ms',
        'cpu':'original static instructions/deadline admission; native per-module execution',
        'network':'native YAFS link queuing including propagation; not altered',
        'traffic':'one independent native-discretized exponential stream per BOT task',
        'statistics':'paired by instance ID; Holm correction per metric; signed effect sizes'})
    for workload in counts:
        for run in range(1,args.runs+1):
            instance=args.output/f'apps_{workload}'/f'run_{run}'
            scenario=instance/'scenario'
            scenario.mkdir(parents=True)
            app_seed=stable_seed(args.seed,args.topology_seed,workload,run,'apps')
            traffic_seed=stable_seed(args.seed,args.topology_seed,workload,run,'traffic')
            topology=generate_topology(args.topology_seed,args.topology_size)
            applications=generate_applications(app_seed,workload,'BOT')
            users=generate_users(topology,applications,app_seed)
            for filename,value in [('networkDefinition.json',topology),('appDefinition.json',applications),('usersDefinition.json',users)]:
                write_json(scenario/filename,value)
            for algorithm in algorithms:
                allocation,search=optimize(algorithm,topology,applications,users,
                    stable_seed(app_seed,algorithm),args.budget,weights,args.cloud_mode,args.initialization)
                write_json(scenario/f'allocDefinition{algorithm}.json',{'initialAllocation':allocation})
                result=instance/algorithm
                run_simulation(algorithm+'Placement',args.duration,results_dir=result,
                    scenarios_dir=scenario,drain_time=args.drain_time,run_seed=traffic_seed)
                write_json(result/'time_log.json',search)
                identity=dict(algorithm=algorithm,workload=workload,run=run,
                    instance_id=f'{args.seed}:{args.topology_seed}:{workload}:{run}',
                    application_seed=app_seed,traffic_seed=traffic_seed)
                write_json(result/'instance.json',identity)
                metrics=compute_metrics_for_trace(result/'sim_trace.csv')
                write_json(result/'metrics.json',{**metrics,**identity})
                print(f'{algorithm} W={workload} run={run} emitted={metrics["emitted"]} complete={metrics["completed"]} evaluations={search["fitness_evaluations"]}',flush=True)
    verify_yafs()
    print(f'Finished: {args.output.resolve()} (YAFS hashes unchanged)')


if __name__=='__main__':main()
