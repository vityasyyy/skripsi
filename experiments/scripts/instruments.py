#!/usr/bin/env python3
"""Offline evidence evaluator. No cluster clients or mutation executor."""
import argparse
import json
import math
from pathlib import Path
import re
import sys


class EvidenceError(ValueError):
    pass


class InjectionError(EvidenceError):
    pass


class RecoveryError(EvidenceError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"{label}: expected finite nonnegative number")
    return value


def indexed(items, key, label):
    require(isinstance(items, list) and items, f"{label}: nonempty inventory required")
    result = {}
    for item in items:
        require(isinstance(item, dict) and isinstance(item.get(key), str) and item[key],
                f"{label}: missing identity")
        require(item[key] not in result, f"{label}: duplicate identity")
        result[item[key]] = item
    return result


def contract(evidence):
    spec = evidence["contract"]
    require(re.fullmatch(r"[0-9a-f]{40}", spec["source_revision"]), "source revision must be pinned")
    require(re.fullmatch(r"[0-9a-f]{64}", spec["render_sha256"]), "render digest required")
    resources = indexed(spec["resources"], "id", "expected resources")
    targets = spec["hpa_targets"]
    require(isinstance(targets, list) and targets and all(isinstance(target, str) for target in targets)
            and len(set(targets)) == len(targets) and set(targets) <= set(resources),
            "HPA target inventory must identify expected resources")
    for resource in resources.values():
        fields = resource.get("fields")
        require(isinstance(fields, dict) and fields, "explicit field contract required")
        require(all(isinstance(key, str) and key.startswith("/") for key in fields),
                "field identities must be paths")
        # Secret values/hashes must never enter evidence artifacts.
        if "/Secret/" in resource["id"]:
            require(all(value is True for value in fields.values()),
                    "Secret contract accepts equality booleans only")
        require(resource["id"] not in targets or "/spec/replicas" not in fields,
                "HPA-owned replicas excluded from static R1")
    for key in ("nodes", "pods"):
        require(isinstance(spec[key], list) and spec[key] and
                all(isinstance(name, str) and name for name in spec[key]) and
                len(set(spec[key])) == len(spec[key]), f"expected {key} inventory required")
    return spec


def score(spec, snapshot):
    require(not snapshot.get("error"), "instrumentation failure in snapshot")
    for key in ("source_revision", "render_sha256"):
        require(snapshot[key] == spec[key], f"snapshot {key} mismatch")
    # A successful complete API list may be empty: all resources then score zero.
    actual_items = snapshot["resources"]
    require(isinstance(actual_items, list), "resource read evidence required")
    actual = indexed(actual_items, "id", "actual resources") if actual_items else {}
    matches = 0
    for desired in spec["resources"]:
        observed = actual.get(desired["id"])
        if observed is None:
            continue
        values = observed["fields"]
        require(isinstance(values, dict), "field read evidence required")
        require(set(desired["fields"]) <= set(values), "missing selected-field evidence")
        if "/Secret/" in desired["id"]:
            require(all(type(values[key]) is bool for key in desired["fields"]),
                    "Secret observations must be equality booleans")
        matches += all(type(values[key]) is type(value) and values[key] == value
                       for key, value in desired["fields"].items())
    return 100 * matches / len(spec["resources"])


CHECKS = ("audit", "smtp", "application_reset", "clock", "isolation", "hpa",
          "lifecycle", "quiet_window", "runtime_adoption", "queue", "data")


