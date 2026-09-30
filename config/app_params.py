"""
Application configuration parameters for fog computing simulation.
Extended workflow models for service placement research.

Workflow Types:
1. BOT      -> Bag of Tasks (independent)
2. CHAIN    -> Linear pipeline
3. DAG      -> General DAG workflow

Recommended for comparative workflow-aware service placement studies.

Provenance (sumber tiap nilai):
  - Modul/app, instruction size, RAM, message size -> [Pakpahan et al., 2025], Table 1.
  - Model BOT (service independen, tanpa precedence) -> [Apat et al., 2024].
  - Deadline -> ASUMSI (this work); tak ada di Pakpahan, tak bernilai numerik di Apat.
"""

import random
from typing import Optional
import networkx as nx

# ---------------------------------------------------------------------------
# Application count
# ---------------------------------------------------------------------------

NUM_APPLICATIONS = 10

# ---------------------------------------------------------------------------
# Modules / services per application
# ---------------------------------------------------------------------------

MODULES_PER_APP_MIN = 2    # [Pakpahan et al., 2025] (Number of Module 2-8)
MODULES_PER_APP_MAX = 8    # [Pakpahan et al., 2025]

# ---------------------------------------------------------------------------
# WORKFLOW MODEL CONFIGURATION
# ---------------------------------------------------------------------------

APP_MODEL_TYPE = 'BOT'

APP_MODEL_TYPES = [
    "BOT",
    "CHAIN",
    "DAG",
]

# DAG / Hybrid configuration
DAG_EXTRA_EDGE_PROB = 0.30
HYBRID_EXTRA_EDGE_PROB = 0.20

# ---------------------------------------------------------------------------
# Task / service attributes
# ---------------------------------------------------------------------------

# Instruction count per service (workload); dipakai untuk t_proc = instructions / IPT.
TASK_LENGTH_MIN = 20000  # instructions  [Pakpahan et al., 2025] (Instruction Size 20000-60000)
TASK_LENGTH_MAX = 60000  # instructions

RAM_USAGE_MIN = 1    # MB  [Pakpahan et al., 2025] (Required RAM 1-6)
RAM_USAGE_MAX = 6    # MB

# NOTE (novelty, this work): CPU demand BUKAN atribut acak bebas. Diturunkan dari beban
# sebagai laju (cpu_i = instructions / deadline, satuan inst/ms) di build_problem(),
# konsisten dengan IPT node & semantik YAFS (YAFS memakai IPT, bukan MIPS).

INPUT_BYTES_MIN = 1_500_000   # bytes  [Pakpahan et al., 2025] (Message Size 1.5M-4.5M)
INPUT_BYTES_MAX = 4_500_000   # bytes

# Response/result size (uplink) -- model Apat (request + response, Eq.14 T_comm = Req+Res).
# AI inference result is small (KB). ASSUMPTION (this work): Apat defines a separate
# output task size but gives no number; Pakpahan has no response leg.
OUTPUT_BYTES_MIN = 1_000    # bytes (assumption, this work)
OUTPUT_BYTES_MAX = 10_000   # bytes

# ASSUMPTION (this work): deadline level-aplikasi. Tak ada di Pakpahan (tanpa deadline)
# maupun nilai numerik di Apat. Skala 50-250 ms menjaga constraint deadline & CPU aktif
# (cpu_i = inst/deadline). Sumber numerik final masih perlu ditetapkan.
DEADLINE_MIN = 50    # ms  (assumption, this work)
DEADLINE_MAX = 250   # ms

# ---------------------------------------------------------------------------
# WORKFLOW GENERATOR
# ---------------------------------------------------------------------------

def generate_app_dag(app_model_type: Optional[str] = None) -> nx.DiGraph:
    """
    Generate workflow graph based on APP_MODEL_TYPE.

    Supported workflow types:
    - BOT
    - CHAIN
    - DAG
    """

    model_type = app_model_type or APP_MODEL_TYPE

    num_modules = random.randint(
        MODULES_PER_APP_MIN,
        MODULES_PER_APP_MAX
    )

    dag = nx.DiGraph()

    dag.add_nodes_from(range(num_modules))

    # ===============================================================
    # 1. BOT (Bag of Tasks)
    # Independent services
    # ===============================================================

    if model_type == 'BOT':

        # No dependency edges
        pass

    # ===============================================================
    # 2. CHAIN
    # Linear workflow
    # ===============================================================

    elif model_type == 'CHAIN':

        for i in range(num_modules - 1):
            dag.add_edge(i, i + 1)

    # ===============================================================
    # 3. DAG
    # General workflow DAG
    # ===============================================================

    elif model_type == 'DAG':

        # Base chain to ensure connectivity
        for i in range(num_modules - 1):
            dag.add_edge(i, i + 1)

        # Add random DAG edges
        for i in range(num_modules):
            for j in range(i + 2, num_modules):

                if random.random() < DAG_EXTRA_EDGE_PROB:
                    dag.add_edge(i, j)

    else:

        raise ValueError(
            f"Unknown APP_MODEL_TYPE: {model_type}"
        )

    return dag


# ---------------------------------------------------------------------------
# SERVICE ATTRIBUTE GENERATOR
# ---------------------------------------------------------------------------

def get_service_attrs() -> dict:
    """
    Generate random attributes for a single service/module.
    """

    return {

        "instructions": random.randint(
            TASK_LENGTH_MIN,
            TASK_LENGTH_MAX
        ),

        "RAM": random.randint(
            RAM_USAGE_MIN,
            RAM_USAGE_MAX
        ),

        "bytes": random.randint(
            INPUT_BYTES_MIN,
            INPUT_BYTES_MAX
        ),
        "output_bytes": random.randint(
            OUTPUT_BYTES_MIN,
            OUTPUT_BYTES_MAX
        ),
        "deadline": random.randint(
            DEADLINE_MIN,
            DEADLINE_MAX
        ),
    }


# ---------------------------------------------------------------------------
# APPLICATION DEADLINE
# ---------------------------------------------------------------------------

def get_app_deadline() -> int:

    return random.randint(
        DEADLINE_MIN,
        DEADLINE_MAX
    )


# ---------------------------------------------------------------------------
# OUTPUT FILE
# ---------------------------------------------------------------------------

OUTPUT_FILE = "scenarios/appDefinition.json"