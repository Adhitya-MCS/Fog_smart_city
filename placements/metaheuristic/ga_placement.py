"""Genetic Algorithm Placement (GAPlacement) - Minimizes Cost.

Algoritma & encoding (list integer module->node, crossover/mutation/tournament):
[Apat et al., 2024] dan [Pakpahan et al., 2025] (Algorithm 6).
"""
from __future__ import annotations
import random
from typing import List, Optional

from placements.placement import Placement
from placements.metaheuristic._common import (
    PlacementProblem, ServiceNormBounds, build_problem,
    precompute_normalization_bounds, compute_total_cost,
    greedy_seed_chrom, random_chrom, repair_chromosome, to_allocation,
)

class GAPlacement(Placement):
    def __init__(self, pop_size=30, generations=100, cx_rate=0.8, tourn_k=3,
                 alpha=1.0 / 3.0, beta=1.0 / 3.0, gamma=1.0 / 3.0, seed=None):
        super().__init__()
        self.name = "GA"
        self.pop_size = pop_size
        self.generations = generations
        self.cx_rate = cx_rate
        self.tourn_k = tourn_k
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.seed = seed

    def generate_allocation(self, topology, applications, users):
        if self.seed is not None: random.seed(self.seed)
        prob = build_problem(topology, applications, users, alpha=self.alpha, beta=self.beta, gamma=self.gamma)
        if not prob.services or not prob.candidate_nodes: return []

        bounds = precompute_normalization_bounds(prob)
        population = self._generate_initial_population(prob, bounds)
        costs = [compute_total_cost(c, prob, bounds) for c in population]

        best_idx = min(range(self.pop_size), key=lambda i: costs[i])
        best, best_cost = list(population[best_idx]), costs[best_idx]

        for _gen in range(self.generations):
            new_pop = [list(best)]  # Elitism
            while len(new_pop) < self.pop_size:
                p1 = self._tournament_select(population, costs)
                p2 = self._tournament_select(population, costs)
                c1, c2 = self._crossover(p1, p2)
                self._mutate(c1, prob)
                self._mutate(c2, prob)
                c1 = repair_chromosome(c1, prob, bounds)
                c2 = repair_chromosome(c2, prob, bounds)
                new_pop.append(c1)
                if len(new_pop) < self.pop_size: new_pop.append(c2)

            population = new_pop
            costs = [compute_total_cost(c, prob, bounds) for c in population]
            idx = min(range(self.pop_size), key=lambda i: costs[i])
            if costs[idx] < best_cost:
                best_cost = costs[idx]
                best = list(population[idx])
            if max(costs) - min(costs) < 1e-12: break  # Convergence check

        return to_allocation(repair_chromosome(best, prob, bounds), prob)

    def _generate_initial_population(self, prob, bounds):
        pop = [greedy_seed_chrom(prob)]
        while len(pop) < self.pop_size:
            pop.append(repair_chromosome(random_chrom(prob), prob, bounds))
        return pop

    def _mutate(self, chrom, prob):
        if not chrom: return
        j = random.randrange(len(chrom))
        options = [n for n in prob.candidate_nodes if n != chrom[j]]
        if options: chrom[j] = random.choice(options)

    def _crossover(self, p1, p2):
        if random.random() > self.cx_rate or len(p1) < 2: return list(p1), list(p2)
        cut = random.randint(1, len(p1) - 1)
        return p1[:cut] + p2[cut:], p2[:cut] + p1[cut:]

    def _tournament_select(self, population, costs):
        candidates = random.sample(range(len(population)), min(self.tourn_k, len(population)))
        winner = min(candidates, key=lambda i: costs[i])  # Minimize cost
        return list(population[winner])