def baseline(evidence, snapshot):
    spec = contract(evidence)
    require(snapshot["run_id"] == evidence["run_id"], "baseline/reset belongs to another run")
    number(snapshot["at"], "baseline/reset time")
    require(score(spec, snapshot) == 100, "baseline field/inventory mismatch")
    require({obj["id"] for obj in snapshot["resources"]} ==
            {obj["id"] for obj in spec["resources"]}, "extra resource hidden from inventory")
    require(hpa_restored(spec, snapshot), "HPA baseline/reset not converged")
    require(snapshot["extra_resources"] == [], "unexpected/quarantine resources remain")
    require(snapshot["memory_metric"] == "metrics-server-working-set/allocatable",
            "memory metric must be fixed, not substituted")
    nodes = indexed(snapshot["nodes"], "name", "nodes")
    require(set(nodes) == set(spec["nodes"]), "incomplete node inventory")
    for node in nodes.values():
        for metric in ("cpu_percent", "memory_percent"):
            require(number(node[metric], metric) < 70, f"{metric}: threshold >=70%")
    pods = indexed(snapshot["pods"], "name", "pods")
    require(set(pods) == set(spec["pods"]), "incomplete pod inventory")
    require(all(pod["phase"] == "Running" and pod["ready"] is True for pod in pods.values()),
            "pods must be Running and Ready")
    for key in CHECKS:
        require(snapshot["checks"][key] is True, f"missing/failed prerequisite: {key}")
    if evidence["env"] == "gitops":
        require(snapshot["argo"] == {"sync": "Synced", "health": "Healthy"},
                "ArgoCD status is not Synced/Healthy")


def injection(evidence):
    event = evidence["injection"]
    require(type(event["count"]) is int and event["count"] == 1,
            "one injection per verified reset only")
    if event["accepted"] is not True or event["verified"] is not True:
        raise InjectionError("injection failed or acceptance unverified")
    start = number(event["started"], "injection start")
    ack = number(event["acknowledged"], "API acknowledgement")
    require(number(evidence["collector_started"], "collector start") < start <= ack,
            "collector must start before injection; invalid API timing")
    require(evidence["baseline"]["at"] <= evidence["collector_started"],
            "baseline must precede collector/injection")
    changes = event["changed_fields"]
    require(isinstance(changes, list) and changes, "accepted changed-field evidence required")
    fields = {resource["id"]: set(resource["fields"]) for resource in contract(evidence)["resources"]}
    foreign = evidence["scenario"] == "F"
    if foreign:
        spec = evidence["contract"]
        namespace = spec["quarantine_namespace"]
        quarantine = spec["quarantine_resources"]
        require(isinstance(quarantine, list) and quarantine and
                all(isinstance(item, str) and item.startswith(namespace + "/") for item in quarantine)
                and not set(quarantine) & set(fields), "explicit separate quarantine inventory required")
        metadata = event["request_metadata"]
        require(isinstance(metadata, dict) and set(metadata) <= {"name", "namespace", "labels", "annotations"}
                and metadata["namespace"] == namespace and metadata["name"],
                "F request must omit server-generated metadata")
    for change in changes:
        allowed = ({"/metadata/namespace"} if foreign else {"/spec/replicas"}
                   if evidence["scenario"] == "A" else fields.get(change["resource"], set()))
        inventory = quarantine if foreign else fields
        effect = change.get("effect", "value_changed")
        require(effect in ("value_changed", "deleted", "created"), "unsupported injection effect")
        if evidence["scenario"] == "D":
            require(effect == "deleted" and change["resource"] in fields and
                    change["path"] == "/metadata/name", "injection D requires verified deletion evidence")
        elif foreign:
            require(effect == "created" and change["resource"] in inventory and
                    change["path"] == "/metadata/namespace", "injection F requires verified creation evidence")
        else:
            require(effect == "value_changed" and change["resource"] in inventory and
                    change["path"] in allowed, "injection change not verified against baseline")
        require(change["matches_desired"] is False, "injection must differ from baseline")
    return start, ack


def hpa_restored(spec, sample):
    targets = spec["hpa_targets"]
    require(isinstance(targets, list) and targets and len(set(targets)) == len(targets),
            "HPA target inventory required")
    states = indexed(sample["hpa_states"], "target", "HPA observations")
    require(set(states) == set(targets), "incomplete HPA observations")
    restored = True
    for state in states.values():
        for key in ("desired", "replicas", "ready", "generation", "observed_generation"):
            require(type(state[key]) is int and state[key] >= 0, "invalid HPA state")
        require(state["active"] is True and state["able_to_scale"] is True,
                "HPA not active/able to scale")
        restored &= (state["desired"] == state["replicas"] == state["ready"] and
                     state["generation"] == state["observed_generation"])
    return restored


