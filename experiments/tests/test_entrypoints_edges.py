"""Import-level coverage for the offline entrypoints and sensitivity script."""

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
LIVE = ROOT / "live"
SENSITIVITY = ROOT / "sensitivity"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(LIVE))
sys.path.insert(0, str(SENSITIVITY))

import instruments  # noqa: E402
import run_one  # noqa: E402


def load_acquisition():
    spec = importlib.util.spec_from_file_location(
        "acquire_readonly", SCRIPTS / "acquire-readonly.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acquire = load_acquisition()


class EntrypointSmokeTests(unittest.TestCase):
    def test_modules_import(self):
        self.assertTrue(callable(instruments.main))
        self.assertTrue(callable(acquire.main))
        self.assertTrue(callable(run_one.main))


class PackageImportTests(unittest.TestCase):
    def test_package_imports_avoid_relative_import_warnings(self):
        root = str(ROOT.parent)
        sys.path.insert(0, root)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                from experiments.analysis import analyze_live as package_analyze_live
                from experiments.live import harness as package_harness
                from experiments.live import run_matrix as package_run_matrix
                from experiments.live import run_one as package_run_one
        finally:
            sys.path.remove(root)
        self.assertTrue(callable(package_analyze_live.main))
        self.assertTrue(callable(package_harness.main))
        self.assertTrue(callable(package_run_matrix.main))
        self.assertTrue(callable(package_run_one.main))


def bundle():
    return {
        "run_id": "fixture-run",
        "contract": {
            "source_revision": "a" * 40,
            "resources": [
                {
                    "id": "exp-a/Deployment/web",
                    "fields": {
                        "/spec/replicas": 2,
                        "/spec/template/spec/containers/0/image": "img",
                    },
                }
            ],
        },
        "nodes": {
            "items": [
                {
                    "metadata": {"name": "node"},
                    "status": {
                        "allocatable": {"cpu": "2", "memory": "2Gi"},
                        "nodeInfo": {"kubeletVersion": "v1", "osImage": "Ubuntu"},
                    },
                }
            ]
        },
        "metrics": {
            "items": [{"metadata": {"name": "node"}, "usage": {"cpu": "500m", "memory": "1Gi"}}]
        },
        "pods": {
            "items": [
                {
                    "metadata": {"name": "web"},
                    "status": {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                },
                {"metadata": {"name": "job"}, "status": {"phase": "Succeeded"}},
            ]
        },
        "resources": {
            "items": [
                {
                    "kind": "Deployment",
                    "metadata": {"namespace": "exp-a", "name": "web"},
                    "spec": {
                        "replicas": 2,
                        "template": {"spec": {"containers": [{"image": "img", "resources": {}}]}},
                    },
                }
            ]
        },
    }


class RunOneHelpTests(unittest.TestCase):
    def test_help_keeps_the_module_description_concise(self):
        with (
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            self.assertRaises(SystemExit) as caught,
        ):
            run_one.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        text = stdout.getvalue()
        self.assertIn("Dry-run by default", text)
        self.assertNotIn("Architecture", text)


class AcquireReadonlyTests(unittest.TestCase):
    def test_quantity_units_and_rejection(self):
        self.assertEqual(acquire.quantity("2"), 2)
        self.assertEqual(acquire.quantity("500m"), acquire.Decimal("0.5"))
        self.assertEqual(acquire.quantity("1Ki"), 1024)
        self.assertEqual(acquire.quantity("1Mi"), 1024**2)
        self.assertEqual(acquire.quantity("1Gi"), 1024**3)
        self.assertEqual(acquire.quantity("1Ti"), 1024**4)
        self.assertEqual(acquire.quantity("1k"), 1000)
        self.assertEqual(acquire.quantity("1M"), 1000**2)
        self.assertEqual(acquire.quantity("1G"), 1000**3)
        self.assertEqual(acquire.quantity("1T"), 1000**4)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            acquire.quantity("1x")

    def test_selected_field_accepts_only_reviewed_paths(self):
        deployment = {
            "spec": {
                "replicas": 2,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "image": "img",
                                "resources": {
                                    "requests": {"cpu": "1", "memory": "1Gi"},
                                    "limits": {"cpu": "2", "memory": "2Gi"},
                                },
                            }
                        ]
                    }
                },
            }
        }
        self.assertEqual(acquire.selected_field(deployment, "Deployment", "/spec/replicas"), 2)
        self.assertEqual(
            acquire.selected_field(
                deployment,
                "Deployment",
                "/spec/template/spec/containers/0/image",
            ),
            "img",
        )
        self.assertEqual(
            acquire.selected_field(
                deployment,
                "Deployment",
                "/spec/template/spec/containers/0/resources/requests/cpu",
            ),
            "1",
        )
        service = {
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": "web"},
                "ports": [{"port": 80, "targetPort": 8080, "protocol": "TCP"}],
            }
        }
        for path in (
            "/spec/type",
            "/spec/selector",
            "/spec/ports/0/port",
            "/spec/ports/0/targetPort",
            "/spec/ports/0/protocol",
        ):
            acquire.selected_field(service, "Service", path)
        hpa = {"spec": {"minReplicas": 1, "maxReplicas": 3}}
        self.assertEqual(
            acquire.selected_field(hpa, "HorizontalPodAutoscaler", "/spec/minReplicas"), 1
        )
        self.assertEqual(
            acquire.selected_field(hpa, "HorizontalPodAutoscaler", "/spec/maxReplicas"), 3
        )
        with self.assertRaisesRegex(ValueError, "unsupported/sensitive"):
            acquire.selected_field({}, "Deployment", "/data/password")

    def test_unique_rejects_duplicates(self):
        self.assertEqual(acquire.unique([{"id": "a"}], lambda item: item["id"]), {"a": {"id": "a"}})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            acquire.unique([{"id": "a"}, {"id": "a"}], lambda item: item["id"])

    def test_export_accepts_a_complete_bundle(self):
        exported = acquire.export(bundle(), "exp-a", "fixture-run")
        self.assertEqual(exported["status"], "read_only_export")
        self.assertFalse(exported["readiness_verified"])
        self.assertEqual(exported["absent_resources"], [])
        self.assertEqual(exported["resources"][0]["fields"]["/spec/replicas"], 2)
        self.assertTrue(exported["pods"][0]["ready"])
        self.assertFalse(exported["pods"][1]["ready"])

    def test_export_rejects_invalid_identity_and_inventory(self):
        cases = []
        bad = bundle()
        bad["contract"]["source_revision"] = "short"
        cases.append((bad, "pinned reference revision"))
        bad = bundle()
        bad["nodes"]["items"] = []
        cases.append((bad, "node metrics incomplete"))
        bad = bundle()
        bad["metrics"]["items"] = []
        cases.append((bad, "node metrics incomplete"))
        bad = bundle()
        bad["nodes"]["items"].append(dict(bad["nodes"]["items"][0]))
        cases.append((bad, "duplicate observation identity"))
        bad = bundle()
        bad["nodes"]["items"][0]["status"]["allocatable"]["cpu"] = "0"
        cases.append((bad, "allocatable must be positive"))
        bad = bundle()
        bad["contract"]["resources"] = []
        cases.append((bad, "selected resource inventory"))
        bad = bundle()
        bad["contract"]["resources"][0]["id"] = "other/Deployment/web"
        cases.append((bad, "only selected non-secret resources"))
        bad = bundle()
        bad["contract"]["resources"][0]["id"] = "exp-a/Secret/web"
        cases.append((bad, "only selected non-secret resources"))
        bad = bundle()
        bad["contract"]["resources"][0]["fields"] = {}
        cases.append((bad, "selected fields required"))
        bad = bundle()
        bad["contract"]["resources"][0]["fields"] = {"/data/password": True}
        cases.append((bad, "unsupported/sensitive"))
        with self.assertRaisesRegex(ValueError, "run identity required"):
            acquire.export(bundle(), "exp-a", "")
        for bad, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValueError, message),
            ):
                acquire.export(bad, "exp-a", "fixture-run")

    def test_export_marks_absent_resources_and_empty_pod_conditions(self):
        bad = bundle()
        bad["resources"]["items"] = []
        bad["pods"]["items"] = [{"metadata": {"name": "p"}, "status": {"phase": "Pending"}}]
        exported = acquire.export(bad, "exp-a", "fixture-run")
        self.assertEqual(exported["absent_resources"], ["exp-a/Deployment/web"])
        self.assertFalse(exported["pods"][0]["ready"])

    def test_kubectl_json_adds_output_flags(self):
        completed = subprocess.CompletedProcess(["kubectl"], 0, stdout='{"ok": true}', stderr="")
        with mock.patch.object(acquire.subprocess, "run", return_value=completed) as run:
            self.assertEqual(acquire.kubectl_json(["get", "nodes"]), {"ok": True})
            self.assertIn("-o", run.call_args[0][0])
            acquire.kubectl_json(["get", "--raw", "/apis/x"])
            self.assertNotIn("-o", run.call_args[0][0])

    def run_main(self, argv):
        with (
            mock.patch.object(sys, "argv", ["acquire-readonly.py", *argv]),
            mock.patch("sys.stdout"),
            mock.patch("sys.stderr"),
        ):
            return acquire.main()

    def test_main_replays_an_input_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle.json"
            source.write_text(json.dumps(bundle()))
            code = self.run_main(["--namespace", "exp-a", "--input", str(source)])
        self.assertEqual(code, 0)

    def test_main_read_only_uses_fixed_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            contract = Path(directory) / "contract.json"
            contract.write_text(json.dumps(bundle()["contract"]))
            data = bundle()
            responses = {
                "nodes": data["nodes"],
                "metrics": data["metrics"],
                "pods": data["pods"],
                "resources": data["resources"],
            }

            def read(arguments):
                if arguments[:2] == ["get", "nodes"]:
                    return responses["nodes"]
                if "--raw" in arguments:
                    return responses["metrics"]
                if "pods" in arguments:
                    return responses["pods"]
                return responses["resources"]

            with mock.patch.object(acquire, "kubectl_json", side_effect=read):
                code = self.run_main(
                    [
                        "--namespace",
                        "exp-a",
                        "--read-only",
                        "--contract",
                        str(contract),
                        "--run-id",
                        "fixture-run",
                    ]
                )
        self.assertEqual(code, 0)

    def test_main_rejects_invalid_arguments_and_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle.json"
            source.write_text(json.dumps(bundle()))
            cases = (
                (["--namespace", "Invalid", "--input", str(source)], SystemExit),
                (
                    ["--namespace", "exp-a", "--input", str(source), "--run-id", " "],
                    SystemExit,
                ),
                (
                    ["--namespace", "exp-a", "--read-only"],
                    SystemExit,
                ),
                (
                    ["--namespace", "exp-a", "--input", str(source), "--run-id", "other"],
                    1,
                ),
                (
                    ["--namespace", "exp-a", "--input", str(Path(directory) / "missing")],
                    1,
                ),
            )
            for argv, expected in cases:
                with (
                    self.subTest(argv=argv),
                    mock.patch.object(sys, "argv", ["acquire-readonly.py", *argv]),
                    mock.patch("sys.stdout"),
                    mock.patch("sys.stderr"),
                ):
                    if isinstance(expected, type):
                        with self.assertRaises(expected):
                            acquire.main()
                    else:
                        self.assertEqual(acquire.main(), expected)

    def test_main_reports_export_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bundle.json"
            source.write_text(json.dumps({"contract": {}}))
            self.assertEqual(self.run_main(["--namespace", "exp-a", "--input", str(source)]), 1)


if __name__ == "__main__":
    unittest.main()
