import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.scripts import apparatus


def _set_path(obj, path, value):
    current = obj
    for index, part in enumerate(path[:-1]):
        if isinstance(part, int):
            while len(current) <= part:
                current.append({})
            current = current[part]
        else:
            next_part = path[index + 1]
            current = current.setdefault(part, [] if isinstance(next_part, int) else {})
    final = path[-1]
    if isinstance(final, int):
        while len(current) <= final:
            current.append(None)
        current[final] = value
    else:
        current[final] = value


def _expected_objects(subject="s1", namespace="exp-s1-manual"):
    objects = []
    for spec in apparatus.expected_inventory(subject):
        obj = {
            "kind": spec.kind,
            "metadata": {"name": spec.name, "namespace": namespace, "resourceVersion": "dynamic"},
            "status": {"observedGeneration": 999},
        }
        for path, value in spec.fields:
            _set_path(obj, path, value)
        objects.append(obj)
    return objects


class FakeAdapter:
    def __init__(self, subject="s1", env="manual", namespace=None):
        self.subject = subject
        self.env = env
        self.namespace = namespace or "exp-{}-{}".format(subject, env)
        self.objects = _expected_objects(subject, self.namespace)
        self.pod_count = 1
        self.healthy = True
        self.node_cpu_pct = [5.0]
        self.mutate_on_inject = True
        self.injection_delay = 0.0
        self.injection_error = None
        self.correction_error = None
        self.gitops_signal = None
        self.gitops_evidence = None
        self.auto_restore_after = None
        self.snapshots = 0
        self.injections = []
        self.responses = []

    def snapshot(self):
        self.snapshots += 1
        if self.auto_restore_after and self.snapshots >= self.auto_restore_after:
            self.objects = _expected_objects(self.subject, self.namespace)
        return apparatus.Observation(
            copy.deepcopy(self.objects), self.pod_count, self.healthy, list(self.node_cpu_pct)
        )

    def mechanism_signal(self, expected):
        if self.env == "gitops":
            if self.gitops_signal is not None:
                return self.gitops_signal
            score, _ = apparatus.compare_inventory(expected, self.objects)
            return score != 100.0
        score, differences = apparatus.compare_inventory(expected, self.objects)
        return differences if score != 100.0 or differences else []

    def inject(self, scenario):
        self.injections.append(scenario)
        if self.injection_error:
            raise apparatus.ApparatusError(self.injection_error)
        if self.mutate_on_inject and scenario != "F":
            config = next(item for item in self.objects if item["kind"] == "ConfigMap")
            config["data"]["LOG_LEVEL"] = "debug"
        if self.injection_delay:
            time.sleep(self.injection_delay)
        return time.monotonic()

    def mechanism_evidence(self, expected):
        if self.env == "gitops":
            return self.gitops_evidence
        return self.mechanism_signal(expected)

    def apply_baseline(self, expected, differences):
        self.responses.append((expected, differences))
        if self.correction_error:
            self.objects = _expected_objects(self.subject, self.namespace)
            raise apparatus.ApparatusError(self.correction_error)
        self.objects = _expected_objects(self.subject, self.namespace)


