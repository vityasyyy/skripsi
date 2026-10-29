"""Offline regressions for the live InvenioRDM harness.

No test starts a cluster process. `subprocess.run` is patched where the dry-run
path could reach it and every kubectl interaction in the remaining tests uses
an in-memory fake.
"""
import copy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live"
sys.path.insert(0, str(LIVE))

import harness  # noqa: E402
import convert  # noqa: E402


def point(mono, utc="2026-10-27T00:00:00+00:00"):
    return harness.Point(mono=mono, utc=utc)


def result(argv=None, code=0, stdout="", stderr="", started=None, finished=None):
    return harness.CommandResult(
        argv=argv or ["kubectl"], returncode=code, stdout=stdout,
        stderr=stderr, started=started or point(0),
        finished=finished or point(0),
    )


def web_deployment(image="ghcr.io/vityasyyy/invenio-ugm@sha256:" + "a" * 64):
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "invenio-web",
            "namespace": "invenio",
            "uid": "server-uid",
            "resourceVersion": "42",
            "generation": 3,
            "managedFields": [{"manager": "argocd"}],
            "creationTimestamp": "2026-10-25T00:00:00Z",
            "annotations": {
                "kubectl.kubernetes.io/last-applied-configuration": "{secret-ish noise}",
                "deployment.kubernetes.io/revision": "7",
            },
            "labels": {"app.kubernetes.io/name": "invenio-web"},
        },
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": {"app.kubernetes.io/name": "invenio-web"}},
            "template": {
                "metadata": {
                    "creationTimestamp": None,
                    "labels": {"app.kubernetes.io/name": "invenio-web"},
                },
                "spec": {
                    "containers": [{
                        "name": "web",
                        "image": image,
                        "envFrom": [
                            {"configMapRef": {"name": "invenio-app-config-6dg2chdbh4"}},
                            {"secretRef": {"name": "invenio-app-secrets"}},
                        ],
                        "resources": {
                            "requests": {"cpu": "250m", "memory": "512Mi"},
                            "limits": {"cpu": "1", "memory": "2Gi"},
                        },
                    }],
                },
            },
        },
        "status": {"replicas": 2, "readyReplicas": 2},
    }


def web_configmap(tagline="Share your research."):
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "invenio-app-config-6dg2chdbh4",
            "namespace": "invenio",
            "resourceVersion": "9",
            "uid": "cm-uid",
        },
        "data": {"INSTANCE_NAME": "UGM Research Data Repository",
                 "INSTANCE_TAGLINE": tagline},
    }


def sealed_secret(annotations=None):
    return {
        "apiVersion": "bitnami.com/v1alpha1",
        "kind": "SealedSecret",
        "metadata": {
            "name": "invenio-app-secrets",
            "namespace": "invenio",
            "resourceVersion": "3",
            "uid": "ss-uid",
            "annotations": annotations or {},
        },
        "spec": {"encryptedData": {"INVENIO_SECRET_KEY": "PLAINTEXT-MUST-NOT-LEAK"}},
    }


def web_service():
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "invenio-web", "namespace": "invenio"},
        "spec": {
            "type": "ClusterIP",
            "selector": {"app.kubernetes.io/name": "invenio-web"},
            "ports": [{"port": 8000, "targetPort": "http"}],
            "clusterIP": "10.43.0.10",
            "clusterIPs": ["10.43.0.10"],
        },
    }


def web_hpa(desired=2, current=2, spec_replicas=2, last_scale="2026-10-27T00:00:00Z",
            generation=1, observed_generation=1):
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": "invenio-web-hpa", "namespace": "invenio",
                     "generation": generation},
        "spec": {
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment",
                               "name": "invenio-web"},
            "minReplicas": 2,
            "maxReplicas": 4,
        },
        "status": {
            "currentReplicas": current,
            "desiredReplicas": desired,
            "observedGeneration": observed_generation,
            "lastScaleTime": last_scale,
            "conditions": [{"type": "AbleToScale", "status": "True"}],
        },
    }


def application(name="invenio-bootstrap", automated=None, sync="Synced"):
    if automated is None:
        automated = {"prune": True, "selfHeal": True}
    return {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Application",
        "metadata": {
            "name": name,
            "namespace": "argocd",
            "uid": "uid-" + name,
            "resourceVersion": "10",
            "annotations": {"argocd.argoproj.io/refresh-timestamp": "old"},
        },
        "spec": {
            "project": "default",
            "source": {"repoURL": "https://example.invalid/repo", "path": "apps"},
            "destination": {"server": "https://kubernetes.default.svc",
                            "namespace": "argocd" if name == "apps" else "invenio"},
            "syncPolicy": {"automated": automated,
                           "syncOptions": ["CreateNamespace=true"]},
        },
        "status": {
            "sync": {"status": sync, "revision": "b" * 40},
            "health": {"status": "Healthy"},
            "operationState": {"phase": "Succeeded"},
        },
    }


def observation(at=0, deployment=None, configmap=None, secret=None, service=None,
                hpa=None, argo=None, extras=None):
    deployment = deployment or web_deployment()
    objects = [deployment, configmap or web_configmap(), secret or sealed_secret(),
               service or web_service()]
    return harness.observation_from_objects(
        objects, at=point(at),
        argo=argo or {"invenio-bootstrap": harness.application_state(application()),
                      "apps": harness.application_state(application("apps"))},
        hpa=hpa or harness.hpa_state(web_hpa(), deployment),
        extras=extras or [],
    )


def contract(obs=None):
    obs = obs or observation()
    return harness.build_contract(
        obs, namespace="invenio", quarantine_namespace="exp-invenio-drift",
        source_revision="b" * 40, render_sha256="c" * 64,
    )


def node_object(name, cpu="4", memory="8Gi"):
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {"name": name},
        "status": {"allocatable": {"cpu": cpu, "memory": memory}},
    }


def node_metric(name, cpu="500m", memory="1Gi",
                timestamp="2026-10-27T00:00:00Z", window="30s"):
    return {
        "metadata": {"name": name},
        "timestamp": timestamp,
        "window": window,
        "usage": {"cpu": cpu, "memory": memory},
    }


def node_metrics(*items):
    return {"kind": "NodeMetricsList", "apiVersion": "metrics.k8s.io/v1beta1",
            "items": list(items)}


def node_inventory(*items):
    return {"kind": "List", "apiVersion": "v1", "items": list(items)}


READY_POD = {"name": "invenio-web-1", "phase": "Running", "ready": True}
UNREADY_POD = {"name": "invenio-web-1", "phase": "Running", "ready": False}
DEFAULT_NODES = [{"name": "worker-01", "cpu_percent": 10, "memory_percent": 20}]


def injection(started=100.0, ack=100.1, verified=100.2, accepted=True,
              changed=None):
    return harness.Injection(
        started=point(started), acknowledged=point(ack), verified=point(verified),
        accepted=accepted, changed=changed or [
            {"resource": "Deployment/invenio-web",
             "path": "/spec/template/spec/containers/web/image",
             "effect": "value_changed", "matches_desired": False,
             "expected": "baseline", "actual": "drift"}],
        commands=[], error=None,
    )


