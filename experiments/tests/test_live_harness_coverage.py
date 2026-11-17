"""Coverage-focused harness tests; every cluster interaction is an in-memory fake."""

import argparse
import copy
import email.message
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib import error as urlerror
from urllib import request as urlrequest

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live"
sys.path.insert(0, str(LIVE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402
from test_live_harness import (  # noqa: E402
    AdvancingClock,
    DeterministicSampler,
    FakeKubectl,
    application,
    contract,
    declaration,
    injection,
    node_reading,
    observation,
    point,
    result,
    sealed_secret,
    web_configmap,
    web_deployment,
    web_hpa,
    web_service,
    write_render,
)


class _Response:
    def __init__(self, body):
        self.status = 200
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Opener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def open(self, request, timeout=None):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _SequenceHttp:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, path, accept=None):
        return self.responses.pop(0)


class _RecordingKubectl:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get(self, kind, name=None, namespace=None, selector=None):
        self.calls.append((kind, name, namespace, selector))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.payload)

    def run(self, argv, input_text=None, mutating=False, timeout=None):
        self.calls.append((argv, input_text, mutating, timeout))
        return result(argv=list(argv))


class HarnessUtilityCoverageTests(unittest.TestCase):
    def test_real_clock_points_and_http_repr(self):
        now = harness.Clock().now()
        self.assertIsInstance(now, harness.Point)
        self.assertIsInstance(now.mono, float)
        self.assertEqual(repr(harness.Http("tok")), "Http(token=<redacted>)")

    def test_quarantine_rejects_names_that_exceed_the_label_limit(self):
        with self.assertRaises(harness.SafetyError):
            harness.quarantine_namespace("exp-" + "a" * 50)

    def test_redirect_handler_drops_auth_only_across_hosts(self):
        handler = harness._CrossHostRedirectHandler()
        headers = email.message.Message()
        same = urlrequest.Request(
            "https://a.example/x",
            headers={"Authorization": "Bearer t", "Accept": "json"},
        )
        redirected = handler.redirect_request(
            same, io.BytesIO(), 302, "Found", headers, "https://a.example/y"
        )
        self.assertIsNotNone(redirected)
        self.assertIn("Authorization", redirected.headers)
        cross = urlrequest.Request(
            "https://a.example/x",
            headers={"Authorization": "Bearer t", "Accept": "json"},
        )
        redirected = handler.redirect_request(
            cross, io.BytesIO(), 302, "Found", headers, "https://b.example/y"
        )
        self.assertIsNotNone(redirected)
        self.assertNotIn("Authorization", redirected.headers)
        self.assertNotIn("Accept", redirected.headers)

    def test_http_get_retries_transient_errors_then_succeeds(self):
        http = harness.Http("tok")
        error = urlerror.HTTPError("https://x", 503, "err", {}, io.BytesIO(b"down"))
        http._opener = _Opener([error, _Response(b"ok")])
        with mock.patch.object(harness.time, "sleep") as sleep:
            self.assertEqual(http.get("/api"), (200, b"ok"))
        sleep.assert_called_once()

    def test_http_get_returns_the_last_transient_error_body(self):
        http = harness.Http("tok")
        errors = [
            urlerror.HTTPError("https://x", 503, "err", {}, io.BytesIO(b"down"))
            for _ in range(harness.HTTP_RETRY_ATTEMPTS)
        ]
        http._opener = _Opener(errors)
        with mock.patch.object(harness.time, "sleep"):
            self.assertEqual(http.get("/api"), (503, b"down"))

    def test_http_get_fails_closed_for_transport_errors(self):
        http = harness.Http("tok")
        http._opener = _Opener(
            [urlerror.URLError("down") for _ in range(harness.HTTP_RETRY_ATTEMPTS)]
        )
        with mock.patch.object(harness.time, "sleep"), self.assertRaises(harness.HarnessError):
            http.get("/api")
        http._opener = _Opener([OSError("boom")])
        with self.assertRaises(harness.HarnessError):
            http.get("/api")

    def test_sanitize_object_removes_each_sensitive_shape(self):
        app = application()
        self.assertEqual(harness.sanitize_object(app)["name"], "invenio-bootstrap")
        configmap = web_configmap()
        configmap["binaryData"] = {"blob": "x"}
        self.assertNotIn("binaryData", harness.sanitize_object(configmap))
        deployment = web_deployment()
        deployment["spec"]["template"]["metadata"] = {"creationTimestamp": "now"}
        self.assertNotIn(
            "creationTimestamp",
            harness.sanitize_object(deployment)["spec"]["template"]["metadata"],
        )
        secret = {
            "kind": "Secret",
            "metadata": {"name": "s"},
            "data": {"x": "eA=="},
            "stringData": {"y": "z"},
        }
        sanitized = harness.sanitize_object(secret)
        self.assertNotIn("data", sanitized)
        self.assertNotIn("stringData", sanitized)

    def test_observation_rejects_duplicates_and_skips_non_objects(self):
        with self.assertRaises(harness.InstrumentationError):
            harness.observation_from_objects([web_deployment(), web_deployment()], at=point(0))
        observed = harness.observation_from_objects(
            ["ignored", {}, web_deployment()], at=point(0), extras=["x"]
        )
        self.assertEqual(observed.extra_resources, ["x"])
        self.assertEqual(len(observed.resources), 1)

    def test_build_contract_rejects_each_invalid_identity(self):
        observed = observation()
        with self.assertRaises(harness.InstrumentationError):
            harness.build_contract(object(), observed, "invenio", "exp-invenio-drift")
        good = declaration()
        bad_revision = harness.Declaration(
            source_revision="short",
            render_sha256=good.render_sha256,
            configmap_name=good.configmap_name,
            resources=good.resources,
        )
        with self.assertRaisesRegex(harness.InstrumentationError, "source revision"):
            harness.build_contract(bad_revision, observed, "invenio", "exp-invenio-drift")
        bad_digest = harness.Declaration(
            source_revision=good.source_revision,
            render_sha256="short",
            configmap_name=good.configmap_name,
            resources=good.resources,
        )
        with self.assertRaisesRegex(harness.InstrumentationError, "render SHA-256"):
            harness.build_contract(bad_digest, observed, "invenio", "exp-invenio-drift")
        mismatched = observation(argo={"invenio-bootstrap": {"revision": "c" * 40}})
        with self.assertRaisesRegex(harness.InstrumentationError, "observed Argo"):
            harness.build_contract(good, mismatched, "invenio", "exp-invenio-drift")
        foreign = harness.Declaration(
            source_revision=good.source_revision,
            render_sha256=good.render_sha256,
            configmap_name=good.configmap_name,
            resources=(dict(good.resources[0], namespace="other"),),
        )
        with self.assertRaisesRegex(harness.InstrumentationError, "not in namespace"):
            harness.build_contract(foreign, observed, "invenio", "exp-invenio-drift")
        with self.assertRaisesRegex(harness.InstrumentationError, "exactly four"):
            harness.build_contract(
                harness.Declaration(
                    source_revision=good.source_revision,
                    render_sha256=good.render_sha256,
                    configmap_name=good.configmap_name,
                    resources=(good.resources[0],),
                ),
                observed,
                "invenio",
                "exp-invenio-drift",
            )
        without_hpa = observation()
        without_hpa.hpa = None
        self.assertEqual(
            harness.build_contract(good, without_hpa, "invenio", "exp-invenio-drift").hpa_targets,
            [],
        )

    def test_normalized_quantity_and_cluster_ip_placeholders(self):
        self.assertTrue(harness._field_matches("/spec/type", None, "ClusterIP"))
        cpu_path = "/spec/template/spec/containers/web/resources/requests/cpu"
        self.assertIsNone(harness._normalized_value(cpu_path, None))
        self.assertEqual(harness._quantity_nanocores("250m", "cpu"), 250_000_000)

    def test_resource_results_without_a_contract(self):
        self.assertEqual(
            harness.resource_results(SimpleNamespace(resources=[]), observation()),
            {"score": 0.0, "matched": 0, "total": 0, "resources": []},
        )

    def test_hpa_and_argo_signal_helpers(self):
        self.assertFalse(harness.hpa_settled(None))
        self.assertFalse(harness.hpa_settled({"desired": 1}))
        self.assertFalse(
            harness.hpa_settled(
                {
                    "desired": 2,
                    "current": 2,
                    "deployment_spec_replicas": 2,
                    "min": 2,
                    "max": 4,
                    "generation": 1,
                    "observed_generation": 2,
                    "able_to_scale": True,
                }
            )
        )
        self.assertTrue(
            harness.hpa_settled(
                {
                    "desired": 2,
                    "current": 2,
                    "deployment_spec_replicas": 2,
                    "min": 2,
                    "max": 4,
                    "generation": None,
                    "observed_generation": None,
                    "able_to_scale": True,
                }
            )
        )
        self.assertFalse(harness.hpa_telemetry_valid({"desired": -1}))
        self.assertTrue(
            harness.hpa_telemetry_valid(
                {
                    "desired": 2,
                    "current": 2,
                    "deployment_spec_replicas": 2,
                    "min": 2,
                    "max": 4,
                    "able_to_scale": True,
                    "generation": None,
                    "observed_generation": None,
                }
            )
        )
        self.assertFalse(harness.hpa_changed(None, {}))
        self.assertFalse(harness.argo_signal(None))
        self.assertTrue(harness.argo_signal({"operation_phase": "Running"}))
        self.assertTrue(
            harness.argo_signal({"conditions": [{"type": "SyncError", "status": "True"}]})
        )

    def test_quantity_decoding_rejects_each_invalid_form(self):
        cases = (
            (lambda: harness._quantity(1, "x"), "not a valid"),
            (lambda: harness._quantity(" 1", "x"), "not a valid"),
            (lambda: harness._quantity("1Q", "x"), "not a valid"),
            (lambda: harness._quantity("1K", "x"), "not a valid"),
            (lambda: harness._quantity_nanocores("0.1n", "x"), "nanocores"),
            (lambda: harness._quantity_nanocores("-1", "x"), "non-negative"),
            (lambda: harness._quantity_nanocores("0", "x", positive=True), "positive"),
            (lambda: harness._quantity_bytes("0.5", "x"), "bytes"),
        )
        for call, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(harness.InstrumentationError, message),
            ):
                call()

    def test_duration_decoding_rejects_each_invalid_form(self):
        cases = (
            (lambda: harness._duration_seconds(1, "x"), "valid duration"),
            (lambda: harness._duration_seconds("1s-2s", "x"), "valid duration"),
            (lambda: harness._duration_seconds("0s", "x"), "valid duration"),
        )
        for call, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(harness.InstrumentationError, message),
            ):
                call()

    def test_node_name_rejects_malformed_entries(self):
        cases = (
            (object(), "non-object"),
            ({"metadata": None}, "no metadata"),
            ({"metadata": {}}, "no name"),
        )
        for item, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(harness.InstrumentationError, message),
            ):
                harness._node_name(item, "inventory", set())

    def test_parse_node_metrics_rejects_malformed_payloads(self):
        bounds = {"started_mono": 0.0}
        cases = (
            ([], {}, "payload is not an object"),
            ({}, {}, "no node metrics"),
            (
                {
                    "items": [
                        {
                            "metadata": {"name": "n"},
                            "usage": {},
                            "timestamp": "2026-10-27T00:00:00Z",
                            "window": "30s",
                        }
                    ]
                },
                {"items": [{"metadata": {"name": "n"}}]},
                "no status",
            ),
            (
                {
                    "items": [
                        {
                            "metadata": {"name": "n"},
                            "usage": {},
                            "timestamp": "2026-10-27T00:00:00Z",
                            "window": "30s",
                        }
                    ]
                },
                {"items": [{"metadata": {"name": "n"}, "status": {}}]},
                "no allocatable",
            ),
            (
                {"items": [{"metadata": {"name": "n"}}]},
                {
                    "items": [
                        {
                            "metadata": {"name": "n"},
                            "status": {"allocatable": {"cpu": "1", "memory": "1Gi"}},
                        }
                    ]
                },
                "no usage",
            ),
        )
        for metrics, nodes, message in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(harness.InstrumentationError, message),
            ):
                harness.parse_node_metrics(metrics, nodes, bounds, bounds)


