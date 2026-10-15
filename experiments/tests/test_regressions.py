import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "experiments" / "scripts"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


FAKE_CLIENT = r'''#!{python}
import json
import os
import sys

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
calls = os.environ.get("FAKE_CALLS")
if calls:
    with open(calls, "a", encoding="utf-8") as output:
        output.write(json.dumps([name, *args]) + "\n")
mode = os.environ.get("FAKE_MODE", "")
code, stdout, stderr = 0, "", ""
if name == "argocd":
    stdout = "Sync Status: Synced\nHealth Status: Healthy\n"
elif args[:2] == ["top", "nodes"]:
    stdout = "" if mode == "empty-metrics" else "node-1 100m 5% 1Gi 10%\n"
elif args[:2] == ["get", "pods"]:
    stdout = "" if mode == "empty-pods" else "pod-1 1/1 Running 0 1m\n"
elif args[:2] == ["get", "deployment/exp-web"]:
    if any("jsonpath" in item for item in args):
        stdout = "5\n"
    else:
        stdout = "deployment.apps/exp-web\n"
elif args and args[0] == "scale" and mode == "correction-fails":
    code, stderr = 1, "simulated correction failure"
elif args[:2] == ["get", "deployment/exp-web"]:
    stdout = "deployment.apps/exp-web\n"
sys.stdout.write(stdout)
sys.stderr.write(stderr)
raise SystemExit(code)
'''


class ScriptRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls.jsonl"
        for client in ("kubectl", "argocd"):
            path = self.bin / client
            path.write_text(FAKE_CLIENT.format(python=os.sys.executable), encoding="utf-8")
            path.chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "PATH": f"{self.bin}:{SYSTEM_PATH}",
            "FAKE_CALLS": str(self.calls),
        })

    def run_script(self, name, *args, mode=""):
        env = self.env.copy()
        env["FAKE_MODE"] = mode
        return subprocess.run(
            ["/bin/bash", str(SCRIPTS / name), *args],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def recorded_calls(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()]

    def test_empty_node_metrics_cannot_establish_baseline(self):
        result = self.run_script(
            "baseline-check.sh", "--live", "--namespace", "exp-s1-manual",
            mode="empty-metrics",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_empty_pod_inventory_cannot_establish_baseline(self):
        result = self.run_script(
            "baseline-check.sh", "--live", "--namespace", "exp-s1-manual",
            mode="empty-pods",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_gitops_collection_cannot_write_measurements(self):
        output = self.root / "run.csv"
        result = self.run_script(
            "metrics-collect.sh", "--live", "--subject", "s1", "--env", "gitops",
            "--scenario", "C", "--namespace", "exp-s1-gitops", "--app", "fixture-app",
            "--t0", "100", "--timeout", "0", "--output", str(output),
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(output.exists())

    def test_failed_correction_cannot_emit_successful_recovery(self):
        result = self.run_script(
            "recovery-runbook.sh", "--live", "--namespace", "exp-s1-manual",
            "--scenario", "A", mode="correction-fails",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('"event":"runbook_complete"', result.stdout)

    def test_f_boundary_does_not_delete_namespace_in_runbook(self):
        result = self.run_script(
            "recovery-runbook.sh", "--namespace", "exp-s1-manual", "--scenario", "F",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("delete namespace", result.stdout + result.stderr)

    def test_multi_scenario_live_injection_is_rejected_without_client_calls(self):
        result = self.run_script(
            "drift-inject.sh", "--live", "--namespace", "exp-s1-manual", "--scenario", "all",
            "--order", "sequential",
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.recorded_calls(), [])

    def test_default_injection_preview_uses_no_external_commands_or_writes(self):
        log = self.root / "preview.log"
        result = self.run_script(
            "drift-inject.sh", "--namespace", "exp-s1-manual", "--scenario", "all", "--log", str(log),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.recorded_calls(), [])
        self.assertFalse(log.exists())

    def test_legacy_synthetic_csv_shape_is_preserved(self):
        output = self.root / "sample.csv"
        result = self.run_script(
            "metrics-collect.sh", "--live-dryrun", "--subject", "s1", "--env", "manual",
            "--scenario", "A", "--rep", "1", "--namespace", "exp-s1-manual",
            "--t0", "123", "--output", str(output),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output.read_text(encoding="utf-8").splitlines(), [
            "subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes",
            "s1,manual,A,1,123,123,123,123,100,0,100,0,DRYRUN-sample-tidak-menyentuh-klaster",
        ])

if __name__ == "__main__":
    unittest.main()
