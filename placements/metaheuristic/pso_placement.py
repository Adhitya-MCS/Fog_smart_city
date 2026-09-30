"""Particle Swarm Optimization Placement (PSOPlacement) - Combinatorial PSO Approach.

Algoritma diterapkan ke fog service placement: [Apat et al., 2024] (FSPPSO).
"""
from __future__ import annotations
import random

from placements.placement import Placement
from placements.metaheuristic._common import build_problem, precompute_normalization_bounds, compute_total_cost, greedy_seed_chrom, random_chrom, repair_chromosome, to_allocation

class PSOPlacement(Placement):
    def __init__(self, pop_size=30, iterations=100, w_max=0.9, w_min=0.4, c1=1.5, c2=1.5, mutation_prob=0.05,
                 alpha=1.0 / 3.0, beta=1.0 / 3.0, gamma=1.0 / 3.0, seed=None):
        super().__init__()
        self.name = "PSO"
        self.pop_size = pop_size
        self.iterations = iterations
        self.w_max = w_max  # Inertia weight awal (eksplorasi)
        self.w_min = w_min  # Inertia weight akhir (eksploitasi)
        self.c1 = c1        # Cognitive (pbest)
        self.c2 = c2        # Social (gbest)
        self.mutation_prob = mutation_prob  # Peluang eksplorasi acak
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.seed = seed

    def generate_allocation(self, topology, applications, users):
        if self.seed is not None: random.seed(self.seed)
        prob = build_problem(topology, applications, users, alpha=self.alpha, beta=self.beta, gamma=self.gamma)
        if not prob.services or not prob.candidate_nodes: return []

        bounds = precompute_normalization_bounds(prob)
        
        # Inisialisasi swarm: 1 greedy-seed + sisanya acak (konsisten dengan GA,
        # supaya inisialisasi tidak lagi 100% acak untuk semua algoritma populasi).
        positions = [greedy_seed_chrom(prob)]
        while len(positions) < self.pop_size:
            positions.append(repair_chromosome(random_chrom(prob), prob, bounds))
        
        pbest_positions = [list(p) for p in positions]
        pbest_costs = [compute_total_cost(p, prob, bounds) for p in positions]
        
        gbest_idx = min(range(self.pop_size), key=lambda i: pbest_costs[i])
        gbest_pos, gbest_cost = list(pbest_positions[gbest_idx]), pbest_costs[gbest_idx]

        for it in range(self.iterations):
            # FIX 3: Linear Decreasing Inertia Weight
            w = self.w_max - (self.w_max - self.w_min) * (it / self.iterations)

            for i in range(self.pop_size):
                new_pos = list(positions[i])
                
                for j in range(len(prob.services)):
                    r1, r2 = random.random(), random.random()
                    
                    # FIX 1: Probabilistic Action Selection (Roulette Wheel)
                    p_pbest = self.c1 * r1
                    p_gbest = self.c2 * r2
                    total = w + p_pbest + p_gbest
                    
                    roll = random.random() * total
                    
                    if roll < w:
                        pass  # Inersia: Pertahankan posisi saat ini
                    elif roll < w + p_pbest:
                        new_pos[j] = pbest_positions[i][j]  # Kognitif: Ikuti pbest
                    else:
                        new_pos[j] = gbest_pos[j]           # Sosial: Ikuti gbest
                        
                    # FIX 2: Mekanisme eksplorasi acak untuk mencegah stagnasi
                    if random.random() < self.mutation_prob:
                        new_pos[j] = random.choice(prob.candidate_nodes)

                # Repair dan evaluasi
                positions[i] = repair_chromosome(new_pos, prob, bounds)
                current_cost = compute_total_cost(positions[i], prob, bounds)
                
                # Update pbest
                if current_cost < pbest_costs[i]:
                    pbest_costs[i] = current_cost
                    pbest_positions[i] = list(positions[i])
                    
                    # Update gbest
                    if current_cost < gbest_cost:
                        gbest_cost = current_cost
                        gbest_pos = list(positions[i])

        return to_allocation(repair_chromosome(gbest_pos, prob, bounds), prob)