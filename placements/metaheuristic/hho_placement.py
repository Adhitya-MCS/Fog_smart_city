"""Harris Hawks Optimization Placement (HHOPlacement) - With segment mutation & Discrete Fixes.

Algoritma asli: [Heidari et al., 2019] (Harris Hawks Optimization).
Model placement (objective/constraint): [Apat et al., 2024]. Perluasan (this work).
"""
from __future__ import annotations
import random

from placements.placement import Placement
from placements.metaheuristic._common import build_problem, precompute_normalization_bounds, compute_total_cost, greedy_seed_chrom, random_chrom, repair_chromosome, to_allocation

class HHOPlacement(Placement):
    def __init__(self, pop_size=30, iterations=100, alpha=1.0 / 3.0, beta=1.0 / 3.0, gamma=1.0 / 3.0, seed=None):
        super().__init__()
        self.name = "HHO"
        self.pop_size = pop_size
        self.iterations = iterations
        self.alpha_obj = alpha
        self.beta_obj = beta
        self.gamma_obj = gamma
        self.seed = seed

    @staticmethod
    def _segment_mutation(dim):
        """Generates a mask for bounded short/long segment mutation."""
        mask = [False] * dim
        if dim == 0: return mask
        # FIX 3: Gunakan dim//4 dan minimum 1 untuk variasi yang lebih baik di problem kecil
        if random.random() < 0.3:  # 30% chance of long jump (segment)
            start = random.randint(0, dim - 1)
            length = random.randint(1, max(2, dim // 4))
            for k in range(start, min(dim, start + length)):
                mask[k] = True
        else:  # 70% short jump
            mask[random.randint(0, dim - 1)] = True
        return mask

    def generate_allocation(self, topology, applications, users):
        if self.seed is not None: random.seed(self.seed)
        prob = build_problem(topology, applications, users, alpha=self.alpha_obj, beta=self.beta_obj, gamma=self.gamma_obj)
        if not prob.services or not prob.candidate_nodes: return []

        bounds = precompute_normalization_bounds(prob)
        # 1 greedy-seed + sisanya acak (konsisten dengan GA).
        hawks = [greedy_seed_chrom(prob)]
        while len(hawks) < self.pop_size:
            hawks.append(repair_chromosome(random_chrom(prob), prob, bounds))
        costs = [compute_total_cost(h, prob, bounds) for h in hawks]

        best_idx = min(range(self.pop_size), key=lambda i: costs[i])
        best_pos, best_cost = list(hawks[best_idx]), costs[best_idx]

        for it in range(self.iterations):
            E0 = 2 * random.random() - 1
            escaping_energy = 2 * E0 * (1.0 - (it / self.iterations))

            for i in range(self.pop_size):
                hawk = list(hawks[i])
                r = random.random()
                
                # FIX 4: Siapkan daftar elang lain agar tidak memilih dirinya sendiri
                other_hawks = [h for idx, h in enumerate(hawks) if idx != i]
                if not other_hawks: other_hawks = hawks # Fallback jika pop_size=1

                if abs(escaping_energy) >= 1:
                    # EXPLORATION
                    if random.random() < 0.5:
                        # Berdasarkan elang lain
                        rand_hawk = random.choice(other_hawks)
                        for j in range(len(prob.services)):
                            hawk[j] = rand_hawk[j]
                    else:
                        # Berdasarkan best dan elang lain
                        rand_hawk = random.choice(other_hawks)
                        for j in range(len(prob.services)):
                            if random.random() < 0.5:
                                hawk[j] = best_pos[j]
                            else:
                                hawk[j] = rand_hawk[j]
                
                else:
                    # EXPLOITATION
                    if r >= 0.5 and abs(escaping_energy) < 0.5:
                        # Soft besiege (Gradual move to best)
                        for j in range(len(prob.services)):
                            if random.random() < abs(escaping_energy):
                                hawk[j] = best_pos[j]
                                
                    elif r >= 0.5 and abs(escaping_energy) >= 0.5:
                        # FIX 2: Hard besiege dengan 10% noise untuk mencegah konvergensi prematur
                        for j in range(len(prob.services)):
                            if random.random() < 0.9:
                                hawk[j] = best_pos[j]
                            else:
                                hawk[j] = random.choice(prob.candidate_nodes)
                            
                    elif r < 0.5 and abs(escaping_energy) >= 0.5:
                        # Soft besiege with progressive rapid dives (segment mutation)
                        levy_mask = self._segment_mutation(len(prob.services))
                        for j in range(len(prob.services)):
                            if levy_mask[j]:
                                options = [n for n in prob.candidate_nodes if n != hawk[j]]
                                if options: hawk[j] = random.choice(options)
                            else:
                                if random.random() < 0.7:
                                    hawk[j] = best_pos[j]
                                
                    else:
                        # Hard besiege with progressive rapid dives (Aggressive segment + Best)
                        levy_mask = self._segment_mutation(len(prob.services))
                        for j in range(len(prob.services)):
                            if levy_mask[j]:
                                options = [n for n in prob.candidate_nodes if n != hawk[j]]
                                if options: hawk[j] = random.choice(options)
                            else:
                                hawk[j] = best_pos[j]

                hawks[i] = repair_chromosome(hawk, prob, bounds)
                costs[i] = compute_total_cost(hawks[i], prob, bounds)
                
                if costs[i] < best_cost:
                    best_cost = costs[i]
                    best_pos = list(hawks[i])

        return to_allocation(repair_chromosome(best_pos, prob, bounds), prob)