def metrics(evidence):
    baseline(evidence, evidence["baseline"])
    spec = contract(evidence)
    start, ack = injection(evidence)
    end = number(evidence["observation_end"], "observation end")
    timeout = number(evidence["timeout_seconds"], "timeout")
    require(end > ack, "observation end must follow injection acknowledgement")
    require(end <= start + timeout, "observation cannot exceed frozen timeout")
    stop_reason = evidence["stop_reason"]
    require(stop_reason in ("timeout", "recovery"), "explicit stop reason required")
    if stop_reason == "timeout":
        require(end == start + timeout, "timeout run must cover the frozen observation limit")
    if "recovery" in evidence:
        correction_results(evidence, start, end)
    max_gap = number(evidence["max_sample_gap_seconds"], "maximum sample gap")
    require(max_gap > 0, "maximum sample gap must be positive")
    scenario = evidence["scenario"]
    group = "hpa_control" if scenario == "A" else "visibility_boundary" if scenario == "F" else "managed_drift"
    controller = "hpa" if scenario == "A" else "imperative" if evidence["env"] == "manual" else "argocd"
    events = evidence["events"]
    require(isinstance(events, list), "event stream required, even if empty")
    found = {}
    previous = start
    desired = {resource["id"]: resource["fields"] for resource in spec["resources"]}
    for event in events:
        at = number(event["at"], "event time")
        require(previous <= at <= end, "unordered/out-of-window event")
        previous = at
        require(event["run_id"] == evidence["run_id"], "stale event from another run")
        require(event["type"] in ("detection", "evidence"), "unknown event type")
        require(event["controller"] == controller, "detection from wrong controller")
        paths = event["fields"]
        if scenario == "A":
            require(event["resource"] in spec["hpa_targets"], "event from unmeasured HPA target")
            allowed = {"/spec/replicas"}
        elif scenario == "F":
            require(event["resource"] in spec["quarantine_resources"], "unmeasured quarantine object")
            allowed = {"/metadata/namespace"}
        else:
            allowed = set(desired.get(event["resource"], {}))
        require(isinstance(paths, list) and paths and set(paths) <= allowed,
                "event must identify measured resource/fields")
        if event["type"] == "evidence":
            require(isinstance(event.get("artifact"), str) and event["artifact"],
                    "sanitized deviation artifact reference required")
        found.setdefault(event["type"], at)
    if "evidence" in found:
        require("detection" in found and found["detection"] <= found["evidence"],
                "evidence without preceding detection")
    samples = evidence["samples"]
    require(isinstance(samples, list) and samples, "observation snapshots required")
    previous = start
    scores = []
    recovery = None
    candidate = None
    deleted = {change["resource"] for change in evidence["injection"]["changed_fields"]
               if change.get("effect") == "deleted"}
    for position, sample in enumerate(samples):
        at = number(sample["at"], "sample time")
        require(previous < at <= end, "unordered/out-of-window sample")
        require(at - previous <= max_gap, "sample gap exceeds frozen coverage limit")
        previous = at
        require("run_id" in sample, "sample run identity required")
        require(sample["run_id"] == evidence["run_id"], "stale sample from another run")
        if scenario == "F":
            extra = sample.get("extra_resources")
            require(isinstance(extra, list), "F quarantine observation required")
            if position == 0:
                require(set(spec["quarantine_resources"]) <= set(extra),
                        "F injection not visible in first observation")
        value = score(spec, sample)
        scores.append(value)
        if position == 0 and deleted:
            present = {resource["id"] for resource in sample["resources"]}
            require(not deleted & present, "D deletion not visible in first observation")
        # A's dynamic replica state requires HPA observation, not static R1=100.
        restored = value == 100
        if scenario == "A":
            hpa_equal = hpa_restored(spec, sample)
            restored = restored and hpa_equal
        if scenario == "F":
            restored = restored and sample["extra_resources"] == []
        if restored:
            if candidate is not None and recovery is None:
                recovery = candidate
            candidate = at if candidate is None else candidate
        else:
            candidate = None
    require(previous == end, "snapshot stream does not cover observation end")
    if stop_reason == "recovery":
        require(recovery is not None, "recovery stop without confirmed restoration")
    result = {
        "schema_version": 2, "run_id": evidence["run_id"], "env": evidence["env"],
        "scenario": scenario, "synthetic": evidence["synthetic"], "offline_only": True,
        "analysis_group": group, "efficacy_eligible": group == "managed_drift",
        "formal_execution_approved": False,
        "detection_controller": controller, "api_seconds": ack - start,
        "stop_reason": stop_reason, "r1_baseline": 100, "r1_first": scores[0], "r1_last": scores[-1],
        "censor_seconds": end - start,
        "source_revision": spec["source_revision"], "render_sha256": spec["render_sha256"],
    }
    for name, at in (("detection", found.get("detection")), ("evidence", found.get("evidence")),
                     ("recovery", recovery)):
        result[name + "_seconds"] = None if at is None else at - start
        if at is not None:
            result[name + "_status"] = "observed"
        elif stop_reason == "timeout":
            result[name + "_status"] = "right_censored"
        else:
            result[name + "_status"] = "unobserved_before_stop"
    return result