class ApparatusUnitTests(unittest.TestCase):
    def run_fake(self, adapter, scenario="C", timeout=0.04, poll=0.001):
        return apparatus.run_experiment(
            adapter, adapter.subject, adapter.env, scenario, timeout_s=timeout,
            poll_interval_s=poll, run_id="fixture-test",
        )

    def test_empty_metrics_and_pod_inventory_fail_baseline_closed(self):
        for change, reason in (("metrics", "baseline_metrics_empty"), ("pods", "baseline_pods_empty"),
                               ("not_ready", "baseline_pods_not_ready")):
            with self.subTest(change=change):
                adapter = FakeAdapter()
                if change == "metrics":
                    adapter.node_cpu_pct = []
                elif change == "pods":
                    adapter.pod_count = 0
                    adapter.healthy = None
                else:
                    adapter.healthy = False
                record = self.run_fake(adapter)
                self.assertEqual(record["status"], "baseline_failed")
                self.assertEqual(record["reason"], reason)
                self.assertIsNone(record["t0_mono_s"])
                self.assertEqual(adapter.injections, [])

    def test_node_metric_parser_rejects_empty_or_malformed_output(self):
        self.assertEqual(apparatus.parse_node_cpu_percentages(""), [])
        with self.assertRaises(apparatus.ApparatusError):
            apparatus.parse_node_cpu_percentages("node-a 100m invalid 1Gi 10%\n")

    def test_field_comparison_ignores_dynamic_metadata_and_status(self):
        objects = _expected_objects()
        score, differences = apparatus.compare_inventory(apparatus.expected_inventory("s1"), objects)
        self.assertEqual(score, 100.0)
        self.assertEqual(differences, [])

    def test_missing_expected_resource_reduces_r1(self):
        objects = _expected_objects()
        objects.pop(0)
        score, differences = apparatus.compare_inventory(apparatus.expected_inventory("s1"), objects)
        self.assertEqual(score, 80.0)
        self.assertEqual(differences[0]["field_paths"], ["$identity"])

    def test_unexpected_resource_is_reported_outside_r1_denominator(self):
        objects = _expected_objects()
        objects.append({"kind": "ConfigMap", "metadata": {"name": "unmanaged"}})
        score, differences = apparatus.compare_inventory(apparatus.expected_inventory("s1"), objects)
        self.assertEqual(score, 100.0)
        self.assertEqual(differences[0]["source"], "unexpected-inventory")
        self.assertEqual(differences[0]["field_paths"], ["$identity"])

    def test_post_r1_remains_expected_inventory_percent_when_extra_is_observed(self):
        adapter = FakeAdapter()
        adapter.mutate_on_inject = False
        def inject_extra(scenario):
            adapter.objects.append({"kind": "ConfigMap", "metadata": {"name": "unmanaged"}})
            return time.monotonic()
        adapter.inject = inject_extra
        adapter.apply_baseline = lambda expected, differences: None
        record = self.run_fake(adapter, timeout=0.03)
        self.assertEqual(record["r1_post_pct"], 100.0)
        self.assertEqual(record["evidence"][0]["source"], "unexpected-inventory")

    def test_secret_difference_evidence_contains_path_not_value(self):
        objects = _expected_objects()
        secret = next(item for item in objects if item["kind"] == "Secret")
        secret["data"]["password"] = "SENTINEL_SECRET_VALUE"
        score, differences = apparatus.compare_inventory(apparatus.expected_inventory("s1"), objects)
        serialized = json.dumps(differences)
        self.assertLess(score, 100.0)
        self.assertIn("data.password", serialized)
        self.assertNotIn("SENTINEL_SECRET_VALUE", serialized)
        self.assertNotIn("ZXhwLXNlY3JldC0xMjM=", serialized)

    def test_health_remains_true_while_desired_fields_drift(self):
        adapter = FakeAdapter()
        adapter.injection_delay = 0.02
        record = self.run_fake(adapter, timeout=0.05)
        self.assertTrue(record["healthy_baseline"])
        self.assertTrue(record["healthy_final"])
        self.assertLess(record["r1_post_pct"], 100.0)
        self.assertEqual(record["detection_status"], "observed")
        self.assertEqual(record["recovery_status"], "observed")

    def test_gitops_health_and_common_oracle_do_not_replace_argocd_signal(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        record = self.run_fake(adapter, timeout=0.03)
        self.assertTrue(record["healthy_final"])
        self.assertLess(record["r1_post_pct"], 100.0)
        self.assertIsNone(record["td_mono_s"])
        self.assertEqual(record["detection_status"], "right_censored")
        self.assertEqual(record["status"], "instrumentation_failed")

    def test_gitops_restoration_is_observed_without_controller_signal(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        adapter.auto_restore_after = 3
        record = self.run_fake(adapter, timeout=0.04)
        self.assertIsNone(record["td_mono_s"])
        self.assertLess(record["r1_post_pct"], 100.0)
        self.assertIsNotNone(record["tr_mono_s"])
        self.assertEqual(record["recovery_status"], "observed")

    def test_gitops_oracle_differences_do_not_fabricate_mechanism_evidence(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        record = self.run_fake(adapter, timeout=0.03)
        self.assertIsNone(record["te_mono_s"])
        self.assertEqual(record["evidence"], [])
        self.assertEqual(record["evidence_status"], "not_evaluable")

    def test_detection_can_precede_injection_acknowledgement(self):
        adapter = FakeAdapter()
        adapter.injection_delay = 0.05
        record = self.run_fake(adapter, timeout=0.08)
        self.assertIsNotNone(record["td_mono_s"])
        self.assertLessEqual(record["t0_mono_s"], record["td_mono_s"])
        self.assertLess(record["td_mono_s"], record["ta_mono_s"])

    def test_all_observed_endpoints_finish_before_the_cutoff(self):
        adapter = FakeAdapter()
        started = time.monotonic()
        record = self.run_fake(adapter, timeout=0.5)
        self.assertEqual(record["status"], "complete")
        self.assertLess(time.monotonic() - started, 0.4)

    def test_timeout_keeps_unobserved_event_times_null_and_runs_to_cutoff(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        adapter.gitops_evidence = []
        started = time.monotonic()
        record = self.run_fake(adapter, timeout=0.04)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.035)
        self.assertEqual(record["status"], "timeout")
        self.assertIsNotNone(record["ta_mono_s"])
        self.assertIsNone(record["td_mono_s"])
        self.assertIsNone(record["te_mono_s"])
        self.assertIsNone(record["tr_mono_s"])
        self.assertEqual(record["detection_status"], "right_censored")

    def test_collection_continues_to_cutoff_after_early_restoration(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        adapter.auto_restore_after = 3
        started = time.monotonic()
        record = self.run_fake(adapter, timeout=0.04)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 0.035)
        self.assertEqual(record["detection_status"], "right_censored")
        self.assertIsNone(record["td_mono_s"])

    def test_failed_correction_cannot_declare_recovery(self):
        adapter = FakeAdapter()
        adapter.correction_error = "external_command_failed"
        record = self.run_fake(adapter)
        self.assertEqual(record["status"], "correction_failed")
        self.assertEqual(record["recovery_status"], "not_evaluable")
        self.assertIsNone(record["tr_mono_s"])
        self.assertIsNone(record["r1_recovered_pct"])

    def test_f_does_not_call_responder_or_claim_recovery(self):
        adapter = FakeAdapter()
        record = self.run_fake(adapter, scenario="F", timeout=0.02)
        self.assertEqual(adapter.responses, [])
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["reason"], "scenario_f_visibility_boundary")
        self.assertEqual(record["recovery_status"], "not_evaluable")

    def test_responder_receives_declarations_and_differences_not_scenario(self):
        adapter = FakeAdapter()
        record = self.run_fake(adapter)
        self.assertEqual(record["status"], "complete")
        self.assertEqual(len(adapter.responses), 1)
        expected, differences = adapter.responses[0]
        self.assertEqual(expected, apparatus.expected_inventory("s1"))
        self.assertTrue(differences)

    def test_runner_rejects_bad_rep_and_non_finite_timing(self):
        adapter = FakeAdapter()
        with self.assertRaises(apparatus.ApparatusError):
            apparatus.run_experiment(adapter, "s1", "manual", "A", rep=0)
        with self.assertRaises(apparatus.ApparatusError):
            apparatus.run_experiment(adapter, "s1", "manual", "A", timeout_s=float("nan"))
        with self.assertRaises(apparatus.ApparatusError):
            apparatus.run_experiment(adapter, "s1", "manual", "A", phase="formal")

    def test_unverified_injection_is_a_failure_not_a_timeout(self):
        adapter = FakeAdapter()
        adapter.inject = lambda scenario: False
        record = self.run_fake(adapter)
        self.assertEqual(record["status"], "injection_failed")
        self.assertIsNone(record["ta_mono_s"])
        self.assertEqual(record["detection_status"], "not_evaluable")

    def test_injection_response_must_prove_the_requested_change(self):
        adapter = apparatus.SubprocessAdapter("s1", "manual", "exp-s1-manual", "fixture")
        unchanged = {"kind": "ConfigMap", "metadata": {"name": "exp-web-config"},
                     "data": {"LOG_LEVEL": "info"}}
        with patch.object(adapter, "_run", return_value=json.dumps(unchanged)):
            with self.assertRaises(apparatus.ApparatusError):
                adapter.inject("C")

    def test_verified_api_response_survives_immediate_reconciliation(self):
        adapter = apparatus.SubprocessAdapter("s1", "gitops", "exp-s1-gitops", "fixture", "fixture-app")
        accepted = {"kind": "ConfigMap", "metadata": {"name": "exp-web-config"},
                    "data": {"LOG_LEVEL": "debug"}}
        with patch.object(adapter, "_run", return_value=json.dumps(accepted)):
            self.assertIsInstance(adapter.inject("C"), float)

    def test_unrelated_delete_response_does_not_verify_deletion(self):
        adapter = apparatus.SubprocessAdapter("s1", "manual", "exp-s1-manual", "fixture")
        with patch.object(adapter, "_run", return_value='{"kind":"Status","status":"Failure"}'):
            with self.assertRaises(apparatus.ApparatusError):
                adapter.inject("D")

    def test_later_read_error_preserves_already_verified_restoration(self):
        adapter = FakeAdapter(env="gitops")
        adapter.gitops_signal = False
        adapter.auto_restore_after = 3
        snapshot = adapter.snapshot
        def read_until_restored():
            if adapter.snapshots >= 4:
                raise apparatus.ApparatusError("external_command_failed")
            return snapshot()
        adapter.snapshot = read_until_restored
        record = self.run_fake(adapter)
        self.assertEqual(record["status"], "instrumentation_failed")
        self.assertIsNotNone(record["tr_mono_s"])
        self.assertEqual(record["recovery_status"], "observed")


class FakeSubprocessIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"
        objects = _expected_objects()
        argocd_resources = [
            {"kind": item["kind"], "group": apparatus.RESOURCE_GROUPS[item["kind"]], "name": item["metadata"]["name"],
             "namespace": "exp-s1-gitops", "status": "Synced"}
            for item in _expected_objects(namespace="exp-s1-gitops")
        ]
        app = {"spec": {"destination": {"namespace": "exp-s1-gitops", "server": "https://fixture.invalid"}},
               "status": {"resources": argocd_resources}}
        fake = r'''#!__PYTHON__
import json
import os
import sys
import time
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
if name == "argocd":
    sys.stdout.write(os.environ["FAKE_ARGOCD"])
    raise SystemExit(0)
if os.environ.get("FAKE_HANG"):
    time.sleep(2)
if os.environ.get("FAKE_FAIL"):
    sys.stderr.write(os.environ.get("FAKE_STDERR", "fake failure"))
    raise SystemExit(1)
if "top" in args:
    sys.stdout.write("node-1 100m 5% 1Gi 10%\n")
elif "pods" in args:
    sys.stdout.write(json.dumps({"items": [{"status": {"phase": "Running", "containerStatuses": [{"ready": True}]}}]}))
elif "get" in args:
    key = "FAKE_INJECTED_OBJECTS" if os.environ.get("FAKE_VERIFY_DRIFT") else "FAKE_OBJECTS"
    sys.stdout.write(os.environ[key])
'''.replace("__PYTHON__", sys.executable)
        for name in ("kubectl", "argocd", "shuf"):
            path = self.bin / name
            path.write_text(fake, encoding="utf-8")
            path.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "PATH": str(self.bin),
            "FAKE_CALLS": str(self.calls),
            "FAKE_OBJECTS": json.dumps({"items": objects}),
            "FAKE_ARGOCD": json.dumps(app),
        })

    def test_subprocess_adapter_uses_only_fake_client_executables(self):
        with patch.dict(os.environ, self.env):
            adapter = apparatus.SubprocessAdapter("s1", "gitops", "exp-s1-gitops", "fixture-context", "fixture-app",
                argocd_context="fixture-argo", destination_server="https://fixture.invalid")
            observation = adapter.snapshot()
            self.assertEqual(observation.healthy, True)
            self.assertEqual(observation.node_cpu_pct, [5.0])
            self.assertFalse(adapter.mechanism_signal(apparatus.expected_inventory("s1")))
        calls = [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(calls)
        self.assertTrue(all(call[0] in ("kubectl", "argocd") for call in calls))
        self.assertTrue(all("--context" in call for call in calls if call[0] == "kubectl"))

    def test_subprocess_errors_do_not_expose_sensitive_stderr(self):
        self.env["FAKE_FAIL"] = "1"
        self.env["FAKE_STDERR"] = "SENTINEL_SECRET_STDERR"
        adapter = apparatus.SubprocessAdapter("s1", "manual", "exp-s1-manual", "fixture-context")
        with patch.dict(os.environ, self.env):
            with self.assertRaises(apparatus.ApparatusError) as raised:
                adapter.snapshot()
        self.assertNotIn("SENTINEL_SECRET_STDERR", str(raised.exception))
        self.assertEqual(raised.exception.code, "external_command_failed")

    def test_successful_noop_injection_is_not_accepted(self):
        adapter = apparatus.SubprocessAdapter("s1", "manual", "exp-s1-manual", "fixture-context")
        with patch.dict(os.environ, self.env):
            with self.assertRaises(apparatus.ApparatusError) as raised:
                adapter.inject("A")
        self.assertEqual(raised.exception.code, "injection_acceptance_unverified")
        self.assertIsNotNone(raised.exception.accepted_at)

    def test_injection_requires_verified_target_field_change(self):
        injected = _expected_objects()
        config = next(item for item in injected if item["kind"] == "ConfigMap")
        config["data"]["LOG_LEVEL"] = "debug"
        env = self.env.copy()
        env["FAKE_VERIFY_DRIFT"] = "1"
        env["FAKE_INJECTED_OBJECTS"] = json.dumps({"items": injected})
        adapter = apparatus.SubprocessAdapter("s1", "manual", "exp-s1-manual", "fixture-context")
        with patch.dict(os.environ, env):
            accepted_at = adapter.inject("C")
        self.assertIsInstance(accepted_at, float)

    def test_subprocess_timeout_is_bounded(self):
        self.env["FAKE_HANG"] = "1"
        adapter = apparatus.SubprocessAdapter("s1", "manual", "exp-s1-manual", "fixture-context", command_timeout_s=0.05)
        started = time.monotonic()
        with patch.dict(os.environ, self.env):
            with self.assertRaises(apparatus.ApparatusError) as raised:
                adapter.snapshot()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(raised.exception.code, "external_command_timeout")

    def test_dry_run_executes_no_clients_and_writes_no_record(self):
        output = self.root / "run.json"
        result = subprocess.run(
            [sys.executable, str(ROOT / "experiments/scripts/apparatus.py"), "--scenario", "A", "--output", str(output)],
            env=self.env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(output.exists())
        self.assertFalse(self.calls.exists())

    def test_unallowlisted_live_context_is_rejected_before_client_execution(self):
        env = self.env.copy()
        env.update({
            "APPARATUS_PILOT_CONTEXTS": "approved-context",
            "APPARATUS_PILOT_TARGETS": "approved-context|exp-s1-gitops|fixture-app",
        })
        result = subprocess.run(
            [sys.executable, str(ROOT / "experiments/scripts/apparatus.py"), "--live", "--phase", "pilot",
             "--subject", "s1", "--env", "gitops", "--scenario", "C", "--namespace", "exp-s1-gitops",
             "--context", "other-context", "--app", "fixture-app"],
            env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("pilot_context_not_allowlisted", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_mismatched_gitops_target_is_rejected_before_client_execution(self):
        env = self.env.copy()
        env.update({
            "APPARATUS_PILOT_CONTEXTS": "approved-context",
            "APPARATUS_PILOT_TARGETS": "approved-context|exp-s2-gitops|other-app",
        })
        result = subprocess.run(
            [sys.executable, str(ROOT / "experiments/scripts/apparatus.py"), "--live", "--phase", "pilot",
             "--subject", "s1", "--env", "gitops", "--scenario", "C", "--namespace", "exp-s1-gitops",
             "--context", "approved-context", "--app", "other-app"],
            env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("pilot_target_not_allowlisted", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_scenario_f_is_rejected_before_any_boundary_command(self):
        env = self.env.copy()
        env["APPARATUS_PILOT_CONTEXTS"] = "approved-context"
        result = subprocess.run(
            [sys.executable, str(ROOT / "experiments/scripts/apparatus.py"), "--live", "--phase", "pilot",
             "--subject", "s1", "--env", "manual", "--scenario", "F", "--namespace", "exp-s1-manual",
             "--context", "approved-context"],
            env=env, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("scenario_f_requires_separate_boundary_approval", result.stderr)
        self.assertFalse(self.calls.exists())

    def test_gitops_live_is_blocked_without_an_explicit_controller_mapping(self):
        env = self.env.copy()
        env.update({"APPARATUS_PILOT_CONTEXTS": "fixture-context",
                    "APPARATUS_PILOT_TARGETS": "fixture-context|exp-s1-gitops|fixture-app"})
        result = subprocess.run(
            [sys.executable, str(ROOT / "experiments/scripts/apparatus.py"), "--live", "--phase", "pilot",
             "--env", "gitops", "--scenario", "C", "--context", "fixture-context", "--app", "fixture-app"],
            env=env, text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gitops_connection_not_allowlisted", result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
