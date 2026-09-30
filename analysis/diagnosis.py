"""Why QoS degrades: per-request latency decomposition and CPU reservation vs runtime load.

Run: python -m analysis.diagnosis RESULTS_ROOT      (writes RESULTS_ROOT/diagnosis/)

Only requests completed before the observation cutoff are decomposed (see completed_share); with many
unfinished requests the split describes the finished ones, not the delay of every request.
Latency of a completed request = request network + module wait + processing + response network.
Network time is split into the ideal part (transmission + propagation, from the link trace) and
queueing (observed minus ideal). CPU reservation (static admission, sum cpu_rate / IPT) is reported
next to runtime load (busy time / emission window, in full-node equivalents; YAFS does not share CPU,
so values above 1 mean the node runs more concurrent work than its IPT).
"""
import argparse
import csv
import json
from pathlib import Path

import pandas as pd

TIERS = ['L1', 'L2', 'L3', 'CLOUD']


def diagnose_instance(directory):
    d = Path(directory)
    meta = json.loads((d / 'simulation_metadata.json').read_text())
    end, emit_end = meta['observation_end_ms'], meta['emission_end_ms']
    nodes = {n['id']: n for n in json.loads((d / 'networkDefinition.json').read_text())['entity']}
    apps = {str(a['id']): a for a in json.loads((d / 'appDefinition.json').read_text())}
    allocation = json.loads((d / 'allocation_used.json').read_text())['initialAllocation']
    trace = pd.read_csv(d / 'sim_trace.csv')
    trace['app'] = trace['app'].astype(str)
    link = pd.read_csv(d / 'sim_trace_link.csv')
    link['app'] = link['app'].astype(str)

    comp = trace[trace['type'] == 'COMP_M']
    is_act = comp['module'].str.endswith('_ACT')
    task = comp[~is_act]
    act = comp[is_act & (comp['time_out'] < end)][['id', 'app', 'time_out']].rename(columns={'time_out': 'act_done'})
    ideal = link.groupby(['id', 'app'])['latency'].sum().rename('ideal_net').reset_index()
    rt = task.merge(act, on=['id', 'app'], validate='one_to_one').merge(ideal, on=['id', 'app'], how='left')
    rt['ideal_net'] = pd.to_numeric(rt['ideal_net']).fillna(0.0)
    rt['total'] = rt['act_done'] - rt['time_emit']
    rt['proc'] = rt['time_out'] - rt['time_in']
    rt['module_wait'] = rt['time_in'] - rt['time_reception']
    rt['net'] = (rt['time_reception'] - rt['time_emit']) + (rt['act_done'] - rt['time_out'])
    rt['net_queue'] = (rt['net'] - rt['ideal_net']).clip(lower=0.0)
    rt['tier'] = rt['TOPO.dst'].map(lambda n: nodes[n]['type'])

    emitted = len(json.loads((d / 'emissions.json').read_text()))
    row = dict(completed=int(len(rt)), emitted=emitted, completed_share=len(rt) / emitted if emitted else None)
    if len(rt):
        for col in ['total', 'proc', 'module_wait', 'ideal_net', 'net_queue']:
            row[f'mean_{col}_ms'] = float(rt[col].mean())
        row['net_queue_share'] = float(rt['net_queue'].sum() / rt['total'].sum()) if rt['total'].sum() else None
        row['module_wait_share'] = float(rt['module_wait'].sum() / rt['total'].sum()) if rt['total'].sum() else None

    reserved = {}
    for a in allocation:
        for m in apps.get(str(a['app']), {}).get('module', []):
            if m['name'] == a['module_name'] and m.get('type') == 'MODULE':
                reserved[a['id_resource']] = reserved.get(a['id_resource'], 0.0) + float(m.get('cpu_rate', 0.0))
    busy = task.assign(start=task['time_in'].clip(lower=0, upper=emit_end), stop=task['time_out'].clip(lower=0, upper=emit_end))
    busy = (busy['stop'] - busy['start']).groupby(busy['TOPO.dst']).sum() / emit_end
    for tier in TIERS:
        ids = [n for n, v in nodes.items() if v['type'] == tier]
        if not ids:
            continue
        res = [reserved.get(n, 0.0) / nodes[n]['IPT'] for n in ids]
        run = [float(busy.get(n, 0.0)) for n in ids]
        row[f'{tier}_reserved_mean'] = sum(res) / len(ids)
        row[f'{tier}_reserved_max'] = max(res)
        row[f'{tier}_runtime_mean'] = sum(run) / len(ids)
        row[f'{tier}_runtime_max'] = max(run)
        row[f'{tier}_runtime_over_1'] = sum(1 for v in run if v > 1.0)
    row['cloud_services'] = sum(1 for a in allocation if nodes[a['id_resource']]['type'] == 'CLOUD' and not a['module_name'].endswith('_ACT'))
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('results', type=Path)
    args = p.parse_args()
    out = args.results / 'diagnosis'
    out.mkdir(exist_ok=False)
    rows = []
    for trace in sorted(args.results.glob('apps_*/run_*/*/sim_trace.csv')):
        identity = json.loads((trace.parent / 'instance.json').read_text())
        rows.append({**{k: identity[k] for k in ('workload', 'algorithm', 'run')}, **diagnose_instance(trace.parent)})
    if not rows:
        raise ValueError('No traces found')
    columns = sorted({k for r in rows for k in r}, key=lambda k: (k not in ('workload', 'algorithm', 'run'), k))
    with (out / 'diagnosis_runs.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    frame = pd.DataFrame(rows).drop(columns=['run'])
    summary = frame.groupby(['workload', 'algorithm']).mean(numeric_only=True).reset_index()
    summary.to_csv(out / 'diagnosis_summary.csv', index=False)
    print(f'{len(rows)} instances: {out}')


if __name__ == '__main__':
    main()
