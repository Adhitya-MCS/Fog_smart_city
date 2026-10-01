import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from analysis import ablation

BASE = dict(design='fps-fixed-deadline', manifest_sha256='m', topology_seed=42, seed=1, runs=5, budget=3000,
            duration=10000, drain_time=10000, yafs_sha256={'a': 'x'}, python='3.13', packages={},
            cloud_mode='adaptive', experiment_sha256={'runner/a.py': '1', 'analysis/b.py': '1'})


class ComparableTests(unittest.TestCase):
    def test_ablated_options_and_analysis_code_may_differ(self):
        other = dict(BASE, cloud_mode='none', experiment_sha256={'runner/a.py': '1', 'analysis/b.py': '2'})
        ablation.check_comparable(BASE, other, 'none')

    def test_different_design_or_result_code_is_rejected(self):
        with self.assertRaises(ValueError):
            ablation.check_comparable(BASE, dict(BASE, design='fps-intensity'), 'x')
        with self.assertRaises(ValueError):
            ablation.check_comparable(BASE, dict(BASE, experiment_sha256={'runner/a.py': '2', 'analysis/b.py': '1'}), 'x')

    def test_different_scenario_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in [('ref', 'a'), ('var', 'b')]:
                d = Path(tmp) / name / 'apps_1.0' / 'run_1' / 'scenario'
                d.mkdir(parents=True)
                for f in ablation.SCENARIO_FILES:
                    (d / f).write_text(content)
            with self.assertRaises(ValueError):
                ablation.check_scenarios(Path(tmp) / 'ref', Path(tmp) / 'var', 'var')


class MetricVersionTests(unittest.TestCase):
    @staticmethod
    def folder(tmp, name, manifest):
        d = Path(tmp) / name / 'analysis'
        d.mkdir(parents=True)
        if manifest is not None:
            (d / 'analysis_manifest.json').write_text(json.dumps(manifest))
        return Path(tmp) / name

    def test_same_metric_code_is_accepted_and_different_or_missing_is_rejected(self):
        same = dict(metrics_code_sha256='a', packages={'pandas': '2'})
        with tempfile.TemporaryDirectory() as tmp:
            ref = self.folder(tmp, 'ref', same)
            ablation.check_metrics(ref, self.folder(tmp, 'ok', dict(same)), 'ok')
            with self.assertRaises(ValueError):
                ablation.check_metrics(ref, self.folder(tmp, 'other', dict(same, metrics_code_sha256='b')), 'other')
            with self.assertRaises(ValueError):
                ablation.check_metrics(ref, self.folder(tmp, 'missing', None), 'missing')


class CompareTests(unittest.TestCase):
    @staticmethod
    def groups(n, offset=0.0):
        return {('GA', 1.0): {f'i{k}': dict(ontime_delivery_ratio=0.5 + 0.01 * k + offset) for k in range(n)}}

    def test_too_few_pairs_gives_status_rows_instead_of_failing(self):
        rows = ablation.compare(self.groups(1), {'v': self.groups(1, 0.1)}, ['ontime_delivery_ratio'])
        self.assertEqual([r['status'] for r in rows], ['insufficient paired runs'])
        self.assertEqual(rows[0]['n'], 1)

    def test_enough_pairs_are_tested(self):
        rows = ablation.compare(self.groups(6), {'v': self.groups(6, 0.1)}, ['ontime_delivery_ratio'])
        self.assertEqual(rows[0]['status'], 'tested')
        self.assertAlmostEqual(rows[0]['mean_difference'], 0.1)

    def test_duplicate_instance_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'analysis').mkdir()
            rec = dict(algorithm='GA', workload=1.0, run=1, instance_id='same')
            (root / 'analysis' / 'run_metrics.json').write_text(json.dumps([rec, rec]))
            log = root / 'apps_1.0' / 'run_1' / 'GA'
            log.mkdir(parents=True)
            (log / 'time_log.json').write_text(json.dumps(dict(execution_time_sec=1.0)))
            with self.assertRaises(ValueError):
                ablation.load_variant(root)


class CliIntegrationTests(unittest.TestCase):
    """Tiny real runs: seeds keep the fixed deadline constant across levels; CLI handles 1-run variants."""

    def test_runner_levels_share_cameras_and_ablation_cli_reports_insufficient_pairs(self):
        from analysis import constraint_analysis
        from config.users_params import DESIGNS
        from runner import run_experiment
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            for name, mode in [('full', 'adaptive'), ('constant', 'constant')]:
                argv = ['run_experiment', '--output', str(root / name), '--manifest', 'data/cameras_SYNTHETIC.csv',
                        '--runs', '1', '--algorithms', 'Greedy', '--budget', '10', '--duration', '300',
                        '--drain-time', '300', '--cloud-mode', mode]
                with patch.object(sys, 'argv', argv):
                    run_experiment.main()
                with patch.object(sys, 'argv', ['constraint_analysis', str(root / name)]):
                    constraint_analysis.main()
            deadlines = []
            for scenario in sorted((root / 'full').glob('apps_*/run_1/scenario/appDefinition.json')):
                deadlines.append([round(a['deadline'], 6) for a in json.loads(scenario.read_text())])
            self.assertEqual(len(deadlines), len(DESIGNS['fps-fixed-deadline']))
            self.assertTrue(all(d == deadlines[0] for d in deadlines))

            argv = ['ablation', str(root / 'out'), f"full={root / 'full'}", f"constant={root / 'constant'}"]
            with patch.object(sys, 'argv', argv):
                ablation.main()
            rows = json.loads((root / 'out' / 'ablation.json').read_text())['comparisons']
            self.assertTrue(rows and all(r['status'] == 'insufficient paired runs' for r in rows))

            self.assertTrue((root / 'full' / 'analysis' / 'analysis_manifest.json').exists())
            manifest = json.loads((root / 'constant' / 'manifest.json').read_text())
            manifest['design'] = 'fps-intensity'
            (root / 'constant' / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(sys, 'argv', ['ablation', str(root / 'out2'), f"full={root / 'full'}", f"constant={root / 'constant'}"]):
                with self.assertRaises(ValueError):
                    ablation.main()


if __name__ == '__main__':
    unittest.main()