class KubectlCoverageTests(unittest.TestCase):
    def test_run_maps_timeout_and_start_failures(self):
        kubectl = harness.Kubectl(harness.Clock(), recorder=[])
        with mock.patch.object(
            harness.subprocess, "run", side_effect=harness.subprocess.TimeoutExpired("kubectl", 1)
        ):
            self.assertEqual(kubectl.run(["get", "pods"]).returncode, 124)
        with (
            mock.patch.object(harness.subprocess, "run", side_effect=OSError("missing")),
            self.assertRaises(harness.InstrumentationError),
        ):
            kubectl.run(["get", "pods"])
        with mock.patch.object(
            harness.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=None),
        ):
            kubectl.run(["patch", "x"], mutating=True)
        self.assertEqual(len(kubectl.recorder), 1)

    def test_read_handles_empty_list_and_invalid_json(self):
        kubectl = harness.Kubectl(harness.Clock())
        with mock.patch.object(
            harness.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ):
            payload, bounds = kubectl.read("Pod", namespace="invenio")
        self.assertIsNone(payload)
        self.assertFalse(bounds["present"])
        with mock.patch.object(
            harness.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"kind": "List", "items": [{"kind": "Pod"}]}),
                stderr="",
            ),
        ):
            payload, _ = kubectl.read("Pod", namespace="invenio")
        self.assertEqual(len(payload), 1)
        with mock.patch.object(
            harness.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=0, stdout=json.dumps({"kind": "List", "items": []}), stderr=""
            ),
        ):
            payload, _ = kubectl.read("Pod", name="one", namespace="invenio")
        self.assertIsNone(payload)
        with (
            mock.patch.object(
                harness.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="{", stderr=""),
            ),
            self.assertRaises(harness.InstrumentationError) as caught,
        ):
            kubectl.read("Pod", namespace="invenio")
        self.assertTrue(caught.exception.read_bounds)

    def test_read_retries_transient_stderr_then_succeeds(self):
        kubectl = harness.Kubectl(harness.Clock())
        responses = [
            SimpleNamespace(returncode=1, stdout="", stderr="connection reset"),
            SimpleNamespace(returncode=0, stdout='{"kind": "Pod"}', stderr=""),
        ]
        with (
            mock.patch.object(harness.subprocess, "run", side_effect=responses),
            mock.patch.object(harness.time, "sleep"),
        ):
            payload, _ = kubectl.read("Pod", namespace="invenio")
        self.assertEqual(payload["kind"], "Pod")

    def test_read_raises_with_bounds_after_a_permanent_failure(self):
        kubectl = harness.Kubectl(harness.Clock())
        with (
            mock.patch.object(
                harness.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="forbidden"),
            ),
            self.assertRaises(harness.InstrumentationError) as caught,
        ):
            kubectl.read("Pod", namespace="invenio")
        self.assertTrue(caught.exception.read_bounds)

    def test_read_stops_before_first_request_and_during_backoff(self):
        kubectl = harness.Kubectl(harness.Clock())
        with self.assertRaises(harness.ReadStopped) as caught:
            kubectl.read("Pod", namespace="invenio", guard=lambda: "stop")
        self.assertIsNone(caught.exception.read_bounds)
        stop = {"value": False}

        def guard():
            return "stop" if stop["value"] else None

        def sleep(_seconds):
            stop["value"] = True

        with (
            mock.patch.object(
                harness.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="connection reset"),
            ),
            mock.patch.object(harness.time, "sleep", side_effect=sleep),
            self.assertRaises(harness.ReadStopped) as caught,
        ):
            kubectl.read("Pod", namespace="invenio", guard=guard)
        self.assertTrue(caught.exception.read_bounds)

    def test_read_stop_during_a_start_failure_uses_current_bounds(self):
        kubectl = harness.Kubectl(harness.Clock())
        stop = {"value": False}

        def guard():
            return "stop" if stop["value"] else None

        def run(argv):
            stop["value"] = True
            raise harness.InstrumentationError("boom")

        with (
            mock.patch.object(kubectl, "run", side_effect=run),
            self.assertRaises(harness.ReadStopped),
        ):
            kubectl.read("Pod", namespace="invenio", guard=guard)

    def test_mutation_argv_building(self):
        kubectl = harness.Kubectl(harness.Clock())
        kubectl.run = mock.Mock(return_value=result())
        kubectl.patch("Deployment", "d", "invenio", {"a": 1})
        argv = kubectl.run.call_args[0][0]
        self.assertEqual(argv[:3], ["patch", "Deployment", "d"])
        self.assertIn("--type", argv)
        kubectl.annotate("Deployment", "d", "invenio", "key")
        self.assertTrue(kubectl.run.call_args[0][0][-1].endswith("-"))
        kubectl.annotate("Deployment", "d", "invenio", "key", "value")
        self.assertIn("--overwrite", kubectl.run.call_args[0][0])
        kubectl.apply({"kind": "Deployment"})
        self.assertEqual(kubectl.run.call_args[1]["input_text"], '{"kind": "Deployment"}')
        kubectl.delete("Deployment", "d")
        self.assertIn("--wait=false", kubectl.run.call_args[0][0])
        kubectl.delete("Deployment", "d", "invenio", wait=True)
        self.assertNotIn("--wait=false", kubectl.run.call_args[0][0])

    def test_pods_filters_succeeded_and_computes_readiness(self):
        kubectl = harness.Kubectl(harness.Clock())
        items = [
            {"metadata": {"name": "done"}, "status": {"phase": "Succeeded"}},
            {
                "metadata": {"name": "ready"},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [{"ready": True}],
                    "initContainerStatuses": [{"ready": True}],
                },
            },
            {"metadata": {"name": "pending"}, "status": {"phase": "Pending"}},
        ]
        kubectl.get = mock.Mock(return_value=items)
        pods = kubectl.pods("invenio")
        self.assertEqual([item["name"] for item in pods], ["ready", "pending"])
        self.assertTrue(pods[0]["ready"])
        self.assertFalse(pods[1]["ready"])


class SnapshotterCoverageTests(unittest.TestCase):
    def snapshotter(self, kubectl, **kwargs):
        return harness.Snapshotter(
            kubectl, "invenio", "exp-invenio-drift", harness.Clock(), **kwargs
        )

    def test_discover_configmap_prefers_deployment_reference(self):
        snapshotter = self.snapshotter(FakeKubectl())
        name = snapshotter.discover_configmap(web_deployment())
        self.assertEqual(name, "invenio-app-config-6dg2chdbh4")
        self.assertEqual(snapshotter.discover_configmap(None), None)

    def test_discover_configmap_uses_the_single_matching_configmap(self):
        kubectl = mock.Mock()
        kubectl.get.return_value = [
            {"metadata": {"name": "invenio-app-config-a"}},
            {"metadata": {"name": "other"}},
        ]
        snapshotter = self.snapshotter(kubectl)
        self.assertEqual(snapshotter.discover_configmap(None), "invenio-app-config-a")
        kubectl.get.return_value.append({"metadata": {"name": "invenio-app-config-b"}})
        self.assertIsNone(snapshotter.discover_configmap(None))

    def test_discover_configmap_ignores_unrelated_references(self):
        deployment = web_deployment()
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        container["envFrom"] = [{"configMapRef": {"name": "other"}}, {"secretRef": {}}]
        snapshotter = self.snapshotter(FakeKubectl(objects={}))
        self.assertIsNone(snapshotter.discover_configmap(deployment))

    def test_discover_configmap_honors_the_stop_guard(self):
        snapshotter = self.snapshotter(FakeKubectl())
        with self.assertRaises(harness.CaptureStopped):
            snapshotter.discover_configmap(None, guard=lambda: "stop")

    def test_capture_records_quarantine_extras_and_requires_apps(self):
        objects = {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"): web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
            ("Namespace", "exp-invenio-drift", None): {"kind": "Namespace"},
            ("Deployment", "invenio-web", "exp-invenio-drift"): web_deployment(),
        }
        fake = FakeKubectl(objects=objects)
        snapshotter = self.snapshotter(fake, configmap_name="invenio-app-config-6dg2chdbh4")
        observed = snapshotter.capture()
        self.assertEqual(observed.extra_resources, ["exp-invenio-drift/Deployment/invenio-web"])
        missing_app = FakeKubectl(
            objects=objects,
            apps={"apps": application("apps")},
        )
        snapshotter = self.snapshotter(missing_app, configmap_name="invenio-app-config-6dg2chdbh4")
        with self.assertRaises(harness.InstrumentationError):
            snapshotter.capture()


class SeedCoverageTests(unittest.TestCase):
    CONTENT = b"data"
    MD5 = hashlib.md5(CONTENT).hexdigest()
    SHA = hashlib.sha256(CONTENT).hexdigest()

    def responses(self):
        draft = {"files": {"enabled": True}}
        listing = {
            "entries": [
                {
                    "key": "seed.bin",
                    "status": "completed",
                    "size": len(self.CONTENT),
                    "checksum": "md5:" + self.MD5,
                }
            ]
        }
        return [
            (200, json.dumps(draft).encode()),
            (200, json.dumps(listing).encode()),
            (200, self.CONTENT),
        ]

    def verify(self, responses):
        return harness.verify_seed(
            _SequenceHttp(responses), "record", "seed.bin", len(self.CONTENT), self.MD5, self.SHA
        )

    def test_success_reports_content_identity(self):
        self.assertEqual(self.verify(self.responses())["size"], len(self.CONTENT))

    def test_seed_failures_close_every_boundary(self):
        cases = []
        for index, replacement, message in (
            (0, (500, b""), "draft endpoint"),
            (0, (200, b"not-json"), "draft response is not JSON"),
            (0, (200, b'{"files": {"enabled": false}}'), "files disabled"),
            (1, (500, b""), "file listing"),
            (1, (200, b"not-json"), "listing is not JSON"),
            (1, (200, b'{"entries": []}'), "is missing"),
            (
                1,
                (
                    200,
                    json.dumps(
                        {
                            "entries": [
                                {
                                    "key": "seed.bin",
                                    "status": "pending",
                                    "size": len(self.CONTENT),
                                }
                            ]
                        }
                    ).encode(),
                ),
                "not completed",
            ),
            (
                1,
                (
                    200,
                    json.dumps(
                        {
                            "entries": [
                                {
                                    "key": "seed.bin",
                                    "status": "completed",
                                    "size": 1,
                                }
                            ]
                        }
                    ).encode(),
                ),
                "size mismatch",
            ),
            (
                1,
                (
                    200,
                    json.dumps(
                        {
                            "entries": [
                                {
                                    "key": "seed.bin",
                                    "status": "completed",
                                    "size": len(self.CONTENT),
                                    "checksum": "md5:bad",
                                }
                            ]
                        }
                    ).encode(),
                ),
                "MD5 checksum",
            ),
            (2, (500, b""), "content endpoint"),
            (2, (200, b"x"), "content size"),
        ):
            cases.append((index, replacement, message))
        for index, replacement, message in cases:
            with self.subTest(message=message):
                responses = self.responses()
                responses[index] = replacement
                with self.assertRaisesRegex(harness.SeedVerificationError, message):
                    self.verify(responses)
        responses = self.responses()
        responses[2] = (200, b"xxxx")
        with self.assertRaisesRegex(harness.SeedVerificationError, "content MD5"):
            harness.verify_seed(
                _SequenceHttp(responses),
                "record",
                "seed.bin",
                len(self.CONTENT),
                self.MD5,
                self.SHA,
            )
        responses = self.responses()
        with self.assertRaisesRegex(harness.SeedVerificationError, "content SHA-256"):
            harness.verify_seed(
                _SequenceHttp(responses),
                "record",
                "seed.bin",
                len(self.CONTENT),
                self.MD5,
                "0" * 64,
            )


