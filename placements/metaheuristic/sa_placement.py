"""Simulated Annealing Placement (SAPlacement) - Single-solution metaheuristic.

Algoritma diterapkan ke fog service placement: [Apat et al., 2024] (FSPSA).
"""
from __future__ import annotations
import random
import math
from typing import List

from placements.placement import Placement
from placements.metaheuristic._common import PlacementProblem, build_problem, precompute_normalization_bounds, compute_total_cost, greedy_seed_chrom, repair_chromosome, to_allocation

class SAPlacement(Placement):
    def __init__(
        self,
        iterations: int = 1000,
        temp_init: float = 1.0,
        temp_min: float = 1e-4,
        cooling_rate: float = 0.995,
        neighbor_k: int = 3,
        alpha: float = 1.0 / 3.0,
        beta: float = 1.0 / 3.0,
        gamma: float = 1.0 / 3.0,
        seed: int = None,
    ):
        """
        Parameters
        ----------
        iterations  : Jumlah maksimum iterasi SA.
        temp_init   : Suhu awal (T0). Dalam ruang cost ternormalisasi [0,1],
                      nilai 1.0 berarti hampir semua solusi buruk masih diterima di awal.
        temp_min    : Suhu berhenti. Loop berhenti lebih awal jika T < temp_min.
        cooling_rate: Faktor pendinginan geometris (T = T * cooling_rate per iterasi).
        neighbor_k  : Jumlah gene yang dimutasi per langkah untuk membuat tetangga.
                      Nilai kecil (1-3) = eksplorasi lokal; nilai besar = lompatan jauh.
        """
        super().__init__()
        self.name        = "SA"
        self.iterations  = iterations
        self.temp_init   = temp_init
        self.temp_min    = temp_min
        self.cooling_rate = cooling_rate
        self.neighbor_k  = neighbor_k
        self.alpha_obj   = alpha
        self.beta_obj    = beta
        self.gamma_obj   = gamma
        self.seed        = seed

    # ------------------------------------------------------------------
    # Neighbour generation: mutasi k gene secara acak
    # ------------------------------------------------------------------
    @staticmethod
    def _get_neighbour(chrom: List[int], prob: PlacementProblem, k: int) -> List[int]:
        """Membuat solusi tetangga dengan memutasi k posisi acak."""
        neighbour = list(chrom)
        positions = random.sample(range(len(chrom)), min(k, len(chrom)))
        for j in positions:
            options = [n for n in prob.candidate_nodes if n != neighbour[j]]
            if options:
                neighbour[j] = random.choice(options)
        return neighbour

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------
    def generate_allocation(self, topology, applications, users):
        if self.seed is not None: random.seed(self.seed)

        prob = build_problem(topology, applications, users,
                             alpha=self.alpha_obj, beta=self.beta_obj, gamma=self.gamma_obj)
        if not prob.services or not prob.candidate_nodes: return []

        bounds = precompute_normalization_bounds(prob)

        # Inisialisasi solusi awal dengan greedy seed
        current = repair_chromosome(greedy_seed_chrom(prob), prob, bounds)
        current_cost = compute_total_cost(current, prob, bounds)

        # Catat solusi terbaik secara historis
        best = list(current)
        best_cost = current_cost

        T = self.temp_init

        for _ in range(self.iterations):
            if T < self.temp_min:
                break

            # Buat tetangga dengan mutasi k gene
            neighbour = repair_chromosome(
                self._get_neighbour(current, prob, self.neighbor_k), prob, bounds
            )
            neighbour_cost = compute_total_cost(neighbour, prob, bounds)

            delta = neighbour_cost - current_cost  # Positif = lebih buruk

            # Kriteria penerimaan Metropolis
            if delta < 0:
                # Solusi lebih baik → selalu diterima
                current = neighbour
                current_cost = neighbour_cost
            else:
                # Solusi lebih buruk → diterima dengan probabilitas exp(-delta/T)
                if random.random() < math.exp(-delta / T):
                    current = neighbour
                    current_cost = neighbour_cost

            # Update best historis
            if current_cost < best_cost:
                best_cost = current_cost
                best = list(current)

            # Pendinginan geometris
            T *= self.cooling_rate

        return to_allocation(repair_chromosome(best, prob, bounds), prob)