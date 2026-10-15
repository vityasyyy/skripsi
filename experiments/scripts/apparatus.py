#!/usr/bin/env python3
"""Offline-testable coordinator for one controlled experiment run."""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PILOT_NAMESPACES = {
    ("s1", "manual"): "exp-s1-manual",
    ("s1", "gitops"): "exp-s1-gitops",
    ("s2", "manual"): "exp-s2-manual",
    ("s2", "gitops"): "exp-s2-gitops",
}
SUBPROCESS_TIMEOUT_S = 10.0
CPU_LIMIT_PCT = 70.0
SAFE_ERROR_CODES = {
    "apparatus_error", "external_command_timeout", "external_command_unavailable", "external_command_failed",
    "inventory_shape_invalid", "pod_inventory_invalid", "node_metrics_invalid", "invalid_resource_identity",
    "duplicate_resource_identity", "baseline_inventory_mismatch", "baseline_pods_empty",
    "baseline_pods_not_ready", "baseline_metrics_empty", "baseline_node_cpu_high",
    "baseline_mechanism_signal_present", "gitops_app_required", "gitops_target_or_status_invalid",
    "gitops_expected_resources_unavailable", "scenario_f_requires_separate_boundary_approval",
    "scenario_invalid", "correction_has_no_observed_differences", "baseline_manifest_unavailable",
    "baseline_manifest_invalid", "run_parameters_invalid", "rep_must_be_positive_integer",
    "timing_parameters_invalid", "subject_or_environment_invalid", "namespace_subject_environment_mismatch",
    "one_scenario_A_to_G_required", "formal_execution_not_supported", "live_phase_must_be_pilot",
    "one_scenario_required", "pilot_context_not_allowlisted", "pilot_target_not_allowlisted",
    "app_not_allowed_for_manual_environment", "pilot_timeout_below_command_bound", "injection_failed",
    "correction_failed", "injection_ack_not_observed", "output_already_exists",
    "injection_acceptance_unverified", "mechanism_evidence_unavailable",
    "gitops_evidence_transport_not_validated",
}


class ApparatusError(Exception):
    def __init__(self, code, accepted_at=None):
        self.code = code if code in SAFE_ERROR_CODES else "apparatus_error"
        self.accepted_at = accepted_at
        super().__init__(self.code)


@dataclass(frozen=True)
class ResourceSpec:
    kind: str
    name: str
    fields: tuple


@dataclass
class Observation:
    objects: list
    pod_count: int
    healthy: object
    node_cpu_pct: list


def expected_inventory(subject):
    specs = [
        ResourceSpec("ConfigMap", "exp-web-config", (
            (("data", "LOG_LEVEL"), "info"),
            (("data", "DATABASE_URL"), "postgres://db:5432/app"),
            (("data", "APP_NAME"), "exp-web"),
        )),
        ResourceSpec("Secret", "exp-web-secret", (
            (("type",), "Opaque"),
            (("data", "username"), "ZXhwLXVzZXI="),
            (("data", "password"), "ZXhwLXNlY3JldC0xMjM="),
        )),
        ResourceSpec("Deployment", "exp-web", (
            (("spec", "replicas"), 3),
            (("spec", "template", "spec", "containers", 0, "image"), "nginx:1.25.3"),
            (("spec", "template", "spec", "containers", 0, "resources", "limits", "cpu"), "200m"),
        )),
        ResourceSpec("Service", "exp-web", (
            (("spec", "type"), "ClusterIP"),
            (("spec", "ports", 0, "port"), 80),
            (("spec", "ports", 0, "targetPort"), 80),
        )),
        ResourceSpec("CronJob", "exp-web-tick", (
            (("spec", "schedule"), "*/5 * * * *"),
            (("spec", "jobTemplate", "spec", "template", "spec", "containers", 0, "image"), "busybox:1.36"),
        )),
    ]
    if subject == "s2":
        specs.extend((
            ResourceSpec("PersistentVolumeClaim", "exp-store-data", (
                (("spec", "accessModes", 0), "ReadWriteOnce"),
                (("spec", "resources", "requests", "storage"), "1Gi"),
            )),
            ResourceSpec("StatefulSet", "exp-store", (
                (("spec", "replicas"), 1),
                (("spec", "template", "spec", "containers", 0, "image"), "nginx:1.25.3"),
            )),
        ))
    return tuple(specs)


