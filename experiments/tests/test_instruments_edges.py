"""Import-level coverage for the offline evidence evaluator; all data is synthetic."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import instruments  # noqa: E402
from test_instruments import fixture  # noqa: E402


class InstrumentsUnitTests(unittest.TestCase):
    def assertError(self, call, message):
        with self.assertRaisesRegex(instruments.EvidenceError, message):
            call()

    def test_require_number_and_indexed(self):
        instruments.require(True, "ok")
        self.assertError(lambda: instruments.require(False, "bad"), "bad")
        self.assertEqual(instruments.number(0, "n"), 0)
        self.assertEqual(instruments.number(1.5, "n"), 1.5)
        for value in (True, -1, float("nan"), "1"):
            with self.subTest(value=value):
                self.assertError(
                    lambda value=value: instruments.number(value, "n"),
                    "finite nonnegative",
                )
        self.assertEqual(instruments.indexed([{"id": "a"}], "id", "x"), {"a": {"id": "a"}})
        for items in ([], "bad"):
            self.assertError(
                lambda items=items: instruments.indexed(items, "id", "x"),
                "nonempty inventory",
            )
        self.assertError(lambda: instruments.indexed([{"id": ""}], "id", "x"), "missing identity")
        self.assertError(
            lambda: instruments.indexed([{"id": "a"}, {"id": "a"}], "id", "x"),
            "duplicate identity",
        )

    def test_contract_validates_identity_fields_and_inventory(self):
        instruments.contract(fixture())
        mutations = []
        bad = fixture()
        bad["contract"]["source_revision"] = "short"
        mutations.append((bad, "source revision"))
        bad = fixture()
        bad["contract"]["render_sha256"] = "short"
        mutations.append((bad, "render digest"))
        bad = fixture()
        bad["contract"]["resources"] = []
        mutations.append((bad, "nonempty inventory"))
        for change, message in (
            (lambda value: value.update(hpa_targets=[]), "HPA target inventory"),
            (lambda value: value.update(hpa_targets=[1]), "HPA target inventory"),
            (
                lambda value: value.update(
                    hpa_targets=["app/Deployment/web", "app/Deployment/web"]
                ),
                "HPA target inventory",
            ),
            (lambda value: value.update(hpa_targets=["missing"]), "HPA target inventory"),
        ):
            bad = fixture()
            change(bad["contract"])
            mutations.append((bad, message))
        for change, message in (
            (lambda resource: resource.pop("fields"), "explicit field contract"),
            (lambda resource: resource.update(fields={}), "explicit field contract"),
            (lambda resource: resource.update(fields={"bad": 1}), "identities must be paths"),
            (
                lambda resource: resource["fields"].update({"/spec/replicas": 2}),
                "HPA-owned replicas",
            ),
        ):
            bad = fixture()
            change(bad["contract"]["resources"][0])
            mutations.append((bad, message))
        for change, message in (
            (lambda value: value.update(nodes=[]), "expected nodes inventory"),
            (lambda value: value.update(pods="bad"), "expected pods inventory"),
        ):
            bad = fixture()
            change(bad["contract"])
            mutations.append((bad, message))
        secret = fixture()
        secret["contract"]["resources"].append({"id": "app/Secret/s", "fields": {"/data": "plain"}})
        mutations.append((secret, "Secret contract"))
        for bad, message in mutations:
            with self.subTest(message=message):
                self.assertError(lambda bad=bad: instruments.contract(bad), message)

    def test_score_reports_mismatch_and_inventory_failures(self):
        evidence = fixture()
        spec = instruments.contract(evidence)
        self.assertEqual(instruments.score(spec, evidence["baseline"]), 100.0)
        bad = copy.deepcopy(evidence["baseline"])
        bad["error"] = "boom"
        self.assertError(lambda: instruments.score(spec, bad), "instrumentation failure")
        bad = copy.deepcopy(evidence["baseline"])
        bad["source_revision"] = "wrong"
        self.assertError(lambda: instruments.score(spec, bad), "snapshot source_revision")
        bad = copy.deepcopy(evidence["baseline"])
        bad["resources"] = "bad"
        self.assertError(lambda: instruments.score(spec, bad), "resource read evidence")
        self.assertEqual(instruments.score(spec, dict(evidence["baseline"], resources=[])), 0.0)
        bad = copy.deepcopy(evidence["baseline"])
        bad["resources"][0]["fields"] = "bad"
        self.assertError(lambda: instruments.score(spec, bad), "field read evidence")
        bad = copy.deepcopy(evidence["baseline"])
        bad["resources"][0]["fields"].pop("/image")
        self.assertError(lambda: instruments.score(spec, bad), "missing selected-field")
        secret_spec = instruments.contract(
            dict(
                evidence,
                contract=dict(
                    evidence["contract"],
                    hpa_targets=["app/Deployment/web"],
                    resources=evidence["contract"]["resources"]
                    + [{"id": "app/Secret/s", "fields": {"/data": True}}],
                ),
            )
        )
        secret_snapshot = {
            "source_revision": evidence["contract"]["source_revision"],
            "render_sha256": evidence["contract"]["render_sha256"],
            "resources": [
                dict(evidence["baseline"]["resources"][0]),
                {"id": "app/Secret/s", "fields": {"/data": "plain"}},
            ],
        }
        self.assertError(
            lambda: instruments.score(secret_spec, secret_snapshot), "equality booleans"
        )
        mismatched = copy.deepcopy(evidence["baseline"])
        mismatched["resources"][0]["fields"]["/image"] = "other"
        self.assertLess(instruments.score(spec, mismatched), 100.0)

    def test_baseline_rejects_each_readiness_gap(self):
        evidence = fixture()
        instruments.baseline(evidence, evidence["baseline"])
        mutations = []
        for change, message in (
            (lambda value: value.update(run_id="other"), "another run"),
            (lambda value: value.update(at="bad"), "baseline/reset time"),
            (
                lambda value: value["resources"][0]["fields"].update({"/image": "wrong"}),
                "baseline field",
            ),
            (
                lambda value: value["resources"].append({"id": "extra", "fields": {}}),
                "extra resource",
            ),
            (lambda value: value["hpa_states"][0].update(desired=4), "HPA baseline"),
            (lambda value: value.update(extra_resources=["x"]), "quarantine resources"),
            (lambda value: value.update(memory_metric="host"), "memory metric"),
            (lambda value: value["nodes"][0].update(cpu_percent=70), "threshold >=70"),
            (lambda value: value["pods"][0].update(ready=False), "Running and Ready"),
            (lambda value: value["checks"].update(audit=False), "prerequisite: audit"),
            (lambda value: value.update(argo={"sync": "OutOfSync"}), "Synced/Healthy"),
        ):
            bad = copy.deepcopy(evidence["baseline"])
            change(bad)
            mutations.append((bad, message))
        bad = copy.deepcopy(evidence["baseline"])
        bad["nodes"] = []
        mutations.append((bad, "nodes: nonempty inventory"))
        bad = copy.deepcopy(evidence["baseline"])
        bad["pods"] = []
        mutations.append((bad, "pods: nonempty inventory"))
        for bad, message in mutations:
            with self.subTest(message=message):
                self.assertError(lambda bad=bad: instruments.baseline(evidence, bad), message)
        manual = copy.deepcopy(evidence)
        manual["env"] = "manual"
        manual["baseline"].pop("argo", None)
        instruments.baseline(manual, manual["baseline"])

    def test_injection_covers_scenarios_and_foreign_quarantine(self):
        evidence = fixture()
        self.assertEqual(instruments.injection(evidence), (100, 100.5))
        mutations = []

        def add(bad, message):
            mutations.append((bad, message))

        for change, message in (
            (lambda value: value["injection"].update(count=0), "one injection"),
            (lambda value: value["injection"].update(accepted=False), "acceptance unverified"),
            (lambda value: value["injection"].update(verified=False), "acceptance unverified"),
            (lambda value: value.update(collector_started=101), "collector must start"),
            (lambda value: value["baseline"].update(at=101), "baseline must precede"),
            (lambda value: value["injection"].update(changed_fields=[]), "changed-field"),
            (
                lambda value: value["injection"]["changed_fields"][0].update(matches_desired=True),
                "differ from baseline",
            ),
            (
                lambda value: value["injection"]["changed_fields"][0].update(effect="unsupported"),
                "unsupported injection effect",
            ),
        ):
            bad = copy.deepcopy(evidence)
            change(bad)
            add(bad, message)
        foreign = copy.deepcopy(evidence)
        foreign["scenario"] = "F"
        foreign["contract"].update(
            quarantine_namespace="exp-q",
            quarantine_resources=["exp-q/Namespace/q"],
        )
        foreign["injection"]["changed_fields"] = [
            {
                "resource": "exp-q/Namespace/q",
                "path": "/metadata/namespace",
                "effect": "created",
                "matches_desired": False,
            }
        ]
        foreign["injection"]["request_metadata"] = {"name": "q", "namespace": "exp-q"}
        instruments.injection(foreign)
        for change, message in (
            (
                lambda value: value["contract"].update(quarantine_resources="bad"),
                "separate quarantine",
            ),
            (
                lambda value: value["contract"].update(quarantine_resources=[]),
                "separate quarantine",
            ),
            (
                lambda value: value["contract"].update(quarantine_resources=["bad"]),
                "separate quarantine",
            ),
            (
                lambda value: value["contract"].update(quarantine_resources=["app/Deployment/web"]),
                "separate quarantine",
            ),
            (
                lambda value: value["injection"].update(request_metadata=[]),
                "omit server-generated",
            ),
            (
                lambda value: value["injection"]["request_metadata"].update(extra="x"),
                "omit server-generated",
            ),
            (
                lambda value: value["injection"]["request_metadata"].update(namespace="other"),
                "omit server-generated",
            ),
            (
                lambda value: value["injection"]["request_metadata"].update(name=""),
                "omit server-generated",
            ),
            (
                lambda value: value["injection"]["changed_fields"][0].update(
                    effect="value_changed"
                ),
                "verified creation",
            ),
        ):
            bad = copy.deepcopy(foreign)
            change(bad)
            add(bad, message)
        deleted = copy.deepcopy(evidence)
        deleted["scenario"] = "D"
        deleted["injection"]["changed_fields"] = [
            {
                "resource": "app/Deployment/web",
                "path": "/metadata/name",
                "effect": "deleted",
                "matches_desired": False,
            }
        ]
        instruments.injection(deleted)
        bad = copy.deepcopy(deleted)
        bad["injection"]["changed_fields"][0]["path"] = "/image"
        add(bad, "verified deletion")
        hpa = copy.deepcopy(evidence)
        hpa["scenario"] = "A"
        hpa["injection"]["changed_fields"] = [
            {
                "resource": "app/Deployment/web",
                "path": "/spec/replicas",
                "effect": "value_changed",
                "matches_desired": False,
            }
        ]
        instruments.injection(hpa)
        bad = copy.deepcopy(hpa)
        bad["injection"]["changed_fields"][0]["path"] = "/image"
        add(bad, "not verified against baseline")
        for bad, message in mutations:
            with self.subTest(message=message):
                self.assertError(lambda bad=bad: instruments.injection(bad), message)

    def test_hpa_and_correction_helpers(self):
        evidence = fixture()
        spec = instruments.contract(evidence)
        self.assertTrue(instruments.hpa_restored(spec, evidence["baseline"]))
        bad = copy.deepcopy(evidence["baseline"])
        bad["hpa_states"] = []
        self.assertError(
            lambda: instruments.hpa_restored(spec, bad), "HPA observations: nonempty inventory"
        )
        bad = copy.deepcopy(evidence["baseline"])
        bad["hpa_states"][0].update(desired=-1)
        self.assertError(lambda: instruments.hpa_restored(spec, bad), "invalid HPA state")
        bad = copy.deepcopy(evidence["baseline"])
        bad["hpa_states"][0].update(active=False)
        self.assertError(lambda: instruments.hpa_restored(spec, bad), "not active")
        bad = copy.deepcopy(evidence["baseline"])
        bad["hpa_states"][0].update(desired=5)
        self.assertFalse(instruments.hpa_restored(spec, bad))
        self.assertEqual(instruments.correction_results(evidence, 100, 110), (104, 1))
        for change, message in (
            (lambda value: value["recovery"].update(commands=[]), "command results required"),
            (
                lambda value: value["recovery"]["commands"][0].update(returncode="1"),
                "command exit code",
            ),
            (
                lambda value: value["recovery"]["commands"][0].update(returncode=1),
                "correction failed",
            ),
            (
                lambda value: value["recovery"]["commands"][0].update(started=99),
                "invalid command timing",
            ),
            (
                lambda value: value["recovery"]["commands"][0].update(finished=111),
                "within the observation window",
            ),
        ):
            bad = copy.deepcopy(evidence)
            change(bad)
            with self.subTest(message=message):
                self.assertRaises(
                    (instruments.EvidenceError, instruments.RecoveryError),
                    lambda bad=bad: instruments.correction_results(bad, 100, 110),
                )
        instruments.recovery(evidence)
        bad = copy.deepcopy(evidence)
        bad["observation_end"] = 100
        self.assertError(lambda: instruments.recovery(bad), "observation end")
        bad = copy.deepcopy(evidence)
        bad["reset"]["at"] = 100
        self.assertError(lambda: instruments.recovery(bad), "predates correction")

    def test_metrics_covers_timeout_and_recovery_outcomes(self):
        evidence = fixture()
        result = instruments.metrics(evidence)
        self.assertEqual(result["stop_reason"], "timeout")
        self.assertEqual(result["recovery_status"], "observed")
        no_recovery = copy.deepcopy(evidence)
        no_recovery["samples"] = [dict(sample, resources=[]) for sample in evidence["samples"]]
        self.assertEqual(instruments.metrics(no_recovery)["recovery_status"], "right_censored")
        mutations = []
        for change, message in (
            (lambda value: value.update(observation_end=100), "observation end"),
            (lambda value: value.update(observation_end=121), "cannot exceed"),
            (lambda value: value.update(stop_reason="other"), "explicit stop reason"),
            (lambda value: value.update(observation_end=109), "frozen observation limit"),
            (lambda value: value.update(max_sample_gap_seconds=0), "must be positive"),
        ):
            bad = copy.deepcopy(evidence)
            change(bad)
            mutations.append((bad, message))
        for change, message in (
            (lambda value: value.update(events={}), "event stream"),
            (lambda value: value["events"][0].update(at=99), "unordered/out-of-window event"),
            (lambda value: value["events"][0].update(run_id="other"), "stale event"),
            (lambda value: value["events"][0].update(type="other"), "unknown event type"),
            (lambda value: value["events"][0].update(controller="hpa"), "wrong controller"),
            (lambda value: value["events"][0].update(fields=[]), "measured resource/fields"),
            (lambda value: value["events"][1].pop("artifact"), "artifact reference"),
            (lambda value: value["events"].pop(0), "evidence without preceding detection"),
            (lambda value: value.update(samples={}), "observation snapshots"),
            (lambda value: value.update(samples=[]), "observation snapshots"),
            (lambda value: value["samples"][0].update(at=100), "unordered/out-of-window sample"),
            (lambda value: value["samples"][1].update(at=109), "sample gap exceeds"),
            (lambda value: value["samples"][0].pop("run_id"), "sample run identity"),
            (lambda value: value["samples"][0].update(run_id="other"), "stale sample"),
            (lambda value: value["samples"][-1].update(at=109), "does not cover observation end"),
        ):
            bad = copy.deepcopy(evidence)
            change(bad)
            mutations.append((bad, message))
        for bad, message in mutations:
            with self.subTest(message=message):
                self.assertError(lambda bad=bad: instruments.metrics(bad), message)
        no_recovery_commands = copy.deepcopy(evidence)
        no_recovery_commands.pop("recovery")
        self.assertEqual(instruments.metrics(no_recovery_commands)["stop_reason"], "timeout")
        recovery_stop = copy.deepcopy(evidence)
        recovery_stop["stop_reason"] = "recovery"
        recovery_stop["observation_end"] = 109
        recovery_stop["samples"] = [
            dict(copy.deepcopy(evidence["baseline"]), run_id=evidence["run_id"], at=at)
            for at in (101, 105, 109)
        ]
        result = instruments.metrics(recovery_stop)
        self.assertEqual(result["recovery_status"], "observed")
        missing_recovery = copy.deepcopy(recovery_stop)
        missing_recovery["samples"] = [
            dict(
                copy.deepcopy(evidence["baseline"]),
                run_id=evidence["run_id"],
                at=at,
                resources=[],
            )
            for at in (101, 105, 109)
        ]
        self.assertError(
            lambda: instruments.metrics(missing_recovery), "without confirmed restoration"
        )
        early_stop = copy.deepcopy(recovery_stop)
        early_stop["events"] = []
        result = instruments.metrics(early_stop)
        self.assertEqual(result["detection_status"], "unobserved_before_stop")
        self.assertEqual(result["evidence_status"], "unobserved_before_stop")
        deleted = copy.deepcopy(evidence)
        deleted["scenario"] = "D"
        deleted["injection"]["changed_fields"][0].update(effect="deleted", path="/metadata/name")
        bad = copy.deepcopy(deleted)
        bad["samples"][0]["resources"] = copy.deepcopy(evidence["baseline"]["resources"])
        self.assertError(lambda bad=bad: instruments.metrics(bad), "deletion not visible")

    def test_metrics_hpa_and_visibility_scenarios(self):
        evidence = fixture()
        hpa = copy.deepcopy(evidence)
        hpa["scenario"] = "A"
        hpa["injection"]["changed_fields"] = [
            {
                "resource": "app/Deployment/web",
                "path": "/spec/replicas",
                "effect": "value_changed",
                "matches_desired": False,
            }
        ]
        hpa["events"] = [
            {
                "run_id": evidence["run_id"],
                "type": "detection",
                "at": 102,
                "controller": "hpa",
                "resource": "app/Deployment/web",
                "fields": ["/spec/replicas"],
            },
            {
                "run_id": evidence["run_id"],
                "type": "evidence",
                "at": 103,
                "controller": "hpa",
                "resource": "app/Deployment/web",
                "fields": ["/spec/replicas"],
                "artifact": "a.json",
            },
        ]
        hpa["samples"] = [
            dict(copy.deepcopy(evidence["baseline"]), run_id=evidence["run_id"], at=at)
            for at in (101, 105, 109, 110)
        ]
        result = instruments.metrics(hpa)
        self.assertEqual(result["detection_controller"], "hpa")
        bad = copy.deepcopy(hpa)
        bad["events"][0]["resource"] = "app/Service/web"
        self.assertError(lambda bad=bad: instruments.metrics(bad), "unmeasured HPA target")
        bad = copy.deepcopy(hpa)
        bad["samples"][0]["hpa_states"][0]["desired"] = 5
        self.assertIsNotNone(instruments.metrics(bad))
        foreign = copy.deepcopy(evidence)
        foreign["scenario"] = "F"
        foreign["contract"].update(
            quarantine_namespace="exp-q",
            quarantine_resources=["exp-q/Namespace/q"],
        )
        foreign["injection"]["changed_fields"] = [
            {
                "resource": "exp-q/Namespace/q",
                "path": "/metadata/namespace",
                "effect": "created",
                "matches_desired": False,
            }
        ]
        foreign["injection"]["request_metadata"] = {"name": "q", "namespace": "exp-q"}
        foreign["events"] = [
            {
                "run_id": evidence["run_id"],
                "type": "detection",
                "at": 102,
                "controller": "argocd",
                "resource": "exp-q/Namespace/q",
                "fields": ["/metadata/namespace"],
            }
        ]
        foreign["samples"] = [
            dict(
                copy.deepcopy(evidence["baseline"]),
                run_id=evidence["run_id"],
                at=at,
                extra_resources=["exp-q/Namespace/q"] if index == 0 else [],
            )
            for index, at in enumerate((101, 105, 109, 110))
        ]
        result = instruments.metrics(foreign)
        self.assertEqual(result["analysis_group"], "visibility_boundary")
        bad = copy.deepcopy(foreign)
        bad["events"][0]["resource"] = "app/Deployment/web"
        self.assertError(lambda bad=bad: instruments.metrics(bad), "unmeasured quarantine object")
        bad = copy.deepcopy(foreign)
        bad["samples"][0].pop("extra_resources")
        self.assertError(lambda bad=bad: instruments.metrics(bad), "F quarantine observation")
        bad = copy.deepcopy(foreign)
        bad["samples"][0]["extra_resources"] = []
        self.assertError(
            lambda bad=bad: instruments.metrics(bad), "not visible in first observation"
        )
        bad = copy.deepcopy(foreign)
        bad["samples"][1]["extra_resources"] = ["still-there"]
        self.assertIsNotNone(instruments.metrics(bad))

    def test_injection_fixture_and_main_modes(self):
        evidence = fixture()
        instruments.baseline(evidence, evidence["baseline"])
        self.assertEqual(instruments.injection(evidence)[0], 100)

    def run_main(self, argv):
        with (
            mock.patch.object(sys, "argv", ["instruments.py", *argv]),
            mock.patch("sys.stdout"),
            mock.patch("sys.stderr"),
        ):
            return instruments.main()

    def test_main_modes_and_failure_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.json"
            good.write_text(json.dumps(fixture()))
            for mode in ("baseline", "metrics", "recovery", "injection"):
                with self.subTest(mode=mode):
                    self.assertEqual(self.run_main([mode, "--evidence", str(good)]), 0)
            invalid = root / "invalid.json"
            invalid.write_text("{bad")
            self.assertEqual(self.run_main(["baseline", "--evidence", str(invalid)]), 1)
            bad_env = copy.deepcopy(fixture())
            bad_env["env"] = "other"
            invalid.write_text(json.dumps(bad_env))
            self.assertEqual(self.run_main(["baseline", "--evidence", str(invalid)]), 1)
            injection_failure = copy.deepcopy(fixture())
            injection_failure["injection"]["accepted"] = False
            invalid.write_text(json.dumps(injection_failure))
            self.assertEqual(self.run_main(["injection", "--evidence", str(invalid)]), 1)
            recovery_failure = copy.deepcopy(fixture())
            recovery_failure["recovery"]["commands"][0]["returncode"] = 1
            invalid.write_text(json.dumps(recovery_failure))
            self.assertEqual(self.run_main(["recovery", "--evidence", str(invalid)]), 1)
            with (
                self.assertRaises(SystemExit) as caught,
                mock.patch.object(sys, "argv", ["instruments.py", "baseline", "--live"]),
            ):
                instruments.main()
            self.assertEqual(caught.exception.code, 3)
            with (
                self.assertRaises(SystemExit) as caught,
                mock.patch.object(sys, "argv", ["instruments.py", "baseline"]),
            ):
                instruments.main()
            self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