class BaselineIssueCoverageTests(unittest.TestCase):
    def codes(self, observed, arm="gitops"):
        return [issue["code"] for issue in harness._baseline_issues(observed, arm)]

    def test_missing_inventory_reports_each_gap(self):
        observed = observation()
        observed.resources = {}
        observed.hpa = None
        codes = self.codes(observed)
        self.assertIn("missing_configmap", codes)
        self.assertIn("missing_deployment", codes)
        self.assertIn("missing_sealed_secret", codes)
        self.assertIn("missing_service", codes)
        self.assertIn("missing_hpa", codes)

    def test_contamination_wrong_target_and_unsettled_hpa(self):
        observed = observation()
        observed.resources["SealedSecret/" + harness.SEALED_SECRET]["fields"][
            "/metadata/annotations/" + harness.DRIFT_ANNOTATION
        ] = "present"
        self.assertIn("contamination", self.codes(observed))
        observed = observation()
        observed.hpa = dict(harness.hpa_state(web_hpa(), web_deployment()))
        observed.hpa["target"] = "Deployment/other"
        self.assertIn("hpa_target", self.codes(observed))
        observed = observation()
        observed.hpa = harness.hpa_state(web_hpa(desired=3), web_deployment())
        self.assertIn("hpa_settling", self.codes(observed))
        observed = observation()
        observed.hpa = {"target": "Deployment/invenio-web", "desired": "bad"}
        with self.assertRaises(harness.InstrumentationError):
            self.codes(observed)

    def test_pod_node_and_argo_issues(self):
        observed = observation()
        observed.pods = []
        self.assertIn(
            "no pods observed",
            [issue["detail"] for issue in harness._baseline_issues(observed, "gitops")],
        )
        observed.pods = [{"name": "p", "phase": "Pending", "ready": False}]
        self.assertIn("pod_readiness", self.codes(observed))
        observed.pods = [object()]
        with self.assertRaises(harness.InstrumentationError):
            self.codes(observed)
        observed = observation()
        observed.nodes = []
        self.assertIn("missing_node_metrics", self.codes(observed))
        observed.nodes = [object()]
        with self.assertRaises(harness.InstrumentationError):
            self.codes(observed)
        observed = observation()
        observed.nodes = [node_reading(cpu=70)]
        self.assertIn("capacity", self.codes(observed))
        observed.nodes = [node_reading(timestamp="2020-01-01T00:00:00Z")]
        self.assertIn("stale_metrics", self.codes(observed))
        observed.nodes = [node_reading(timestamp="2026-10-29T00:00:00Z")]
        self.assertIn("clock_anomaly", self.codes(observed))
        observed.nodes = [node_reading(window=60)]
        self.assertIn("long_window", self.codes(observed))
        observed.nodes = [node_reading(window=0)]
        with self.assertRaises(harness.InstrumentationError):
            self.codes(observed)
        observed = observation()
        observed.argo = {"apps": {"sync": "OutOfSync", "health": "Healthy"}}
        self.assertIn("argo_state", self.codes(observed))

    def test_extras_and_instrumentation_record_fallbacks(self):
        observed = observation()
        observed.extra_resources = ["quarantine"]
        self.assertIn("quarantine_preexisting", self.codes(observed))
        error = harness.InstrumentationError("bad")
        error.acquisition = {"started_mono": 0.0}
        record = harness._instrumentation_record(error, point(0), point(1))
        self.assertEqual(record["acquisition"], {"started_mono": 0.0})
        empty = harness._instrumentation_record(
            harness.InstrumentationError("bad"), point(0), point(1)
        )
        self.assertIn("snapshot", empty["acquisition"])


class _SequenceSnapshotter:
    def __init__(self, observations):
        self.observations = list(observations)
        self.namespace = "invenio"

    def capture(self):
        return copy.deepcopy(self.observations.pop(0))


class _BaselineKubectl:
    def __init__(self, pods=None, nodes=None, fail_pods=False):
        self.pods_result = pods or [{"name": "p", "phase": "Running", "ready": True}]
        self.nodes_result = nodes or [node_reading()]
        self.fail_pods = fail_pods

    def pods(self, namespace):
        if self.fail_pods:
            raise harness.InstrumentationError("pods unavailable")
        return copy.deepcopy(self.pods_result)

    def top_nodes(self):
        return copy.deepcopy(self.nodes_result)


class StabilizeCoverageTests(unittest.TestCase):
    def test_instrumentation_failure_records_pods_started(self):
        snapshotter = _SequenceSnapshotter([observation()])
        kubectl = _BaselineKubectl(fail_pods=True)
        with self.assertRaises(harness.InstrumentationError) as caught:
            harness.stabilize_baseline(
                snapshotter, kubectl, "gitops", 5.0, 0.01, AdvancingClock(), sleep=lambda _s: None
            )
        self.assertTrue(caught.exception.readiness_failures)

    def test_unmatched_read_is_recorded_before_settling(self):
        first = observation()
        second = observation()
        second.resources["ConfigMap/invenio-app-config-6dg2chdbh4"]["fields"][
            "/data/INSTANCE_TAGLINE"
        ] = "changed"
        snapshotter = _SequenceSnapshotter([first, second, copy.deepcopy(second)])
        kubectl = _BaselineKubectl()
        observed = harness.stabilize_baseline(
            snapshotter, kubectl, "gitops", 100.0, 0.01, AdvancingClock(), sleep=lambda _s: None
        )
        codes = [record["reason"] for record in observed.readiness_failures]
        self.assertIn("unmatched_read", codes)


class ArmCoverageTests(unittest.TestCase):
    def test_arm_activation_rejections(self):
        controller = harness.ArmController(FakeKubectl(apps={}))
        with self.assertRaises(harness.ArmStateError):
            controller.get_app("missing")
        with self.assertRaises(harness.SafetyError):
            controller.activate("bogus")
        disabled = application(automated={"selfHeal": False})
        controller = harness.ArmController(
            FakeKubectl(apps={"apps": disabled, "invenio-bootstrap": disabled})
        )
        with self.assertRaises(harness.ArmStateError):
            controller.activate("gitops")
        with self.assertRaises(harness.ArmStateError):
            controller.activate("imperative")

    def test_pause_failures_restore_or_report_restore_failure(self):
        fake = FakeKubectl(fail_patch=True)
        controller = harness.ArmController(fake)
        with self.assertRaises(harness.ArmRestoreError):
            controller.activate("imperative")
        fake = FakeKubectl(no_op_patch=True)
        controller = harness.ArmController(fake)
        with self.assertRaises(harness.ArmStateError):
            controller.activate("imperative")
        self.assertIsNone(controller.restore())

    def test_restore_reports_observed_mismatch(self):
        fake = FakeKubectl(no_op_patch=True)
        controller = harness.ArmController(fake)
        controller.original = {
            name: {"automated": {"selfHeal": True}} for name in ("apps", "invenio-bootstrap")
        }
        for app in fake.apps.values():
            app["spec"]["syncPolicy"]["automated"] = None
        with self.assertRaises(harness.ArmRestoreError):
            controller.restore()


class _InjectKubectl:
    def __init__(self, code=0, observed=None, get_error=None, patch_error=None):
        self.code = code
        self.observed = observed
        self.get_error = get_error
        self.patch_error = patch_error

    def _command(self, argv):
        if self.patch_error is not None:
            raise self.patch_error
        return result(argv=argv, code=self.code)

    def patch(self, kind, name, namespace, patch, patch_type="merge"):
        return self._command(["patch", kind, name])

    def delete(self, kind, name, namespace=None, wait=False, timeout=90):
        return self._command(["delete", kind, name])

    def annotate(self, kind, name, namespace, key, value=None):
        return self._command(["annotate", kind, name])

    def get(self, kind, name=None, namespace=None, selector=None):
        if self.get_error is not None:
            raise self.get_error
        return copy.deepcopy(self.observed)


class InjectCoverageTests(unittest.TestCase):
    def test_unknown_scenario_and_impossible_baselines(self):
        fake = FakeKubectl()
        clock = harness.Clock()
        with self.assertRaises(harness.SafetyError):
            harness.inject(fake, contract(), "Z", "run", clock)
        broken = copy.deepcopy(contract())
        broken.baseline_hpa = None
        with self.assertRaisesRegex(harness.InjectionError, "did not retain"):
            harness.inject(fake, broken, "A", "run", clock)
        image_contract = copy.deepcopy(contract())
        image_contract.resources[0]["fields"]["/spec/template/spec/containers/web/image"] = (
            "repo:drift-" + harness._short("run")
        )
        with self.assertRaisesRegex(harness.InjectionError, "identical"):
            harness.inject(fake, image_contract, "B", "run", clock)
        configmap_contract = copy.deepcopy(contract())
        configmap_contract.resources[1]["fields"]["/data/" + harness.CONFIG_KEY] = (
            harness.CONFIG_DRIFT + "-" + harness._short("run")
        )
        with self.assertRaisesRegex(harness.InjectionError, "identical"):
            harness.inject(fake, configmap_contract, "C", "run", clock)

    def test_command_failure_carries_injection_evidence(self):
        fake = _InjectKubectl(code=1)
        with self.assertRaises(harness.InjectionError) as caught:
            harness.inject(fake, contract(), "D", "run", harness.Clock())
        self.assertEqual(caught.exception.injection.accepted, False)

    def test_verification_failure_for_every_scenario(self):
        wrong = {
            "A": {"spec": {"replicas": 0}},
            "B": {"spec": {"template": {"spec": {"containers": [{"name": "web", "image": "x"}]}}}},
            "C": {"data": {harness.CONFIG_KEY: "wrong"}},
            "D": {"kind": "Deployment"},
            "E": {
                "spec": {"template": {"spec": {"containers": [{"name": "web", "resources": {}}]}}}
            },
            "F": {"spec": {"ports": [{"port": 1, "targetPort": 2}]}},
            "G": {"metadata": {"annotations": {harness.DRIFT_ANNOTATION: "wrong"}}},
        }
        for scenario, observed in wrong.items():
            with self.subTest(scenario=scenario):
                fake = _InjectKubectl(observed=observed)
                with self.assertRaises(harness.InjectionError):
                    harness.inject(fake, contract(), scenario, "run", harness.Clock())

    def test_harness_and_unexpected_errors_during_verification(self):
        fake = _InjectKubectl(get_error=harness.SafetyError("refused"))
        with self.assertRaises(harness.SafetyError) as caught:
            harness.inject(fake, contract(), "D", "run", harness.Clock())
        self.assertTrue(caught.exception.injection)
        fake = _InjectKubectl(get_error=RuntimeError("boom"))
        with self.assertRaisesRegex(harness.InjectionError, "verification failed"):
            harness.inject(fake, contract(), "D", "run", harness.Clock())
        fake = _InjectKubectl(patch_error=RuntimeError("boom"))
        with self.assertRaisesRegex(harness.InjectionError, "command failed"):
            harness.inject(fake, contract(), "G", "run", harness.Clock())