def _path_value(obj, path):
    value = obj
    for part in path:
        if isinstance(value, dict) and isinstance(part, str):
            if part not in value:
                return False, None
            value = value[part]
        elif isinstance(value, list) and isinstance(part, int) and 0 <= part < len(value):
            value = value[part]
        else:
            return False, None
    return True, value


def _field_name(path):
    result = ""
    for part in path:
        if isinstance(part, int):
            result += "[{}]".format(part)
        else:
            result += ("." if result else "") + part
    return result


def _resource_name(kind, name):
    if not isinstance(kind, str) or not isinstance(name, str):
        raise ApparatusError("invalid_resource_identity")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", kind) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ApparatusError("invalid_resource_identity")
    return "{}/{}".format(kind, name)


def compare_inventory(expected, objects):
    expected_by_id = {(spec.kind, spec.name): spec for spec in expected}
    actual_by_id = {}
    for obj in objects:
        metadata = obj.get("metadata") if isinstance(obj, dict) else None
        if not isinstance(metadata, dict):
            raise ApparatusError("inventory_shape_invalid")
        identity = (obj.get("kind"), metadata.get("name"))
        _resource_name(*identity)
        if identity in actual_by_id:
            raise ApparatusError("duplicate_resource_identity")
        actual_by_id[identity] = obj

    matched = 0
    differences = []
    for identity, spec in expected_by_id.items():
        obj = actual_by_id.get(identity)
        resource = _resource_name(*identity)
        if obj is None:
            differences.append({"resource": resource, "field_paths": ["$identity"], "source": "inventory-comparison"})
            continue
        mismatches = []
        for path, expected_value in spec.fields:
            present, value = _path_value(obj, path)
            if not present or value != expected_value:
                mismatches.append(_field_name(path))
        if mismatches:
            differences.append({"resource": resource, "field_paths": mismatches, "source": "inventory-comparison"})
        else:
            matched += 1

    for identity in actual_by_id.keys() - expected_by_id.keys():
        differences.append({
            "resource": _resource_name(*identity),
            "field_paths": ["$identity"],
            "source": "unexpected-inventory",
        })
    differences.sort(key=lambda item: (item["resource"], item["source"]))
    score = 100.0 * matched / len(expected_by_id) if expected_by_id else None
    return score, differences


def _pod_health(pods):
    if not pods:
        return None
    for pod in pods:
        status = pod.get("status", {})
        phase = status.get("phase")
        if phase == "Succeeded":
            continue
        if phase != "Running":
            return False
        containers = status.get("containerStatuses")
        if not containers or not all(item.get("ready") is True for item in containers):
            return False
    return True


def parse_node_cpu_percentages(output):
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if not rows:
        return []
    result = []
    for row in rows:
        if len(row) < 3 or not re.fullmatch(r"\d+(?:\.\d+)?%", row[2]):
            raise ApparatusError("node_metrics_invalid")
        result.append(float(row[2][:-1]))
    return result


def _baseline_failure(score, observation):
    if score != 100.0:
        return "baseline_inventory_mismatch"
    if observation.pod_count == 0:
        return "baseline_pods_empty"
    if observation.healthy is not True:
        return "baseline_pods_not_ready"
    if not observation.node_cpu_pct:
        return "baseline_metrics_empty"
    if any(value >= CPU_LIMIT_PCT for value in observation.node_cpu_pct):
        return "baseline_node_cpu_high"
    return None


