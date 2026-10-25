"""Offline instrument regressions; all timestamps and workload values are synthetic."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "tests/fixtures/complete.json").read_text())


def hpa_fixture():
    evidence = fixture()
    evidence["scenario"] = "A"
    evidence["contract"]["hpa_targets"] = ["app/Deployment/web"]
    evidence["injection"]["changed_fields"][0]["path"] = "/spec/replicas"
    for event in evidence["events"]:
        event.update(controller="hpa", fields=["/spec/replicas"])
    for sample in evidence["samples"]:
        sample["resources"] = copy.deepcopy(evidence["contract"]["resources"])
        sample["hpa_states"] = [{"target": "app/Deployment/web", "desired": 3,
                                 "replicas": 3, "ready": 3, "generation": 1,
                                 "observed_generation": 1, "active": True, "able_to_scale": True}]
    evidence["samples"][0]["hpa_states"][0]["replicas"] = 5
    return evidence


class InstrumentsTest(unittest.TestCase):
    def run_tool(self, tool, evidence):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence))
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / tool), "--evidence", str(path)],
                capture_output=True, text=True, timeout=5,
            )
            return result

    def test_baseline_accepts_complete_offline_evidence(self):
        result = self.run_tool("baseline-check.sh", fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "baseline_verified_offline")

    def test_baseline_fails_closed_for_missing_or_invalid_evidence(self):
        mutations = [
            lambda e: e["baseline"].pop("nodes"),
            lambda e: e["baseline"].update(nodes=[]),
            lambda e: e["baseline"]["nodes"][0].pop("memory_percent"),
            lambda e: e["baseline"]["nodes"][0].update(memory_percent=70),
            lambda e: e["baseline"]["nodes"][0].update(cpu_percent=70),
            lambda e: e["baseline"]["nodes"][0].update(memory_percent=-1),
            lambda e: e["baseline"]["nodes"][0].update(memory_percent="NaN"),
            lambda e: e["baseline"].update(pods=[]),
            lambda e: e["baseline"]["pods"][0].update(ready=False),
            lambda e: e["baseline"]["resources"].pop(),
            lambda e: e["contract"].update(resources=[]),
            lambda e: e["baseline"]["checks"].update(audit=False),
            lambda e: e["baseline"]["checks"].pop("application_reset"),
            lambda e: e["baseline"].update(source_revision="wrong"),
            lambda e: e["baseline"].update(argo={"sync": "Unknown", "health": "Healthy"}),
            lambda e: e["baseline"]["hpa_states"][0].update(active=False),
        ]
        for mutate in mutations:
            evidence = fixture()
            mutate(evidence)
            with self.subTest(evidence=evidence):
                result = self.run_tool("baseline-check.sh", evidence)
                self.assertNotEqual(result.returncode, 0)

    def test_fixed_scheduler_replicas_can_be_scored_but_hpa_replicas_cannot(self):
        evidence = fixture()
        scheduler = {"id": "app/Deployment/scheduler", "fields": {"/spec/replicas": 1}}
        evidence["contract"]["resources"].append(scheduler)
        evidence["baseline"]["resources"].append(scheduler)
        result = self.run_tool("baseline-check.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        evidence["contract"]["resources"][0]["fields"]["/spec/replicas"] = 3
        result = self.run_tool("baseline-check.sh", evidence)
        self.assertNotEqual(result.returncode, 0)

    def test_same_field_score_in_both_arms_despite_healthy_synced_status(self):
        for arm in ("manual", "gitops"):
            evidence = fixture()
            evidence["env"] = arm
            for event in evidence["events"]:
                event["controller"] = "imperative" if arm == "manual" else "argocd"
            evidence["samples"][0]["resources"][0]["fields"]["/image"] = "wrong"
            result = self.run_tool("metrics-collect.sh", evidence)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["r1_first"], 50)

    def test_observed_events_are_not_root_cause_or_rollout_timestamps(self):
        result = self.run_tool("metrics-collect.sh", fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row["detection_seconds"], 2)
        self.assertEqual(row["evidence_seconds"], 3)
        self.assertEqual(row["recovery_seconds"], 4)
        self.assertNotIn("trci", row)

    def test_absent_detection_is_censored_not_zero_even_if_recovered(self):
        evidence = fixture()
        evidence["events"] = []
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertIsNone(row["detection_seconds"])
        self.assertEqual(row["detection_status"], "right_censored")
        self.assertEqual(row["censor_seconds"], 10)

    def test_hpa_control_does_not_report_argo_detection_or_efficacy(self):
        evidence = hpa_fixture()
        for sample in evidence["samples"][1:]:
            sample["hpa_restored"] = True
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row["analysis_group"], "hpa_control")
        self.assertFalse(row["efficacy_eligible"])
        self.assertEqual(row["detection_controller"], "hpa")
        self.assertEqual(row["recovery_seconds"], 4)

    def test_hpa_cannot_recover_from_static_equality_without_controller_evidence(self):
        evidence = hpa_fixture()
        evidence["events"] = []
        for sample in evidence["samples"]:
            sample["hpa_states"][0]["replicas"] = 5
            sample["hpa_restored"] = True
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)["recovery_seconds"])

    def test_hpa_missing_or_inactive_controller_evidence_fails_closed(self):
        evidence = hpa_fixture()
        evidence["samples"][1].pop("hpa_states")
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertNotEqual(result.returncode, 0)

    def test_snapshot_missing_object_scores_zero_but_missing_fields_is_invalid(self):
        evidence = fixture()
        evidence["samples"][0]["resources"] = []
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["r1_first"], 0)

    def test_injection_acceptance_requires_changed_field_evidence(self):
        evidence = fixture()
        evidence["injection"].pop("changed_fields", None)
        result = self.run_tool("drift-inject.sh", evidence)
        self.assertNotEqual(result.returncode, 0)

    def test_wrong_run_and_short_observation_coverage_are_invalid(self):
        mutations = [
            lambda e: e["events"][0].update(run_id="previous-run"),
            lambda e: e["events"][0].update(controller="rollout"),
            lambda e: e["samples"].pop(),
            lambda e: e["baseline"].update(run_id="previous-run"),
            lambda e: e["reset"].update(at=99),
        ]
        for mutate in mutations:
            evidence = fixture()
            mutate(evidence)
            tool = "recovery-runbook.sh" if evidence["reset"].get("at") == 99 else "metrics-collect.sh"
            result = self.run_tool(tool, evidence)
            self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_secret_values_are_refused_without_leaking_input(self):
        evidence = fixture()
        evidence["contract"]["resources"][0] = {
            "id": "app/Secret/synthetic", "fields": {"/data/password": "DO-NOT-LEAK"}}
        result = self.run_tool("baseline-check.sh", evidence)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("DO-NOT-LEAK", result.stderr + result.stdout)

    def test_timeout_keeps_recovery_missing(self):
        evidence = fixture()
        for sample in evidence["samples"]:
            sample["resources"][0]["fields"]["/image"] = "wrong"
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertIsNone(row["recovery_seconds"])
        self.assertEqual(row["recovery_status"], "right_censored")

    def test_invalid_injection_or_instrumentation_is_not_a_timeout(self):
        mutations = [
            lambda e: e["injection"].update(accepted=False),
            lambda e: e["injection"].update(verified=False),
            lambda e: e["injection"].update(count=2),
            lambda e: e["samples"][0].update(error="API unavailable"),
            lambda e: e["samples"][0]["resources"][0]["fields"].pop("/image"),
            lambda e: e["events"][1].update(fields=[]),
            lambda e: e["events"][1].update(at=99),
            lambda e: e["samples"][1].update(at=99),
            lambda e: e.update(collector_started=101),
            lambda e: e["samples"][0].update(source_revision="wrong"),
            lambda e: e.pop("stop_reason"),
            lambda e: e.update(stop_reason="early"),
            lambda e: e.update(observation_end=109),
        ]
        for mutate in mutations:
            evidence = fixture()
            mutate(evidence)
            result = self.run_tool("metrics-collect.sh", evidence)
            self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_sample_run_identity_must_match_evidence_run(self):
        for mutate in (
            lambda e: e["samples"][0].pop("run_id", None),
            lambda e: e["samples"][0].update(run_id="different-run"),
        ):
            evidence = fixture()
            mutate(evidence)
            result = self.run_tool("metrics-collect.sh", evidence)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stderr)
            self.assertEqual(payload["status"], "invalid_evidence")
            self.assertIn("sample", payload["reason"].lower())

    def test_matching_sample_run_identity_is_accepted(self):
        evidence = fixture()
        for sample in evidence["samples"]:
            sample["run_id"] = evidence["run_id"]
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_measured_correction_must_finish_within_observation_window(self):
        evidence = fixture()
        evidence["recovery"]["commands"][0].update(started=150, finished=151)
        for tool in ("metrics-collect.sh", "recovery-runbook.sh"):
            result = self.run_tool(tool, evidence)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            payload = json.loads(result.stderr)
            self.assertEqual(payload["status"], "recovery_failed")
            self.assertIn("observation window", payload["reason"])

    def test_correction_at_observation_window_boundary_is_accepted(self):
        evidence = fixture()
        evidence["recovery"]["commands"][0].update(started=103, finished=110)
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["recovery_seconds"], 4)

    def test_correction_before_injection_start_is_invalid(self):
        evidence = fixture()
        evidence["recovery"]["commands"][0].update(started=99, finished=100)
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertNotEqual(result.returncode, 0)

    def test_recovery_propagates_failed_commands_and_incomplete_reset(self):
        mutations = [
            lambda e: e["recovery"]["commands"][0].update(returncode=1),
            lambda e: e["recovery"].update(commands=[]),
            lambda e: e["reset"]["checks"].update(queue=False),
            lambda e: e["reset"]["checks"].pop("runtime_adoption"),
            lambda e: e["reset"].update(extra_resources=["quarantine/Deployment/extra"]),
            lambda e: e["reset"]["resources"][0]["fields"].update({"/image": "wrong"}),
            lambda e: e["reset"]["pods"][0].update(ready=False),
            lambda e: e["reset"]["resources"].append({"id": "app/Deployment/untracked", "fields": {"/image": "extra"}}),
        ]
        for mutate in mutations:
            evidence = fixture()
            mutate(evidence)
            result = self.run_tool("recovery-runbook.sh", evidence)
            self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_complete_recovery_reset_is_verified_offline_only(self):
        result = self.run_tool("recovery-runbook.sh", fixture())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "reset_verified_offline")

    def test_foreign_namespace_case_needs_sanitized_request_and_is_not_efficacy(self):
        evidence = fixture()
        evidence["scenario"] = "F"
        evidence["contract"]["quarantine_namespace"] = "exp-fixture-wrong"
        evidence["contract"]["quarantine_resources"] = ["exp-fixture-wrong/Deployment/web"]
        evidence["injection"]["changed_fields"] = [{
            "resource": "exp-fixture-wrong/Deployment/web", "path": "/metadata/namespace",
            "effect": "created", "matches_desired": False}]
        evidence["injection"]["request_metadata"] = {"name": "web", "namespace": "exp-fixture-wrong"}
        evidence["events"] = []
        evidence["stop_reason"] = "recovery"
        for position, sample in enumerate(evidence["samples"]):
            sample["extra_resources"] = (["exp-fixture-wrong/Deployment/web"]
                                         if position == 0 else [])
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row["analysis_group"], "visibility_boundary")
        self.assertFalse(row["efficacy_eligible"])
        self.assertEqual(row["recovery_seconds"], 4)
        evidence["injection"]["request_metadata"]["uid"] = "server-generated"
        result = self.run_tool("drift-inject.sh", evidence)
        self.assertNotEqual(result.returncode, 0)

    def test_deletion_uses_existence_evidence_not_a_fake_field_value(self):
        evidence = fixture()
        evidence["scenario"] = "D"
        evidence["injection"]["changed_fields"] = [{
            "resource": "app/Deployment/web", "path": "/metadata/name",
            "effect": "deleted", "matches_desired": False}]
        evidence["samples"][0]["resources"] = [
            {"id": "app/Service/web", "fields": {"/port": 80}}]
        evidence["stop_reason"] = "recovery"
        for sample in evidence["samples"][1:]:
            sample["resources"] = [
                {"id": "app/Deployment/web", "fields": {"/image": "fixture@sha256:abc",
                                                         "/limits/memory": "1Gi"}},
                {"id": "app/Service/web", "fields": {"/port": 80}}]
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["r1_first"], 50)

    def test_early_recovery_stop_is_not_labeled_right_censored(self):
        evidence = fixture()
        evidence["samples"] = evidence["samples"][:3]
        evidence["observation_end"] = 105
        evidence["stop_reason"] = "recovery"
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row["recovery_seconds"], 4)
        self.assertEqual(row["detection_seconds"], 2)

    def test_missing_detection_before_early_recovery_is_unobserved_not_censored(self):
        evidence = fixture()
        evidence["events"] = []
        evidence["samples"] = evidence["samples"][:3]
        evidence["observation_end"] = 105
        evidence["stop_reason"] = "recovery"
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertIsNone(row["detection_seconds"])
        self.assertEqual(row["detection_status"], "unobserved_before_stop")
        self.assertEqual(row["recovery_seconds"], 4)

    def test_failed_injection_and_correction_have_distinct_failure_status(self):
        evidence = fixture()
        evidence["injection"]["accepted"] = False
        result = self.run_tool("drift-inject.sh", evidence)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["status"], "injection_failed")
        evidence = fixture()
        evidence["recovery"]["commands"][0]["returncode"] = 1
        result = self.run_tool("recovery-runbook.sh", evidence)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["status"], "recovery_failed")
        result = self.run_tool("metrics-collect.sh", evidence)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stderr)["status"], "recovery_failed")

    def test_all_entrypoints_refuse_live_without_invoking_external_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "external-called"
            for name in ("kubectl", "argocd", "shuf"):
                fake = Path(directory) / name
                fake.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n')
                fake.chmod(0o755)
            env = {**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]}
            for tool in ("baseline-check.sh", "metrics-collect.sh", "recovery-runbook.sh", "drift-inject.sh"):
                with self.subTest(tool=tool):
                    result = subprocess.run(["bash", str(ROOT / "scripts" / tool), "--live"],
                                            capture_output=True, text=True, timeout=5, env=env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("disabled", result.stderr)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