class RepairCoverageTests(unittest.TestCase):
    def commands(self, observed):
        fake = mock.Mock()
        fake.apply.return_value = result()
        fake.patch.return_value = result()
        fake.annotate.return_value = result()
        return fake, harness.repair(fake, contract(), observed, harness.Clock())

    def test_missing_resources_apply_except_sealed_secret(self):
        observed = observation()
        observed.resources.pop("Deployment/" + harness.WEB_DEPLOYMENT)
        observed.resources.pop("SealedSecret/" + harness.SEALED_SECRET)
        fake, commands = self.commands(observed)
        self.assertEqual(len(commands), 1)
        fake.apply.assert_called_once()

    def test_deployment_configmap_and_service_drift_are_patched(self):
        observed = observation()
        observed.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/image"
        ] = "drift"
        observed.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/resources/limits/memory"
        ] = "1Gi"
        observed.resources["ConfigMap/invenio-app-config-6dg2chdbh4"]["fields"][
            "/data/" + harness.CONFIG_KEY
        ] = "drift"
        observed.resources["Service/" + harness.WEB_SERVICE]["fields"][
            "/spec/ports/0/targetPort"
        ] = 1
        fake, commands = self.commands(observed)
        self.assertEqual(len(commands), 3)
        self.assertEqual(fake.patch.call_count, 2)
        self.assertEqual(fake.apply.call_count, 1)

    def test_sealed_secret_annotation_drift_is_removed(self):
        observed = observation()
        observed.resources["SealedSecret/" + harness.SEALED_SECRET]["fields"][
            "/metadata/annotations/" + harness.DRIFT_ANNOTATION
        ] = "present"
        fake, commands = self.commands(observed)
        self.assertEqual(len(commands), 1)
        fake.annotate.assert_called_once()


class CleanupCoverageTests(unittest.TestCase):
    def test_g_annotation_cleanup_paths(self):
        fake = mock.Mock()
        fake.get.return_value = sealed_secret()
        self.assertTrue(harness.cleanup_g_annotation(fake, "invenio").ok)
        fake.get.return_value = sealed_secret({harness.DRIFT_ANNOTATION: "present"})
        fake.annotate.return_value = result(code=1, stderr="failed")
        report = harness.cleanup_g_annotation(fake, "invenio")
        self.assertFalse(report.ok)
        fake.get.side_effect = harness.HarnessError("boom")
        self.assertFalse(harness.cleanup_g_annotation(fake, "invenio").ok)

    def test_quarantine_cleanup_paths(self):
        fake = mock.Mock()
        fake.get.return_value = None
        self.assertTrue(harness.cleanup_quarantine(fake, "exp-a").ok)
        fake.get.return_value = {"metadata": {"labels": {}}}
        self.assertFalse(harness.cleanup_quarantine(fake, "exp-a", owner="run").ok)
        fake = mock.Mock()
        fake.get.return_value = {"metadata": {"labels": {}}}
        fake.delete.return_value = result(code=1, stderr="forbidden")
        report = harness.cleanup_quarantine(fake, "exp-a", wait_seconds=0)
        self.assertFalse(report.ok)
        fake = mock.Mock()
        fake.get.side_effect = harness.HarnessError("boom")
        with self.assertRaises(harness.HarnessError):
            harness.cleanup_quarantine(fake, "exp-a")
        with self.assertRaises(harness.SafetyError):
            harness.cleanup_quarantine(fake, "invenio")


class AcquisitionTimelineCoverageTests(unittest.TestCase):
    def test_validate_acquisition_rejects_malformed_bounds(self):
        valid = observation()
        cases = []
        broken = copy.deepcopy(valid)
        broken.acquisition = []
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["started_mono"] = None
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["started_mono"] = 2.0
        broken.acquisition["finished_mono"] = 1.0
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["reads"] = {}
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["reads"]["Deployment/invenio-web"] = []
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["reads"]["Deployment/invenio-web"]["started_mono"] = 1.0
        broken.acquisition["reads"]["Deployment/invenio-web"]["finished_mono"] = 0.0
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["reads"]["Deployment/invenio-web"]["finished_mono"] = 99.0
        cases.append(broken)
        broken = copy.deepcopy(valid)
        broken.acquisition["reads"]["Deployment/invenio-web"]["ok"] = "yes"
        cases.append(broken)
        for broken in cases:
            with self.subTest(), self.assertRaises(harness.InstrumentationError):
                harness._validate_acquisition(broken)
        self.assertEqual(harness._validate_acquisition(copy.deepcopy(valid)), valid.acquisition)

    def test_read_helpers_handle_incomplete_and_complete_records(self):
        sample = observation()
        keys = ["Deployment/invenio-web"]
        self.assertIsNotNone(harness._complete_match_completion(sample, keys))
        sample.acquisition["reads"]["Deployment/invenio-web"]["ok"] = False
        self.assertIsNone(harness._complete_match_completion(sample, keys))
        self.assertIsNone(harness._complete_match_completion(sample, []))

    def test_imperative_and_evaluation_key_helpers(self):
        observed = observation()
        contract_obj = contract()
        sample = copy.deepcopy(observed)
        sample.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/image"
        ] = "drift"
        keys = harness._diff_keys(contract_obj, sample)
        self.assertTrue(keys)
        event = point(0.0)
        self.assertIsNone(harness._imperative_event_keys(contract_obj, sample, None, -1.0, 1.0))
        self.assertIsNone(
            harness._imperative_event_keys(
                contract_obj, sample, harness.Point(float("nan"), event.utc), -1.0, 1.0
            )
        )
        self.assertIsNone(
            harness._imperative_event_keys(contract_obj, sample, point(5.0), -1.0, 1.0)
        )
        self.assertEqual(
            harness._imperative_event_keys(contract_obj, sample, event, -1.0, 1.0), keys
        )
        self.assertIsNone(harness._evaluation_keys(contract_obj, sample, "B"))
        no_diff = copy.deepcopy(sample)
        no_diff.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/image"
        ] = contract_obj.resources[0]["fields"]["/spec/template/spec/containers/web/image"]
        self.assertIsNone(harness._imperative_event_keys(contract_obj, no_diff, event, -1.0, 1.0))
        self.assertIsNone(
            harness._imperative_event_keys(contract_obj, sample, point(-0.5), -1.0, 1.0)
        )
        sample.evaluated_signal = True
        sample.evaluated_reads = []
        self.assertIsNone(harness._evaluation_keys(contract_obj, sample, "B"))
        sample.evaluated_reads = ["unknown"]
        self.assertIsNone(harness._evaluation_keys(contract_obj, sample, "B"))
        sample.evaluated_reads = keys
        self.assertEqual(harness._evaluation_keys(contract_obj, sample, "B"), keys)
        self.assertEqual(
            harness._evaluation_evidence([sample], contract_obj, "B", -1.0, 1.0), (None, [])
        )
        bad = copy.deepcopy(sample)
        bad.evaluated_at = harness.Point(float("nan"), sample.at.utc)
        self.assertEqual(
            harness._evaluation_evidence([bad], contract_obj, "B", -1.0, 1.0), (None, [])
        )
        early = copy.deepcopy(sample)
        early.evaluated_at = point(-0.5)
        self.assertEqual(
            harness._evaluation_evidence([early], contract_obj, "B", -1.0, 1.0), (None, [])
        )
        late = copy.deepcopy(sample)
        late.evaluated_at = point(5.0)
        self.assertEqual(
            harness._evaluation_evidence([late], contract_obj, "B", -1.0, 1.0), (None, [])
        )
        self.assertEqual(
            harness._evaluation_evidence(
                [sample], contract_obj, "B", -1.0, 1.0, evidence_at=point(5.0)
            ),
            (None, []),
        )
        no_event = copy.deepcopy(sample)
        no_event.evaluated_at = None
        self.assertEqual(
            harness._evaluation_evidence(
                [no_event], contract_obj, "B", -1.0, 1.0, evidence_at=point(-0.5)
            ),
            (None, []),
        )
        self.assertEqual(
            harness._evaluation_evidence(
                [no_event],
                contract_obj,
                "B",
                -1.0,
                1.0,
                evidence_at=harness.Point(float("nan"), sample.at.utc),
            ),
            (None, []),
        )
        sample.evaluated_at = event
        self.assertEqual(
            harness._evaluation_evidence([sample], contract_obj, "B", -1.0, 1.0), (event, keys)
        )
        self.assertEqual(
            harness._evaluation_evidence([sample], contract_obj, "B", -1.0, 1.0, evidence_at=event),
            (event, keys),
        )
        with self.assertRaises(harness.InstrumentationError):
            harness._evaluation_evidence(
                [sample], contract_obj, "B", -1.0, 1.0, evidence_at=point(1.0)
            )

    def test_analyze_timeline_status_mapping(self):
        observed = observation()
        timeline = harness.analyze_timeline(
            contract(), [observed], injection(accepted=False), "gitops", "B", 10.0
        )
        self.assertEqual(timeline["status"], "invalid_injection")
        imperative = harness.ImperativeRun(failed=True)
        timeline = harness.analyze_timeline(
            contract(), [observed], injection(), "imperative", "B", 10.0, imperative
        )
        self.assertEqual(timeline["status"], "recovery_failure")

    def test_analyze_timeline_populated_detection_and_recovery_paths(self):
        contract_obj = contract()
        hpa_sample = observation(
            at=101.0,
            hpa=harness.hpa_state(web_hpa(desired=3), web_deployment()),
        )
        timeline = harness.analyze_timeline(
            contract_obj, [hpa_sample], injection(), "gitops", "A", 10.0
        )
        self.assertIsNotNone(timeline["detection_seconds"])
        argo_sample = observation(
            at=101.0,
            argo={"invenio-bootstrap": {"sync": "OutOfSync", "health": "Healthy"}},
        )
        timeline = harness.analyze_timeline(
            contract_obj, [argo_sample], injection(), "gitops", "B", 10.0
        )
        self.assertIsNotNone(timeline["detection_seconds"])
        drifted = observation(at=101.0)
        drifted.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/image"
        ] = "drift"
        imperative = harness.ImperativeRun(detection_at=point(101.0), evidence_at=point(101.0))
        timeline = harness.analyze_timeline(
            contract_obj, [drifted], injection(), "imperative", "B", 10.0, imperative
        )
        self.assertIsNotNone(timeline["detection_seconds"])
        self.assertIsNotNone(timeline["evidence_seconds"])
        clean = observation(at=101.0)
        drifted_later = observation(at=102.0)
        drifted_later.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/image"
        ] = "drift"
        event = point(102.0)
        imperative = harness.ImperativeRun(detection_at=event, evidence_at=event)
        timeline = harness.analyze_timeline(
            contract_obj,
            [clean, drifted_later],
            injection(),
            "imperative",
            "B",
            10.0,
            imperative,
        )
        self.assertIsNotNone(timeline["detection_seconds"])
        self.assertIsNotNone(timeline["evidence_seconds"])
        slow_hpa = observation(
            at=101.0,
            read_finish=111.0,
            hpa=harness.hpa_state(web_hpa(desired=3), web_deployment()),
        )
        timeline = harness.analyze_timeline(
            contract_obj, [slow_hpa], injection(), "gitops", "A", 10.0
        )
        self.assertIsNone(timeline["detection_seconds"])
        timeline = harness.analyze_timeline(
            contract_obj,
            [drifted],
            injection(),
            "imperative",
            "B",
            10.0,
            harness.ImperativeRun(failed=True),
        )
        self.assertEqual(timeline["status"], "recovery_failure")
        first = observation(at=101.0)
        second = observation(at=102.0)
        timeline = harness.analyze_timeline(
            contract_obj, [first, second], injection(), "gitops", "B", 10.0
        )
        self.assertEqual(timeline["status"], "observed")
        self.assertEqual(timeline["recovery_confirmation"], "confirmed")


