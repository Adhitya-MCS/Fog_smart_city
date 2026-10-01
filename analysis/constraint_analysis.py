"""Trace analysis for unchanged YAFS with verified experiment-owned emissions.

Run: python -m analysis.constraint_analysis RESULTS_ROOT
All ratios use [0,1]; completed-only latency is conditional, not full-cohort QoS.
"""
import argparse
import csv
import json
import statistics
from pathlib import Path
import pandas as pd


def compute_metrics_for_trace(trace_csv,run_dir=None,scenarios_dir=None):
    trace_csv=Path(trace_csv)
    directory=trace_csv.parent
    meta=json.loads((directory/'simulation_metadata.json').read_text())
    end=meta['observation_end_ms']
    ledger=json.loads((directory/'emissions.json').read_text())
    apps={str(a['id']):a for a in json.loads((directory/'appDefinition.json').read_text())}
    nodes={n['id']:n for n in json.loads((directory/'networkDefinition.json').read_text())['entity']}
    df=pd.read_csv(trace_csv)
    df['app']=df['app'].astype(str)
    comp=df[df['type']=='COMP_M'].copy()
    task=comp[~comp['module'].str.endswith('_ACT')].copy()
    actuator=comp[comp['module'].str.endswith('_ACT') & (comp['time_out']<end)].copy()
    task_done=task[task['time_out']<end]
    rt=task[['id','app','module','DES.src','time_emit']].merge(
        actuator[['id','app','time_out']],on=['id','app'],how='inner',validate='one_to_one')
    rt=rt.rename(columns={'DES.src':'source_des','time_out':'completed_ms'})
    emitted=pd.DataFrame(ledger,columns=['app','module','source_des','time_emit','sequence'])
    emitted['app']=emitted['app'].astype(str)
    keys=['app','module','source_des','time_emit']
    # Native source delays are integral ms in this experiment, so keys are exact.
    merged=emitted.merge(rt,on=keys,how='left',validate='one_to_one')
    matched=int(merged['completed_ms'].notna().sum())
    if matched!=len(rt):raise ValueError('Completed requests did not match emission ledger')
    merged['deadline']=merged['app'].map(lambda a:float(apps[a]['deadline']))
    if (merged['deadline']<=0).any():raise ValueError('Positive application deadlines required')
    merged['latency']=merged['completed_ms']-merged['time_emit']
    done=merged['completed_ms'].notna()
    late=done & (merged['latency']>merged['deadline'])
    ontime=done & ~late
    expired=~done & ((end-merged['time_emit'])>=merged['deadline'])
    pending=~done & ~expired
    n=len(merged)
    ratio=lambda a,b:float(a/b) if b else None
    cloud={nid for nid,node in nodes.items() if node.get('type')=='CLOUD'}
    allocations=json.loads((directory/'allocation_used.json').read_text())['initialAllocation']
    destinations={(str(a['app']),a['module_name']):a['id_resource'] for a in allocations}
    targeted=sum(destinations[str(r['app']),r['module']] in cloud for r in ledger)
    to_cloud=pd.Series([destinations[a,m] in cloud for a,m in zip(merged['app'],merged['module'])],index=merged.index)
    # Native COMP_M is recorded at service START, with a projected finish.
    # This proxy clips partial processing and is NOT physical aggregate-node energy.
    max_ipt=max(node['IPT'] for node in nodes.values())
    proxy=0.0
    for row in task.to_dict('records'):
        peak=10.0*nodes[row['TOPO.dst']]['IPT']/max_ipt
        idle=0.22*peak
        proc=max(0,min(row['time_out'],end)-row['time_in'])/1000
        residence=max(0,min(row['time_reception'],end)-row['time_emit'])/1000
        proxy+=(idle+2.0)*residence+(idle+peak)*proc
    latencies=merged.loc[done,'latency']
    return dict(emitted=n,completed=int(done.sum()),unfinished=int((~done).sum()),
        deadline_missed=int(late.sum()+expired.sum()),deadline_pending=int(pending.sum()),
        completion_ratio=ratio(done.sum(),n),ontime_delivery_ratio=ratio(ontime.sum(),n),
        deadline_miss_ratio=ratio(late.sum()+expired.sum(),n),
        completed_only_slav=ratio(late.sum(),done.sum()),
        completed_only_cvi=float(((merged.loc[done,'latency']-merged.loc[done,'deadline'])/merged.loc[done,'deadline']).clip(lower=0).mean()) if done.any() else None,
        mean_completed_response_ms=float(latencies.mean()) if done.any() else None,
        max_observed_response_ms=float(latencies.max()) if done.any() else None,
        completion_by_emission_end=ratio((done & (merged['completed_ms']<meta['emission_end_ms'])).sum(),n),
        requested_cloud_ratio=ratio(targeted,n),
        ontime_cloud_ratio=ratio((ontime & to_cloud).sum(),to_cloud.sum()),
        ontime_fog_ratio=ratio((ontime & ~to_cloud).sum(),(~to_cloud).sum()),
        completed_compute_cloud_ratio=ratio(task_done['TOPO.dst'].isin(cloud).sum(),len(task_done)),
        projected_computations_not_finished=int((task['time_out']>=end).sum()),
        energy_proxy_j=proxy,energy_interpretation='per-task delay-weighted proxy; not physical system energy',
        emission_end_ms=meta['emission_end_ms'],observation_end_ms=end)


METRICS=['completion_ratio','ontime_delivery_ratio','deadline_miss_ratio','completed_only_slav',
         'completed_only_cvi','mean_completed_response_ms','max_observed_response_ms',
         'requested_cloud_ratio','ontime_cloud_ratio','ontime_fog_ratio','completed_compute_cloud_ratio','energy_proxy_j']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('results',type=Path)
    args=p.parse_args()
    # Analysis goes to a new directory; legacy outputs never silently overwritten.
    output=args.results/'analysis'
    output.mkdir(exist_ok=False)
    records=[]
    for trace in sorted(args.results.glob('apps_*/run_*/*/sim_trace.csv')):
        metrics=compute_metrics_for_trace(trace)
        identity=json.loads((trace.parent/'instance.json').read_text())
        records.append({**metrics,**identity})
    if not records:raise ValueError('No new-protocol traces found')
    (output/'run_metrics.json').write_text(json.dumps(records,indent=2,allow_nan=False))
    # Metric definitions used for run_metrics.json; ablation compares this before pairing folders.
    import hashlib,importlib.metadata
    (output/'analysis_manifest.json').write_text(json.dumps(dict(
        metrics_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        packages={k:importlib.metadata.version(k) for k in ['numpy','pandas','scipy']}),indent=2))
    with (output/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['workload','algorithm','metric','n','mean','sample_std'])
        writer.writeheader()
        for workload,algorithm in sorted(set((r['workload'],r['algorithm']) for r in records)):
            for metric in METRICS:
                values=[r[metric] for r in records if r['workload']==workload and r['algorithm']==algorithm and r[metric] is not None]
                writer.writerow(dict(workload=workload,algorithm=algorithm,metric=metric,n=len(values),
                    mean=statistics.mean(values) if values else '',sample_std=statistics.stdev(values) if len(values)>1 else ''))
    from analysis.statistik import compare
    report=compare(records,METRICS)
    (output/'pairwise_statistics.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    print(output)


if __name__=='__main__':main()
