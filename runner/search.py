"""Placement evaluation budgets and reproducible diagnostics; no YAFS changes."""
import math
import time
from placements.metaheuristic import GAPlacement,PSOPlacement,GWOPlacement,WOAPlacement,HHOPlacement,SAPlacement,RandomPlacement
from placements.metaheuristic import _common as common

STRATEGIES=dict(GA=GAPlacement,PSO=PSOPlacement,GWO=GWOPlacement,WOA=WOAPlacement,
                HHO=HHOPlacement,SA=SAPlacement,Random=RandomPlacement)


BASELINES=dict(Greedy=common.greedy_seed_chrom,Nearest=common.nearest_feasible_chrom,MinLatency=common.min_latency_chrom)


def optimize(name,topology,apps,users,seed,budget=3000,weights=(1/3,1/3,1/3),cloud_mode='adaptive',initialization='mixed'):
    if budget<1 or cloud_mode not in ('adaptive','constant','none') or initialization not in ('mixed','random'):
        raise ValueError('Invalid search configuration')
    old=(common.CLOUD_MODE,common.INITIALIZATION)
    common.CLOUD_MODE=cloud_mode
    common.INITIALIZATION='mixed' if name in BASELINES else initialization
    started=time.perf_counter()
    try:
        with common.EvaluationBudget(1 if name in BASELINES else budget) as tracker:
            if name in BASELINES:
                prob=common.build_problem(topology,apps,users,*weights)
                bounds=common.precompute_normalization_bounds(prob)
                common.compute_total_cost(BASELINES[name](prob),prob,bounds)
            else:
                kwargs=dict(seed=seed,alpha=weights[0],beta=weights[1],gamma=weights[2])
                if name=='Random':kwargs.update(iterations=budget)
                elif name=='SA':kwargs.update(iterations=max(1,budget-1),temp_min=0.0,cooling_rate=(1e-4)**(1/max(1,budget-1)))
                else:
                    kwargs['pop_size']=min(30,budget)
                    kwargs['generations' if name=='GA' else 'iterations']=max(1,math.ceil((budget-kwargs['pop_size'])/kwargs['pop_size']))
                try:STRATEGIES[name](**kwargs).generate_allocation(topology,apps,users)
                except common.BudgetExhausted:pass
        if tracker.best_chrom is None:raise RuntimeError('No evaluated solution')
        if not (common.evaluate_ram_valid(tracker.best_chrom,tracker.problem) and common.evaluate_cpu_valid(tracker.best_chrom,tracker.problem)):
            raise RuntimeError('Placement violates static admission constraints')
        cloud_report=common.cloud_pressure_report(tracker.best_chrom,tracker.problem)
        return common.to_allocation(tracker.best_chrom,tracker.problem),dict(
            execution_time_sec=time.perf_counter()-started,fitness_evaluations=tracker.evaluations,
            evaluation_limit=tracker.limit,best_fitness=tracker.best_cost,history=tracker.history,
            repair_calls=tracker.repair_calls,repaired_genes=tracker.repaired_genes,
            initialization=common.INITIALIZATION,cloud_mode=cloud_mode,
            cloud_pressure=cloud_report,
            capacity_model='static cpu_rate reservation (instructions/deadline if absent); no shared CPU claim',
            variant='project-specific discrete adaptation' if name in ('PSO','GWO','WOA','HHO') else name)
    finally:
        common.CLOUD_MODE,common.INITIALIZATION=old