class NumericCoverageTests(unittest.TestCase):
    def test_quantity_underflow_duration_overflow_and_node_percent_overflow(self):
        with self.assertRaisesRegex(harness.InstrumentationError, "underflows"):
            harness._quantity("1e-999999999", "x")
        with self.assertRaisesRegex(harness.InstrumentationError, "valid duration"):
            harness._duration_seconds("9" * 1_000_000 + "h", "x")
        metrics = {
            "items": [
                {
                    "metadata": {"name": "n"},
                    "usage": {"cpu": "1e1000", "memory": "1Gi"},
                    "timestamp": "2026-10-27T00:00:00Z",
                    "window": "30s",
                }
            ]
        }
        nodes = {
            "items": [
                {
                    "metadata": {"name": "n"},
                    "status": {"allocatable": {"cpu": "1", "memory": "8Gi"}},
                }
            ]
        }
        with self.assertRaisesRegex(harness.InstrumentationError, "not finite"):
            harness.parse_node_metrics(metrics, nodes, {}, {})

    def test_nanocores_overflow_is_an_instrumentation_error(self):
        with self.assertRaisesRegex(harness.InstrumentationError, "not a valid CPU quantity"):
            harness._quantity_nanocores("1E+999999", "cpu")

    def test_hpa_telemetry_rejects_zero_minimum(self):
        self.assertFalse(
            harness.hpa_telemetry_valid(
                {
                    "desired": 0,
                    "current": 0,
                    "deployment_spec_replicas": 0,
                    "min": 0,
                    "max": 1,
                    "able_to_scale": True,
                }
            )
        )


class ReadCoverageTests(unittest.TestCase):
    def test_request_error_without_a_stop_is_re_raised(self):
        kubectl = harness.Kubectl(harness.Clock())
        with (
            mock.patch.object(kubectl, "run", side_effect=harness.InstrumentationError("boom")),
            self.assertRaises(harness.InstrumentationError),
        ):
            kubectl.read("Pod", namespace="invenio")

    def test_two_transient_retries_then_permanent_failure(self):
        kubectl = harness.Kubectl(harness.Clock())
        responses = [
            SimpleNamespace(returncode=1, stdout="", stderr="connection reset") for _ in range(3)
        ]
        with (
            mock.patch.object(harness.subprocess, "run", side_effect=responses),
            mock.patch.object(harness.time, "sleep"),
            self.assertRaises(harness.InstrumentationError),
        ):
            kubectl.read("Pod", namespace="invenio")

    def test_stop_after_the_retry_loop_raises_with_bounds(self):
        kubectl = harness.Kubectl(harness.Clock())
        stop = {"value": False}
        calls = {"count": 0}

        def run(argv):
            calls["count"] += 1
            if calls["count"] == 3:
                stop["value"] = True
            return result(code=1, stderr="connection reset")

        with (
            mock.patch.object(kubectl, "run", side_effect=run),
            mock.patch.object(harness.time, "sleep"),
            self.assertRaises(harness.ReadStopped),
        ):
            kubectl.read(
                "Pod", namespace="invenio", guard=lambda: "stop" if stop["value"] else None
            )

    def test_mutation_argv_without_namespace(self):
        kubectl = harness.Kubectl(harness.Clock())
        kubectl.run = mock.Mock(return_value=result())
        kubectl.patch("Namespace", "n", "", {})
        self.assertNotIn("-n", kubectl.run.call_args[0][0])
        kubectl.annotate("Namespace", "n", "", "key", "value")
        self.assertNotIn("-n", kubectl.run.call_args[0][0])


class SnapshotReadCoverageTests(unittest.TestCase):
    def test_read_forwards_partial_bounds_for_both_stop_and_error(self):
        snapshotter = harness.Snapshotter(
            mock.Mock(), "invenio", "exp-invenio-drift", harness.Clock()
        )
        stopped = harness.ReadStopped("stop", {"started_mono": 0.0})
        snapshotter.kubectl.read = mock.Mock(side_effect=stopped)
        with self.assertRaises(harness.CaptureStopped) as caught:
            snapshotter._read({}, "Deployment/invenio-web", "Deployment")
        self.assertIn("Deployment/invenio-web", caught.exception.acquisition["reads"])
        error = harness.InstrumentationError("boom")
        error.read_bounds = {"started_mono": 0.0}
        snapshotter.kubectl.read = mock.Mock(side_effect=error)
        with self.assertRaises(harness.InstrumentationError) as caught:
            snapshotter._read({}, "Deployment/invenio-web", "Deployment")
        self.assertIn("Deployment/invenio-web", caught.exception.acquisition["reads"])

    def test_read_without_partial_bounds_still_raises_capture_stop(self):
        snapshotter = harness.Snapshotter(
            mock.Mock(), "invenio", "exp-invenio-drift", harness.Clock()
        )
        snapshotter.kubectl.read = mock.Mock(side_effect=harness.ReadStopped("stop"))
        with self.assertRaises(harness.CaptureStopped):
            snapshotter._read({}, "Deployment/invenio-web", "Deployment")
        error = harness.InstrumentationError("boom")
        snapshotter.kubectl.read = mock.Mock(side_effect=error)
        with self.assertRaises(harness.InstrumentationError):
            snapshotter._read({}, "Deployment/invenio-web", "Deployment")

    def test_capture_discovers_configmap_and_handles_empty_quarantine(self):
        objects = {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"): web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
            ("Namespace", "exp-invenio-drift", None): {"kind": "Namespace"},
        }
        snapshotter = harness.Snapshotter(
            FakeKubectl(objects=objects), "invenio", "exp-invenio-drift", harness.Clock()
        )
        observed = snapshotter.capture()
        self.assertEqual(snapshotter.configmap_name, "invenio-app-config-6dg2chdbh4")
        self.assertEqual(observed.extra_resources, [])


class BaselineHelperCoverageTests(unittest.TestCase):
    def test_instrumentation_record_prefers_empty_observation_acquisition(self):
        observed = observation()
        observed.acquisition = {}
        record = harness._instrumentation_record(
            harness.InstrumentationError("boom"), point(0), point(1), observed
        )
        self.assertIn("snapshot", record["acquisition"])

    def test_stabilize_records_capture_and_node_failures(self):
        class FailingCapture:
            namespace = "invenio"

            def capture(self):
                raise harness.InstrumentationError("capture failed")

        with self.assertRaises(harness.InstrumentationError):
            harness.stabilize_baseline(
                FailingCapture(),
                _BaselineKubectl(),
                "gitops",
                5.0,
                0.01,
                AdvancingClock(),
                sleep=lambda _s: None,
            )

        class FailingNodes(_BaselineKubectl):
            def top_nodes(self):
                raise harness.InstrumentationError("nodes failed")

        with self.assertRaises(harness.InstrumentationError):
            harness.stabilize_baseline(
                _SequenceSnapshotter([observation()]),
                FailingNodes(),
                "gitops",
                5.0,
                0.01,
                AdvancingClock(),
                sleep=lambda _s: None,
            )

    def test_stabilize_skips_bounds_already_present(self):
        observed = observation()
        observed.acquisition["nodes"] = {"started_mono": 0.0, "finished_mono": 0.0}

        class FailingNodes(_BaselineKubectl):
            def top_nodes(self):
                raise harness.InstrumentationError("nodes failed")

        with self.assertRaises(harness.InstrumentationError):
            harness.stabilize_baseline(
                _SequenceSnapshotter([observed]),
                FailingNodes(),
                "gitops",
                5.0,
                0.01,
                AdvancingClock(),
                sleep=lambda _s: None,
            )

    def test_field_and_configmap_helpers_fail_closed(self):
        contract_obj = contract()
        with self.assertRaisesRegex(harness.InjectionError, "resource"):
            harness._field(contract_obj, "Deployment/missing", "/x")
        with self.assertRaisesRegex(harness.InjectionError, "field"):
            harness._field(contract_obj, "Deployment/" + harness.WEB_DEPLOYMENT, "/missing")
        contract_obj.configmap_name = ""
        with self.assertRaisesRegex(harness.InjectionError, "ConfigMap"):
            harness._configmap_name(contract_obj)

    def test_read_diff_evidence_keeps_missing_marker_without_values(self):
        observed = observation()
        observed.resources.pop("Deployment/" + harness.WEB_DEPLOYMENT)
        diffs = harness.read_diff_evidence(contract(), observed)
        self.assertTrue(diffs)
        self.assertEqual(diffs[0]["expected"], "present")
        self.assertTrue(diffs[0]["missing"])


