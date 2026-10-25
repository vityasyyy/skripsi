"""Read-only exporter tests use saved API JSON, never a cluster."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AcquisitionTest(unittest.TestCase):
    def export(self, change=None, read_only=False, bundle_run_id="fixture-run", cli_run_id=None):
        bundle = {
            "run_id": bundle_run_id,
            "contract": {"source_revision": "6cacea6642a7c1690243d3b54130fa08216a9595",
                         "resources": [{"id": "exp-fixture/Deployment/web", "fields": {
                             "/spec/template/spec/containers/0/image": "fixture@sha256:abc"}}]},
            "nodes": {"items": [{"metadata": {"name": "node"}, "status": {
                "allocatable": {"cpu": "2", "memory": "200Mi"},
                "nodeInfo": {"kubeletVersion": "v1.32.6+rke2r1", "osImage": "Ubuntu 24.04"}}}]},
            "metrics": {"items": [{"metadata": {"name": "node"}, "usage": {
                "cpu": "500000000n", "memory": "100Mi"}}]},
            "pods": {"items": [{"metadata": {"name": "web-abc"}, "status": {
                "phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}}]},
            "resources": {"items": [{"kind": "Deployment", "metadata": {
                "namespace": "exp-fixture", "name": "web"}, "spec": {"template": {
                "spec": {"containers": [{"image": "fixture@sha256:abc", "env": [
                    {"name": "PRIVATE", "value": "NEVER-EXPORT-THIS"}]}]}}}}]},
        }
        if change:
            change(bundle)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "capture.json"
            source.write_text(json.dumps(bundle))
            if read_only:
                contract = Path(directory) / "contract.json"
                contract.write_text(json.dumps(bundle["contract"]))
                fake = Path(directory) / "kubectl"
                fake.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
responses = {{
 ("--request-timeout=10s", "get", "nodes", "-o", "json"): "nodes",
 ("--request-timeout=10s", "get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"): "metrics",
 ("--request-timeout=10s", "get", "pods", "-n", "exp-fixture", "-o", "json"): "pods",
 ("--request-timeout=10s", "get", "deployments,services,hpa", "-n", "exp-fixture", "-o", "json"): "resources"
}}
key = responses.get(tuple(sys.argv[1:]))
if key is None: sys.exit(99)
print(json.dumps(json.loads(Path({str(source)!r}).read_text())[key]))
''')
                fake.chmod(0o755)
                args = ["--read-only", "--contract", str(contract)]
                if cli_run_id or bundle_run_id:
                    args += ["--run-id", cli_run_id or bundle_run_id]
            else:
                args = ["--input", str(source)]
                if cli_run_id:
                    args += ["--run-id", cli_run_id]
            return subprocess.run([sys.executable, str(ROOT / "scripts/acquire-readonly.py"),
                                   "--namespace", "exp-fixture", *args],
                                  capture_output=True, text=True, timeout=5,
                                  env={**os.environ, "PATH": directory + os.pathsep + os.environ["PATH"]})

    def test_read_only_adapter_uses_only_fixed_get_calls_and_raw_metrics_without_output_flag(self):
        result = self.export(read_only=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertFalse(row["replay"])
        self.assertFalse(row["readiness_verified"])
        self.assertEqual(row["nodes"][0]["memory_percent"], 50)

    def test_export_records_precise_metrics_versions_and_only_selected_safe_fields(self):
        result = self.export()
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertFalse(row["readiness_verified"])
        self.assertEqual(row["nodes"][0]["cpu_percent"], 25)
        self.assertEqual(row["nodes"][0]["memory_percent"], 50)
        self.assertEqual(row["nodes"][0]["kubelet_version"], "v1.32.6+rke2r1")
        self.assertEqual(row["resources"][0]["fields"], {
            "/spec/template/spec/containers/0/image": "fixture@sha256:abc"})
        self.assertNotIn("NEVER-EXPORT-THIS", result.stdout + result.stderr)
        self.assertIn("deployment_revision_attestation", row["missing_evidence"])

    def test_export_preserves_run_identity_for_sample_binding(self):
        for read_only in (False, True):
            result = self.export(read_only=read_only)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["run_id"], "fixture-run")

    def test_export_requires_run_identity_and_rejects_mismatch(self):
        for read_only in (False, True):
            result = self.export(read_only=read_only, bundle_run_id=None, cli_run_id=None)
            self.assertNotEqual(result.returncode, 0, result.stdout)
        result = self.export(bundle_run_id="bundle-run", cli_run_id="other")
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_export_records_absence_without_inventing_an_object(self):
        result = self.export(lambda b: b["resources"].update(items=[]))
        self.assertEqual(result.returncode, 0, result.stderr)
        row = json.loads(result.stdout)
        self.assertEqual(row["resources"], [])
        self.assertEqual(row["absent_resources"], ["exp-fixture/Deployment/web"])

    def test_export_fails_closed_when_node_metrics_or_selected_field_are_missing(self):
        for change in (
            lambda b: b["metrics"]["items"][0]["usage"].pop("memory"),
            lambda b: b["metrics"].update(items=[]),
            lambda b: b["resources"]["items"][0]["spec"]["template"]["spec"]["containers"][0].pop("image"),
            lambda b: b["nodes"]["items"][0]["status"]["allocatable"].update(memory="0"),
        ):
            result = self.export(change)
            self.assertNotEqual(result.returncode, 0)

    def test_secret_and_arbitrary_pod_fields_cannot_be_exported(self):
        for path in ("/spec/template/spec/containers/0/env", "/data/password"):
            result = self.export(lambda b: b["contract"]["resources"][0].update(fields={path: True}))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("NEVER-EXPORT-THIS", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
