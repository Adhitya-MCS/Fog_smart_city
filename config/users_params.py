"""
Users / IoT devices configuration parameters for fog computing simulation.

  - Application request rate    : 1 – 5 per second
    → inter-arrival time        : 200 – 1000 ms  (1/rate × 1000)
"""

import random

# ---------------------------------------------------------------------------
# Request rate (Table 4)
# ---------------------------------------------------------------------------
# Request rate -> [Pakpahan et al., 2025] (IoT request rate 200-1000 ms)
#                  ekuivalen [Apat et al., 2024] ("Application request rate 1-5 per second").
# 1/5 s = 200 ms ; 1/1 s = 1000 ms
REQUEST_RATE_MIN = 1   # requests/second  [Apat et al., 2024]
REQUEST_RATE_MAX = 5   # requests/second

REQUEST_INTERVAL_MIN = 200    # ms  [Pakpahan et al., 2025]
REQUEST_INTERVAL_MAX = 1000   # ms

# ---------------------------------------------------------------------------
# Application popularity / workload model
# ---------------------------------------------------------------------------

# Probability range that a gateway node requests an application
# Lower = unpopular app
# Higher = hotspot/popular app

APP_POPULARITY_MIN = 0.0
APP_POPULARITY_MAX = 0.25

# Ensure every application has at least one user source
ENSURE_AT_LEAST_ONE_USER = True

# ---------------------------------------------------------------------------
# Attribute generator functions
# ---------------------------------------------------------------------------

def get_user_request_rate() -> int:
    """
    Return a random inter-arrival time (ms) for one IoT source.

    Derived from Table 4 "Application request rate: 1–5 per second":
      interval = 1000 / rate  →  range [200, 1000] ms
    """
    return random.randint(REQUEST_INTERVAL_MIN, REQUEST_INTERVAL_MAX)


def get_request_rate_per_second() -> float:
    """
    Return a random request rate in requests/second [1, 5].
    Convenience function when the generator needs rate directly.
    """
    return random.uniform(REQUEST_RATE_MIN, REQUEST_RATE_MAX)


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------
OUTPUT_FILE = "scenarios/usersDefinition.json"
