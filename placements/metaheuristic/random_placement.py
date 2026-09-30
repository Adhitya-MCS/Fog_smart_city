"""Random Baseline Placement - Evaluates multiple random guesses and picks the best.

Baseline acak (random node + cek resource + fallback cloud): [Pakpahan et al., 2025]
(Algorithm 3) dan [Apat et al., 2024] (RFSP). Catatan: implementasi ini "best-of-N"
(N sampel acak di-repair, ambil cost terbaik), bukan single uniform pick.
"""
from __future__ import annotations
import random

from placements.placement import Placement
from placements.metaheuristic._common import build_problem, precompute_normalization_bounds, compute_total_cost, random_chrom, repair_chromosome, to_allocation

class RandomPlacement(Placement):
    def __init__(self, iterations=50, alpha=1.0 / 3.0, beta=1.0 / 3.0, gamma=1.0 / 3.0, seed=None):
        super().__init__()
        self.name = "Random"
        self.iterations = iterations
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.seed = seed

    def generate_allocation(self, topology, applications, users):
        if self.seed is not None: random.seed(self.seed)
        prob = build_problem(topology, applications, users, alpha=self.alpha, beta=self.beta, gamma=self.gamma)
        if not prob.services or not prob.candidate_nodes: return []

        bounds = precompute_normalization_bounds(prob)

        best_chrom = None
        best_cost = float('inf')

        # Generate multiple random chromosomes and keep the best one. Repair uses the
        # same `bounds`-aligned formula as the other 6 algorithms (not a dumber
        # criterion) so the comparison stays apples-to-apples: only the SEARCH
        # STRATEGY differs across strategies, not the shared repair/fitness mechanism.
        for _ in range(self.iterations):
            chrom = repair_chromosome(random_chrom(prob), prob, bounds)
            cost = compute_total_cost(chrom, prob, bounds)
            
            if cost < best_cost:
                best_cost = cost
                best_chrom = chrom
                
        return to_allocation(best_chrom, prob)