class FakeKubectl:
    """In-memory kubectl with just the high-level operations the harness uses."""

    def __init__(self, apps=None, objects=None, fail_patch=False,
                 no_op_patch=False, fail_delete=False):
        self.apps = apps or {
            "apps": application("apps"),
            "invenio-bootstrap": application(),
        }
        self.objects = objects or {}
        self.fail_patch = fail_patch
        self.no_op_patch = no_op_patch
        self.fail_delete = fail_delete
        self.patches = []
        self.deletes = []
        self.applies = []
        self.annotations = []

    def get(self, kind, name=None, namespace=None, selector=None):
        if kind == "Application":
            return copy.deepcopy(self.apps.get(name))
        key = (kind, name, namespace)
        if name is None:
            return [copy.deepcopy(value) for (k, _, ns), value in self.objects.items()
                    if k == kind and (namespace is None or ns == namespace)]
        return copy.deepcopy(self.objects.get(key))

    def patch(self, kind, name, namespace, patch, patch_type="merge"):
        if self.fail_patch:
            return result(code=1, stderr="patch failed")
        self.patches.append((kind, name, namespace, copy.deepcopy(patch), patch_type))
        if kind == "Application":
            app = self.apps.get(name)
            if app is not None and not self.no_op_patch:
                sync = patch.get("spec", {}).get("syncPolicy", {})
                if "automated" in sync:
                    app["spec"]["syncPolicy"]["automated"] = copy.deepcopy(
                        sync["automated"])
        else:
            key = (kind, name, namespace)
            doc = self.objects.get(key)
            if doc is not None and not self.no_op_patch:
                _merge(doc, patch)
        return result()

    def annotate(self, kind, name, namespace, key, value=None):
        self.annotations.append((kind, name, namespace, key, value))
        doc = self.objects.get((kind, name, namespace))
        if doc is not None:
            annotations = doc.setdefault("metadata", {}).setdefault("annotations", {})
            if value is None:
                annotations.pop(key, None)
            else:
                annotations[key] = value
        return result()

    def apply(self, manifest):
        self.applies.append(copy.deepcopy(manifest))
        key = (manifest["kind"], manifest["metadata"]["name"],
               manifest["metadata"].get("namespace"))
        self.objects[key] = copy.deepcopy(manifest)
        return result()

    def delete(self, kind, name, namespace, wait=False):
        self.deletes.append((kind, name, namespace, wait))
        if self.fail_delete:
            return result(code=1, stderr="delete failed")
        self.objects.pop((kind, name, namespace), None)
        return result()

    def top_nodes(self):
        return [{"name": "worker-01", "cpu_percent": 10, "memory_percent": 40},
                {"name": "worker-02", "cpu_percent": 12, "memory_percent": 45}]

    def pods(self, namespace):
        return [{"name": "invenio-web-1", "phase": "Running", "ready": True}]


def _merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        elif isinstance(value, list) and isinstance(target.get(key), list):
            for item in value:
                if isinstance(item, dict) and "name" in item:
                    for existing in target[key]:
                        if existing.get("name") == item["name"]:
                            _merge(existing, item)
                            break
                    else:
                        target[key].append(copy.deepcopy(item))
                else:
                    target[key].append(copy.deepcopy(item))
        else:
            target[key] = copy.deepcopy(value)


class SafetyTests(unittest.TestCase):
    def test_allows_only_invenio_or_exp_namespaces(self):
        self.assertEqual(harness.validate_namespace("invenio"), "invenio")
        self.assertEqual(harness.validate_namespace("exp-arm-a"), "exp-arm-a")
        for unsafe in ("argocd", "kube-system", "database", "invenio-drift",
                       "exp", "../invenio", ""):
            with self.subTest(namespace=unsafe):
                with self.assertRaises(harness.SafetyError):
                    harness.validate_namespace(unsafe)

    def test_quarantine_is_an_exp_namespace(self):
        self.assertEqual(harness.quarantine_namespace("invenio"), "exp-invenio-drift")
        self.assertEqual(harness.quarantine_namespace("exp-arm-a"),
                         "exp-exp-arm-a-drift")
        self.assertTrue(harness.validate_namespace(
            harness.quarantine_namespace("invenio")).startswith("exp-"))

    def test_live_requires_confirm_single_stack(self):
        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
            "--namespace", "invenio", "--app", "invenio-bootstrap",
        ])
        with self.assertRaises(harness.SafetyError):
            harness.validate_live_args(args, environ={"INVENIO_TOKEN": "x"})

    def test_live_requires_token_and_explicit_arm_state(self):
        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
            "--namespace", "invenio", "--app", "invenio-bootstrap", "--confirm-single-stack",
        ])
        with self.assertRaises(harness.SeedVerificationError):
            harness.validate_live_args(args, environ={})

    def test_live_requires_explicit_namespace_and_app(self):
        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
            "--namespace", "invenio", "--confirm-single-stack",
        ])
        with self.assertRaises(harness.SafetyError):
            harness.validate_live_args(args, environ={"INVENIO_TOKEN": "x"})
        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
            "--app", "invenio-bootstrap", "--confirm-single-stack",
        ])
        with self.assertRaises(harness.SafetyError):
            harness.validate_live_args(args, environ={"INVENIO_TOKEN": "x"})

    def test_read_retries_a_transient_response_body_timeout(self):
        kubectl = harness.Kubectl(harness.FakeClock([1.0, 1.1, 1.2]))
        bad = result(code=1, stderr="Unexpected error when reading response body")
        good = result(stdout='{"kind":"ConfigMap","metadata":{"name":"x"}}')
        with mock.patch.object(kubectl, "run", side_effect=[bad, good]) as run:
            configmap = kubectl.get("ConfigMap", "x", "invenio")
        self.assertEqual(configmap["metadata"]["name"], "x")
        self.assertEqual(run.call_count, 2)

    def test_cluster_wide_inventory_uses_all_namespaces(self):
        completed = mock.Mock(returncode=0, stdout='{"items": []}', stderr="")
        kubectl = harness.Kubectl(harness.FakeClock([1.0]))
        with mock.patch("harness.subprocess.run", return_value=completed) as run:
            kubectl.get("Deployment", selector="app.kubernetes.io/name=invenio-web")
        argv = run.call_args.args[0]
        self.assertIn("--all-namespaces", argv)
        self.assertNotIn("-n", argv)

    def test_http_with_token_is_refused_off_loopback(self):
        with self.assertRaises(harness.SafetyError):
            harness.Http("token", base_url="http://invenio.example")
        self.assertIsInstance(harness.Http("token", base_url="http://127.0.0.1:8080"),
                              harness.Http)

    def test_http_sets_a_stable_user_agent(self):
        response = mock.MagicMock()
        response.status = 200
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        http = harness.Http("token")
        http._opener = mock.MagicMock()
        http._opener.open.return_value = response
        status, body = http.get("/api/me")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"{}")
        request = http._opener.open.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), harness.USER_AGENT)

    def test_cross_host_redirect_drops_api_auth_headers(self):
        handler = harness._CrossHostRedirectHandler()
        request = harness.urlrequest.Request(
            "https://invenio.example/api/records/x/draft/files/y/content",
            headers={"Authorization": "Bearer tok", "Accept": "application/octet-stream"},
        )
        redirected = handler.redirect_request(
            request, None, 302, "Found", {},
            "https://minio.example/bucket/key?signature=redacted",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertIsNone(redirected.get_header("Accept"))

    def test_no_token_is_ever_printed(self):
        secret = "tok-SECRET-123"
        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
            "--namespace", "invenio", "--app", "invenio-bootstrap",
            "--confirm-single-stack",
            "--source-revision", "b" * 40, "--render-sha256", "c" * 64,
        ])
        with mock.patch("harness.Http") as http:
            http.return_value.get.side_effect = harness.HarnessError("boom")
            with self.assertRaises(harness.HarnessError) as caught:
                harness.validate_live_args(args, environ={"INVENIO_TOKEN": secret})
        self.assertNotIn(secret, str(caught.exception))


