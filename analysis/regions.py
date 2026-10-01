"""Peta keberhasilan layanan dan aturan pemilihan titik konfirmasi (aturan tetap, lihat PROTOCOL.md).

Run: python -m analysis.regions OUTPUT_DIR EXPLORATION_ROOT
EXPLORATION_ROOT berisi satu folder hasil per kondisi (mis. pr25.6_accel_B), masing-masing sudah
dianalisis dengan analysis.constraint_analysis. Unit analisis adalah run, bukan request.
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from config import protocol as proto


def category(mean_ontime):
    if mean_ontime >= proto.ONTIME_TARGET:
        return 'target_met'
    return 'severe_degradation' if mean_ontime < proto.ONTIME_SEVERE else 'target_missed'


def bootstrap_ci(values, seed=0, resamples=2000):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return None, None
    means = np.random.RandomState(seed).choice(values, (resamples, len(values))).mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _mean(values):
    values = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.mean(values)) if values else None


def region_table(records_by_condition):
    """records_by_condition: {condition: [run_metrics records]} -> one row per condition, algorithm, workload."""
    rows = []
    for condition, records in sorted(records_by_condition.items()):
        groups = defaultdict(list)
        for r in records:
            groups[r['algorithm'], r['workload']].append(r)
        for (algorithm, workload), runs in sorted(groups.items()):
            ontime = [r['ontime_delivery_ratio'] for r in runs]
            lo, hi = bootstrap_ci(ontime)
            rows.append(dict(
                condition=condition, algorithm=algorithm, workload=workload, runs=len(runs),
                ontime_mean=float(np.mean(ontime)), ontime_ci_low=lo, ontime_ci_high=hi,
                runs_target_met=sum(v >= proto.ONTIME_TARGET for v in ontime) / len(runs),
                straddles_threshold=any(min(ontime) < t <= max(ontime) for t in (proto.ONTIME_TARGET, proto.ONTIME_SEVERE)),
                category=category(float(np.mean(ontime))),
                unfinished_share=_mean([r['unfinished'] / r['emitted'] for r in runs]),
                pending_share=_mean([r['deadline_pending'] / r['emitted'] for r in runs]),
                cloud_request_share=_mean([r['requested_cloud_ratio'] for r in runs]),
                ontime_cloud_requests=_mean([r['ontime_cloud_ratio'] for r in runs]),
                ontime_fog_requests=_mean([r['ontime_fog_ratio'] for r in runs])))
    return rows


def select_confirmation_points(rows):
    """Per condition: for each algorithm, the pair of adjacent levels bracketing each threshold
    (and the midpoint between them), plus the lowest level, the highest level, and the fixed grid
    midpoint. No crossing -> only the fixed points. Points are shared by all algorithms at confirmation."""
    series = defaultdict(list)
    for r in rows:
        series[r['condition'], r['algorithm']].append((r['workload'], r['ontime_mean']))
    points, notes = defaultdict(set), []
    for (condition, algorithm), values in sorted(series.items()):
        values.sort()
        points[condition].update([values[0][0], values[-1][0], proto.FIXED_MIDPOINT_LEVEL])
        for threshold in (proto.ONTIME_TARGET, proto.ONTIME_SEVERE):
            crossings = [(a, b) for (a, va), (b, vb) in zip(values, values[1:]) if (va >= threshold) != (vb >= threshold)]
            if not crossings:
                notes.append(f'{condition} {algorithm}: no crossing of {threshold}')
            for a, b in crossings:
                points[condition].update([a, b, round((a + b) / 2, 6)])
    return {c: sorted(p) for c, p in points.items()}, notes


def cells_to_escalate(rows):
    """Exploration cells whose runs lie on both sides of a threshold: rerun with ESCALATED_RUNS runs."""
    return [dict(condition=r['condition'], algorithm=r['algorithm'], workload=r['workload'])
            for r in rows if r['straddles_threshold'] and r['runs'] < proto.ESCALATED_RUNS]


def cloud_pr_max_ms(manifest_csv, l1_class='accel_B', deadline_ms=100.0):
    """Largest one-way L3-cloud propagation (ms) for which the no-queue estimate of a cloud-placed
    DET request still meets the deadline: (D - estimate at PR = 0) / 2, minimum over sources."""
    from generator.generate_scenario import generate_applications, generate_users
    from generator.hierarchical_topology import generate_hierarchical_topology, load_cameras
    from placements.metaheuristic import _common as common
    cameras = load_cameras(manifest_csv)
    topology, camera_to_l1 = generate_hierarchical_topology(cameras, l1_class=l1_class, cloud_pr_ms=0.0)
    apps = generate_applications(cameras, 1, 1.0, 0, fixed_deadline=True)
    prob = common.build_problem(topology, apps, generate_users(apps, camera_to_l1, 0))
    return min((deadline_ms - sum(common._calc_times(i, prob.cloud_id, prob)) * 1000) / 2 for i in range(len(prob.services)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('root', type=Path)
    p.add_argument('--manifest', default='data/cameras_SYNTHETIC.csv')
    args = p.parse_args()
    records = {}
    for folder in sorted(args.root.iterdir()):
        if (folder / 'analysis' / 'run_metrics.json').exists():
            records[folder.name] = json.loads((folder / 'analysis' / 'run_metrics.json').read_text())
    if not records:
        raise ValueError('No analysed condition folders found')
    rows = region_table(records)
    points, notes = select_confirmation_points(rows)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / 'regions.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.output / 'confirmation_points.json').write_text(json.dumps(
        dict(protocol_version=proto.PROTOCOL_VERSION, points=points, escalate=cells_to_escalate(rows), notes=notes, target=proto.ONTIME_TARGET, severe=proto.ONTIME_SEVERE,
             analytic_cloud_pr_max_ms=cloud_pr_max_ms(args.manifest)), indent=2, allow_nan=False))
    print(f'{len(rows)} rows, {len(points)} conditions: {args.output}')


if __name__ == '__main__':
    main()
