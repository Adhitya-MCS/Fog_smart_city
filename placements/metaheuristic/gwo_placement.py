"""Grey Wolf Optimizer Placement (GWOPlacement) - Minimizes Cost.

Algoritma asli: [Mirjalili, Mirjalili & Lewis, 2014] (Grey Wolf Optimizer).
Model placement (objective/constraint): [Apat et al., 2024]. Perluasan (this work).
"""
from __future__ import annotations
import random
from typing import List

from placements.placement import Placement
from placements.metaheuristic._common import (
    PlacementProblem, ServiceNormBounds, build_problem,
    precompute_normalization_bounds, compute_total_cost,
    greedy_seed_chrom, random_chrom, repair_chromosome, to_allocation,
)

class GWOPlacement(Placement):
    def __init__(self, pop_size=30, iterations=100, alpha=1.0 / 3.0, beta=1.0 / 3.0, gamma=1.0 / 3.0, seed=None):
        super().__init__()
        self.name = "GWO"
        self.pop_size = pop_size
        self.iterations = iterations
        self.alpha_obj = alpha
        self.beta_obj = beta
        self.gamma_obj = gamma
        self.seed = seed

    def generate_allocation(self, topology, applications, users):
        if self.seed is not None: random.seed(self.seed)
        prob = build_problem(topology, applications, users, alpha=self.alpha_obj, beta=self.beta_obj, gamma=self.gamma_obj)
        if not prob.services or not prob.candidate_nodes: return []

        bounds = precompute_normalization_bounds(prob)
        # 1 greedy-seed + sisanya acak (konsisten dengan GA).
        wolves = [greedy_seed_chrom(prob)]
        while len(wolves) < self.pop_size:
            wolves.append(repair_chromosome(random_chrom(prob), prob, bounds))
        costs = [compute_total_cost(w, prob, bounds) for w in wolves]

        # Inisialisasi Alpha, Beta, Delta secara historis
        alpha_pos, alpha_cost = None, float('inf')
        beta_pos, beta_cost = None, float('inf')
        delta_pos, delta_cost = None, float('inf')

        def update_top_3(current_wolves, current_costs):
            nonlocal alpha_pos, alpha_cost, beta_pos, beta_cost, delta_pos, delta_cost
            
            # Gabungkan top 3 saat ini dengan top 3 historis
            current_sorted = sorted(zip(current_costs, current_wolves), key=lambda x: x[0])
            candidates = [
                (alpha_cost, alpha_pos),
                (beta_cost, beta_pos),
                (delta_cost, delta_pos)
            ]
            
            for k in range(min(3, len(current_sorted))):
                candidates.append((current_sorted[k][0], current_sorted[k][1]))
            
            # FIX 1: Deduplikasi berdasarkan konten kromosom untuk mencegah diversitas nol
            seen = set()
            deduped = []
            for c, p in candidates:
                if p is None or c == float('inf'): continue
                key = tuple(p)
                if key not in seen:
                    seen.add(key)
                    deduped.append((c, p))
            
            # Sort dan ambil 3 terbaik yang unik
            deduped.sort(key=lambda x: x[0])
            
            if len(deduped) > 0: alpha_cost, alpha_pos = deduped[0][0], list(deduped[0][1])
            if len(deduped) > 1: beta_cost, beta_pos = deduped[1][0], list(deduped[1][1])
            if len(deduped) > 2: delta_cost, delta_pos = deduped[2][0], list(deduped[2][1])

            if beta_pos is None: beta_pos,beta_cost=list(alpha_pos),alpha_cost
            if delta_pos is None: delta_pos,delta_cost=list(beta_pos),beta_cost

        # Inisialisasi awal top 3
        update_top_3(wolves, costs)

        for it in range(self.iterations):
            # a menurun dari 2 ke 0 sepanjang iterasi
            a = 2.0 - it * (2.0 / self.iterations)  
            
            for i in range(self.pop_size):
                new_wolf = list(wolves[i])
                
                for j in range(len(prob.services)):
                    # FIX 2: Gunakan a/2.0 yang di-clamp agar tidak 100% acak di awal
                    explore_prob = min(0.5, a / 2.0)
                    
                    if random.random() < explore_prob:
                        # EKSPLORASI: Pilih node acak (diversifikasi)
                        new_wolf[j] = random.choice(prob.candidate_nodes)
                    else:
                        # EKSPLOITASI: Ikuti Alpha/Beta/Delta (intensifikasi)
                        # Pemberian bobot [3, 2, 1] mencerminkan hirarki GWO
                        new_wolf[j] = random.choices(
                            [alpha_pos[j], beta_pos[j], delta_pos[j]],
                            weights=[3, 2, 1]
                        )[0]

                wolves[i] = repair_chromosome(new_wolf, prob, bounds)
                costs[i] = compute_total_cost(wolves[i], prob, bounds)

            # Update Alpha, Beta, Delta berdasarkan seluruh riwayat (historis)
            update_top_3(wolves, costs)

        # Return solusi terbaik absolut
        if alpha_pos is None:
             return to_allocation(repair_chromosome(wolves[0], prob, bounds), prob)
        return to_allocation(repair_chromosome(alpha_pos, prob, bounds), prob)