class InjectSuccessCoverageTests(unittest.TestCase):
    def test_each_scenario_verifies_and_reports_the_change(self):
        clock = harness.Clock()
        run_id = "run"
        short = harness._short(run_id)
        frozen = contract()
        image = frozen.resources[0]["fields"]["/spec/template/spec/containers/web/image"]
        repository = image.split("@")[0]
        observed_docs = {
            "A": {"spec": {"replicas": 1}},
            "B": {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{"name": "web", "image": repository + ":drift-" + short}]
                        }
                    }
                }
            },
            "C": {"data": {harness.CONFIG_KEY: harness.CONFIG_DRIFT + "-" + short}},
            "D": None,
            "E": {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "web",
                                    "resources": {"limits": {"memory": harness.MEMORY_LIMIT_DRIFT}},
                                }
                            ]
                        }
                    }
                }
            },
            "F": {"spec": {"ports": [{"port": 8000, "targetPort": 65535}]}},
            "G": {"metadata": {"annotations": {harness.DRIFT_ANNOTATION: "scenario-g-" + short}}},
        }
        for scenario, observed in observed_docs.items():
            with self.subTest(scenario=scenario):
                fake = _InjectKubectl(observed=observed)
                result_injection = harness.inject(fake, frozen, scenario, run_id, clock)
                self.assertTrue(result_injection.accepted)
                self.assertEqual(len(result_injection.changed), 1)

    def test_scenario_a_uses_the_alternate_replica_candidate(self):
        frozen = copy.deepcopy(contract())
        frozen.baseline_hpa["min"] = 1
        fake = _InjectKubectl(observed={"spec": {"replicas": 1}})
        result_injection = harness.inject(fake, frozen, "A", "run", harness.Clock())
        self.assertEqual(result_injection.changed[0]["actual"], 1)


class RepairExtraCoverageTests(unittest.TestCase):
    def test_resource_only_deployment_and_missing_annotation(self):
        observed = observation()
        observed.resources["Deployment/" + harness.WEB_DEPLOYMENT]["fields"][
            "/spec/template/spec/containers/web/resources/limits/memory"
        ] = "1Gi"
        observed.resources["SealedSecret/" + harness.SEALED_SECRET]["fields"] = {}
        fake = mock.Mock()
        fake.apply.return_value = result()
        fake.patch.return_value = result()
        fake.annotate.return_value = result()
        commands = harness.repair(fake, contract(), observed, harness.Clock())
        self.assertEqual(len(commands), 1)
        fake.patch.assert_called_once()
        fake.annotate.assert_not_called()


class CleanupExtraCoverageTests(unittest.TestCase):
    def test_owner_match_and_not_found_deletes_clear_cleanup(self):
        fake = mock.Mock()
        fake.get.side_effect = [
            {"metadata": {"labels": {"experiment.invenio.ugm/run-id": "run"}}},
            None,
        ]
        fake.delete.return_value = result(code=1, stderr="not found")
        report = harness.cleanup_quarantine(fake, "exp-a", owner="run", wait_seconds=0)
        self.assertTrue(report.ok)
        self.assertEqual(len(report.results), 2)

    def test_cleanup_waits_then_reports_a_still_existing_namespace(self):
        fake = mock.Mock()
        fake.get.return_value = {"metadata": {"labels": {}}}
        fake.delete.return_value = result()
        with (
            mock.patch.object(harness.time, "monotonic", side_effect=[0.0, 0.0, 2.0]),
            mock.patch.object(harness.time, "sleep") as sleep,
        ):
            report = harness.cleanup_quarantine(fake, "exp-a", wait_seconds=1.0)
        self.assertFalse(report.ok)
        sleep.assert_called_once()

    def test_cleanup_verification_errors_are_reported(self):
        fake = mock.Mock()
        fake.get.side_effect = [
            {"metadata": {"labels": {}}},
            harness.HarnessError("verification failed"),
        ]
        fake.delete.return_value = result()
        report = harness.cleanup_quarantine(fake, "exp-a", wait_seconds=0)
        self.assertFalse(report.ok)
        fake = mock.Mock()
        fake.get.return_value = {"metadata": {"labels": {}}}
        fake.delete.side_effect = harness.HarnessError("delete failed")
        report = harness.cleanup_quarantine(fake, "exp-a", wait_seconds=0)
        self.assertFalse(report.ok)