class SubprocessAdapter:
    def __init__(self, subject, env, namespace, context, app=None, command_timeout_s=SUBPROCESS_TIMEOUT_S):
        self.subject = subject
        self.env = env
        self.namespace = namespace
        self.context = context
        self.app = app
        self.command_timeout_s = command_timeout_s

    def _run(self, client, args, input_text=None):
        command = [client]
        if client == "kubectl":
            command.extend(("--context", self.context))
        command.extend(args)
        try:
            result = subprocess.run(
                command,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=self.command_timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ApparatusError("external_command_timeout") from exc
        except OSError as exc:
            raise ApparatusError("external_command_unavailable") from exc
        if result.returncode != 0:
            raise ApparatusError("external_command_failed")
        return result.stdout

    def _read_inventory(self):
        kinds = "configmaps,secrets,deployments,services,cronjobs"
        if self.subject == "s2":
            kinds += ",persistentvolumeclaims,statefulsets"
        output = self._run("kubectl", ["get", kinds, "--namespace", self.namespace, "-o", "json"])
        try:
            payload = json.loads(output)
            objects = payload["items"]
            if not isinstance(objects, list):
                raise ValueError
            return objects
        except (KeyError, TypeError, ValueError) as exc:
            raise ApparatusError("inventory_shape_invalid") from exc

    def snapshot(self):
        objects = self._read_inventory()
        pod_output = self._run("kubectl", ["get", "pods", "--namespace", self.namespace, "-o", "json"])
        try:
            pods = json.loads(pod_output)["items"]
            if not isinstance(pods, list):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ApparatusError("pod_inventory_invalid") from exc
        metrics = parse_node_cpu_percentages(self._run("kubectl", ["top", "nodes", "--no-headers"]))
        return Observation(objects, len(pods), _pod_health(pods), metrics)

    def mechanism_signal(self, expected):
        if self.env == "manual":
            score, differences = compare_inventory(expected, self._read_inventory())
            return differences if score != 100.0 or any(item["source"] == "unexpected-inventory" for item in differences) else []
        if not self.app:
            raise ApparatusError("gitops_app_required")
        output = self._run("argocd", ["app", "get", self.app, "-o", "json"])
        try:
            payload = json.loads(output)
            destination = payload["spec"]["destination"]
            resources = payload["status"]["resources"]
            if destination.get("namespace") != self.namespace or not isinstance(resources, list):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ApparatusError("gitops_target_or_status_invalid") from exc
        expected_ids = {(spec.kind, spec.name) for spec in expected}
        resource_status = {}
        for item in resources:
            if item.get("namespace", self.namespace) != self.namespace:
                continue
            identity = (item.get("kind"), item.get("name"))
            if identity in expected_ids:
                resource_status[identity] = item.get("status")
        if set(resource_status) != expected_ids:
            raise ApparatusError("gitops_expected_resources_unavailable")
        return any(status in ("OutOfSync", "Missing") for status in resource_status.values())

    def inject(self, scenario):
        if scenario == "F":
            raise ApparatusError("scenario_f_requires_separate_boundary_approval")
        if scenario == "A":
            args = ["scale", "deployment/exp-web", "--namespace", self.namespace, "--replicas=5"]
        elif scenario == "B":
            args = ["set", "image", "deployment/exp-web", "nginx=nginx:1.26-alpine", "--namespace", self.namespace]
        elif scenario == "C":
            args = ["patch", "configmap/exp-web-config", "--namespace", self.namespace, "--type", "merge", "--patch", '{"data":{"LOG_LEVEL":"debug"}}']
        elif scenario == "D":
            args = ["delete", "deployment/exp-web", "--namespace", self.namespace, "--wait=false"]
        elif scenario == "E":
            patch = '{"spec":{"template":{"spec":{"containers":[{"name":"nginx","resources":{"limits":{"cpu":"500m"}}}]}}}}'
            args = ["patch", "deployment/exp-web", "--namespace", self.namespace, "--type", "strategic", "--patch", patch]
        elif scenario == "G":
            args = ["patch", "secret/exp-web-secret", "--namespace", self.namespace, "--type", "merge", "--patch", '{"data":{"password":"ZHJpZnQtZ2l0b3Bz"}}']
        else:
            raise ApparatusError("scenario_invalid")
        output = self._run("kubectl", [*args, "-o", "json"])
        accepted_at = time.monotonic()
        try:
            objects = [json.loads(output)] if output.strip() else self._read_inventory()
            if scenario == "D":
                accepted = not output.strip() and not any(
                    obj.get("kind") == "Deployment" and obj.get("metadata", {}).get("name") == "exp-web"
                    for obj in objects)
                accepted = accepted or any(obj.get("kind") == "Deployment" and
                                          obj.get("metadata", {}).get("name") == "exp-web" and
                                          obj.get("metadata", {}).get("namespace", self.namespace) == self.namespace and
                                          obj.get("metadata", {}).get("deletionTimestamp")
                                          for obj in objects)
            else:
                kind, name, path, value = {
                    "A": ("Deployment", "exp-web", ("spec", "replicas"), 5),
                    "B": ("Deployment", "exp-web", ("spec", "template", "spec", "containers", 0, "image"), "nginx:1.26-alpine"),
                    "C": ("ConfigMap", "exp-web-config", ("data", "LOG_LEVEL"), "debug"),
                    "E": ("Deployment", "exp-web", ("spec", "template", "spec", "containers", 0, "resources", "limits", "cpu"), "500m"),
                    "G": ("Secret", "exp-web-secret", ("data", "password"), "ZHJpZnQtZ2l0b3Bz"),
                }[scenario]
                accepted = any(obj.get("kind") == kind and
                               obj.get("metadata", {}).get("name") == name and
                               obj.get("metadata", {}).get("namespace", self.namespace) == self.namespace and
                               _path_value(obj, path) == (True, value) for obj in objects)
        except (ValueError, TypeError, AttributeError, ApparatusError):
            accepted = False
        if not accepted:
            raise ApparatusError("injection_acceptance_unverified", accepted_at)
        return accepted_at

    def mechanism_evidence(self, expected):
        if self.env == "manual":
            return self.mechanism_signal(expected)
        # Controller status alone does not expose the differing field. A live
        # ArgoCD evidence adapter must be validated before this endpoint is used.
        return None

    def apply_baseline(self, expected, differences):
        if not differences:
            raise ApparatusError("correction_has_no_observed_differences")
        manifest = ROOT / "experiments" / "subjects" / self.subject / "manifests.yaml"
        try:
            content = manifest.read_text(encoding="utf-8")
        except OSError as exc:
            raise ApparatusError("baseline_manifest_unavailable") from exc
        if "EXP_NS" not in content:
            raise ApparatusError("baseline_manifest_invalid")
        self._run("kubectl", ["apply", "--namespace", self.namespace, "-f", "-"], content.replace("EXP_NS", self.namespace))


def respond(adapter, expected, differences):
    """Apply declarations to observed differences without scenario metadata."""
    adapter.apply_baseline(expected, differences)


def _timestamp_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _empty_record(run_id, phase, subject, env, scenario, rep, timeout_s, poll_interval_s, started_at_utc):
    return {
        "schema_version": 2,
        "run_id": run_id,
        "phase": phase,
        "subject": subject,
        "env": env,
        "scenario": scenario,
        "rep": rep,
        "status": "instrumentation_failed",
        "reason": None,
        "started_at_utc": started_at_utc,
        "t0_mono_s": None,
        "ta_mono_s": None,
        "td_mono_s": None,
        "te_mono_s": None,
        "tr_mono_s": None,
        "timeout_s": timeout_s,
        "poll_interval_s": poll_interval_s,
        "detection_status": "not_evaluable",
        "evidence_status": "not_evaluable",
        "recovery_status": "not_evaluable",
        "r1_baseline_pct": None,
        "r1_post_pct": None,
        "r1_recovered_pct": None,
        "healthy_baseline": None,
        "healthy_final": None,
        "evidence": [],
    }


def run_experiment(adapter, subject, env, scenario, rep=1, phase="fixture", timeout_s=600.0,
                   poll_interval_s=1.0, run_id=None, clock=time.monotonic, utc_now=_timestamp_utc):
    if (subject not in ("s1", "s2") or env not in ("manual", "gitops")
            or scenario not in tuple("ABCDEFG") or phase not in ("fixture", "pilot")):
        raise ApparatusError("run_parameters_invalid")
    if not isinstance(rep, int) or isinstance(rep, bool) or rep < 1:
        raise ApparatusError("rep_must_be_positive_integer")
    if not math.isfinite(timeout_s) or timeout_s <= 0 or not math.isfinite(poll_interval_s) or poll_interval_s <= 0:
        raise ApparatusError("timing_parameters_invalid")

    started_at = utc_now()
    record = _empty_record(run_id or str(uuid.uuid4()), phase, subject, env, scenario, rep,
                           float(timeout_s), float(poll_interval_s), started_at)
    expected = expected_inventory(subject)
    try:
        baseline = adapter.snapshot()
        baseline_score, _ = compare_inventory(expected, baseline.objects)
        record["r1_baseline_pct"] = baseline_score
        record["healthy_baseline"] = baseline.healthy
        reason = _baseline_failure(baseline_score, baseline)
        if reason:
            record["status"], record["reason"] = "baseline_failed", reason
            return record
        baseline_signal = adapter.mechanism_signal(expected)
        if bool(baseline_signal):
            record["status"], record["reason"] = "baseline_failed", "baseline_mechanism_signal_present"
            return record
    except ApparatusError as exc:
        record["reason"] = exc.code
        return record
    except Exception:
        record["reason"] = "instrumentation_failed"
        return record

    state_lock = threading.Lock()
    injection = {"done": False, "error": None}
    correction = {"started": False, "done": False, "error": None, "completed_at": None}

    def inject_worker():
        try:
            accepted_at = adapter.inject(scenario)
            if isinstance(accepted_at, bool) or not isinstance(accepted_at, (int, float)) or not math.isfinite(accepted_at):
                raise ApparatusError("injection_acceptance_unverified")
        except ApparatusError as exc:
            error = exc.code
            accepted_at = exc.accepted_at
        except Exception:
            error = "injection_failed"
            accepted_at = None
        else:
            error = None
        with state_lock:
            injection["error"] = error
            injection["ack_at"] = accepted_at
            injection["done"] = True

    def correct_worker(differences):
        try:
            respond(adapter, expected, differences)
        except ApparatusError as exc:
            error = exc.code
        except Exception:
            error = "correction_failed"
        else:
            error = None
        with state_lock:
            correction["error"] = error
            correction["completed_at"] = clock() if error is None else None
            correction["done"] = True

    record["t0_mono_s"] = clock()
    deadline = record["t0_mono_s"] + timeout_s
    inject_thread = threading.Thread(target=inject_worker, name="apparatus-injection", daemon=True)
    inject_thread.start()
    correction_thread = None
    first_equal = None
    cutoff_reached = False
    instrumentation_error = None
    correction_error = None
    evidence_keys = set()
    evidence_available = True

    while True:
        with state_lock:
            injection_done = injection["done"]
            injection_error = injection["error"]
            ack_at = injection.get("ack_at")
            correction_done = correction["done"]
            correction_error = correction["error"]
            correction_completed_at = correction["completed_at"]
        if injection_done and injection_error:
            break
        if correction_done and correction_error:
            break
        try:
            observation = adapter.snapshot()
            score, differences = compare_inventory(expected, observation.objects)
            signal = adapter.mechanism_signal(expected)
            mechanism_evidence = adapter.mechanism_evidence(expected)
            evidence_available = mechanism_evidence is not None
        except ApparatusError as exc:
            instrumentation_error = exc.code
            break
        except Exception:
            instrumentation_error = "instrumentation_failed"
            break

        observed_at = clock()
        if observed_at <= deadline:
            record["healthy_final"] = observation.healthy
            if differences and record["r1_post_pct"] is None:
                record["r1_post_pct"] = score
            for item in mechanism_evidence or []:
                key = (item["resource"], tuple(item["field_paths"]), item["source"])
                if key not in evidence_keys:
                    evidence_keys.add(key)
                    record["evidence"].append({
                        **item,
                        "observed_at_mono_s": observed_at,
                    })
                    if record["te_mono_s"] is None:
                        record["te_mono_s"] = observed_at

            detected = bool(signal)
            if detected and record["td_mono_s"] is None:
                record["td_mono_s"] = observed_at

            with state_lock:
                injection_done = injection["done"]
                injection_error = injection["error"]
                ack_at = injection.get("ack_at")
                correction_done = correction["done"]
                correction_error = correction["error"]
                correction_completed_at = correction["completed_at"]
                correction_started = correction["started"]

            if (record["td_mono_s"] is not None and injection_done and not injection_error
                    and env == "manual" and scenario != "F" and not correction_started):
                response_differences = signal if isinstance(signal, list) else differences
                if response_differences:
                    with state_lock:
                        correction["started"] = True
                    correction_thread = threading.Thread(
                        target=correct_worker,
                        args=(list(response_differences),),
                        name="apparatus-responder",
                        daemon=True,
                    )
                    correction_thread.start()
            response_ready = injection_done and not injection_error and (
                env == "gitops" or (correction_done and not correction_error)
            )
            if response_ready and ack_at is not None and scenario != "F" and observed_at >= ack_at:
                if score == 100.0:
                    if first_equal is None:
                        first_equal = (observed_at, score)
                    else:
                        if record["tr_mono_s"] is None:
                            record["tr_mono_s"] = first_equal[0]
                            record["r1_recovered_pct"] = first_equal[1]
                        record["healthy_final"] = observation.healthy
                else:
                    first_equal = None

            if all(record[name] is not None for name in ("td_mono_s", "te_mono_s", "tr_mono_s")):
                break

        if clock() >= deadline:
            cutoff_reached = True
            break
        time.sleep(min(poll_interval_s, max(0.0, deadline - clock())))

    inject_thread.join(timeout=SUBPROCESS_TIMEOUT_S + 0.1)
    if correction_thread is not None:
        correction_thread.join(timeout=SUBPROCESS_TIMEOUT_S + 0.1)
    with state_lock:
        injection_done = injection["done"]
        injection_error = injection["error"]
        ack_at = injection.get("ack_at")
        correction_done = correction["done"]
        correction_error = correction["error"]

    if ack_at is not None:
        record["ta_mono_s"] = ack_at

    if not injection_done:
        injection_error = "injection_ack_not_observed"
    if not correction_done and correction.get("started"):
        correction_error = None
    if injection_error:
        record["status"], record["reason"] = "injection_failed", injection_error
    elif instrumentation_error:
        record["status"], record["reason"] = "instrumentation_failed", instrumentation_error
    elif correction_error:
        record["status"], record["reason"] = "correction_failed", correction_error
        record["tr_mono_s"] = None
        record["r1_recovered_pct"] = None
    elif not evidence_available and scenario != "F":
        record["status"], record["reason"] = "instrumentation_failed", "mechanism_evidence_unavailable"
    elif scenario == "F" and cutoff_reached:
        record["status"], record["reason"] = "complete", "scenario_f_visibility_boundary"
    elif all(record[name] is not None for name in ("td_mono_s", "te_mono_s", "tr_mono_s")):
        record["status"], record["reason"] = "complete", None
    else:
        record["status"], record["reason"] = "timeout", "endpoint_cutoff_reached"

    if record["td_mono_s"] is not None:
        record["detection_status"] = "observed"
    elif cutoff_reached and not instrumentation_error and not injection_error and not correction_error:
        record["detection_status"] = "right_censored"
    if record["te_mono_s"] is not None:
        record["evidence_status"] = "observed"
    elif cutoff_reached and evidence_available and not instrumentation_error and not injection_error and not correction_error:
        record["evidence_status"] = "right_censored"
    if scenario == "F" or injection_error or correction_error:
        record["recovery_status"] = "not_evaluable"
    elif record["tr_mono_s"] is not None:
        record["recovery_status"] = "observed"
    elif instrumentation_error:
        record["recovery_status"] = "not_evaluable"
    elif cutoff_reached:
        record["recovery_status"] = "right_censored"
    if injection_error:
        for name in ("td_mono_s", "te_mono_s", "tr_mono_s"):
            record[name] = None
        for name in ("detection_status", "evidence_status", "recovery_status"):
            record[name] = "not_evaluable"
        record["evidence"] = []
        record["r1_recovered_pct"] = None
    return record


def _allowed_list(name):
    return {item.strip() for item in os.environ.get(name, "").split(",") if item.strip()}


def _allowed_targets():
    targets = set()
    for item in os.environ.get("APPARATUS_PILOT_TARGETS", "").split(","):
        parts = tuple(part.strip() for part in item.split("|"))
        if len(parts) == 3 and all(parts):
            targets.add(parts)
    return targets


def _write_summary(path, data):
    try:
        with Path(path).open("x", encoding="utf-8") as output:
            output.write(data)
    except FileExistsError as exc:
        raise ApparatusError("output_already_exists") from exc


def _validate_cli(args):
    if args.subject not in ("s1", "s2") or args.env not in ("manual", "gitops"):
        raise ApparatusError("subject_or_environment_invalid")
    expected_namespace = PILOT_NAMESPACES[(args.subject, args.env)]
    if args.namespace and args.namespace != expected_namespace:
        raise ApparatusError("namespace_subject_environment_mismatch")
    args.namespace = expected_namespace
    if args.scenario is not None and args.scenario not in tuple("ABCDEFG"):
        raise ApparatusError("one_scenario_A_to_G_required")
    if args.rep < 1:
        raise ApparatusError("rep_must_be_positive_integer")
    if args.phase == "formal":
        raise ApparatusError("formal_execution_not_supported")
    if args.live:
        if args.phase != "pilot":
            raise ApparatusError("live_phase_must_be_pilot")
        if args.scenario is None:
            raise ApparatusError("one_scenario_required")
        if args.scenario == "F":
            raise ApparatusError("scenario_f_requires_separate_boundary_approval")
        if not args.context or args.context not in _allowed_list("APPARATUS_PILOT_CONTEXTS"):
            raise ApparatusError("pilot_context_not_allowlisted")
        if args.env == "gitops":
            if not args.app or (args.context, args.namespace, args.app) not in _allowed_targets():
                raise ApparatusError("pilot_target_not_allowlisted")
            raise ApparatusError("gitops_evidence_transport_not_validated")
        elif args.app:
            raise ApparatusError("app_not_allowed_for_manual_environment")
        elif (args.context, args.namespace, "manual") not in _allowed_targets():
            raise ApparatusError("pilot_target_not_allowlisted")
        if (not math.isfinite(args.timeout_s) or not math.isfinite(args.poll_interval_s)
                or args.timeout_s <= 0 or args.poll_interval_s <= 0):
            raise ApparatusError("timing_parameters_invalid")
        if args.timeout_s < SUBPROCESS_TIMEOUT_S:
            raise ApparatusError("pilot_timeout_below_command_bound")


def main(argv=None):
    parser = argparse.ArgumentParser(description="One-run offline-testable Kubernetes experiment apparatus")
    parser.add_argument("--live", action="store_true", help="execute one allowlisted pilot run")
    parser.add_argument("--phase", choices=("fixture", "pilot", "formal"), default="fixture")
    parser.add_argument("--subject", default="s1")
    parser.add_argument("--env", choices=("manual", "gitops"), default="manual")
    parser.add_argument("--scenario", choices=tuple("ABCDEFG"))
    parser.add_argument("--rep", type=int, default=1)
    parser.add_argument("--namespace")
    parser.add_argument("--context")
    parser.add_argument("--app")
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--poll-interval-s", type=float, default=1.0)
    parser.add_argument("--output", help="JSON output path; default is stdout")
    args = parser.parse_args(argv)
    try:
        _validate_cli(args)
        if not args.live:
            print("[DRY-RUN] one run subject={} env={} namespace={} scenario={} phase={}".format(
                args.subject, args.env, args.namespace, args.scenario or "<required-for-run>", args.phase))
            print("[DRY-RUN] no clients executed; no records written. Use --live --phase pilot with explicit allowlists.")
            return 0
        if args.output and Path(args.output).exists():
            raise ApparatusError("output_already_exists")
        adapter = SubprocessAdapter(args.subject, args.env, args.namespace, args.context, args.app)
        record = run_experiment(adapter, args.subject, args.env, args.scenario, args.rep, "pilot",
                                args.timeout_s, args.poll_interval_s)
        data = json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
        if args.output:
            _write_summary(args.output, data)
        else:
            sys.stdout.write(data)
        return 0 if record["status"] == "complete" else 1
    except ApparatusError as exc:
        print("ERROR: {}".format(exc.code), file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("ERROR: output_or_input_failure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
