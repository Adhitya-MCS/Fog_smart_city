"""Paired ablation comparison across result folders that share scenario, traffic, and budget.

Run: python -m analysis.ablation OUTPUT_DIR REF=results/full VARIANT=results/no-cloud ...
Each folder must already have analysis/run_metrics.json (python -m analysis.constraint_analysis).
The first REF=path is the reference; every other variant is compared with it, paired by
(algorithm, instance_id), per algorithm and workload level. Holm correction is applied
within each metric across all tests.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import wilcoxon

from analysis.statistik import holm, paired_values, rank_biserial

METRICS = ['ontime_delivery_ratio', 'requested_cloud_ratio', 'deadline_miss_ratio', 'completion_ratio']
MIN_PAIRS = 5
# Must be identical for paired variants; only the ablated options (cloud_mode, alpha/beta/gamma,
# initialization) and output paths may differ. Analysis code is excluded here because it does not
# affect simulation results; the metric code is verified separately (check_metrics).
REQUIRED_EQUAL = ('design', 'manifest_sha256', 'topology_seed', 'seed', 'runs', 'budget', 'duration',
                  'drain_time', 'l1_class', 'cloud_pr', 'fps_jitter', 'yafs_sha256', 'python', 'packages')
CODE_PREFIXES = ('config/', 'generator/', 'placements/', 'runner/')
SCENARIO_FILES = ('networkDefinition.json', 'appDefinition.json', 'usersDefinition.json')
FIELDS = ['variant', 'algorithm', 'workload', 'metric', 'n', 'status', 'reference_mean', 'variant_mean',
          'mean_difference', 'signed_rank_biserial', 'p_raw', 'p_holm', 'significant']


def check_comparable(reference, variant, name):
    problems = [f'{k}: {reference.get(k)!r} != {variant.get(k)!r}' for k in REQUIRED_EQUAL if reference.get(k) != variant.get(k)]
    code = lambda m: {k: v for k, v in m.get('experiment_sha256', {}).items() if k.startswith(CODE_PREFIXES)}
    if code(reference) != code(variant):
        problems.append('experiment code hashes (config/generator/placements/runner) differ')
    if problems:
        raise ValueError(f'{name} is not comparable with the reference: ' + '; '.join(problems))


def check_metrics(reference_path, variant_path, name):
    """Both folders must have been analysed by the same metric code (analysis_manifest.json)."""
    load = lambda p: json.loads((Path(p) / 'analysis' / 'analysis_manifest.json').read_text()) if (Path(p) / 'analysis' / 'analysis_manifest.json').exists() else None
    ref, var = load(reference_path), load(variant_path)
    if ref is None or var is None:
        raise ValueError(f'{name}: missing analysis/analysis_manifest.json; re-run analysis.constraint_analysis on a new copy of the analysis')
    if ref != var:
        raise ValueError(f'{name} was analysed with different metric code or package versions than the reference')


def check_scenarios(reference_path, variant_path, name):
    bad = []
    for ref_dir in sorted(Path(reference_path).glob('apps_*/run_*/scenario')):
        var_dir = Path(variant_path) / ref_dir.relative_to(reference_path)
        if not var_dir.exists():
            continue
        for f in SCENARIO_FILES:
            digest = lambda d: hashlib.sha256((d / f).read_bytes()).hexdigest()
            if digest(ref_dir) != digest(var_dir):
                bad.append(f'{ref_dir.relative_to(reference_path)}/{f}')
    if bad:
        raise ValueError(f'{name} used different scenario inputs than the reference: ' + ', '.join(bad[:5]))


def load_variant(path):
    path = Path(path)
    records = json.loads((path / 'analysis' / 'run_metrics.json').read_text())
    for r in records:
        log = json.loads((path / f"apps_{r['workload']}" / f"run_{r['run']}" / r['algorithm'] / 'time_log.json').read_text())
        r['runtime_sec'] = log['execution_time_sec']
        r['cloud_coefficient'] = (log.get('cloud_pressure') or {}).get('cloud_coefficient')
    groups = {}
    for r in records:
        group = groups.setdefault((r['algorithm'], r['workload']), {})
        if r['instance_id'] in group:
            raise ValueError(f"Duplicate instance_id {r['instance_id']} for {r['algorithm']} workload {r['workload']} in {path}")
        group[r['instance_id']] = r
    return groups


def compare(reference, variants, metrics):
    rows = []
    for name, groups in variants.items():
        for key in sorted(set(reference) & set(groups)):
            algorithm, workload = key
            for metric in metrics:
                ids, x, y = paired_values(groups[key], reference[key], metric)
                if len(ids) < MIN_PAIRS:
                    rows.append(dict(variant=name, algorithm=algorithm, workload=workload, metric=metric, n=len(ids),
                                     status='insufficient paired runs'))
                    continue
                delta = x - y
                p = 1.0 if np.all(delta == 0) else float(wilcoxon(x, y, zero_method='wilcox').pvalue)
                rows.append(dict(variant=name, algorithm=algorithm, workload=workload, metric=metric, n=len(ids), status='tested',
                                 reference_mean=float(y.mean()), variant_mean=float(x.mean()),
                                 mean_difference=float(delta.mean()), signed_rank_biserial=rank_biserial(x, y), p_raw=p))
    for metric in metrics:
        subset = [r for r in rows if r['metric'] == metric and r['status'] == 'tested']
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
    manifests = {name: json.loads((Path(path) / 'manifest.json').read_text()) for name, path in named}
    for name, path in named[1:]:
        check_comparable(manifests[named[0][0]], manifests[name], name)
        check_scenarios(named[0][1], path, name)
        check_metrics(named[0][1], path, name)
    loaded = {name: load_variant(path) for name, path in named}
    reference = loaded[named[0][0]]
    rows = compare(reference, {k: v for k, v in loaded.items() if k != named[0][0]}, args.metrics.split(','))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'ablation.json').write_text(json.dumps(dict(reference=named[0][0], comparisons=rows), indent=2, allow_nan=False))
    with (args.output / 'ablation.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tested = sum(1 for r in rows if r['status'] == 'tested')
    print(f'{tested} tested and {len(rows) - tested} insufficient-pair comparisons against {named[0][0]}: {args.output}')


if __name__ == '__main__':
    main()