def correction_results(evidence, start, end):
    commands = evidence["recovery"]["commands"]
    require(isinstance(commands, list) and commands, "correction command results required")
    previous = start
    for command in commands:
        require(type(command["returncode"]) is int, "command exit code required")
        if command["returncode"] != 0:
            raise RecoveryError("correction failed; reset not verified")
        started = number(command["started"], "command start")
        finished = number(command["finished"], "command finish")
        require(previous <= started <= finished, "invalid command timing")
        if finished > end:
            raise RecoveryError(
                "measured correction command must finish within the observation window; "
                "later reset actions are not measured recovery evidence"
            )
        previous = finished
    return previous, len(commands)


def recovery(evidence):
    baseline(evidence, evidence["baseline"])
    start, ack = injection(evidence)
    end = number(evidence["observation_end"], "observation end")
    require(end > ack, "observation end must follow injection acknowledgement")
    previous, count = correction_results(evidence, start, end)
    baseline(evidence, evidence["reset"])
    require(evidence["reset"]["at"] >= previous, "reset snapshot predates correction")
    return {"status": "reset_verified_offline", "commands": count, "offline_only": True}


def main():
    parser = argparse.ArgumentParser(description="Offline evidence validation only; live execution disabled.")
    parser.add_argument("mode", choices=("baseline", "metrics", "recovery", "injection"))
    parser.add_argument("--evidence", type=Path, help="sanitized JSON evidence bundle")
    parser.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.live:
        parser.exit(3, "Live execution disabled: owner method review and readiness approval pending.\n")
    if args.evidence is None:
        parser.exit(2, "No actions executed. Use --evidence FILE for offline validation; live execution disabled.\n")
    try:
        evidence = json.loads(args.evidence.read_text())
        require(evidence["env"] in ("manual", "gitops"), "unknown arm")
        require(evidence["scenario"] in list("ABCDEFG"), "unknown scenario")
        require(type(evidence["synthetic"]) is bool, "synthetic evidence must be labeled")
        require(isinstance(evidence["run_id"], str) and evidence["run_id"], "run identity required")
        if args.mode == "baseline":
            baseline(evidence, evidence["baseline"])
            result = {"status": "baseline_verified_offline", "offline_only": True}
        elif args.mode == "metrics":
            result = metrics(evidence)
        elif args.mode == "recovery":
            result = recovery(evidence)
        else:
            baseline(evidence, evidence["baseline"])
            start, ack = injection(evidence)
            result = {"status": "injection_verified_offline", "api_seconds": ack - start,
                      "offline_only": True}
        result.update(run_id=evidence["run_id"], synthetic=evidence["synthetic"],
                      formal_execution_approved=False)
        print(json.dumps(result, allow_nan=False, sort_keys=True))
    except (EvidenceError, KeyError, TypeError, OSError, ValueError) as error:
        # Do not echo evidence values: an invalid input may contain a Secret.
        status = ("injection_failed" if isinstance(error, InjectionError) else
                  "recovery_failed" if isinstance(error, RecoveryError) else "invalid_evidence")
        print(json.dumps({"status": status, "error_type": type(error).__name__,
                          "reason": str(error) if isinstance(error, EvidenceError) else
                          "missing, malformed or unreadable evidence; check schema",
                          "offline_only": True}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
