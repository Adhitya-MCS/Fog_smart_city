"""Whale Optimization Algorithm Placement (WOAPlacement) - Mathematically Driven.

Algoritma asli: [Mirjalili & Lewis, 2016] (The Whale Optimization Algorithm).
Model placement (objective/constraint): [Apat et al., 2024]. Perluasan (this work).
"""
from __future__ import annotations
import random
import math
from typing import List

from placements.placement import Placement
from placements.metaheuristic._common import (
    PlacementProblem, ServiceNormBounds, build_problem,
    precompute_normalization_bounds, compute_total_cost,
    greedy_seed_chrom, random_chrom, repair_chromosome, to_allocation,
)

class WOAPlacement(Placement):
    def __init__(self, pop_size=30, iterations=100, alpha=1.0 / 3.0, beta=1.0 / 3.0, gamma=1.0 / 3.0, seed=None):
        super().__init__()
        self.name = "WOA"
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
        whales = [greedy_seed_chrom(prob)]
        while len(whales) < self.pop_size:
            whales.append(repair_chromosome(random_chrom(prob), prob, bounds))
        costs = [compute_total_cost(w, prob, bounds) for w in whales]

        best_idx = min(range(self.pop_size), key=lambda i: costs[i])
        best_pos, best_cost = list(whales[best_idx]), costs[best_idx]

        for it in range(self.iterations):
            # 'a' menurun dari 2 ke 0: kontrol keseimbangan eksplorasi/eksploitasi
            a = 2.0 - it * (2.0 / self.iterations)

            # FIX: prob_spiral dihitung sekali per iterasi (bukan per gene),
            # meningkat dari ~0 ke ~1 seiring iterasi berjalan
            prob_spiral = 1.0 - (a / 2.0)

            for i in range(self.pop_size):
                whale = list(whales[i])
                A = 2 * a * random.random() - a  # Range: [-a, a]
                p = random.random()

                for j in range(len(prob.services)):
                    if p < 0.5:
                        if abs(A) < 1:
                            # EKSPLOITASI: Shrinking Encircling — bergerak ke best
                            # Semakin kecil |A|, semakin tinggi probabilitas ikut best
                            if random.random() < 0.5 + (1.0 - abs(A)) / 2.0:
                                whale[j] = best_pos[j]
                            else:
                                # Perturbasi kecil untuk diversitas
                                options = [n for n in prob.candidate_nodes if n != whale[j]]
                                if options: whale[j] = random.choice(options)
                        else:
                            # EKSPLORASI: Search for Prey — bergerak ke whale acak
                            # Hindari memilih diri sendiri
                            other_whales = [w for w in whales if w is not whales[i]]
                            rand_whale = random.choice(other_whales) if other_whales else whales[i]
                            if random.random() < abs(A) / 2.0:
                                whale[j] = rand_whale[j]
                            else:
                                options = [n for n in prob.candidate_nodes if n != whale[j]]
                                if options: whale[j] = random.choice(options)
                    else:
                        # EKSPLOITASI: Spiral Updating (bubble net)
                        # FIX: prob_spiral meningkat seiring iterasi → eksploitasi semakin kuat
                        # Fallback ke perturbasi jika tidak spiral agar posisi tidak diam
                        if random.random() < prob_spiral:
                            whale[j] = best_pos[j]
                        else:
                            # Fallback: perturbasi ringan
                            options = [n for n in prob.candidate_nodes if n != whale[j]]
                            if options: whale[j] = random.choice(options)

                whales[i] = repair_chromosome(whale, prob, bounds)
                costs[i] = compute_total_cost(whales[i], prob, bounds)

                if costs[i] < best_cost:
                    best_cost = costs[i]
                    best_pos = list(whales[i])

        return to_allocation(repair_chromosome(best_pos, prob, bounds), prob)