class SanitizerTests(unittest.TestCase):
    def test_secret_material_and_server_fields_are_removed(self):
        sanitized = harness.sanitize_object(sealed_secret())
        text = json.dumps(sanitized)
        self.assertNotIn("PLAINTEXT-MUST-NOT-LEAK", text)
        self.assertNotIn("encryptedData", text)
        self.assertEqual(sanitized["metadata"]["name"], "invenio-app-secrets")

    def test_deployment_server_fields_and_last_applied_are_removed(self):
        sanitized = harness.sanitize_object(web_deployment())
        text = json.dumps(sanitized)
        self.assertNotIn("server-uid", text)
        self.assertNotIn("last-applied", text)
        self.assertNotIn("managedFields", text)
        self.assertNotIn('"status"', text)
        self.assertEqual(sanitized["spec"]["template"]["spec"]["containers"][0]
                         ["image"].split("@")[0],
                         "ghcr.io/vityasyyy/invenio-ugm")

    def test_recovery_manifest_never_owns_hpa_replicas(self):
        manifest = harness.recovery_manifest(harness.sanitize_object(web_deployment()),
                                             hpa_owned=True)
        self.assertNotIn("replicas", manifest["spec"])

    def test_application_evidence_has_no_server_metadata(self):
        evidence = harness.sanitize_application(application())
        text = json.dumps(evidence)
        self.assertNotIn("uid-invenio-bootstrap", text)
        self.assertNotIn("resourceVersion", text)
        self.assertNotIn("status", text)


class ContractTests(unittest.TestCase):
    def test_baseline_scores_full_and_hpa_replicas_are_excluded(self):
        obs = observation()
        spec = contract(obs)
        self.assertEqual(harness.score(spec, obs), 100)
        self.assertEqual(spec.configmap_name, "invenio-app-config-6dg2chdbh4")
        deployment = next(r for r in spec.resources if r["kind"] == "Deployment")
        self.assertNotIn("/spec/replicas", deployment["fields"])
        changed = observation(deployment=web_deployment())
        changed.resources["Deployment/invenio-web"]["fields"][
            "/spec/template/spec/containers/web/image"] = "drift:tag"
        self.assertLess(harness.score(spec, changed), 100)

    def test_missing_resource_is_a_mismatch_not_an_instrumentation_error(self):
        spec = contract()
        obs = observation()
        obs.resources.pop("Deployment/invenio-web")
        self.assertLess(harness.score(spec, obs), 100)
        self.assertTrue(any(diff.get("missing") for diff in
                            harness.field_diffs(spec, obs)))

    def test_configmap_tagline_and_sealed_annotation_are_contract_fields(self):
        spec = contract()
        self.assertIn("/data/INSTANCE_TAGLINE",
                      next(r for r in spec.resources
                           if r["kind"] == "ConfigMap")["fields"])
        sealed = next(r for r in spec.resources if r["kind"] == "SealedSecret")
        self.assertIn("/metadata/annotations/" + harness.DRIFT_ANNOTATION,
                      sealed["fields"])
        self.assertNotIn("encryptedData", json.dumps(spec.as_dict()))

    def test_hpa_settled_allows_absent_generation_fields(self):
        state = {"desired": 2, "current": 2, "deployment_spec_replicas": 2,
                 "min": 2, "max": 4, "able_to_scale": True,
                 "generation": None, "observed_generation": None}
        self.assertTrue(harness.hpa_settled(state))
        state["observed_generation"] = 3
        self.assertFalse(harness.hpa_settled(state))

    def test_extra_quarantine_object_does_not_change_managed_r1(self):
        spec = contract()
        obs = observation(extras=["exp-invenio-drift/Deployment/invenio-web"])
        self.assertEqual(harness.score(spec, obs), 100)
        self.assertTrue(obs.extra_resources)


