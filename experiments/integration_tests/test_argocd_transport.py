"""Exercise controller JSON transport through fake executables, never a cluster."""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.analysis import analyze
from experiments.scripts import apparatus
from experiments.tests.test_apparatus import _expected_objects


FAKE_CLIENT = r'''#!__PYTHON__
import copy
import json
import os
import sys

client = os.path.basename(sys.argv[0])
args = sys.argv[1:]
safe_args = list(args)
if "--patch" in safe_args:
    safe_args[safe_args.index("--patch") + 1] = "<redacted>"
with open(os.environ["FAKE_CALLS"], "a") as stream:
    stream.write(json.dumps([client, *safe_args]) + "\n")
prefix = "--argocd-context" if client == "argocd" else "--context"
expected_context = "fixture-argo" if client == "argocd" else "fixture-kube"
if args[:2] != [prefix, expected_context]:
    raise SystemExit(99)
args = args[2:]
state_path = os.environ["FAKE_STATE"]
with open(state_path) as stream:
    state = json.load(stream)

def save():
    temporary = state_path + "." + str(os.getpid())
    with open(temporary, "w") as stream:
        json.dump(state, stream)
    os.replace(temporary, state_path)

if client == "argocd":
    if "--help" in args:
        print("Usage: argocd app [command]" if os.environ.get("FAKE_OLD_CLI") else
              "get-resource APPNAME --kind --group --resource-name --output")
    elif args[:2] == ["app", "get"]:
        resources = []
        for obj in state["objects"]:
            group = obj["apiVersion"].split("/")[0] if "/" in obj["apiVersion"] else ""
            changed = state["drift_kind"] == obj["kind"]
            resources.append({"kind": obj["kind"], "group": group, "name": obj["metadata"]["name"],
                "namespace": "exp-s1-gitops", "status": "OutOfSync" if changed else "Synced"})
        print(json.dumps({"spec": {"destination": {"namespace": "exp-s1-gitops",
            "server": "https://kubernetes.default.svc"}}, "status": {"resources": resources}}))
    elif args[:2] == ["app", "get-resource"]:
        kind = args[args.index("--kind") + 1]
        obj = copy.deepcopy(next(obj for obj in state["objects"] if obj["kind"] == kind))
        if state["drift_kind"] == kind:
            original = next(obj for obj in state["baseline"] if obj["kind"] == kind)
            state["objects"] = [original if obj["kind"] == kind else obj for obj in state["objects"]]
            state["drift_kind"] = None
            save()
        if kind == "Secret":
            obj["data"] = {key: "********" for key in obj.get("data", {})}
        print(json.dumps([obj]))
    else:
        raise SystemExit(99)
elif args[:2] == ["top", "nodes"]:
    print("node-1 100m 5% 1Gi 10%")
elif args[:2] == ["get", "pods"]:
    print(json.dumps({"items": [{"status": {"phase": "Running", "containerStatuses": [{"ready": True}]}}]}))
elif args[0] == "get":
    print(json.dumps({"items": state["objects"]}))
elif args[0] in ("scale", "patch"):
    kind = "Deployment" if args[0] == "scale" else "Secret"
    obj = next(obj for obj in state["objects"] if obj["kind"] == kind)
    if kind == "Deployment":
        obj["spec"]["replicas"] = 5
    else:
        obj["data"]["password"] = "ZHJpZnQtZ2l0b3Bz"
    state["drift_kind"] = kind
    save()
    print(json.dumps(obj))
else:
    raise SystemExit(99)
'''


class ArgoCDTransportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        binary = self.root / "bin"
        binary.mkdir()
        for client in ("kubectl", "argocd"):
            executable = binary / client
            executable.write_text(FAKE_CLIENT.replace("__PYTHON__", sys.executable))
            executable.chmod(0o755)
        objects = _expected_objects(namespace="exp-s1-gitops")
        for obj in objects:
            group = apparatus.RESOURCE_GROUPS[obj["kind"]]
            obj["apiVersion"] = group + "/v1" if group else "v1"
        self.state = self.root / "state.json"
        self.state.write_text(json.dumps({"objects": objects, "baseline": copy.deepcopy(objects), "drift_kind": None}))
        self.calls = self.root / "calls.jsonl"
        self.env = {"PATH": str(binary), "FAKE_STATE": str(self.state), "FAKE_CALLS": str(self.calls)}
        self.adapter = apparatus.SubprocessAdapter("s1", "gitops", "exp-s1-gitops", "fixture-kube", "fixture-app",
            argocd_context="fixture-argo", destination_server="https://kubernetes.default.svc")

    def collect(self, scenario="A"):
        with patch.dict(os.environ, self.env):
            record = apparatus.run_experiment(self.adapter, "s1", "gitops", scenario,
                timeout_s=3.0, poll_interval_s=0.001, run_id="fixture-argocd")
        source = self.root / "run.json"
        source.write_text(json.dumps(record, allow_nan=False))
        runs = analyze.load_v2_runs(source, "fixture")
        analyze.write_v2_report(runs, "fixture", self.root / "report")
        report = json.loads((self.root / "report" / "analysis-v2.json").read_text())
        return record, report

    def test_real_adapter_emits_controller_field_evidence_accepted_by_analysis(self):
        record, report = self.collect()
        self.assertEqual(record["status"], "complete", record["reason"])
        self.assertEqual(record["r1_recovered_pct"], 100.0)
        self.assertTrue(any(item["field_paths"] == ["spec.replicas"] and
            item["source"] == "argocd-live-resource" for item in record["evidence"]))
        self.assertEqual(report["groups"][0]["events"]["evidence"]["observed_duration_s"]["n"], 1)
        self.assertEqual(report["label"], "SYNTHETIC FIXTURE — NOT EMPIRICAL")
        self.assertNotIn("ZXhwLXNlY3JldC0xMjM=", json.dumps(record))

    def test_masked_secret_preserves_detection_and_restoration_not_invented_evidence(self):
        record, report = self.collect("G")
        self.assertEqual(record["detection_status"], "observed")
        self.assertEqual(record["recovery_status"], "observed")
        self.assertEqual(record["evidence_status"], "not_evaluable")
        self.assertIsNone(record["te_mono_s"])
        self.assertEqual(report["groups"][0]["events"]["evidence"]["status_counts"]["not_evaluable"], 1)
        self.assertNotIn("ZHJpZnQtZ2l0b3Bz", json.dumps(record))

    def test_wrong_destination_is_rejected_before_kubectl_or_injection(self):
        self.adapter.destination_server = "https://other.invalid"
        record, _ = self.collect()
        self.assertEqual(record["reason"], "gitops_target_or_status_invalid")
        self.assertIsNone(record["t0_mono_s"])
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertTrue(all(call[0] == "argocd" for call in calls))


if __name__ == "__main__":
    unittest.main()
