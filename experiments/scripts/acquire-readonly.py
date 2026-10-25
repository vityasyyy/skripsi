#!/usr/bin/env python3
"""Export selected non-secret observations; never authorize a run or modify a cluster."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def quantity(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(n|u|m|Ki|Mi|Gi|Ti|k|M|G|T)?", value)
    if not match:
        raise ValueError("unsupported Kubernetes quantity")
    factors = {None: 1, "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"),
               "Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
               "k": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}
    return Decimal(match[1]) * factors[match[2]]


def selected_field(obj, kind, path):
    safe = (
        kind == "Deployment" and re.fullmatch(
            r"/spec/(replicas|template/spec/containers/[0-9]+/(image|resources/(requests|limits)/(cpu|memory)))", path)
        or kind == "Service" and re.fullmatch(r"/spec/(type|selector|ports/[0-9]+/(port|targetPort|protocol))", path)
        or kind == "HorizontalPodAutoscaler" and path in ("/spec/minReplicas", "/spec/maxReplicas")
    )
    if not safe:
        raise ValueError("unsupported/sensitive field; separate reviewed evidence required")
    value = obj
    for token in path.split("/")[1:]:
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def unique(items, identity):
    result = {}
    for item in items:
        key = identity(item)
        if key in result:
            raise ValueError("duplicate observation identity")
        result[key] = item
    return result


def export(bundle, namespace, run_id):
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run identity required for sample binding")
    spec = bundle["contract"]
    if not re.fullmatch(r"[0-9a-f]{40}", spec["source_revision"]):
        raise ValueError("pinned reference revision required")
    nodes = unique(bundle["nodes"]["items"], lambda node: node["metadata"]["name"])
    metrics = unique(bundle["metrics"]["items"], lambda node: node["metadata"]["name"])
    if not nodes or set(nodes) != set(metrics):
        raise ValueError("node metrics incomplete")
    observations = []
    for name, node in nodes.items():
        allocatable = node["status"]["allocatable"]
        usage = metrics[name]["usage"]
        values = {}
        for resource in ("cpu", "memory"):
            capacity = quantity(allocatable[resource])
            if capacity <= 0:
                raise ValueError("node allocatable must be positive")
            values[resource + "_percent"] = float(100 * quantity(usage[resource]) / capacity)
        info = node["status"]["nodeInfo"]
        observations.append({"name": name, **values, "kubelet_version": info["kubeletVersion"],
                             "os_image": info["osImage"]})
    actual = unique(bundle["resources"]["items"],
                    lambda obj: f'{obj["metadata"]["namespace"]}/{obj["kind"]}/{obj["metadata"]["name"]}')
    resources, absent = [], []
    if not spec["resources"]:
        raise ValueError("selected resource inventory required")
    expected = unique(spec["resources"], lambda obj: obj["id"])
    for identity, desired in expected.items():
        ns, kind, name = identity.split("/")
        if ns != namespace or kind not in ("Deployment", "Service", "HorizontalPodAutoscaler"):
            raise ValueError("only selected non-secret resources in target namespace can be exported")
        if not desired["fields"]:
            raise ValueError("selected fields required")
        # Validate paths even when the object is absent; absence is not permission to read secrets later.
        for path in desired["fields"]:
            try:
                selected_field({}, kind, path)
            except KeyError:
                pass
        if identity in actual:
            resources.append({"id": identity, "fields": {
                path: selected_field(actual[identity], kind, path) for path in desired["fields"]}})
        else:
            absent.append(identity)
    pods = [{"name": pod["metadata"]["name"], "phase": pod["status"]["phase"],
             "ready": any(condition["type"] == "Ready" and condition["status"] == "True"
                          for condition in pod["status"].get("conditions", []))}
            for pod in bundle["pods"]["items"]]
    return {"status": "read_only_export", "readiness_verified": False,
            "formal_execution_approved": False, "run_id": run_id,
            "reference_source_revision": spec["source_revision"],
            "memory_metric": "metrics-server-working-set/allocatable", "nodes": observations,
            "pods": pods, "resources": resources, "absent_resources": absent,
            "missing_evidence": ["deployment_revision_attestation", "render_digest_attestation",
                                 "configmap_equality", "secret_equality", "audit", "smtp",
                                 "application_reset", "queue_and_data", "runtime_adoption",
                                 "lifecycle", "hpa_policy_and_state",
                                 "controller_detection_event_stream", "quiet_window"]}


def kubectl_json(arguments):
    output_flags = [] if "--raw" in arguments else ["-o", "json"]
    result = subprocess.run(["kubectl", "--request-timeout=10s", *arguments, *output_flags],
                            capture_output=True, text=True, timeout=15, check=True)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="offline saved API JSON bundle, no external commands")
    source.add_argument("--read-only", action="store_true", help="explicit read-only acquisition; not a formal run")
    parser.add_argument("--contract", type=Path, help="selected non-secret field contract for --read-only")
    parser.add_argument("--run-id", help="evidence run identity stamped on the exported fragment")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", args.namespace):
        parser.error("invalid namespace")
    if args.run_id is not None and not args.run_id.strip():
        parser.error("--run-id must be nonempty")
    start = time.monotonic()
    utc = datetime.now(timezone.utc).isoformat()
    try:
        if args.input:
            bundle = json.loads(args.input.read_text())
        else:
            if args.contract is None:
                parser.error("--contract required for read-only acquisition")
            spec = json.loads(args.contract.read_text())
            # Fixed read-only calls only; no Secret/ConfigMap reads, shell, or user-provided command.
            bundle = {"contract": spec, "nodes": kubectl_json(["get", "nodes"]),
                      "metrics": kubectl_json(["get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"]),
                      "pods": kubectl_json(["get", "pods", "-n", args.namespace]),
                      "resources": kubectl_json(["get", "deployments,services,hpa", "-n", args.namespace])}
        bundle_run_id = bundle.get("run_id")
        if args.run_id and bundle_run_id and args.run_id != bundle_run_id:
            raise ValueError("run identity mismatch between bundle and --run-id")
        run_id = args.run_id or bundle_run_id
        result = export(bundle, args.namespace, run_id)
        result.update(acquisition_started=start, acquisition_finished=time.monotonic(), acquired_utc=utc,
                      replay=args.input is not None)
        print(json.dumps(result, allow_nan=False, sort_keys=True))
    except (KeyError, IndexError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        print("Read-only export failed: missing/unsupported evidence or API failure; no readiness claim.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
