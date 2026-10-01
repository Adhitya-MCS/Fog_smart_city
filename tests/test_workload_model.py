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


class BaselineTests(unittest.TestCase):
    def setUp(self):
        from generator.generate_scenario import generate_users
        from generator.hierarchical_topology import generate_hierarchical_topology, load_cameras
        cams = load_cameras("data/cameras_SYNTHETIC.csv")
        topo, c2l1 = generate_hierarchical_topology(cams)
        apps = generate_applications(cams, 2, 1.0, 5)
        self.prob = common.build_problem(topo, apps, generate_users(apps, c2l1, 5))

    def test_baselines_are_admissible(self):
        for fn in (common.greedy_seed_chrom, common.nearest_feasible_chrom, common.min_latency_chrom):
            chrom = fn(self.prob)
            self.assertEqual(len(chrom), len(self.prob.services))
            self.assertTrue(common.evaluate_ram_valid(chrom, self.prob))
            self.assertTrue(common.evaluate_cpu_valid(chrom, self.prob))

    def test_source_aware_baselines_stay_closer_than_greedy(self):
        hops = lambda ch: sum(common._get_hops(i, n, self.prob) for i, n in enumerate(ch))
        lat = lambda ch: sum(sum(common._calc_times(i, n, self.prob)) for i, n in enumerate(ch))
        greedy = common.greedy_seed_chrom(self.prob)
        self.assertLessEqual(hops(common.nearest_feasible_chrom(self.prob)), hops(greedy))
        self.assertLessEqual(lat(common.min_latency_chrom(self.prob)), lat(greedy))


class LiteratureProfileTests(unittest.TestCase):
    def test_edge_ipt_reproduces_literature_det_times(self):
        from config import app_params, topology_params as tp
        self.assertEqual(app_params.DET_INSTRUCTIONS, 93_000)
        self.assertEqual({k: v["IPT"] for k, v in tp.EDGE_CLASSES.items()},
                         {"cpu_A": 445, "cpu_B": 1000, "accel_A": 7750, "accel_B": 9300})
        for name, ms in tp.EDGE_DET_MS.items():
            self.assertAlmostEqual(app_params.DET_INSTRUCTIONS / tp.EDGE_CLASSES[name]["IPT"], ms, delta=0.2)

    def test_upper_tiers_are_multiples_of_reference_class(self):
        from config import topology_params as tp
        self.assertEqual(tp.NODE_CLASSES["L2"]["IPT"], 3 * 9300)
        self.assertEqual(tp.NODE_CLASSES["L3"]["IPT"], 10 * 9300)
        self.assertEqual(tp.CLOUD_ATTRS["IPT"], 10 * 9300)

    def test_det_stream_reservation_is_one_tenth_of_reference_l1(self):
        app = generate_applications(CAMS, 1, 1.0, 1, fixed_deadline=True)[0]
        self.assertAlmostEqual(app["module"][0]["cpu_rate"], 930.0)
        self.assertAlmostEqual(app["deadline"], 100.0)


class TopologyOptionTests(unittest.TestCase):
    @staticmethod
    def build(**kw):
        from generator.hierarchical_topology import generate_hierarchical_topology, load_cameras
        return generate_hierarchical_topology(load_cameras("data/cameras_SYNTHETIC.csv"), **kw)[0]

    def test_l1_class_and_cloud_propagation_are_applied(self):
        topo = self.build(l1_class="cpu_B", cloud_pr_ms=100.0)
        l1 = [e for e in topo["entity"] if e["type"] == "L1"]
        self.assertEqual({(e["hw"], e["IPT"]) for e in l1}, {("cpu_B", 1000)})
        self.assertEqual([l["PR"] for l in topo["link"] if l["class"] == "L3-CLOUD"], [100.0])

    def test_defaults_and_unknown_class(self):
        topo = self.build()
        self.assertEqual({e["hw"] for e in topo["entity"] if e["type"] == "L1"}, {"accel_B"})
        self.assertEqual([l["PR"] for l in topo["link"] if l["class"] == "L3-CLOUD"], [25.6])
        with self.assertRaises(ValueError):
            self.build(l1_class="hailo")


class FpsJitterTests(unittest.TestCase):
    def test_uniform_by_default_and_fixed_deadline_survives_jitter(self):
        self.assertTrue(all(abs(a["fps"] - 10.0) < 1e-9 for a in generate_applications(CAMS, 1, 1.0, 4)))
        base = generate_applications(CAMS, 1, 1.0, 4, fixed_deadline=True, fps_jitter=0.2)
        fast = generate_applications(CAMS, 1, 4.0, 4, fixed_deadline=True, fps_jitter=0.2)
        self.assertTrue(len({round(a["deadline"], 6) for a in base}) > 1)
        for a, b in zip(base, fast):
            self.assertAlmostEqual(a["deadline"], b["deadline"])


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
