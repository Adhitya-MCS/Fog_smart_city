"""Paired ablation comparison across result folders that share scenario, traffic, and budget.

Run: python -m analysis.ablation OUTPUT_DIR REF=results/full VARIANT=results/no-cloud ...
Each folder must already have analysis/run_metrics.json (python -m analysis.constraint_analysis).
The first REF=path is the reference; every other variant is compared with it, paired by
(algorithm, instance_id), per algorithm and workload level. Holm correction is applied
within each metric across all tests.
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

from analysis.statistik import holm, paired_values, rank_biserial

METRICS = ['ontime_delivery_ratio', 'requested_cloud_ratio', 'deadline_miss_ratio', 'completion_ratio']


def load_variant(path):
    path = Path(path)
    records = json.loads((path / 'analysis' / 'run_metrics.json').read_text())
    for r in records:
        log = json.loads((path / f"apps_{r['workload']}" / f"run_{r['run']}" / r['algorithm'] / 'time_log.json').read_text())
        r['runtime_sec'] = log['execution_time_sec']
        r['cloud_coefficient'] = (log.get('cloud_pressure') or {}).get('cloud_coefficient')
    groups = {}
    for r in records:
        groups.setdefault((r['algorithm'], r['workload']), {})[r['instance_id']] = r
    return groups


def compare(reference, variants, metrics):
    rows = []
    for name, groups in variants.items():
        for key in sorted(set(reference) & set(groups)):
            algorithm, workload = key
            for metric in metrics:
                ids, x, y = paired_values(groups[key], reference[key], metric)
                if len(ids) < 5:
                    continue
                delta = x - y
                p = 1.0 if np.all(delta == 0) else float(wilcoxon(x, y, zero_method='wilcox').pvalue)
                rows.append(dict(variant=name, algorithm=algorithm, workload=workload, metric=metric, n=len(ids),
                                 reference_mean=float(y.mean()), variant_mean=float(x.mean()),
                                 mean_difference=float(delta.mean()), signed_rank_biserial=rank_biserial(x, y), p_raw=p))
    for metric in metrics:
        subset = [r for r in rows if r['metric'] == metric]
        for row, adjusted in zip(subset, holm([r['p_raw'] for r in subset])):
            row.update(p_holm=adjusted, significant=adjusted < 0.05)
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('variants', nargs='+', help='NAME=results_dir; first one is the reference')
    p.add_argument('--metrics', default=','.join(METRICS + ['runtime_sec']))
    args = p.parse_args()
    named = [v.split('=', 1) for v in args.variants]
    if len(named) < 2 or any(len(v) != 2 for v in named):
        p.error('Need at least a reference and one variant as NAME=path')
    loaded = {name: load_variant(path) for name, path in named}
    reference = loaded[named[0][0]]
    rows = compare(reference, {k: v for k, v in loaded.items() if k != named[0][0]}, args.metrics.split(','))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'ablation.json').write_text(json.dumps(dict(reference=named[0][0], comparisons=rows), indent=2, allow_nan=False))
    with (args.output / 'ablation.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f'{len(rows)} paired comparisons against {named[0][0]}: {args.output}')


if __name__ == '__main__':
    main()
