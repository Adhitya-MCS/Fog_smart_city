import unittest
from types import SimpleNamespace

from generator.generate_scenario import generate_applications
from placements.metaheuristic import _common as common

CAMS = [{"cam_id": "c0"}, {"cam_id": "c1"}]


class CloudCoefficientTests(unittest.TestCase):
    prob = SimpleNamespace(fog_nodes=[0, 1], node_ram={0: 1000, 1: 1000}, node_ipt={0: 1000, 1: 1000})

    def test_cpu_pressure_lowers_coefficient_with_flat_ram(self):
        idle = common.cloud_coefficient(self.prob, 100, 0)
        loaded = common.cloud_coefficient(self.prob, 100, 1800)
        self.assertAlmostEqual(idle, common.CLOUD_PENALTY_BASE * 0.95)
        self.assertAlmostEqual(loaded, common.CLOUD_PENALTY_BASE * 0.1)

    def test_ram_pressure_still_counts(self):
        self.assertAlmostEqual(common.cloud_coefficient(self.prob, 1000, 0), common.CLOUD_PENALTY_BASE * 0.5)


class CloudReportTests(unittest.TestCase):
    def test_report_uses_only_fog_placed_services(self):
        prob = SimpleNamespace(fog_nodes=[0, 1], cloud_id=2, node_ram={0: 1000, 1: 1000}, node_ipt={0: 1000, 1: 1000},
                               service_ram={0: 100, 1: 200}, service_cpu={0: 500, 1: 900})
        rep = common.cloud_pressure_report([0, 2], prob)
        self.assertEqual(rep["cloud_services"], 1)
        self.assertAlmostEqual(rep["cpu_pressure"], 500 / 2000)
        self.assertAlmostEqual(rep["cloud_coefficient"], common.cloud_coefficient(prob, 100, 500))


class DeadlineDesignTests(unittest.TestCase):
    def test_coupled_deadline_shrinks_and_cpu_rate_matches_reservation(self):
        base = generate_applications(CAMS, 1, 1.0, 3)
        fast = generate_applications(CAMS, 1, 4.0, 3)
        for a, b in zip(base, fast):
            self.assertAlmostEqual(b["deadline"], a["deadline"] / 4)
            m = b["module"][0]
            self.assertAlmostEqual(m["cpu_rate"], m["instructions"] / b["deadline"])

    def test_fixed_deadline_keeps_deadline_but_cpu_rate_grows(self):
        base = generate_applications(CAMS, 1, 1.0, 3, fixed_deadline=True)
        fast = generate_applications(CAMS, 1, 4.0, 3, fixed_deadline=True)
        for a, b in zip(base, fast):
            self.assertAlmostEqual(b["deadline"], a["deadline"])
            self.assertAlmostEqual(b["module"][0]["cpu_rate"], 4 * a["module"][0]["cpu_rate"])


class RunnerSeedTests(unittest.TestCase):
    def test_fixed_deadline_is_constant_across_levels_with_runner_seed(self):
        from config.users_params import DESIGNS
        from runner.run_experiment import camera_seed
        seed = camera_seed(20260909, 42, 1)
        levels = DESIGNS["fps-fixed-deadline"]
        apps = [generate_applications(CAMS, layers, mult, seed, fixed) for layers, mult, fixed in levels]
        for level_apps in apps[1:]:
            for a, b in zip(apps[0], level_apps):
                self.assertAlmostEqual(a["deadline"], b["deadline"])

    def test_camera_seed_depends_on_run_only(self):
        from runner.run_experiment import camera_seed
        self.assertEqual(camera_seed(1, 42, 3), camera_seed(1, 42, 3))
        self.assertNotEqual(camera_seed(1, 42, 3), camera_seed(1, 42, 4))


if __name__ == "__main__":
    unittest.main()