class NodeMetricsTests(unittest.TestCase):
    def read(self, responses):
        kubectl = harness.Kubectl(
            harness.FakeClock([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), timeout=1)
        with mock.patch.object(kubectl, "run", side_effect=responses) as run:
            return kubectl.top_nodes(), run

    def ok(self, metrics, nodes):
        return self.read([
            result(stdout=json.dumps(metrics), started=point(10),
                   finished=point(11)),
            result(stdout=json.dumps(nodes), started=point(12),
                   finished=point(13)),
        ])[0]

    def test_raw_usage_and_allocatable_use_kubernetes_quantity_semantics(self):
        values, run = self.read([
            result(stdout=json.dumps(node_metrics(
                node_metric("worker-01", "250m", "1.5Gi"),
                node_metric("worker-02", "1500000u", "1536Mi"))),
                started=point(10), finished=point(11)),
            result(stdout=json.dumps(node_inventory(
                node_object("worker-01", "2", "4Gi"),
                node_object("worker-02", "4", "4Gi"))),
                started=point(12), finished=point(13)),
        ])
        first, second = values
        self.assertEqual(first["name"], "worker-01")
        self.assertEqual(first["cpu_usage"], "250m")
        self.assertEqual(first["memory_usage"], "1.5Gi")
        self.assertEqual(first["cpu_allocatable"], "2")
        self.assertEqual(first["memory_allocatable"], "4Gi")
        self.assertEqual(first["cpu_usage_nanocores"], 250_000_000)
        self.assertEqual(first["cpu_allocatable_nanocores"], 2_000_000_000)
        self.assertEqual(first["memory_usage_bytes"], 1_610_612_736)
        self.assertEqual(first["memory_allocatable_bytes"], 4_294_967_296)
        self.assertAlmostEqual(first["cpu_percent"], 12.5)
        self.assertAlmostEqual(first["memory_percent"], 37.5)
        self.assertEqual(first["metrics_timestamp"], "2026-10-27T00:00:00Z")
        self.assertEqual(first["metrics_window"], "30s")
        self.assertEqual(first["metrics_window_seconds"], 30.0)
        self.assertEqual(first["acquisition"]["metrics"]["started_mono"], 10)
        self.assertEqual(first["acquisition"]["metrics"]["finished_mono"], 11)
        self.assertIn("allocatable", first["acquisition"])
        self.assertEqual(second["cpu_usage_nanocores"], 1_500_000_000)
        self.assertEqual(second["memory_usage_bytes"], 1_610_612_736)
        metric_argv = run.call_args_list[0].args[0]
        self.assertEqual(metric_argv[:3],
                         ["get", "--raw", "/apis/metrics.k8s.io/v1beta1/nodes"])
        self.assertNotIn("top", metric_argv)

    def test_fractional_decimal_and_binary_quantities_are_exact(self):
        values = self.ok(
            node_metrics(node_metric("worker-01", "1.5", "1.5G")),
            node_inventory(node_object("worker-01", "2.5", "3Gi")))
        node = values[0]
        self.assertEqual(node["cpu_usage_nanocores"], 1_500_000_000)
        self.assertEqual(node["cpu_allocatable_nanocores"], 2_500_000_000)
        self.assertEqual(node["memory_usage_bytes"], 1_500_000_000)
        self.assertEqual(node["memory_allocatable_bytes"], 3_221_225_472)
        self.assertAlmostEqual(node["cpu_percent"], 60.0)
        self.assertAlmostEqual(node["memory_percent"], 46.566128730773926)

    def test_missing_invalid_or_duplicate_node_data_fails_closed(self):
        cases = {
            "missing node metrics": (
                node_metrics(node_metric("worker-01")),
                node_inventory(node_object("worker-01"), node_object("worker-02"))),
            "unexpected node metrics": (
                node_metrics(node_metric("worker-01"), node_metric("worker-02")),
                node_inventory(node_object("worker-01"))),
            "duplicate metrics": (
                node_metrics(node_metric("worker-01"), node_metric("worker-01")),
                node_inventory(node_object("worker-01"))),
            "duplicate allocatable": (
                node_metrics(node_metric("worker-01")),
                node_inventory(node_object("worker-01"),
                               node_object("worker-01"))),
            "missing allocatable cpu": (
                node_metrics(node_metric("worker-01")),
                node_inventory({"metadata": {"name": "worker-01"}, "status": {
                    "allocatable": {"memory": "1Gi"}}})),
            "zero allocatable memory": (
                node_metrics(node_metric("worker-01")),
                node_inventory(node_object("worker-01", memory="0"))),
            "invalid usage quantity": (
                node_metrics(node_metric("worker-01", cpu="abc")),
                node_inventory(node_object("worker-01"))),
            "invalid timestamp": (
                node_metrics(node_metric("worker-01", timestamp="not-a-time")),
                node_inventory(node_object("worker-01"))),
            "invalid window": (
                node_metrics(node_metric("worker-01", window="soon")),
                node_inventory(node_object("worker-01"))),
            "empty metrics": (node_metrics(),
                              node_inventory(node_object("worker-01"))),
            "empty inventory": (node_metrics(node_metric("worker-01")),
                                node_inventory()),
        }
        for label, (metrics, nodes) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(harness.InstrumentationError):
                    self.ok(metrics, nodes)

    def test_command_and_json_failures_are_instrumentation_errors(self):
        cases = [
            [result(code=1, stderr="metrics unavailable")],
            [result(stdout="{")],
            [result(stdout=json.dumps(node_metrics(
                node_metric("worker-01")))), result(code=1, stderr="nodes down")],
            [result(stdout=json.dumps(node_metrics(
                node_metric("worker-01")))), result(stdout=json.dumps({}))],
        ]
        for responses in cases:
            with self.subTest(responses=len(responses)):
                with self.assertRaises(harness.InstrumentationError):
                    self.read(responses)

    def test_unbounded_quantity_and_duration_arithmetic_fail_closed(self):
        with self.assertRaises(harness.InstrumentationError):
            harness._quantity("1e9999999", "review")
        with self.assertRaises(harness.InstrumentationError):
            harness._duration_seconds("9" * 400 + "s", "review")
        cases = {
            "overflow quantity": (
                node_metrics(node_metric("worker-01", cpu="1e9999999")),
                node_inventory(node_object("worker-01"))),
            "overflow window": (
                node_metrics(node_metric("worker-01", window="9" * 400 + "s")),
                node_inventory(node_object("worker-01"))),
        }
        for label, (metrics, nodes) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(harness.InstrumentationError):
                    self.ok(metrics, nodes)


class ReadinessClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def now(self):
        self.value += 0.01
        return point(self.value)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds

    def advance(self, seconds):
        self.value += seconds


class BaselineSnapshotter:
    def __init__(self, observation_value, clock=None, advance=0.0):
        self.namespace = "invenio"
        self.observation = observation_value
        self.clock = clock
        self.advance = advance
        self.calls = 0

    def capture(self):
        self.calls += 1
        if self.clock and self.advance:
            self.clock.advance(self.advance)
        return copy.deepcopy(self.observation)


class BaselineKubectl:
    def __init__(self, pods=None, nodes=None, node_error=None):
        self.pod_values = list(pods or [dict(READY_POD)])
        self.node_values = copy.deepcopy(nodes or DEFAULT_NODES)
        self.node_error = node_error

    @staticmethod
    def _take(values):
        return values.pop(0) if len(values) > 1 else values[0]

    def pods(self, namespace):
        return [copy.deepcopy(self._take(self.pod_values))]

    def top_nodes(self):
        if self.node_error is not None:
            raise self.node_error
        return [copy.deepcopy(self._take(self.node_values))]


class BaselineSequenceSnapshotter:
    def __init__(self, values):
        self.namespace = "invenio"
        self.values = list(values)
        self.calls = 0

    def capture(self):
        self.calls += 1
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        return copy.deepcopy(value)


class BaselineGateTests(unittest.TestCase):
    def ready_observation(self):
        obs = observation()
        obs.pods = [dict(READY_POD)]
        obs.nodes = copy.deepcopy(DEFAULT_NODES)
        return obs

    def test_capacity_rejects_both_metrics_at_or_above_seventy(self):
        cases = [
            (69.9, 69.9, True),
            (70.0, 10.0, False),
            (10.0, 70.0, False),
            (70.1, 10.0, False),
            (10.0, 70.1, False),
        ]
        for cpu, memory, accepted in cases:
            obs = self.ready_observation()
            obs.nodes = [{"name": "worker-01", "cpu_percent": cpu,
                          "memory_percent": memory}]
            with self.subTest(cpu=cpu, memory=memory):
                if accepted:
                    harness.baseline_gate(obs, "gitops")
                else:
                    with self.assertRaises(harness.BaselineError):
                        harness.baseline_gate(obs, "gitops")

    def test_invalid_node_percentages_fail_closed(self):
        for value in (None, "NaN", -1, float("inf")):
            obs = self.ready_observation()
            obs.nodes = [{"name": "worker-01", "cpu_percent": value,
                          "memory_percent": 10}]
            with self.subTest(value=value):
                with self.assertRaises(harness.InstrumentationError):
                    harness.baseline_gate(obs, "gitops")

    def test_malformed_hpa_telemetry_fails_closed(self):
        cases = {
            "missing desired": ("desired", None),
            "string replicas": ("deployment_spec_replicas", "2"),
            "missing scale condition": ("able_to_scale", None),
        }
        for label, (key, value) in cases.items():
            obs = self.ready_observation()
            obs.hpa[key] = value
            with self.subTest(case=label):
                with self.assertRaises(harness.InstrumentationError):
                    harness.baseline_gate(obs, "gitops")


class BaselineReadinessTests(unittest.TestCase):
    def stabilize(self, snapshotter, kubectl, timeout=5, interval=1):
        clock = ReadinessClock()
        result = harness.stabilize_baseline(
            snapshotter, kubectl, "gitops", timeout, interval, clock,
            sleep=clock.sleep)
        return result, clock

    def test_transient_readiness_recovers_and_resets_match_history(self):
        snapshotter = BaselineSnapshotter(observation())
        kubectl = BaselineKubectl(pods=[dict(READY_POD), dict(UNREADY_POD),
                                       dict(READY_POD)])
        result, clock = self.stabilize(snapshotter, kubectl)
        self.assertEqual(snapshotter.calls, 4)
        self.assertEqual(len(result.readiness_failures), 1)
        failure = result.readiness_failures[0]
        self.assertEqual(failure["reason"], "pod_readiness")
        self.assertTrue(failure["reasons"][0]["retryable"])
        self.assertEqual(failure["pods"], [UNREADY_POD])
        self.assertTrue(clock.sleeps)

    def test_hpa_settling_recovers_after_a_transient_scale(self):
        unsettled = observation(hpa=harness.hpa_state(
            web_hpa(desired=3, current=2, spec_replicas=2), web_deployment()))
        settled = observation()
        snapshotter = BaselineSequenceSnapshotter([unsettled, settled, settled])
        result, clock = self.stabilize(
            snapshotter, BaselineKubectl())
        self.assertEqual(snapshotter.calls, 3)
        self.assertEqual(result.readiness_failures[0]["reason"],
                         "hpa_settling")
        self.assertTrue(result.readiness_failures[0]["reasons"][0]["retryable"])
        self.assertTrue(clock.sleeps)

    def test_capacity_failure_recovers_when_the_next_read_is_valid(self):
        snapshotter = BaselineSnapshotter(observation())
        kubectl = BaselineKubectl(nodes=[
            {"name": "worker-01", "cpu_percent": 10, "memory_percent": 71},
            {"name": "worker-01", "cpu_percent": 11, "memory_percent": 40},
        ])
        result, _ = self.stabilize(snapshotter, kubectl)
        self.assertEqual(result.readiness_failures[0]["reason"], "capacity")
        self.assertEqual(result.nodes[0]["memory_percent"], 40)

    def test_capacity_timeout_preserves_safe_observations_and_caps_sleep(self):
        snapshotter = BaselineSnapshotter(observation())
        kubectl = BaselineKubectl(nodes=[
            {"name": "worker-01", "cpu_percent": 70, "memory_percent": 10}])
        clock = ReadinessClock()
        with self.assertRaises(harness.BaselineError) as caught:
            harness.stabilize_baseline(
                snapshotter, kubectl, "gitops", 0.5, 10, clock,
                sleep=clock.sleep)
        failures = caught.exception.readiness_failures
        self.assertTrue(failures)
        self.assertEqual(failures[0]["reason"], "capacity")
        self.assertEqual(failures[0]["nodes"][0]["cpu_percent"], 70)
        self.assertTrue(failures[0]["reasons"][0]["retryable"])
        self.assertLessEqual(clock.sleeps[0], 0.5)
        serialized = json.dumps(failures)
        self.assertNotIn("PLAINTEXT-MUST-NOT-LEAK", serialized)
        self.assertNotIn("encryptedData", serialized)

    def test_no_capture_starts_after_the_deadline_is_exhausted(self):
        snapshotter = BaselineSnapshotter(observation())
        kubectl = BaselineKubectl(nodes=[
            {"name": "worker-01", "cpu_percent": 70, "memory_percent": 10}])
        clock = ReadinessClock()
        with self.assertRaises(harness.BaselineError) as caught:
            harness.stabilize_baseline(
                snapshotter, kubectl, "gitops", 0.5, 10, clock,
                sleep=clock.sleep)
        self.assertEqual(snapshotter.calls, 1)
        failures = caught.exception.readiness_failures
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "capacity")
        self.assertAlmostEqual(clock.sleeps[0], 0.43)

    def test_node_metric_failure_keeps_incremental_acquisition_bounds(self):
        snapshotter = BaselineSnapshotter(observation())
        kubectl = BaselineKubectl(
            node_error=harness.InstrumentationError("metrics unavailable"))
        clock = ReadinessClock()
        with self.assertRaises(harness.InstrumentationError) as caught:
            harness.stabilize_baseline(
                snapshotter, kubectl, "gitops", 5, 1, clock,
                sleep=clock.sleep)
        acquisition = caught.exception.readiness_failures[-1]["acquisition"]
        self.assertEqual(set(acquisition), {"snapshot", "pods", "nodes"})
        for segment in acquisition.values():
            self.assertLessEqual(segment["started_mono"],
                                 segment["finished_mono"])
            self.assertEqual(segment["started_utc"], segment["finished_utc"])

    def test_fatal_gate_failures_are_not_retried(self):
        cases = {
            "missing deployment": lambda obs: obs.resources.pop(
                "Deployment/invenio-web"),
            "quarantine preexists": lambda obs: obs.extra_resources.append(
                "exp-invenio-drift/Deployment/invenio-web"),
            "drift contamination": lambda obs: obs.resources[
                "SealedSecret/invenio-app-secrets"]["fields"].__setitem__(
                    "/metadata/annotations/" + harness.DRIFT_ANNOTATION, "x"),
            "wrong hpa target": lambda obs: obs.hpa.__setitem__(
                "target", "Deployment/other"),
        }
        for label, corrupt in cases.items():
            obs = observation()
            corrupt(obs)
            snapshotter = BaselineSnapshotter(obs)
            kubectl = BaselineKubectl()
            clock = ReadinessClock()
            with self.subTest(case=label):
                with self.assertRaises(harness.BaselineError) as caught:
                    harness.stabilize_baseline(
                        snapshotter, kubectl, "gitops", 5, 1, clock,
                        sleep=clock.sleep)
                self.assertEqual(snapshotter.calls, 1)
                self.assertEqual(clock.sleeps, [])
                failure = caught.exception.readiness_failures[0]
                self.assertFalse(failure["reasons"][0]["retryable"])

    def test_instrumentation_failure_is_preserved_and_not_retried(self):
        snapshotter = BaselineSnapshotter(observation())
        kubectl = BaselineKubectl(
            node_error=harness.InstrumentationError("metrics unavailable"))
        clock = ReadinessClock()
        with self.assertRaises(harness.InstrumentationError) as caught:
            harness.stabilize_baseline(
                snapshotter, kubectl, "gitops", 5, 1, clock,
                sleep=clock.sleep)
        self.assertEqual(snapshotter.calls, 1)
        self.assertEqual(clock.sleeps, [])
        failure = caught.exception.readiness_failures[0]
        self.assertEqual(failure["reason"], "instrumentation_failure")
        self.assertFalse(failure["reasons"][0]["retryable"])

    def test_slow_reads_crossing_the_deadline_are_not_accepted(self):
        clock = ReadinessClock()
        snapshotter = BaselineSnapshotter(observation(), clock=clock,
                                          advance=2.0)
        kubectl = BaselineKubectl()
        with self.assertRaises(harness.BaselineError) as caught:
            harness.stabilize_baseline(
                snapshotter, kubectl, "gitops", 1, 1, clock,
                sleep=clock.sleep)
        self.assertEqual(snapshotter.calls, 1)
        self.assertEqual(caught.exception.readiness_failures[-1]["reason"],
                         "deadline")