class CliCoverageTests(unittest.TestCase):
    def test_parse_args_rejects_each_invalid_bound(self):
        cases = (
            ["--arm", "gitops", "--scenario", "A", "--rep", "0"],
            ["--arm", "gitops", "--scenario", "A", "--rep", "1", "--timeout", "0"],
            ["--arm", "gitops", "--scenario", "A", "--rep", "1", "--source-revision", "short"],
            ["--arm", "gitops", "--scenario", "A", "--rep", "1", "--render-sha256", "short"],
            ["--arm", "gitops", "--scenario", "A", "--rep", "1", "--run-id", "bad id"],
            ["--arm", "gitops", "--scenario", "A", "--rep", "1", "--run-id", "x" * 64],
        )
        for argv in cases:
            with (
                self.subTest(argv=argv),
                mock.patch("sys.stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit),
            ):
                harness.parse_args(argv)

    def test_validate_live_args_rejects_each_missing_requirement(self):
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            base = [
                "--arm",
                "gitops",
                "--scenario",
                "A",
                "--rep",
                "1",
                "--live",
                "--confirm-single-stack",
                "--namespace",
                "invenio",
                "--app",
                "invenio-bootstrap",
                "--render-file",
                str(path),
                "--source-revision",
                "b" * 40,
                "--render-sha256",
                digest,
            ]
            args = harness.parse_args(base)
            cases = (
                ("namespace_explicit", False, "--namespace must be explicit"),
                ("app_explicit", False, "--app must be explicit"),
                ("confirm_single_stack", False, "--confirm-single-stack"),
                ("render_sha256", None, "--render-sha256 is required"),
                ("source_revision", None, "--source-revision is required"),
                ("render_file", None, "--render-file is required"),
                ("render_file", "https://example/render.json", "local file"),
            )
            for attribute, value, message in cases:
                current = copy.copy(args)
                setattr(current, attribute, value)
                with (
                    self.subTest(attribute=attribute),
                    self.assertRaisesRegex(harness.SafetyError, message),
                ):
                    harness.validate_live_args(current, environ={"INVENIO_TOKEN": "x"})
            with self.assertRaises(harness.SeedVerificationError):
                harness.validate_live_args(args, environ={})
            broken = copy.copy(args)
            broken.render_file = str(Path(directory) / "missing.json")
            with self.assertRaisesRegex(harness.SafetyError, "invalid frozen render"):
                harness.validate_live_args(broken, environ={"INVENIO_TOKEN": "x"})

    def test_verify_one_stack_rejects_each_violation(self):
        class StackKubectl:
            def __init__(self, deployments, app=None, quarantine=None):
                self.deployments = deployments
                self.app = app
                self.quarantine = quarantine

            def get(self, kind, name=None, namespace=None, selector=None):
                if kind == "Deployment":
                    return self.deployments
                if kind == "Application":
                    return self.app
                return self.quarantine

        with self.assertRaises(harness.SafetyError):
            harness.verify_one_stack(StackKubectl({}), "invenio", "app", "argocd")
        with self.assertRaises(harness.SafetyError):
            harness.verify_one_stack(
                StackKubectl([{"metadata": {"namespace": "other"}}]), "invenio", "app", "argocd"
            )
        with self.assertRaises(harness.SafetyError):
            harness.verify_one_stack(
                StackKubectl([{"metadata": {"namespace": "invenio"}}], app=None),
                "invenio",
                "app",
                "argocd",
            )
        with self.assertRaises(harness.SafetyError):
            harness.verify_one_stack(
                StackKubectl(
                    [{"metadata": {"namespace": "invenio"}}],
                    app={"spec": {"destination": {"namespace": "other"}}},
                ),
                "invenio",
                "app",
                "argocd",
            )
        with self.assertRaises(harness.SafetyError):
            harness.verify_one_stack(
                StackKubectl(
                    [{"metadata": {"namespace": "invenio"}}],
                    app={"spec": {"destination": {"namespace": "invenio"}}},
                    quarantine={"kind": "Namespace"},
                ),
                "invenio",
                "app",
                "argocd",
            )

    def test_validate_live_args_returns_none_for_a_dry_run(self):
        args = harness.parse_args(["--arm", "gitops", "--scenario", "A", "--rep", "1"])
        self.assertIsNone(harness.validate_live_args(args, environ={}))

    def test_validate_live_args_returns_the_verified_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args(
                [
                    "--arm",
                    "gitops",
                    "--scenario",
                    "A",
                    "--rep",
                    "1",
                    "--live",
                    "--confirm-single-stack",
                    "--namespace",
                    "invenio",
                    "--app",
                    "invenio-bootstrap",
                    "--render-file",
                    str(path),
                    "--source-revision",
                    "b" * 40,
                    "--render-sha256",
                    digest,
                ]
            )
            with (
                mock.patch.object(harness, "Http"),
                mock.patch.object(harness, "verify_seed", return_value={"verified": True}),
            ):
                context = harness.validate_live_args(args, environ={"INVENIO_TOKEN": "x"})
            self.assertIsInstance(context["declaration"], harness.Declaration)

    def test_write_outputs_refuses_existing_row(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "run.jsonl").write_text("{}\n")
            args = argparse.Namespace(out=directory)
            with self.assertRaisesRegex(harness.SafetyError, "refusing to overwrite"):
                harness.write_outputs({"run_id": "run"}, args, out / "run", {"row": {}})


class RunnerHelperCoverageTests(unittest.TestCase):
    def runner(self, directory):
        path, digest = write_render(directory)
        args = harness.parse_args(
            [
                "--arm",
                "gitops",
                "--scenario",
                "A",
                "--rep",
                "1",
                "--live",
                "--confirm-single-stack",
                "--namespace",
                "invenio",
                "--app",
                "invenio-bootstrap",
                "--render-file",
                str(path),
                "--source-revision",
                "b" * 40,
                "--render-sha256",
                digest,
                "--out",
                directory,
            ]
        )
        frozen = harness.load_declaration(path, digest, "b" * 40, "invenio")
        return harness.LiveRunner(args, {"declaration": frozen}, FakeKubectl(), harness.Clock())

    def test_declaration_and_baseline_agreement_reject_mismatches(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            self.assertIsInstance(runner._declaration(), harness.Declaration)
            runner.preflight = {}
            with self.assertRaisesRegex(harness.SafetyError, "validated frozen render"):
                runner._declaration()
            runner = self.runner(directory)
            runner.args.source_revision = "c" * 40
            with self.assertRaisesRegex(harness.SafetyError, "identity"):
                runner._declaration()
            runner = self.runner(directory)
            runner.args.namespace = "exp-a"
            with self.assertRaisesRegex(harness.SafetyError, "namespace"):
                runner._declaration()
            runner = self.runner(directory)
            contract_obj = contract()
            baseline = observation()
            runner._require_baseline_agreement(contract_obj, baseline)
            baseline.resources.pop("Deployment/" + harness.WEB_DEPLOYMENT)
            with self.assertRaises(harness.BaselineError) as caught:
                runner._require_baseline_agreement(contract_obj, baseline)
            self.assertTrue(caught.exception.readiness_failures)
            baseline = observation()
            baseline.resources["ConfigMap/invenio-app-config-6dg2chdbh4"]["fields"][
                "/data/" + harness.CONFIG_KEY
            ] = "drift"
            with self.assertRaisesRegex(harness.BaselineError, "differs"):
                runner._require_baseline_agreement(contract_obj, baseline)

    def test_row_status_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            args = runner.args
            contract_obj = contract()
            cases = (
                (harness.ArmStateError("x"), "arm_state_mismatch"),
                (harness.InjectionError("x"), "invalid_injection"),
                (harness.InstrumentationError("x"), "instrumentation_failure"),
                (harness.BaselineError("x"), "baseline_failure"),
                (harness.SafetyError("x"), "safety_refusal"),
                (RuntimeError("x"), "failure"),
            )
            for failure, status in cases:
                with self.subTest(status=status):
                    row = runner._row(
                        "run", args, contract_obj, injection(), None, failure, None, None, None
                    )
                    self.assertEqual(row["status"], status)
            row = runner._row("run", args, None, None, None, None, None, None, None)
            self.assertEqual(row["status"], "failure")
            row = runner._row("run", args, None, None, None, None, None, "restore", None)
            self.assertEqual(row["status"], "arm_restore_failure")
            cleanup = harness.CleanupReport(ok=False, results=[], errors=["bad"])
            row = runner._row("run", args, None, None, None, None, cleanup, None, None)
            self.assertEqual(row["cleanup_status"], "failed")
            timeline = {
                "analysis_group": "hpa_control",
                "efficacy_eligible": False,
                "stop_reason": "timeout",
                "injection_seconds": 0.1,
                "detection_seconds": None,
                "evidence_seconds": None,
                "recovery_seconds": None,
                "detection_status": "right_censored",
                "evidence_status": "right_censored",
                "recovery_status": "right_censored",
                "detection_controller": None,
                "recovery_controller": None,
                "detection_ref": None,
                "evidence_ref": None,
                "detection_reads": [],
                "evidence_reads": [],
                "recovery_reads": [],
                "t_r_first_seconds": None,
                "t_r_confirmed_seconds": None,
                "recovery_confirmation": "none",
                "r1_baseline_reason": None,
                "r1_first_reason": None,
                "r1_last_reason": None,
                "window_completed": True,
                "r1_baseline": None,
                "r1_first": None,
                "r1_last": None,
                "kubectl_cmds": 0,
                "r1_baseline_details": None,
                "r1_first_details": None,
                "r1_last_details": None,
                "max_sample_gap_seconds": None,
                "t_d": None,
                "t_e": None,
                "t_e_store": None,
                "t_r": None,
                "t_r_first": None,
                "t_r_confirmed": None,
                "window_end": None,
                "t0": point(0),
                "observation_end": None,
                "status": "right_censored",
            }
            row = runner._row(
                "run", args, None, injection(), timeline, None, None, None, {"verified": False}
            )
            self.assertEqual(row["status"], "reset_failure")

    def test_main_maps_live_exit_codes(self):
        class FakeRunner:
            def __init__(self, *args, **kwargs):
                pass

            def run(self):
                return 0

        live = ["--arm", "gitops", "--scenario", "A", "--rep", "1", "--live"]
        with (
            mock.patch.object(harness, "validate_live_args", return_value={}),
            mock.patch.object(harness, "LiveRunner", FakeRunner),
        ):
            self.assertEqual(harness.main(live), 0)
        with (
            mock.patch.object(harness, "validate_live_args", side_effect=harness.SafetyError("x")),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(harness.main(live), 2)
        with (
            mock.patch.object(
                harness, "validate_live_args", side_effect=harness.SeedVerificationError("x")
            ),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(harness.main(live), 3)

        class FailingRunner(FakeRunner):
            def run(self):
                raise harness.HarnessError("x")

        with (
            mock.patch.object(harness, "validate_live_args", return_value={}),
            mock.patch.object(harness, "LiveRunner", FailingRunner),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(harness.main(live), 1)

    def test_postcondition_deadline_and_scenario_a(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            runner.args.reset_timeout = 10.0
            runner.args.sample_interval = 0.0
            runner.kubectl = mock.Mock()
            runner.kubectl.pods.return_value = [{"name": "p", "phase": "Running", "ready": True}]

            class ClockValues:
                def __init__(self, values):
                    self.values = list(values)
                    self.index = 0

                def now(self):
                    value = self.values[min(self.index, len(self.values) - 1)]
                    self.index += 1
                    return point(value)

            class Snapshot:
                def __init__(self, observed):
                    self.observed = observed

                def capture(self):
                    return copy.deepcopy(self.observed)

            runner.clock = ClockValues([0.0, 0.0, 5.0, 20.0])
            result_postcondition = runner._postcondition(
                Snapshot(observation()), contract(), "B", "gitops"
            )
            self.assertEqual(result_postcondition["reason"], "deadline")
            runner.clock = ClockValues([0.0, 1.0, 1.0, 2.0, 2.0])
            result_postcondition = runner._postcondition(
                Snapshot(observation()), contract(), "A", "gitops"
            )
            self.assertTrue(result_postcondition["verified"])

    def test_sampler_records_late_results_and_late_errors(self):
        sampler = harness.Sampler(observation, harness.Clock(), 0.01)
        sampler._closed = True

        def capture():
            sampler._stop_event.set()
            return observation()

        sampler.capture = capture
        sampler.run()
        self.assertIsNotNone(sampler._late_result)
        sampler = harness.Sampler(observation, harness.Clock(), 0.01)
        sampler._closed = True
        sampler.capture = mock.Mock(side_effect=RuntimeError("late"))
        sampler.run()
        self.assertIsInstance(sampler.late_error, RuntimeError)
        sampler = harness.Sampler(observation, harness.Clock(), 0.01)
        sampler.capture = mock.Mock(side_effect=RuntimeError("open"))
        sampler.run()
        self.assertIsInstance(sampler.error, RuntimeError)
        self.assertIsNone(sampler.late_error)

    def test_sampler_stop_between_checks_returns_before_capture(self):
        sampler = harness.Sampler(observation, harness.Clock(), 0.01)
        sampler.deadline = 1.0
        calls = {"count": 0}

        class StopClock:
            def now(self):
                calls["count"] += 1
                if calls["count"] == 1:
                    sampler._stop_event.set()
                return point(0.0)

        sampler.clock = StopClock()
        sampler.capture = mock.Mock()
        sampler.run()
        sampler.capture.assert_not_called()


class LiveRunnerBranchCoverageTests(unittest.TestCase):
    def runner(self, directory, run_id, *, timeout="0.1", arm="gitops", scenario="B"):
        path, digest = write_render(directory)
        args = harness.parse_args(
            [
                "--arm",
                arm,
                "--scenario",
                scenario,
                "--rep",
                "1",
                "--live",
                "--confirm-single-stack",
                "--namespace",
                "invenio",
                "--app",
                "invenio-bootstrap",
                "--render-file",
                str(path),
                "--source-revision",
                "b" * 40,
                "--render-sha256",
                digest,
                "--timeout",
                timeout,
                "--sample-interval",
                "0.01",
                "--imperative-interval",
                "0.01",
                "--baseline-timeout",
                "5",
                "--reset-timeout",
                "1",
                "--out",
                directory,
                "--run-id",
                run_id,
            ]
        )
        frozen = harness.load_declaration(path, digest, "b" * 40, "invenio")
        objects = {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"): web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }
        clock = AdvancingClock()
        fake = FakeKubectl(objects=objects, clock=clock)
        return harness.LiveRunner(args, {"declaration": frozen}, fake, clock)

    def run_with(self, runner, directory, run_id, sampler):
        with (
            mock.patch("harness.Sampler", return_value=sampler),
            mock.patch("time.sleep", lambda _: None),
            mock.patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = runner.run()
        row = json.loads((Path(directory) / (run_id + ".jsonl")).read_text())
        return code, row

    def test_initial_sampler_error_and_empty_snapshot_are_failures(self):
        class ErrorSampler(DeterministicSampler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.error = RuntimeError("collector failed")
                self.stopped = {"joined": True, "in_flight": False}

            def stop(self):
                return dict(self.stopped)

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "collector-error")
            sampler = ErrorSampler(observation, runner.clock, 0.01)
            code, row = self.run_with(runner, directory, "collector-error", sampler)
        self.assertEqual(code, 1)
        self.assertIn("collector failed", row["error"])

        class EmptySampler(DeterministicSampler):
            def snapshot(self):
                return []

            def stop(self):
                return {"joined": True, "in_flight": False}

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "empty")
            sampler = EmptySampler(observation, runner.clock, 0.01)
            code, row = self.run_with(runner, directory, "empty", sampler)
        self.assertEqual(code, 1)
        self.assertIn("produced no sample", row["error"])

    def test_short_window_records_an_instrumentation_failure(self):
        timeline = {
            "analysis_group": "managed_drift",
            "efficacy_eligible": True,
            "stop_reason": "timeout",
            "injection_seconds": 0.1,
            "detection_seconds": None,
            "evidence_seconds": None,
            "recovery_seconds": None,
            "detection_status": "right_censored",
            "evidence_status": "right_censored",
            "recovery_status": "right_censored",
            "detection_controller": None,
            "recovery_controller": None,
            "detection_ref": None,
            "evidence_ref": None,
            "detection_reads": [],
            "evidence_reads": [],
            "recovery_reads": [],
            "t_r_first_seconds": None,
            "t_r_confirmed_seconds": None,
            "recovery_confirmation": "none",
            "r1_baseline_reason": None,
            "r1_first_reason": None,
            "r1_last_reason": None,
            "window_completed": False,
            "r1_baseline": None,
            "r1_first": None,
            "r1_last": None,
            "kubectl_cmds": 0,
            "r1_baseline_details": None,
            "r1_first_details": None,
            "r1_last_details": None,
            "max_sample_gap_seconds": None,
            "t_d": None,
            "t_e": None,
            "t_e_store": None,
            "t_r": None,
            "t_r_first": None,
            "t_r_confirmed": None,
            "window_end": None,
            "t0": point(100.0),
            "observation_end": None,
            "status": "right_censored",
        }

        def observe(_runner, _contract, _run_id, _evidence_dir, _sampler, _baseline, window):
            window.injection = injection()
            window.samples = [observation(at=100.0)]

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "short", timeout="100")
            runner.clock = mock.Mock()
            runner.clock.now.return_value = point(100.0)
            with (
                mock.patch.object(harness.LiveRunner, "_observe_until_recovery", observe),
                mock.patch.object(harness, "analyze_timeline", return_value=dict(timeline)),
            ):
                code, row = self.run_with(
                    runner,
                    directory,
                    "short",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
        self.assertEqual(code, 1)
        self.assertEqual(row["status"], "instrumentation_failure")

    def test_sampler_error_after_finalization_is_a_failure(self):
        class LateError(DeterministicSampler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.error = None
                self.late = True

            def stop(self):
                self.error = RuntimeError("late")
                return {"joined": True, "in_flight": False}

        def observe(_runner, _contract, _run_id, _evidence_dir, sampler, _baseline, window):
            window.injection = injection()
            window.samples = []
            sampler.error = RuntimeError("late")

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "late-error")
            sampler = LateError(observation, runner.clock, 0.01)
            timeline = {
                "recovery_seconds": 1.0,
                "window_completed": True,
                "t_e": None,
                "status": "observed",
                "analysis_group": "managed_drift",
                "efficacy_eligible": True,
                "stop_reason": "recovery",
                "injection_seconds": 0.1,
                "detection_seconds": 1.0,
                "evidence_seconds": None,
                "detection_status": "observed",
                "evidence_status": "right_censored",
                "recovery_status": "observed",
                "detection_controller": "argocd",
                "recovery_controller": "argocd",
                "detection_ref": "argo:invenio-bootstrap",
                "evidence_ref": None,
                "detection_reads": [],
                "evidence_reads": [],
                "recovery_reads": [],
                "t_r_first_seconds": 1.0,
                "t_r_confirmed_seconds": 2.0,
                "recovery_confirmation": "confirmed",
                "r1_baseline_reason": None,
                "r1_first_reason": None,
                "r1_last_reason": None,
                "r1_baseline": None,
                "r1_first": None,
                "r1_last": None,
                "kubectl_cmds": 0,
                "r1_baseline_details": None,
                "r1_first_details": None,
                "r1_last_details": None,
                "max_sample_gap_seconds": None,
                "t_d": point(101.0),
                "t_e_store": None,
                "t_r": point(101.0),
                "t_r_first": point(101.0),
                "t_r_confirmed": point(102.0),
                "window_end": point(102.0),
                "t0": point(100.0),
                "observation_end": None,
            }
            with (
                mock.patch.object(harness.LiveRunner, "_observe_until_recovery", observe),
                mock.patch.object(harness, "analyze_timeline", return_value=dict(timeline)),
            ):
                code, row = self.run_with(runner, directory, "late-error", sampler)
        self.assertEqual(code, 1)
        self.assertIn("late", row["error"])

    def test_arm_pause_failure_reconstructs_arm_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "arm-failure", arm="imperative")
            runner.kubectl = FakeKubectl(
                objects=runner.kubectl.objects, fail_patch=True, clock=runner.clock
            )
            sampler = DeterministicSampler(observation, runner.clock, 0.01)
            code, _row = self.run_with(runner, directory, "arm-failure", sampler)
            arm = json.loads((Path(directory) / "arm-failure" / "arm.json").read_text())
        self.assertEqual(code, 1)
        self.assertTrue(arm["paused"])
        self.assertTrue(arm["original"])

    def test_cleanup_restore_and_postcondition_failures_are_reported(self):
        class Fallback:
            def __init__(self):
                self.calls = 0

            def __call__(self, *args, **kwargs):
                self.calls += 1
                return {"verified": False, "error": "postcondition failed"}

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "cleanup-error")
            with mock.patch.object(
                harness, "cleanup_quarantine", side_effect=RuntimeError("cleanup boom")
            ):
                code, row = self.run_with(
                    runner,
                    directory,
                    "cleanup-error",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(code, 1)
            self.assertEqual(row["cleanup_status"], "failed")

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "restore-error")
            with mock.patch.object(
                harness.ArmController,
                "restore",
                side_effect=harness.ArmRestoreError("restore boom"),
            ):
                code, row = self.run_with(
                    runner,
                    directory,
                    "restore-error",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(code, 1)
            self.assertEqual(row["arm_restore_status"], "failed")

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "postcondition-error")
            fallback = mock.Mock(side_effect=RuntimeError("postcondition failed"))
            with mock.patch.object(harness.LiveRunner, "_postcondition", fallback):
                code, row = self.run_with(
                    runner,
                    directory,
                    "postcondition-error",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(fallback.call_count, 3)
            self.assertFalse(row["postcondition"]["verified"])

    def test_postcondition_retry_can_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "postcondition-retry")
            calls = {"count": 0}

            def flaky(*args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    raise RuntimeError("transient")
                return {"verified": True}

            with mock.patch.object(harness.LiveRunner, "_postcondition", flaky):
                _code, row = self.run_with(
                    runner,
                    directory,
                    "postcondition-retry",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(calls["count"], 2)
            self.assertTrue(row["postcondition"]["verified"])


class RunnerFlowCoverageTests(LiveRunnerBranchCoverageTests):
    def test_timeline_none_and_completed_window_paths(self):
        def observe(_runner, _contract, _run_id, _evidence_dir, _sampler, _baseline, window):
            window.injection = injection()
            window.samples = [observation(at=100.0)]

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "no-timeline")
            with (
                mock.patch.object(harness.LiveRunner, "_observe_until_recovery", observe),
                mock.patch.object(harness, "analyze_timeline", return_value=None),
            ):
                code, row = self.run_with(
                    runner,
                    directory,
                    "no-timeline",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "failure")

        timeline = {
            "recovery_seconds": 1.0,
            "window_completed": True,
            "t_e": None,
            "status": "observed",
            "analysis_group": "managed_drift",
            "efficacy_eligible": True,
            "stop_reason": "recovery",
            "injection_seconds": 0.1,
            "detection_seconds": 1.0,
            "evidence_seconds": None,
            "detection_status": "observed",
            "evidence_status": "right_censored",
            "recovery_status": "observed",
            "detection_controller": "argocd",
            "recovery_controller": "argocd",
            "detection_ref": "argo:invenio-bootstrap",
            "evidence_ref": None,
            "detection_reads": [],
            "evidence_reads": [],
            "recovery_reads": [],
            "t_r_first_seconds": 1.0,
            "t_r_confirmed_seconds": 2.0,
            "recovery_confirmation": "confirmed",
            "r1_baseline_reason": None,
            "r1_first_reason": None,
            "r1_last_reason": None,
            "r1_baseline": None,
            "r1_first": None,
            "r1_last": None,
            "kubectl_cmds": 0,
            "r1_baseline_details": None,
            "r1_first_details": None,
            "r1_last_details": None,
            "max_sample_gap_seconds": None,
            "t_d": point(101.0),
            "t_e_store": None,
            "t_r": point(101.0),
            "t_r_first": point(101.0),
            "t_r_confirmed": point(102.0),
            "window_end": point(102.0),
            "t0": point(100.0),
            "observation_end": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "complete-window")
            runner.clock = mock.Mock()
            runner.clock.now.return_value = point(200.0)
            with (
                mock.patch.object(harness.LiveRunner, "_observe_until_recovery", observe),
                mock.patch.object(harness, "analyze_timeline", return_value=dict(timeline)),
            ):
                code, row = self.run_with(
                    runner,
                    directory,
                    "complete-window",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(code, 0)
            self.assertEqual(row["status"], "observed")

    def test_missing_injection_skips_the_timeline_block(self):
        def observe(_runner, _contract, _run_id, _evidence_dir, _sampler, _baseline, window):
            window.samples = [observation(at=100.0)]

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "no-injection")
            with mock.patch.object(harness.LiveRunner, "_observe_until_recovery", observe):
                code, row = self.run_with(
                    runner,
                    directory,
                    "no-injection",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "failure")

    def test_non_harness_exception_is_recorded_as_failure(self):
        def observe(*args, **kwargs):
            raise RuntimeError("unexpected")

        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, "unexpected")
            with mock.patch.object(harness.LiveRunner, "_observe_until_recovery", observe):
                code, row = self.run_with(
                    runner,
                    directory,
                    "unexpected",
                    DeterministicSampler(observation, runner.clock, 0.01),
                )
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "failure")


class ObservationLoopCoverageTests(unittest.TestCase):
    def runner(self, directory, arm="gitops", scenario="B"):
        path, digest = write_render(directory)
        args = harness.parse_args(
            [
                "--arm",
                arm,
                "--scenario",
                scenario,
                "--rep",
                "1",
                "--live",
                "--confirm-single-stack",
                "--namespace",
                "invenio",
                "--app",
                "invenio-bootstrap",
                "--render-file",
                str(path),
                "--source-revision",
                "b" * 40,
                "--render-sha256",
                digest,
                "--timeout",
                "5",
                "--sample-interval",
                "0.01",
                "--out",
                directory,
                "--run-id",
                "loop",
            ]
        )
        frozen = harness.load_declaration(path, digest, "b" * 40, "invenio")
        return harness.LiveRunner(
            args, {"declaration": frozen}, FakeKubectl(), AdvancingClock(step=1)
        )

    class LoopSampler:
        def __init__(self, samples):
            self.samples = samples
            self.error = None
            self.deadline = None

        def snapshot(self):
            return list(self.samples)

        def stop(self):
            return {"joined": True, "in_flight": False}

    def test_collector_evidence_write_failure_and_scenario_a_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            sampler = self.LoopSampler([observation(at=101.0)])
            with (
                mock.patch.object(harness, "inject", return_value=injection()),
                mock.patch.object(
                    harness, "field_diffs", return_value=[{"resource": "Deployment/invenio-web"}]
                ),
                mock.patch.object(harness, "_reads_eligible", return_value=True),
                mock.patch.object(harness, "_write_json", side_effect=OSError("disk")),
                self.assertRaisesRegex(harness.InstrumentationError, "collector evidence write"),
            ):
                runner._observe_until_recovery(
                    contract(),
                    "loop",
                    Path(directory),
                    sampler,
                    observation(),
                    harness._ObservationWindow(),
                )
            runner = self.runner(directory, scenario="A")
            window = harness._ObservationWindow()
            with (
                mock.patch.object(harness, "inject", return_value=injection()),
                mock.patch.object(harness, "hpa_changed", return_value=True),
                mock.patch.object(harness, "_reads_eligible", return_value=True),
            ):
                runner._observe_until_recovery(
                    contract(), "loop", Path(directory), sampler, observation(), window
                )
            self.assertEqual(window.evidence_ref, "samples.jsonl")

    def test_imperative_evidence_write_and_repair_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory, arm="imperative")
            sampler = self.LoopSampler([observation(at=101.0)])
            with (
                mock.patch.object(harness, "inject", return_value=injection()),
                mock.patch.object(
                    harness, "field_diffs", return_value=[{"resource": "Deployment/invenio-web"}]
                ),
                mock.patch.object(harness, "_reads_eligible", return_value=True),
                mock.patch.object(harness, "_write_json", side_effect=OSError("disk")),
                self.assertRaisesRegex(harness.InstrumentationError, "imperative evidence write"),
            ):
                runner._observe_until_recovery(
                    contract(),
                    "loop",
                    Path(directory),
                    sampler,
                    observation(),
                    harness._ObservationWindow(evidence_at=point(1.0)),
                )
            window = harness._ObservationWindow(evidence_at=point(1.0))
            with (
                mock.patch.object(harness, "inject", return_value=injection()),
                mock.patch.object(
                    harness, "field_diffs", return_value=[{"resource": "Deployment/invenio-web"}]
                ),
                mock.patch.object(harness, "_reads_eligible", return_value=True),
                mock.patch.object(harness, "_write_json"),
                mock.patch.object(harness, "repair", return_value=[result(code=1)]),
            ):
                runner._observe_until_recovery(
                    contract(), "loop", Path(directory), sampler, observation(), window
                )
            self.assertTrue(window.imperative.failed)

    def test_two_samples_break_when_recovery_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = self.runner(directory)
            sampler = self.LoopSampler([observation(at=101.0), observation(at=102.0)])
            window = harness._ObservationWindow()
            with (
                mock.patch.object(harness, "inject", return_value=injection()),
                mock.patch.object(
                    harness, "analyze_timeline", return_value={"recovery_seconds": 1.0}
                ),
            ):
                runner._observe_until_recovery(
                    contract(), "loop", Path(directory), sampler, observation(), window
                )
            self.assertEqual(len(window.samples), 2)


if __name__ == "__main__":
    unittest.main()
