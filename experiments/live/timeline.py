"""Detection, evidence, recovery, and censoring timeline analysis."""

from __future__ import annotations

import math
from typing import Any, cast

if __package__:
    from . import contract as _contract
else:  # direct script execution
    import contract as _contract  # type: ignore[no-redef]

if __package__:
    from . import model as _model
else:  # direct script execution
    import model as _model  # type: ignore[no-redef]

DEFAULT_APP = _model.DEFAULT_APP
TIMING_CONVENTION = _model.TIMING_CONVENTION
WEB_DEPLOYMENT = _model.WEB_DEPLOYMENT
WEB_HPA = _model.WEB_HPA
Contract = _model.Contract
ImperativeRun = _model.ImperativeRun
Injection = _model.Injection
InstrumentationError = _model.InstrumentationError
Observation = _model.Observation
Point = _model.Point

argo_signal = _contract.argo_signal
field_diffs = _contract.field_diffs
hpa_changed = _contract.hpa_changed
hpa_settled = _contract.hpa_settled
resource_results = _contract.resource_results
score = _contract.score


def _metric_status(value: object, stop_reason: str) -> str:
    if value is not None:
        return "observed"
    return "right_censored" if stop_reason == "timeout" else "unobserved_before_stop"


def _finite_mono(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(cast(float, value))


def _validate_acquisition(observation: Observation) -> dict:
    acquisition = observation.acquisition
    if not isinstance(acquisition, dict):
        raise InstrumentationError("observation has no acquisition bounds")
    started = acquisition.get("started_mono")
    finished = acquisition.get("finished_mono")
    if not _finite_mono(started) or not _finite_mono(finished):
        raise InstrumentationError("capture bounds are not finite")
    started = cast(float, started)
    finished = cast(float, finished)
    if started > finished:
        raise InstrumentationError("capture bounds are not ordered")
    reads = acquisition.get("reads")
    if not isinstance(reads, dict) or not reads:
        raise InstrumentationError("observation has no read bounds")
    for key, record in reads.items():
        if not isinstance(record, dict):
            raise InstrumentationError(f"read bounds for {key} are not an object")
        read_started = record.get("started_mono")
        read_finished = record.get("finished_mono")
        if not _finite_mono(read_started) or not _finite_mono(read_finished):
            raise InstrumentationError(f"read bounds for {key} are not finite")
        read_started = cast(float, read_started)
        read_finished = cast(float, read_finished)
        if read_started > read_finished:
            raise InstrumentationError(f"read bounds for {key} are not ordered")
        if read_started < started or read_finished > finished:
            raise InstrumentationError(f"read bounds for {key} fall outside the capture")
        if type(record.get("ok")) is not bool:
            raise InstrumentationError(f"read outcome for {key} is not boolean")
    return acquisition


def _read(sample: Observation, key: str) -> dict | None:
    reads = sample.acquisition.get("reads") or {}
    record = reads.get(key)
    return record if isinstance(record, dict) else None


def _read_eligible(sample: Observation, key: str, t0: float, deadline: float) -> bool:
    record = _read(sample, key)
    if record is None or record.get("ok") is not True:
        return False
    return record["started_mono"] >= t0 and record["finished_mono"] <= deadline


def _reads_eligible(sample: Observation, keys: list, t0: float, deadline: float) -> bool:
    return all(_read_eligible(sample, key, t0, deadline) for key in keys)


def _read_completion(sample: Observation, keys: list) -> Point:
    latest = max(
        (cast(dict, _read(sample, key)) for key in keys),
        key=lambda record: record["finished_mono"],
    )
    return Point(latest["finished_mono"], latest["finished_utc"])


def _complete_match_completion(sample: Observation, keys: list) -> Point | None:
    records = [_read(sample, key) for key in keys]
    if not records or any(record is None or record.get("ok") is not True for record in records):
        return None
    latest = max(cast(list[dict], records), key=lambda record: record["finished_mono"])
    return Point(latest["finished_mono"], latest["finished_utc"])


def _diff_keys(contract: Contract, sample: Observation) -> list:
    return sorted({diff["resource"] for diff in field_diffs(contract, sample)})


def _r1_keys(contract: Contract) -> list:
    return [resource["id"] for resource in contract.resources]


def _hpa_keys() -> list:
    return ["Deployment/" + WEB_DEPLOYMENT, "HorizontalPodAutoscaler/" + WEB_HPA]


def _recovery_keys(contract: Contract, scenario: str, sample: Observation) -> list:
    keys = _r1_keys(contract)
    if scenario == "A":
        keys = list(dict.fromkeys(keys + _hpa_keys()))
    elif scenario == "F":
        keys.append("Namespace/" + contract.quarantine_namespace)
        if sample.extra_resources:
            keys.append(f"{contract.quarantine_namespace}/Deployment/" + WEB_DEPLOYMENT)
    return keys


def _post_injection(sample: Observation, t0: float) -> bool:
    acquisition = sample.acquisition
    return acquisition["finished_mono"] >= t0


def _imperative_event_keys(
    contract: Contract, sample: Observation, event: Point, t0: float, deadline: float
) -> list | None:
    if event is None or not _finite_mono(event.mono):
        return None
    if event.mono < t0 or event.mono > deadline:
        return None
    keys = _diff_keys(contract, sample)
    if not keys or not _reads_eligible(sample, keys, t0, deadline):
        return None
    if _read_completion(sample, keys).mono > event.mono:
        return None
    return keys


def _evaluation_keys(contract: Contract, sample: Observation, scenario: str) -> list | None:
    if sample.evaluated_signal is not True:
        return None
    if scenario == "A":
        return _hpa_keys()
    keys = list(sample.evaluated_reads or [])
    if not keys:
        return None
    if not set(keys).issubset(set(_diff_keys(contract, sample))):
        return None
    return keys


def _evaluation_evidence(
    post: list,
    contract: Contract,
    scenario: str,
    t0: float,
    deadline: float,
    evidence_at: Point | None = None,
) -> tuple[Point | None, list]:
    for sample in post:
        keys = _evaluation_keys(contract, sample, scenario)
        if keys is None:
            continue
        if not _reads_eligible(sample, keys, t0, deadline):
            continue
        event = sample.evaluated_at
        if event is not None:
            if not _finite_mono(event.mono):
                continue
            if event.mono < t0 or event.mono > deadline:
                continue
            if any(cast(dict, _read(sample, key))["finished_mono"] > event.mono for key in keys):
                continue
        if evidence_at is not None:
            if event is not None and not math.isclose(
                event.mono, evidence_at.mono, rel_tol=1e-9, abs_tol=1e-9
            ):
                raise InstrumentationError("evidence evaluation disagrees with the persisted event")
            event = evidence_at
        if event is None or not _finite_mono(event.mono):
            continue
        if event.mono < t0 or event.mono > deadline:
            continue
        if any(cast(dict, _read(sample, key))["finished_mono"] > event.mono for key in keys):
            continue
        return event, keys
    return None, []


def _recovered(contract: Contract, observation: Observation, scenario: str) -> bool:
    if score(contract, observation) != 100:
        return False
    if scenario == "A":
        return hpa_settled(observation.hpa)
    if scenario == "F":
        return not observation.extra_resources
    return True


def analyze_timeline(
    contract: Contract,
    samples: list,
    injection: Injection,
    arm: str,
    scenario: str,
    timeout: float,
    imperative: ImperativeRun | None = None,
    evidence_at: Point | None = None,
    provided_evidence_ref: str | None = None,
    app: str = DEFAULT_APP,
    baseline: Observation | None = None,
    window_completed: bool | None = None,
    window_end: Point | None = None,
) -> dict:
    """Derive detection, evidence, recovery, and censoring from samples."""
    samples = sorted(samples, key=lambda item: item.at.mono)
    for sample in samples:
        _validate_acquisition(sample)
    t0 = injection.started.mono
    deadline = t0 + timeout
    post = [sample for sample in samples if _post_injection(sample, t0)]
    detection: Point | None = None
    evidence: Point | None = None
    recovery: Point | None = None
    recovery_pair: tuple[Point, Point] | None = None
    detection_reads: list[str] = []
    evidence_reads: list[str] = []
    recovery_reads: list[str] = []
    t_r_first: Point | None = None
    t_r_confirmed: Point | None = None
    confirmation = "none"
    argo_seen = False

    if injection.accepted:
        for sample in post:
            if scenario in "BCDEFG":
                state = sample.argo.get(app)
                if (
                    state
                    and argo_signal(state)
                    and _read_eligible(sample, "Application/" + app, t0, deadline)
                ):
                    argo_seen = True
            if (
                detection is None
                and scenario == "A"
                and hpa_changed(contract.baseline_hpa, sample.hpa)
            ):
                keys = _hpa_keys()
                if _reads_eligible(sample, keys, t0, deadline):
                    detection = _read_completion(sample, keys)
                    detection_reads = keys
            if (
                detection is None
                and arm == "gitops"
                and scenario in "BCDEFG"
                and argo_signal(sample.argo.get(app))
            ):
                key = "Application/" + app
                if _read_eligible(sample, key, t0, deadline):
                    detection = _read_completion(sample, [key])
                    detection_reads = [key]

        if not (imperative and scenario in "BCDEFG"):
            evidence, evidence_reads = _evaluation_evidence(
                post, contract, scenario, t0, deadline, evidence_at
            )

        if imperative and scenario in "BCDEFG":
            for sample in post:
                if imperative.detection_at is not None:
                    detection_keys = _imperative_event_keys(
                        contract, sample, imperative.detection_at, t0, deadline
                    )
                    if detection_keys:
                        detection = imperative.detection_at
                        detection_reads = detection_keys
                        break
            for sample in post:
                if imperative.evidence_at is not None:
                    evidence_keys = _imperative_event_keys(
                        contract, sample, imperative.evidence_at, t0, deadline
                    )
                    if evidence_keys:
                        evidence = imperative.evidence_at
                        evidence_reads = evidence_keys
                        break

        previous_match: Point | None = None
        first_match: Point | None = None
        late_match = False
        for sample in post:
            keys = _recovery_keys(contract, scenario, sample)
            eligible = _reads_eligible(sample, keys, t0, deadline)
            match = _recovered(contract, sample, scenario)
            if not match:
                previous_match = None
                continue
            completion = _complete_match_completion(sample, keys)
            if completion is not None and completion.mono > deadline:
                late_match = True
            if not eligible:
                previous_match = None
                continue
            completion = _read_completion(sample, keys)
            if first_match is None:
                first_match = completion
            if previous_match is not None:
                recovery_pair = (previous_match, completion)
                recovery = previous_match
                t_r_first = previous_match
                t_r_confirmed = completion
                recovery_reads = keys
                confirmation = "confirmed"
                break
            previous_match = completion
        if recovery is None and first_match is not None:
            t_r_first = first_match
            confirmation = "late_confirmation" if late_match else "missing_confirmation"

    if scenario == "A":
        detection_ref = "hpa:invenio-web-hpa" if detection else None
    elif arm == "imperative":
        detection_ref = "imperative:contract-diff" if detection else None
    else:
        detection_ref = "argo:invenio-bootstrap" if detection else None
    evidence_ref = None
    if evidence is not None:
        if imperative and scenario in "BCDEFG" and imperative.evidence_ref:
            evidence_ref = imperative.evidence_ref
        elif scenario == "A":
            evidence_ref = "samples.jsonl"
        elif provided_evidence_ref:
            evidence_ref = provided_evidence_ref
    stop_reason = "recovery" if recovery is not None else "timeout"
    if not injection.accepted:
        status = "invalid_injection"
    elif imperative and (
        imperative.failed or any(not command.ok for command in imperative.commands)
    ):
        status = "recovery_failure"
    elif recovery is not None:
        status = "observed"
    else:
        status = "right_censored"

    if scenario == "A":
        detection_controller = "hpa"
        recovery_controller = "hpa" if recovery is not None else "unattributed"
    elif arm == "imperative":
        detection_controller = "imperative" if detection else "unattributed"
        recovery_controller = (
            "imperative"
            if any(command.ok for command in (imperative.commands if imperative else []))
            else "unattributed"
        )
    else:
        detection_controller = "argocd" if detection else "unattributed"
        recovery_controller = "argocd" if argo_seen and recovery else "unattributed"

    def duration(at: Point | None) -> float | None:
        return None if at is None else at.mono - t0

    r1_keys = _r1_keys(contract)
    eligible_r1 = [sample for sample in post if _reads_eligible(sample, r1_keys, t0, deadline)]
    r1_first = eligible_r1[0] if eligible_r1 else None
    r1_last = eligible_r1[-1] if eligible_r1 else None
    if not post:
        r1_reason = "no_samples"
    elif not eligible_r1:
        r1_reason = "no_eligible_capture"
    else:
        r1_reason = None

    gaps = [right.at.mono - left.at.mono for left, right in zip(samples, samples[1:])]
    observation_end = None
    if samples:
        acquisition = samples[-1].acquisition
        observation_end = Point(acquisition["finished_mono"], acquisition["finished_utc"])
    return {
        "schema_version": 2,
        "timing_convention": TIMING_CONVENTION,
        "status": status,
        "stop_reason": stop_reason,
        "window_completed": (True if recovery is not None else window_completed),
        "window_end": window_end,
        "detection_seconds": duration(detection),
        "evidence_seconds": duration(evidence),
        "recovery_seconds": duration(recovery),
        "detection_status": _metric_status(detection, stop_reason),
        "evidence_status": _metric_status(evidence, stop_reason),
        "recovery_status": _metric_status(recovery, stop_reason),
        "injection_seconds": injection.acknowledged.mono - t0,
        "censor_seconds": timeout,
        "max_sample_gap_seconds": max(gaps) if gaps else None,
        "observation_end": observation_end,
        "detection_controller": detection_controller,
        "recovery_controller": recovery_controller,
        "detection_ref": detection_ref,
        "evidence_ref": evidence_ref,
        "detection_reads": detection_reads,
        "evidence_reads": evidence_reads,
        "recovery_reads": recovery_reads,
        "t_r_first_seconds": duration(t_r_first),
        "t_r_confirmed_seconds": duration(t_r_confirmed),
        "recovery_confirmation": confirmation,
        "r1_baseline": (score(contract, baseline) if baseline is not None else None),
        "r1_first": score(contract, r1_first) if r1_first else None,
        "r1_last": score(contract, r1_last) if r1_last else None,
        "r1_baseline_details": (
            resource_results(contract, baseline) if baseline is not None else None
        ),
        "r1_first_details": (
            resource_results(contract, r1_first) if r1_first is not None else None
        ),
        "r1_last_details": (resource_results(contract, r1_last) if r1_last is not None else None),
        "r1_baseline_reason": (None if baseline is not None else "baseline_not_observed"),
        "r1_first_reason": r1_reason,
        "r1_last_reason": r1_reason,
        "kubectl_cmds": len(imperative.commands) if imperative else 0,
        "analysis_group": (
            "hpa_control"
            if scenario == "A"
            else "visibility_boundary"
            if scenario == "F"
            else "managed_drift"
        ),
        "efficacy_eligible": scenario not in ("A", "F"),
        "t0": injection.started,
        "t_a": injection.acknowledged,
        "t_d": detection,
        "t_e": evidence,
        "t_r": recovery,
        "t_r_first": t_r_first,
        "t_r_confirmed": t_r_confirmed,
        "t_e_store": (
            imperative.evidence_store_at if imperative and evidence is not None else None
        ),
        "recovery_pair": recovery_pair,
        "samples": len(samples),
    }


__all__ = [
    "_complete_match_completion",
    "_diff_keys",
    "_evaluation_evidence",
    "_evaluation_keys",
    "_finite_mono",
    "_hpa_keys",
    "_imperative_event_keys",
    "_metric_status",
    "_post_injection",
    "_r1_keys",
    "_read",
    "_read_completion",
    "_read_eligible",
    "_reads_eligible",
    "_recovered",
    "_recovery_keys",
    "_validate_acquisition",
    "analyze_timeline",
]