class ArmTests(unittest.TestCase):
    def test_gitops_requires_both_applications_enabled(self):
        for name in ("apps", "invenio-bootstrap"):
            apps = {"apps": application("apps"),
                    "invenio-bootstrap": application()}
            apps[name]["spec"]["syncPolicy"]["automated"]["selfHeal"] = False
            controller = harness.ArmController(FakeKubectl(apps=apps))
            with self.subTest(app=name):
                with self.assertRaises(harness.ArmStateError):
                    controller.activate("gitops")

    def test_gitops_makes_no_application_patch(self):
        fake = FakeKubectl()
        evidence = harness.ArmController(fake).activate("gitops")
        self.assertEqual(fake.patches, [])
        self.assertEqual(evidence.arm, "gitops")

    def test_imperative_pauses_both_then_restores_exact_state(self):
        fake = FakeKubectl()
        controller = harness.ArmController(fake)
        evidence = controller.activate("imperative")
        self.assertEqual([name for _, name, *_ in fake.patches],
                         ["apps", "invenio-bootstrap"])
        for app in fake.apps.values():
            self.assertIsNone(app["spec"]["syncPolicy"].get("automated"))
        self.assertEqual(evidence.original["apps"]["syncPolicy"]["automated"],
                         {"prune": True, "selfHeal": True})
        fake.patches.clear()
        controller.restore()
        self.assertEqual([name for _, name, *_ in fake.patches],
                         ["invenio-bootstrap", "apps"])
        for app in fake.apps.values():
            self.assertEqual(app["spec"]["syncPolicy"]["automated"],
                             {"prune": True, "selfHeal": True})

    def test_imperative_refuses_an_already_paused_application(self):
        apps = {"apps": application("apps"),
                "invenio-bootstrap": application()}
        apps["invenio-bootstrap"]["spec"]["syncPolicy"]["automated"] = None
        fake = FakeKubectl(apps=apps)
        with self.assertRaises(harness.ArmStateError):
            harness.ArmController(fake).activate("imperative")
        self.assertEqual(fake.patches, [])

    def test_restore_failure_is_reported_not_swallowed(self):
        fake = FakeKubectl()
        controller = harness.ArmController(fake)
        controller.activate("imperative")
        fake.fail_patch = True
        with self.assertRaises(harness.ArmRestoreError):
            controller.restore()


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"): web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        })
        self.spec = contract()
        self.clock = harness.FakeClock([100.0, 100.1, 100.2, 100.3])

    def test_image_injection_is_refused_when_the_field_does_not_change(self):
        self.fake.no_op_patch = True
        with self.assertRaises(harness.InjectionError):
            harness.inject(self.fake, self.spec, "B", "run-1", self.clock)
        self.assertTrue(self.fake.patches)

    def test_every_managed_scenario_verifies_changed_fields(self):
        cases = {
            "A": "/spec/replicas",
            "B": "/spec/template/spec/containers/web/image",
            "C": "/data/INSTANCE_TAGLINE",
            "E": "/spec/template/spec/containers/web/resources/limits/memory",
            "G": "/metadata/annotations/" + harness.DRIFT_ANNOTATION,
        }
        for scenario, path in cases.items():
            with self.subTest(scenario=scenario):
                fake = FakeKubectl(objects={
                    ("Deployment", "invenio-web", "invenio"): web_deployment(),
                    ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                        web_configmap(),
                    ("SealedSecret", "invenio-app-secrets", "invenio"):
                        sealed_secret(),
                    ("Service", "invenio-web", "invenio"): web_service(),
                    ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"):
                        web_hpa(),
                })
                injected = harness.inject(fake, self.spec, scenario, "run-1",
                                          harness.FakeClock([100.0, 100.1, 100.2]))
                self.assertTrue(injected.accepted)
                self.assertTrue(any(c["path"] == path for c in injected.changed))

    def test_deletion_scenario_rejects_a_delete_that_did_not_delete(self):
        fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
        })
        fake.delete = lambda *args, **kwargs: result()
        with self.assertRaises(harness.InjectionError):
            harness.inject(fake, self.spec, "D", "run-1", self.clock)

    def test_foreign_scenario_creates_in_exp_namespace_and_cleans_up(self):
        fake = FakeKubectl(objects={})
        injected = harness.inject(fake, self.spec, "F", "run-1", self.clock)
        self.assertTrue(injected.accepted)
        self.assertEqual(injected.changed[0]["effect"], "created")
        self.assertIn(("Deployment", "invenio-web", "exp-invenio-drift"),
                      fake.objects)
        cleanup = harness.cleanup_quarantine(fake, "exp-invenio-drift")
        self.assertTrue(cleanup.ok)
        self.assertNotIn(("Deployment", "invenio-web", "exp-invenio-drift"),
                         fake.objects)

    def test_scenario_g_annotation_is_removed(self):
        sealed = sealed_secret()
        sealed["metadata"].setdefault("annotations", {})[
            harness.DRIFT_ANNOTATION] = "drift"
        fake = FakeKubectl(objects={
            ("SealedSecret", harness.SEALED_SECRET, "invenio"): sealed,
        })
        cleanup = harness.cleanup_g_annotation(fake, "invenio")
        self.assertTrue(cleanup.ok)
        self.assertNotIn(harness.DRIFT_ANNOTATION,
                         fake.objects[("SealedSecret", harness.SEALED_SECRET,
                                       "invenio")]["metadata"].get("annotations", {}))

    def test_cleanup_failure_is_reported(self):
        fake = FakeKubectl(fail_delete=True)
        fake.objects[("Namespace", "exp-invenio-drift", None)] = {
            "apiVersion": "v1", "kind": "Namespace",
            "metadata": {"name": "exp-invenio-drift"},
        }
        cleanup = harness.cleanup_quarantine(fake, "exp-invenio-drift",
                                              wait_seconds=0)
        self.assertFalse(cleanup.ok)
        self.assertTrue(cleanup.errors)

    def test_cleanup_refuses_a_foreign_quarantine_namespace(self):
        fake = FakeKubectl()
        fake.objects[("Namespace", "exp-invenio-drift", None)] = {
            "apiVersion": "v1", "kind": "Namespace",
            "metadata": {"name": "exp-invenio-drift",
                         "labels": {"experiment.invenio.ugm/run-id": "other"}},
        }
        cleanup = harness.cleanup_quarantine(fake, "exp-invenio-drift",
                                              owner="mine")
        self.assertFalse(cleanup.ok)
        self.assertIn("owner", cleanup.errors[0])
        self.assertIn(("Namespace", "exp-invenio-drift", None), fake.objects)

    def test_imperative_repair_is_generic_and_keeps_hpa_replicas(self):
        drifted = web_deployment(image="drift:tag")
        drifted["spec"]["replicas"] = 1
        fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): drifted,
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"): web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
        })
        obs = observation(deployment=drifted)
        commands = harness.repair(fake, self.spec, obs, self.clock)
        self.assertTrue(commands)
        self.assertTrue(all(command.returncode == 0 for command in commands))
        repaired = fake.objects[("Deployment", "invenio-web", "invenio")]
        self.assertEqual(repaired["spec"]["template"]["spec"]["containers"][0]
                         ["image"], web_deployment()["spec"]["template"]["spec"]
                         ["containers"][0]["image"])
        self.assertEqual(repaired["spec"]["replicas"], 1)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.spec = contract()

    def run_timeline(self, samples, arm="gitops", scenario="B",
                     imperative=None, timeout=30, injected=None):
        return harness.analyze_timeline(
            contract=self.spec, samples=samples, injection=injected or injection(),
            arm=arm, scenario=scenario, timeout=timeout, imperative=imperative,
        )

    def test_argo_detection_evidence_and_two_match_recovery(self):
        samples = [
            observation(101, deployment=web_deployment(image="drift:tag"),
                        argo={"invenio-bootstrap": harness.application_state(
                            application(sync="OutOfSync")),
                            "apps": harness.application_state(application("apps"))}),
            observation(102, deployment=web_deployment(image="drift:tag")),
            observation(103),
            observation(104),
        ]
        out = self.run_timeline(samples)
        self.assertEqual(out["detection_seconds"], 1)
        self.assertEqual(out["evidence_seconds"], 1)
        self.assertEqual(out["recovery_seconds"], 3)
        self.assertEqual(out["detection_controller"], "argocd")
        self.assertEqual(out["recovery_controller"], "argocd")
        self.assertEqual(out["status"], "observed")
        self.assertEqual(out["r1_first"], 75)
        self.assertEqual(out["r1_last"], 100)

    def test_missing_detection_is_not_zero(self):
        samples = [
            observation(101, deployment=web_deployment(image="drift:tag")),
            observation(102),
            observation(103),
        ]
        out = self.run_timeline(samples)
        self.assertIsNone(out["detection_seconds"])
        self.assertEqual(out["detection_status"], "unobserved_before_stop")
        self.assertEqual(out["evidence_seconds"], 1)
        self.assertEqual(out["recovery_seconds"], 2)

    def test_timeout_is_right_censored_with_frozen_limit(self):
        samples = [observation(101 + i,
                               deployment=web_deployment(image="drift:tag"))
                   for i in range(5)]
        out = self.run_timeline(samples, timeout=5)
        self.assertIsNone(out["recovery_seconds"])
        self.assertEqual(out["recovery_status"], "right_censored")
        self.assertEqual(out["status"], "right_censored")
        self.assertEqual(out["censor_seconds"], 5)
        self.assertNotEqual(out["recovery_seconds"], 0)

    def test_one_matching_sample_does_not_prove_recovery(self):
        samples = [
            observation(101, deployment=web_deployment(image="drift:tag")),
            observation(102),
            observation(103, deployment=web_deployment(image="drift:tag")),
        ]
        out = self.run_timeline(samples, timeout=30)
        self.assertIsNone(out["recovery_seconds"])

    def test_imperative_attribution_and_command_count(self):
        imperative = harness.ImperativeRun(
            detection_at=point(101), evidence_at=point(101),
            evidence_ref="diff-101.json", commands=[result()], failed=False,
        )
        samples = [
            observation(101, deployment=web_deployment(image="drift:tag")),
            observation(102),
            observation(103),
        ]
        out = self.run_timeline(samples, arm="imperative", imperative=imperative)
        self.assertEqual(out["detection_controller"], "imperative")
        self.assertEqual(out["recovery_controller"], "imperative")
        self.assertEqual(out["kubectl_cmds"], 1)

    def test_hpa_control_excludes_replicas_and_needs_hpa_evidence(self):
        drifted = web_deployment()
        drifted["spec"]["replicas"] = 1
        samples = [
            observation(101, deployment=drifted,
                        hpa=harness.hpa_state(web_hpa(desired=2, current=2),
                                              drifted)),
            observation(102, deployment=drifted,
                        hpa=harness.hpa_state(web_hpa(desired=2, current=2),
                                              drifted)),
            observation(104, deployment=web_deployment(),
                        hpa=harness.hpa_state(web_hpa(), web_deployment())),
            observation(105, deployment=web_deployment(),
                        hpa=harness.hpa_state(web_hpa(), web_deployment())),
        ]
        out = self.run_timeline(samples, scenario="A", timeout=30)
        self.assertEqual(out["analysis_group"], "hpa_control")
        self.assertFalse(out["efficacy_eligible"])
        self.assertEqual(out["r1_first"], 100)
        self.assertEqual(out["detection_controller"], "hpa")
        self.assertEqual(out["recovery_controller"], "hpa")
        self.assertEqual(out["recovery_seconds"], 4)


