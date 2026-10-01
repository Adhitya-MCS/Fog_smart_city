import unittest

from analysis import regions


def record(algorithm, workload, ontime, run=1):
    return dict(algorithm=algorithm, workload=workload, run=run, ontime_delivery_ratio=ontime, emitted=100,
                unfinished=10, deadline_pending=5, requested_cloud_ratio=0.2, ontime_cloud_ratio=None,
                ontime_fog_ratio=ontime)


class RegionTests(unittest.TestCase):
    def test_categories_follow_preset_thresholds(self):
        self.assertEqual(regions.category(0.95), 'target_met')
        self.assertEqual(regions.category(0.949), 'target_missed')
        self.assertEqual(regions.category(0.5), 'target_missed')
        self.assertEqual(regions.category(0.499), 'severe_degradation')

    def test_run_is_the_unit_of_analysis(self):
        rows = regions.region_table({'c': [record('GA', 1.0, 0.96, 1), record('GA', 1.0, 0.90, 2), record('GA', 1.0, 0.97, 3)]})
        self.assertEqual(rows[0]['runs'], 3)
        self.assertAlmostEqual(rows[0]['runs_target_met'], 2 / 3)
        self.assertAlmostEqual(rows[0]['unfinished_share'], 0.1)
        self.assertIsNone(rows[0]['ontime_cloud_requests'])

    def test_selection_brackets_crossings_and_keeps_extremes(self):
        levels = {0.5: 1.0, 2.0: 0.99, 4.0: 0.97, 8.0: 0.80, 12.0: 0.2}
        rows = regions.region_table({'c': [record('GA', w, v) for w, v in levels.items()]})
        points, notes = regions.select_confirmation_points(rows)
        self.assertEqual(points['c'], [0.5, 4.0, 6.0, 8.0, 10.0, 12.0])
        self.assertEqual(notes, [])

    def test_no_crossing_is_reported_not_forced(self):
        rows = regions.region_table({'c': [record('GA', w, 1.0) for w in (1.0, 2.0, 4.0)]})
        points, notes = regions.select_confirmation_points(rows)
        self.assertEqual(points['c'], [1.0, 4.0])
        self.assertEqual(len(notes), 2)

    def test_analytic_cloud_bound_matches_estimator(self):
        self.assertAlmostEqual(regions.cloud_pr_max_ms('data/cameras_SYNTHETIC.csv'), 43.615, places=2)


if __name__ == '__main__':
    unittest.main()
