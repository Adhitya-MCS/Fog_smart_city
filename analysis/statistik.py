"""Seed-aligned peak-tier comparisons, Holm correction, and signed effect sizes.

Run: python -m analysis.statistics PATH_TO_RESULTS
"""
import argparse
import itertools
import json
import math
from pathlib import Path
import numpy as np
from scipy.stats import rankdata, wilcoxon


def paired_values(left, right, metric):
    keys=sorted(set(left)&set(right))
    pairs=[(k,left[k].get(metric),right[k].get(metric)) for k in keys]
    valid=[(k,a,b) for k,a,b in pairs if a is not None and b is not None and math.isfinite(a) and math.isfinite(b)]
    return [k for k,a,b in valid],np.array([a for k,a,b in valid]),np.array([b for k,a,b in valid])


def rank_biserial(left,right):
    difference=np.asarray(left)-np.asarray(right)
    nonzero=difference[difference!=0]
    if not len(nonzero):return 0.0
    ranks=rankdata(np.abs(nonzero))
    return float((ranks[nonzero>0].sum()-ranks[nonzero<0].sum())/ranks.sum())


def holm(pvalues):
    order=sorted(range(len(pvalues)),key=lambda i:pvalues[i])
    adjusted=[None]*len(order)
    previous=0.0
    for rank,index in enumerate(order):
        previous=max(previous,min(1.0,(len(order)-rank)*pvalues[index]))
        adjusted[index]=previous
    return adjusted


def compare(records,metrics):
    peak=max(r['workload'] for r in records)
    groups={}
    for r in records:
        if r['workload']!=peak:continue
        group=groups.setdefault(r['algorithm'],{})
        if r['instance_id'] in group:raise ValueError('Duplicate run identity')
        group[r['instance_id']]=r
    output=[]
    for metric in metrics:
        rows=[]
        for a,b in itertools.combinations(sorted(groups),2):
            keys,x,y=paired_values(groups[a],groups[b],metric)
            if len(keys)<5:
                rows.append(dict(metric=metric,left=a,right=b,n=len(keys),status='insufficient paired runs',p_raw=None))
                continue
            delta=x-y
            p=1.0 if np.all(delta==0) else float(wilcoxon(x,y,zero_method='wilcox').pvalue)
            rows.append(dict(metric=metric,left=a,right=b,n=len(keys),instance_ids=keys,
                p_raw=p,median_difference=float(np.median(delta)),
                signed_rank_biserial=rank_biserial(x,y),status='tested'))
        tested=[r for r in rows if r['p_raw'] is not None]
        for row,adjusted in zip(tested,holm([r['p_raw'] for r in tested])):
            row.update(p_holm=adjusted,significant=adjusted<0.05)
        output.extend(rows)
    return dict(peak_workload=peak,correction='Holm within each metric across pairs',
        effect_direction='positive means left numerically greater; desirability depends on metric',
        design='pre-specified peak-tier paired comparisons; no cross-tier omnibus gate',comparisons=output)


# Executed by analysis.constraint_analysis