class OutputTests(unittest.TestCase):
    def test_dry_run_writes_jsonl_and_csv_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("harness.subprocess.run") as run, \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = harness.main([
                    "--arm", "imperative", "--scenario", "B", "--rep", "2",
                    "--namespace", "invenio", "--out", directory,
                    "--run-id", "dry-1",
                ])
            self.assertEqual(code, 0)
            run.assert_not_called()
            rows = [json.loads(line) for line in
                    (Path(directory) / "dry-1.jsonl").read_text().splitlines()]
            self.assertEqual(rows[0]["status"], "dry_run")
            self.assertIsNone(rows[0]["detection_seconds"])
            self.assertEqual(rows[0]["mutations_executed"], 0)
            with (Path(directory) / "dry-1.csv").open(newline="") as source:
                csv_rows = list(csv.DictReader(source))
            self.assertEqual(csv_rows[0]["env"], "manual")
            self.assertEqual(csv_rows[0]["skenario"], "B")
            self.assertEqual(csv_rows[0]["td"], "")
            self.assertIn("dry_run", csv_rows[0]["notes"])

    def test_existing_run_id_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("sys.stdout", new_callable=io.StringIO), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            args = ["--arm", "gitops", "--scenario", "A", "--rep", "1",
                    "--namespace", "invenio", "--out", directory,
                    "--run-id", "same-id"]
            self.assertEqual(harness.main(args), 0)
            before = (Path(directory) / "same-id.jsonl").read_text()
            self.assertEqual(harness.main(args), 2)
            self.assertEqual((Path(directory) / "same-id.jsonl").read_text(),
                             before)

    def test_csv_mapping_uses_blank_for_censored_and_never_zero(self):
        row = {
            "schema_version": 2, "run_id": "r1", "env": "gitops",
            "arm": "gitops", "scenario": "D", "rep": 1,
            "status": "right_censored", "synthetic": False,
            "injection_seconds": 0.2, "detection_seconds": None,
            "evidence_seconds": 1.5, "recovery_seconds": None,
            "detection_controller": "argocd", "recovery_controller": "unattributed",
            "r1_baseline": 100, "r1_first": 75, "r1_last": 75,
            "kubectl_cmds": 0, "censor_seconds": 30,
        }
        converted = convert.row_to_csv(row)
        self.assertEqual(converted["env"], "gitops")
        self.assertEqual(converted["t0"], "0.2")
        self.assertEqual(converted["td"], "")
        self.assertEqual(converted["trci"], "1.5")
        self.assertEqual(converted["t2"], "")
        self.assertEqual(converted["r1_t1"], "75")
        self.assertIn("right_censored", converted["notes"])
        self.assertNotIn("0", [converted["td"], converted["t2"]])

    def test_converter_cli_writes_existing_analysis_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.jsonl"
            target = Path(directory) / "rows.csv"
            source.write_text(json.dumps({
                "schema_version": 2, "run_id": "r2", "env": "imperative",
                "arm": "imperative", "scenario": "A", "rep": 3,
                "status": "observed", "synthetic": False,
                "injection_seconds": 0.1, "detection_seconds": 2,
                "evidence_seconds": 2, "recovery_seconds": 4,
                "detection_controller": "hpa", "recovery_controller": "hpa",
                "r1_baseline": 100, "r1_first": 100, "r1_last": 100,
                "kubectl_cmds": 0, "censor_seconds": 30,
            }) + "\n")
            self.assertEqual(convert.main(["--in", str(source), "--out",
                                           str(target)]), 0)
            with target.open(newline="") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["env"], "manual")
            self.assertEqual(row["skenario"], "A")
            self.assertEqual(row["t2"], "4")


