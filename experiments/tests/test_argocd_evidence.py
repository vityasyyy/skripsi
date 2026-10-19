"""Controller evidence tests; all external transport is replaced with fixtures."""

import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.scripts import apparatus
from experiments.tests.test_apparatus import FakeAdapter


SERVER = "https://kubernetes.default.svc"
NAMESPACE = "exp-s1-gitops"


class ArgoCDEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.spec = apparatus.ResourceSpec("Deployment", "exp-web", ((("spec", "replicas"), 3),))
        self.expected = (self.spec,)
        self.resource = {"apiVersion": "apps/v1", "kind": "Deployment",
                         "metadata": {"name": "exp-web", "namespace": NAMESPACE},
                         "spec": {"replicas": 5}}
        self.app = {"spec": {"destination": {"namespace": NAMESPACE, "server": SERVER}},
                    "status": {"resources": [{"group": "apps", "kind": "Deployment",
                        "name": "exp-web", "namespace": NAMESPACE, "status": "OutOfSync"}]}}
        self.adapter = apparatus.SubprocessAdapter("s1", "gitops", NAMESPACE, "fixture-kube", "fixture-app")
        self.adapter.argocd_context = "fixture-argo"
        self.adapter.destination_server = SERVER

    def transport(self, client, args, input_text=None):
        self.assertEqual(client, "argocd", "controller evidence must not borrow the kubectl oracle")
        if args[:2] == ["app", "get"]:
            return json.dumps(self.app)
        self.assertEqual(args[:3], ["app", "get-resource", "fixture-app"])
        self.assertIn("--group", args)
        return json.dumps(self.resource)

    def test_field_evidence_comes_from_structured_controller_resource_data(self):
        for shape in (self.resource, [self.resource], {"kind": "List", "items": [self.resource]}):
            with self.subTest(shape=type(shape).__name__):
                def transport(client, args, input_text=None):
                    if args[:2] == ["app", "get"]:
                        return json.dumps(self.app)
                    self.assertEqual(client, "argocd")
                    return json.dumps(shape)
                with patch.object(self.adapter, "_run", side_effect=transport):
                    evidence = self.adapter.mechanism_evidence(self.expected)
                self.assertEqual(evidence, [{"resource": "Deployment/exp-web",
                    "field_paths": ["spec.replicas"], "source": "argocd-live-resource"}])
                self.assertNotIn('"replicas": 5', json.dumps(evidence))

    def test_synced_or_already_restored_resource_has_no_deviation_evidence(self):
        self.resource["spec"]["replicas"] = 3
        with patch.object(self.adapter, "_run", side_effect=self.transport):
            self.assertEqual(self.adapter.mechanism_evidence(self.expected), [])
        self.app["status"]["resources"][0]["status"] = "Synced"
        with patch.object(self.adapter, "_run", return_value=json.dumps(self.app)):
            self.assertEqual(self.adapter.mechanism_evidence(self.expected), [])

    def test_controller_missing_resource_is_identity_evidence(self):
        self.app["status"]["resources"][0]["health"] = {"status": "Missing"}
        with patch.object(self.adapter, "_run", return_value=json.dumps(self.app)):
            evidence = self.adapter.mechanism_evidence(self.expected)
        self.assertEqual(evidence, [{"resource": "Deployment/exp-web", "field_paths": ["$identity"],
                                    "source": "argocd-resource-status"}])

    def test_wrong_namespace_group_or_identity_fails_closed(self):
        for change in ({"metadata": {"name": "exp-web", "namespace": "other"}},
                       {"metadata": {"name": "other", "namespace": NAMESPACE}},
                       {"apiVersion": "other.example/v1"}, {"kind": "StatefulSet"}):
            with self.subTest(change=change):
                original = copy.deepcopy(self.resource)
                self.resource.update(change)
                with patch.object(self.adapter, "_run", side_effect=self.transport):
                    with self.assertRaises(apparatus.ApparatusError):
                        self.adapter.mechanism_evidence(self.expected)
                self.resource = original

    def test_malformed_or_empty_controller_resource_is_not_a_missing_resource(self):
        for payload in ("not-json SENTINEL_SECRET", "[]", "{}", '{"items":null}'):
            with self.subTest(payload=payload):
                def transport(client, args, input_text=None):
                    return json.dumps(self.app) if args[:2] == ["app", "get"] else payload
                with patch.object(self.adapter, "_run", side_effect=transport):
                    with self.assertRaises(apparatus.ApparatusError) as raised:
                        self.adapter.mechanism_evidence(self.expected)
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_redacted_secret_value_is_unavailable_not_a_false_mismatch(self):
        self.expected = (apparatus.ResourceSpec("Secret", "exp-secret", (
            (("type",), "Opaque"), (("data", "password"), "SENTINEL_EXPECTED_SECRET"))),)
        self.app["status"]["resources"] = [{"group": "", "kind": "Secret", "name": "exp-secret",
                                           "namespace": NAMESPACE, "status": "OutOfSync"}]
        self.resource = {"apiVersion": "v1", "kind": "Secret", "type": "Opaque",
                         "metadata": {"name": "exp-secret", "namespace": NAMESPACE},
                         "data": {"password": "********"}}
        with patch.object(self.adapter, "_run", side_effect=self.transport):
            self.assertIsNone(self.adapter.mechanism_evidence(self.expected))
        self.resource["type"] = "kubernetes.io/basic-auth"
        with patch.object(self.adapter, "_run", side_effect=self.transport):
            evidence = self.adapter.mechanism_evidence(self.expected)
        self.assertEqual(evidence[0]["field_paths"], ["type"])
        self.assertNotIn("SENTINEL_EXPECTED_SECRET", json.dumps(evidence))
        self.assertNotIn("********", json.dumps(evidence))

    def test_application_destination_and_unknown_status_are_rejected(self):
        for server, status in (("https://other.invalid", "Synced"), (SERVER, "Unknown")):
            with self.subTest(server=server, status=status):
                self.app["spec"]["destination"]["server"] = server
                self.app["status"]["resources"][0]["status"] = status
                with patch.object(self.adapter, "_run", return_value=json.dumps(self.app)):
                    with self.assertRaises(apparatus.ApparatusError):
                        self.adapter.mechanism_signal(self.expected)

    def test_controller_commands_pin_the_explicit_argocd_context(self):
        result = subprocess.CompletedProcess([], 0, json.dumps(self.app), "")
        with patch.object(apparatus.subprocess, "run", return_value=result) as transport:
            self.assertTrue(self.adapter.mechanism_signal(self.expected))
        command = transport.call_args.args[0]
        index = command.index("--argocd-context")
        self.assertEqual(command[index + 1], "fixture-argo")

    def test_unsupported_cli_is_rejected_before_baseline_and_injection(self):
        calls = []
        def old_cli(client, args, input_text=None):
            calls.append((client, args))
            return "Usage: argocd app [command]" if "--help" in args else "{}"
        with patch.object(self.adapter, "_run", side_effect=old_cli):
            record = apparatus.run_experiment(self.adapter, "s1", "gitops", "C", timeout_s=0.1)
        self.assertEqual(record["reason"], "argocd_resource_command_unavailable")
        self.assertIsNone(record["t0_mono_s"])
        self.assertTrue(all("--help" in args for _, args in calls))

    def test_server_resource_permission_is_checked_before_injection(self):
        calls = []
        def denied(client, args, input_text=None):
            calls.append((client, args))
            if "--help" in args:
                return "get-resource APPNAME --kind --group --resource-name --output"
            if args[:2] == ["app", "get"]:
                return json.dumps(self.app)
            if args[:2] == ["app", "get-resource"]:
                raise apparatus.ApparatusError("external_command_failed")
            self.fail("baseline/injection must not precede permission validation")
        with patch.object(apparatus, "expected_inventory", return_value=self.expected):
            with patch.object(self.adapter, "_run", side_effect=denied):
                record = apparatus.run_experiment(self.adapter, "s1", "gitops", "C", timeout_s=0.1)
        self.assertEqual(record["reason"], "external_command_failed")
        self.assertIsNone(record["t0_mono_s"])
        self.assertTrue(all(client == "argocd" for client, _ in calls))

    def test_unavailable_evidence_during_drift_is_not_censoring_after_heal(self):
        adapter = FakeAdapter(env="gitops")
        adapter.auto_restore_after = 3
        def evidence(expected):
            config = next(obj for obj in adapter.objects if obj["kind"] == "ConfigMap")
            return None if config["data"]["LOG_LEVEL"] == "debug" else []
        adapter.mechanism_evidence = evidence
        record = apparatus.run_experiment(adapter, "s1", "gitops", "C", timeout_s=0.04, poll_interval_s=0.001)
        self.assertEqual(record["evidence_status"], "not_evaluable")
        self.assertEqual(record["recovery_status"], "observed")

    def test_allowlisted_pilot_requires_the_full_explicit_server_mapping(self):
        args = argparse.Namespace(subject="s1", env="gitops", namespace=NAMESPACE, scenario="C", rep=1,
            phase="pilot", live=True, context="fixture-kube", app="fixture-app",
            argocd_context="fixture-argo", destination_server=SERVER, timeout_s=30.0, poll_interval_s=1.0)
        mapping = f"fixture-kube|{NAMESPACE}|fixture-app|fixture-argo|{SERVER}"
        with patch.dict(os.environ, {"APPARATUS_PILOT_CONTEXTS": "fixture-kube",
                                    "APPARATUS_PILOT_TARGETS": mapping}):
            apparatus._validate_cli(args)

    def test_detection_timestamp_does_not_include_the_evidence_query_delay(self):
        adapter = FakeAdapter(env="gitops")
        adapter.auto_restore_after = 3
        def evidence(expected):
            time.sleep(0.025)
            return [{"resource": "ConfigMap/exp-web-config", "field_paths": ["data.LOG_LEVEL"],
                     "source": "argocd-live-resource"}]
        adapter.mechanism_evidence = evidence
        record = apparatus.run_experiment(adapter, "s1", "gitops", "C", timeout_s=0.2, poll_interval_s=0.001)
        self.assertGreater(record["te_mono_s"] - record["td_mono_s"], 0.02)

    def test_slow_evidence_query_does_not_erase_an_in_window_signal(self):
        adapter = FakeAdapter(env="gitops")
        def slow_evidence(expected):
            time.sleep(0.05)
            return []
        adapter.mechanism_evidence = slow_evidence
        record = apparatus.run_experiment(adapter, "s1", "gitops", "C", timeout_s=0.02, poll_interval_s=0.001)
        self.assertEqual(record["detection_status"], "observed")
        self.assertIsNone(record["te_mono_s"])

    def test_manual_correction_does_not_wait_for_a_second_evidence_read(self):
        adapter = FakeAdapter()
        def extra_read(expected):
            self.fail("the existing mechanism signal already contains safe field evidence")
        adapter.mechanism_evidence = extra_read
        record = apparatus.run_experiment(adapter, "s1", "manual", "C", timeout_s=0.1, poll_interval_s=0.001)
        self.assertEqual(record["status"], "complete")

    def test_gitops_signal_failure_does_not_erase_oracle_restoration(self):
        adapter = FakeAdapter(env="gitops")
        adapter.auto_restore_after = 14
        first_loop_signal = threading.Event()
        failed_after_restoration = []
        oracle_times = {}
        original_signal = adapter.mechanism_signal

        def clock():
            now = time.monotonic()
            if adapter.snapshots == 14 and 14 not in oracle_times:
                oracle_times[14] = now
            return now

        def inject(scenario):
            if not first_loop_signal.wait(timeout=1):
                raise apparatus.ApparatusError("injection_failed")
            config = next(obj for obj in adapter.objects if obj["kind"] == "ConfigMap")
            config["data"]["LOG_LEVEL"] = "debug"
            return time.monotonic()

        def signal(expected):
            if adapter.snapshots == 2:
                first_loop_signal.set()
            if adapter.snapshots == 15:
                score, _ = apparatus.compare_inventory(expected, adapter.objects)
                if score == 100.0:
                    failed_after_restoration.append(adapter.snapshots)
                    raise apparatus.ApparatusError("gitops_signal_unavailable")
            return original_signal(expected)

        def evidence(expected):
            config = next(obj for obj in adapter.objects if obj["kind"] == "ConfigMap")
            if config["data"]["LOG_LEVEL"] == "debug":
                return [{"resource": "ConfigMap/exp-web-config", "field_paths": ["data.LOG_LEVEL"],
                         "source": "argocd-live-resource"}]
            return []

        adapter.inject = inject
        adapter.mechanism_signal = signal
        adapter.mechanism_evidence = evidence
        record = apparatus.run_experiment(adapter, "s1", "gitops", "C", timeout_s=1,
                                          poll_interval_s=0.001, clock=clock)

        self.assertEqual(failed_after_restoration, [15])
        self.assertEqual(record["status"], "instrumentation_failed")
        self.assertEqual(record["detection_status"], "observed")
        self.assertEqual(record["evidence_status"], "observed")
        self.assertEqual(record["recovery_status"], "observed")
        self.assertIsNotNone(record["tr_mono_s"])
        self.assertEqual(record["tr_mono_s"], oracle_times[14])
        self.assertEqual(record["r1_recovered_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
