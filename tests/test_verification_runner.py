"""Incomplete evidence must not preserve an earlier successful verification."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('verification_runner', ROOT / 'scripts/verify_project.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class VerificationRunnerTests(unittest.TestCase):
    def check_bad_junit(self, content):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.xml'
            if content is not None:
                path.write_text(content)
            summary = RUNNER.test_summary(path)
            self.assertEqual(summary['status'], 'failed')
            self.assertEqual(summary['errors'], 1)
            self.assertEqual(summary['tests'], 0)
            self.assertTrue(summary['error'])

    def test_missing_junit_is_failed(self):
        self.check_bad_junit(None)

    def test_truncated_junit_is_failed(self):
        self.check_bad_junit('<testsuites><testcase')

    def test_empty_junit_is_failed(self):
        self.check_bad_junit('<testsuites/>')

    def test_case_failures_errors_and_skips_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'report.xml'
            path.write_text('<testsuite><testcase/><testcase><failure/></testcase>'
                            '<testcase><error/></testcase><testcase><skipped/></testcase></testsuite>')
            self.assertEqual(RUNNER.test_summary(path), {'status': 'failed', 'tests': 4,
                                                        'failures': 1, 'errors': 1, 'skipped': 1})

    def configure(self, root):
        (root / 'reports').mkdir()
        (root / 'tests').mkdir()
        (root / 'tests/probe.test.mjs').write_text('// fixture\n')
        (root / 'reports/verification.json').write_text('{"status":"passed","timestamp_utc":"old"}')
        return mock.patch.multiple(RUNNER, ROOT=root,
                                   source_hashes=mock.Mock(return_value={'probe': 'unchanged'}),
                                   observed_versions=mock.Mock(return_value={}), raw_inventory=mock.Mock(return_value={}))

    def test_unexpected_failure_replaces_an_old_pass_before_any_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def fail(*_args):
                current = json.loads((root / 'reports/verification.json').read_text())
                self.assertEqual(current['status'], 'failed')
                self.assertFalse(current['completed'])
                raise RuntimeError('deliberate runner failure')
            with self.configure(root), mock.patch.object(RUNNER, 'run_check', side_effect=fail):
                self.assertEqual(RUNNER.main([]), 1)
            current = json.loads((root / 'reports/verification.json').read_text())
            self.assertEqual(current['status'], 'failed')
            self.assertNotEqual(current['timestamp_utc'], 'old')
            self.assertIn('deliberate runner failure', current['error'])

    def run_report_fixture(self, node_xml, expected_exit):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            def fake_check(name, command, _env, timeout):
                calls.append((command, timeout))
                if 'pytest' in command:
                    (root / 'reports/verification-junit.xml').write_text('<testsuite><testcase/></testsuite>')
                elif '--test' in command:
                    (root / 'reports/verification-node-junit.xml').write_text(node_xml)
                return {'name': name, 'command': command, 'exit_code': 0, 'seconds': 0, 'output': 'finished'}
            with self.configure(root), mock.patch.object(RUNNER, 'run_check', side_effect=fake_check), \
                    mock.patch.object(RUNNER.shutil, 'which', return_value='/fixture/node'):
                self.assertEqual(RUNNER.main([]), expected_exit)
            report = json.loads((root / 'reports/verification.json').read_text())
            self.assertEqual(report['status'], 'passed' if expected_exit == 0 else 'failed')
            self.assertEqual(report['python_test_summary']['tests'], 1)
            self.assertEqual(report['node_test_summary']['status'], report['status'])
            command, timeout = next(call for call in calls if '--test' in call[0])
            self.assertIn('--test-concurrency=1', command)
            self.assertIn('--test-reporter=junit', command)
            self.assertEqual(timeout, 300)

    def test_zero_exit_with_partial_node_xml_still_fails_current_report(self):
        self.run_report_fixture('<testsuites><testcase', 1)

    def test_complete_dual_reporter_evidence_allows_current_pass(self):
        self.run_report_fixture('<testsuite><testcase/></testsuite>', 0)

    @unittest.skipUnless(os.name == 'posix', 'Requires POSIX process groups')
    def test_timeout_preserves_output_and_terminates_descendants(self):
        script = ('import subprocess,sys,time; '
                  'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
                  'print("descendant="+str(child.pid),flush=True); '
                  'print("before timeout",flush=True);time.sleep(60)')
        result = RUNNER.run_check('timeout fixture', [sys.executable, '-c', script], dict(os.environ), .5)
        self.assertEqual(result['exit_code'], 124)
        self.assertTrue(result['timed_out'])
        self.assertIn('before timeout', result['output'])
        pid = int(result['output'].split('descendant=')[1].splitlines()[0])
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        stat = Path(f'/proc/{pid}/stat')
        self.assertTrue(stat.exists())
        self.assertTrue(stat.read_text().split(') ', 1)[1].startswith('Z '))


if __name__ == '__main__':
    unittest.main()