class SeedTests(unittest.TestCase):
    def test_missing_token_fails_closed(self):
        with self.assertRaises(harness.SeedVerificationError):
            harness.load_token({})

    def test_seed_digest_mismatch_fails_closed_without_leaking_token(self):
        token = "token-abc"
        http = FakeHttp({
            "/api/records/seed-1/draft": {
                "files": {"enabled": True},
            },
            "/api/records/seed-1/draft/files": {
                "entries": [{"key": "seed.bin", "size": 4,
                             "checksum": "md5:bad", "status": "completed"}],
            },
            "/api/records/seed-1/draft/files/seed.bin/content": b"data",
        })
        with self.assertRaises(harness.SeedVerificationError) as caught:
            harness.verify_seed(http, "seed-1", "seed.bin", 4,
                                "00000000000000000000000000000000",
                                "0" * 64)
        self.assertNotIn(token, str(caught.exception))

    def test_matching_seed_is_accepted(self):
        content = b"seed-bytes"
        import hashlib
        http = FakeHttp({
            "/api/records/seed-1/draft": {"files": {"enabled": True}},
            "/api/records/seed-1/draft/files": {
                "entries": [{"key": "seed.bin", "size": len(content),
                             "checksum": "md5:" + hashlib.md5(content).hexdigest(),
                             "status": "completed"}],
            },
            "/api/records/seed-1/draft/files/seed.bin/content": content,
        })
        result = harness.verify_seed(
            http, "seed-1", "seed.bin", len(content),
            hashlib.md5(content).hexdigest(), hashlib.sha256(content).hexdigest())
        self.assertTrue(result["verified"])


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def get(self, url, accept=None):
        self.requests.append((url, accept))
        for suffix, body in self.responses.items():
            if url.endswith(suffix):
                if isinstance(body, dict):
                    return 200, json.dumps(body).encode()
                return 200, body
        return 404, b"{}"


class AdvancingClock:
    def __init__(self, start=0.0, step=0.05):
        self.value = start
        self.step = step

    def now(self):
        self.value += self.step
        stamp = datetime(2026, 10, 27, tzinfo=timezone.utc)
        return harness.Point(self.value, stamp.isoformat())


class DeterministicSampler:
    def __init__(self, capture, clock, interval):
        self.capture = capture
        self.clock = clock
        self.interval = interval
        self.samples = []
        self.error = None

    def start(self):
        pass

    def wait_ready(self, timeout=10):
        return True

    def snapshot(self):
        sample = self.capture()
        self.samples.append(sample)
        return list(self.samples)

    def stop(self):
        pass


class LiveRunnerTests(unittest.TestCase):
    def test_imperative_live_path_pauses_injects_repairs_restores_and_writes(self):
        objects = {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }
        apps = {"apps": application("apps"),
                "invenio-bootstrap": application()}
        fake = FakeKubectl(apps=apps, objects=objects)
        with tempfile.TemporaryDirectory() as directory:
            args = harness.parse_args([
                "--arm", "imperative", "--scenario", "B", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--source-revision", "b" * 40, "--render-sha256", "c" * 64,
                "--timeout", "5", "--sample-interval", "0.01",
                "--imperative-interval", "0.01", "--baseline-timeout", "5",
                "--reset-timeout", "5", "--out", directory, "--run-id",
                "live-1",
            ])
            runner = harness.LiveRunner(args, {}, fake, AdvancingClock())
            with mock.patch("harness.Sampler", DeterministicSampler), \
                    mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            self.assertEqual(code, 0)
            row = json.loads((Path(directory) / "live-1.jsonl").read_text())
            self.assertEqual(row["status"], "observed")
            self.assertEqual(row["detection_controller"], "imperative")
            self.assertEqual(row["recovery_controller"], "imperative")
            self.assertGreater(row["kubectl_cmds"], 0)
            self.assertEqual(row["arm_restore_status"], "restored")
            self.assertEqual(row["cleanup_status"], "ok")
            self.assertFalse((Path(directory) / "live-1" / "commands.jsonl")
                             .read_text().strip() == "")
            for app in fake.apps.values():
                self.assertEqual(app["spec"]["syncPolicy"]["automated"],
                                 {"prune": True, "selfHeal": True})
            self.assertNotIn(("Namespace", "exp-invenio-drift"),
                             fake.objects)

    def test_failed_baseline_persists_readiness_without_baseline_snapshot(self):
        objects = {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }
        apps = {"apps": application("apps"),
                "invenio-bootstrap": application()}
        fake = FakeKubectl(apps=apps, objects=objects)
        fake.pods = lambda namespace: [dict(UNREADY_POD)]
        with tempfile.TemporaryDirectory() as directory:
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "B", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--source-revision", "b" * 40, "--render-sha256", "c" * 64,
                "--timeout", "1", "--sample-interval", "0.01",
                "--baseline-timeout", "0.2", "--reset-timeout", "1",
                "--out", directory, "--run-id", "baseline-failed",
            ])
            runner = harness.LiveRunner(args, {}, fake, AdvancingClock())
            with mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            out = Path(directory) / "baseline-failed"
            row = json.loads(
                (Path(directory) / "baseline-failed.jsonl").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "baseline_failure")
            self.assertIn("not Running and Ready", row["error"])
            self.assertIsNone(json.loads((out / "baseline.json").read_text()))
            readiness = json.loads((out / "readiness.json").read_text())
            self.assertTrue(readiness)
            self.assertEqual(readiness[0]["reason"], "pod_readiness")
            self.assertEqual(readiness[0]["pods"], [UNREADY_POD])
            self.assertIn("nodes", readiness[0])
            serialized = json.dumps(readiness)
            self.assertNotIn("PLAINTEXT-MUST-NOT-LEAK", serialized)
            self.assertNotIn("encryptedData", serialized)


class SamplerLifecycleTests(unittest.TestCase):
    def test_sampler_stop_does_not_shadow_thread_stop(self):
        sampler = harness.Sampler(
            lambda: {"ok": True}, harness.FakeClock([1.0]), 0.01,
        )
        sampler.start()
        self.assertTrue(sampler.wait_ready(timeout=2))
        sampler.stop()
        self.assertFalse(sampler.is_alive())


if __name__ == "__main__":
    unittest.main()
