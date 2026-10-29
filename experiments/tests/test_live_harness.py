"""Offline regressions for the live InvenioRDM harness.

No test starts a cluster process. `subprocess.run` is patched where the dry-run
path could reach it and every kubectl interaction in the remaining tests uses
an in-memory fake.
"""
import copy
import csv
from datetime import datetime, timezone
import hashlib
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
                hpa=None, argo=None, extras=None, acquisition=None,
                read_finish=None, evaluated_at=None, evaluated_signal=False,
                evaluated_reads=None):
    deployment = deployment or web_deployment()
    objects = [deployment, configmap or web_configmap(), secret or sealed_secret(),
               service or web_service()]
    if acquisition is None:
        acquisition = acquisition_for(at, read_finish)
    observed = harness.observation_from_objects(
        objects, at=point(at),
        argo=argo or {"invenio-bootstrap": harness.application_state(application()),
                      "apps": harness.application_state(application("apps"))},
        hpa=hpa or harness.hpa_state(web_hpa(), deployment),
        extras=extras or [],
        acquisition=acquisition,
    )
    if evaluated_at is not None:
        observed.evaluated_at = (evaluated_at if isinstance(evaluated_at, harness.Point)
                                 else point(evaluated_at))
        observed.evaluated_signal = bool(evaluated_signal)
        observed.evaluated_reads = list(evaluated_reads or [])
    return observed


def read_record(start, finish=None, kind="ConfigMap", name="x",
                namespace="invenio", ok=True, present=True):
    finish = start if finish is None else finish
    started = point(start)
    finished = point(finish)
    return {
        "kind": kind, "name": name, "namespace": namespace,
        "started_utc": started.utc, "started_mono": started.mono,
        "finished_utc": finished.utc, "finished_mono": finished.mono,
        "ok": ok, "present": present,
        "attempts": [{
            "started_utc": started.utc, "started_mono": started.mono,
            "finished_utc": finished.utc, "finished_mono": finished.mono,
            "ok": ok, "returncode": 0 if ok else 1,
        }],
    }


READ_KEYS = (
    "Deployment/invenio-web",
    "ConfigMap/invenio-app-config-6dg2chdbh4",
    "SealedSecret/invenio-app-secrets",
    "Service/invenio-web",
    "HorizontalPodAutoscaler/invenio-web-hpa",
    "Application/apps",
    "Application/invenio-bootstrap",
    "Namespace/exp-invenio-drift",
)


def acquisition_for(at, read_finish=None, starts=None, finishes=None):
    read_finish = at if read_finish is None else read_finish
    starts = starts or {}
    finishes = finishes or {}
    reads = {}
    for key in READ_KEYS:
        kind, name = key.split("/", 1)
        reads[key] = read_record(
            starts.get(key, at), finishes.get(key, read_finish),
            kind=kind, name=name)
    return {
        "started": {"mono": float(at), "utc": point(at).utc},
        "finished": {"mono": float(read_finish), "utc": point(read_finish).utc},
        "started_mono": float(at), "started_utc": point(at).utc,
        "finished_mono": float(read_finish),
        "finished_utc": point(read_finish).utc,
        "reads": reads,
    }


def contract(obs=None, decl=None):
    obs = obs or observation()
    decl = decl or declaration()
    return harness.build_contract(
        decl, obs, namespace="invenio",
        quarantine_namespace="exp-invenio-drift",
    )


DECLARATION_REVISION = "b" * 40


def declaration_bundle(objects=None, revision=DECLARATION_REVISION):
    if objects is None:
        objects = [
            web_deployment(),
            web_configmap(),
            sealed_secret(),
            web_service(),
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "invenio"},
            },
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "invenio-db-secrets", "namespace": "invenio"},
                "data": {"password": "SECRET-VALUE-MUST-NOT-LEAK"},
            },
        ]
    return {
        "format": "invenio-frozen-render-v1",
        "source_revision": revision,
        "objects": objects,
    }


def declaration(data=None, digest=None, revision=DECLARATION_REVISION,
                namespace="invenio"):
    data = (json.dumps(declaration_bundle(), sort_keys=True).encode()
            if data is None else data)
    digest = hashlib.sha256(data).hexdigest() if digest is None else digest
    return harness.load_declaration_bytes(
        data, digest, revision, namespace)


def declaration_from(mutate, revision=DECLARATION_REVISION):
    bundle = declaration_bundle()
    mutate(bundle)
    data = json.dumps(bundle, sort_keys=True).encode()
    return harness.load_declaration_bytes(
        data, hashlib.sha256(data).hexdigest(), revision, "invenio")


def write_render(directory, bundle=None):
    bundle = declaration_bundle() if bundle is None else bundle
    path = Path(directory) / "render.json"
    data = json.dumps(bundle, sort_keys=True).encode()
    path.write_bytes(data)
    return path, hashlib.sha256(data).hexdigest()


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
                 no_op_patch=False, fail_delete=False, clock=None):
        self.apps = apps or {
            "apps": application("apps"),
            "invenio-bootstrap": application(),
        }
        self.objects = objects or {}
        self.fail_patch = fail_patch
        self.no_op_patch = no_op_patch
        self.fail_delete = fail_delete
        self.clock = clock
        self.patches = []
        self.deletes = []
        self.applies = []
        self.annotations = []
        self.reads = []

    def _now(self):
        if self.clock is not None:
            return self.clock.now()
        return point(0)

    def read(self, kind, name=None, namespace=None, selector=None):
        started = self._now()
        payload = self.get(kind, name, namespace, selector)
        finished = started
        record = {
            "kind": kind, "name": name, "namespace": namespace,
            "started_utc": started.utc, "started_mono": started.mono,
            "finished_utc": finished.utc, "finished_mono": finished.mono,
            "ok": True, "present": payload is not None,
            "attempts": [{
                "started_utc": started.utc, "started_mono": started.mono,
                "finished_utc": finished.utc, "finished_mono": finished.mono,
                "ok": True, "returncode": 0,
            }],
        }
        self.reads.append(record)
        return payload, record

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
        return result(argv=["annotate", kind, name, key])

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
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
                "--namespace", "invenio", "--app", "invenio-bootstrap",
                "--confirm-single-stack", "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
            ])
            with mock.patch("harness.Http") as http:
                http.return_value.get.side_effect = harness.HarnessError("boom")
                with self.assertRaises(harness.HarnessError) as caught:
                    harness.validate_live_args(
                        args, environ={"INVENIO_TOKEN": secret})
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


class IndependentOracleTests(unittest.TestCase):
    def test_live_baseline_cannot_supply_its_own_expected_values(self):
        frozen = declaration()
        drifted = observation(deployment=web_deployment(image="drift:tag"))
        spec = contract(drifted, frozen)
        deployment = next(resource for resource in spec.resources
                          if resource["kind"] == "Deployment")
        self.assertEqual(
            deployment["fields"][
                "/spec/template/spec/containers/web/image"],
            web_deployment()["spec"]["template"]["spec"]["containers"][0][
                "image"])
        self.assertEqual(harness.score(spec, drifted), 75)
        self.assertTrue(any(
            diff["path"] == "/spec/template/spec/containers/web/image"
            for diff in harness.field_diffs(spec, drifted)))
        self.assertEqual(harness.score(spec, observation()), 100)

    def test_live_preflight_requires_and_validates_the_render_bundle(self):
        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
            "--namespace", "invenio", "--app", "invenio-bootstrap",
            "--confirm-single-stack",
            "--source-revision", "b" * 40, "--render-sha256", "c" * 64,
        ])
        with mock.patch.object(harness, "Http") as http, \
                mock.patch.object(harness, "verify_seed") as seed:
            with self.assertRaises(harness.SafetyError):
                harness.validate_live_args(
                    args, environ={"INVENIO_TOKEN": "x"})
        http.assert_not_called()
        seed.assert_not_called()

    def test_live_preflight_rejects_a_tampered_bundle_before_http(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "render.json"
            data = json.dumps(declaration_bundle()).encode()
            path.write_bytes(data)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "B", "--rep", "1", "--live",
                "--namespace", "invenio", "--app", "invenio-bootstrap",
                "--confirm-single-stack", "--render-file", str(path),
                "--source-revision", "b" * 40,
                "--render-sha256", "0" * 64,
            ])
            with mock.patch.object(harness, "Http") as http, \
                    mock.patch.object(harness, "verify_seed") as seed:
                with self.assertRaises(harness.SafetyError):
                    harness.validate_live_args(
                        args, environ={"INVENIO_TOKEN": "x"})
            http.assert_not_called()
            seed.assert_not_called()

    def test_declared_defaults_and_quantities_are_equivalent(self):
        def mutate(bundle):
            container = (bundle["objects"][0]["spec"]["template"]["spec"]
                         ["containers"][0])
            container["resources"]["requests"].update(
                {"cpu": "1000m", "memory": "2Gi"})
            container["resources"]["limits"].update(
                {"cpu": "1", "memory": "2048Mi"})
            bundle["objects"][3]["spec"].pop("type")

        frozen = declaration_from(mutate)
        deployment = web_deployment()
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        container["resources"]["requests"].update(
            {"cpu": "1", "memory": "2048Mi"})
        container["resources"]["limits"].update(
            {"cpu": "1000m", "memory": "2Gi"})
        live = observation(deployment=deployment)
        spec = contract(live, frozen)
        self.assertEqual(harness.score(spec, live), 100)
        self.assertEqual(harness.field_diffs(spec, live), [])

    def test_unrelated_strings_are_not_normalized(self):
        image = "ghcr.io/vityasyyy/invenio-ugm:release-v1"

        def mutate(bundle):
            (bundle["objects"][0]["spec"]["template"]["spec"]["containers"][0]
             ["image"]) = image

        frozen = declaration_from(mutate)
        live = observation(deployment=web_deployment(
            image="ghcr.io/vityasyyy/invenio-ugm:RELEASE-V1"))
        spec = contract(live, frozen)
        self.assertEqual(harness.score(spec, live), 75)

    def test_hpa_owned_replicas_are_excluded_and_retained_separately(self):
        frozen = declaration()
        deployment = web_deployment()
        deployment["spec"]["replicas"] = 1
        live = observation(
            deployment=deployment,
            hpa=harness.hpa_state(web_hpa(desired=1, current=1,
                                          spec_replicas=1), deployment))
        spec = contract(live, frozen)
        declared = next(resource for resource in spec.resources
                        if resource["kind"] == "Deployment")
        self.assertNotIn("/spec/replicas", declared["fields"])
        self.assertNotIn("replicas", declared["manifest"]["spec"])
        self.assertEqual(spec.baseline_hpa["deployment_spec_replicas"], 1)
        self.assertEqual(harness.score(spec, live), 100)

    def test_per_resource_matches_and_mismatches_are_preserved(self):
        frozen = declaration()
        live = observation(
            deployment=web_deployment(image="drift:tag"),
            configmap=web_configmap(tagline="drifted"),
        )
        spec = contract(live, frozen)
        result = harness.resource_results(spec, live)
        self.assertEqual(result["score"], 50)
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["total"], 4)
        by_id = {item["resource"]: item for item in result["resources"]}
        self.assertFalse(by_id["Deployment/invenio-web"]["matched"])
        self.assertFalse(
            by_id["ConfigMap/invenio-app-config-6dg2chdbh4"]["matched"])
        self.assertTrue(by_id["Service/invenio-web"]["matched"])
        self.assertTrue(by_id["SealedSecret/invenio-app-secrets"]["matched"])

    def test_missing_resource_is_a_mismatch_not_an_invented_match(self):
        frozen = declaration()
        live = observation()
        live.resources.pop("Service/invenio-web")
        spec = contract(live, frozen)
        result = harness.resource_results(spec, live)
        self.assertEqual(result["score"], 75)
        service = next(item for item in result["resources"]
                       if item["resource"] == "Service/invenio-web")
        self.assertFalse(service["matched"])
        self.assertTrue(service["missing"])

    def test_missing_observation_stays_unknown(self):
        spec = contract()
        out = harness.analyze_timeline(
            spec, [], injection(), "gitops", "B", 30)
        self.assertIsNone(out["r1_first"])
        self.assertIsNone(out["r1_last"])
        self.assertIsNone(out["r1_baseline"])
        self.assertIsNone(out["r1_baseline_details"])
        self.assertIsNone(out["r1_first_details"])
        self.assertIsNone(out["r1_last_details"])

    def test_supplied_baseline_produces_r1_baseline(self):
        spec = contract()
        baseline = observation()
        out = harness.analyze_timeline(
            spec, [], injection(), "gitops", "B", 30, baseline=baseline)
        self.assertEqual(out["r1_baseline"], 100.0)
        self.assertEqual(out["r1_baseline_details"]["score"], 100.0)
        self.assertEqual(out["r1_baseline_details"]["matched"], 4)

    def test_secret_material_never_enters_contract_or_details(self):
        spec = contract()
        result = harness.resource_results(
            spec, observation())
        text = json.dumps({"contract": spec.as_dict(), "result": result})
        self.assertNotIn("PLAINTEXT-MUST-NOT-LEAK", text)
        self.assertNotIn("SECRET-VALUE-MUST-NOT-LEAK", text)
        self.assertNotIn("encryptedData", text)

    def test_declared_configmap_identity_ignores_a_live_configmap(self):
        frozen = declaration()
        live_configmap = web_configmap()
        live_configmap["metadata"]["name"] = "invenio-app-config-live"
        live = observation(configmap=live_configmap)
        spec = contract(live, frozen)
        self.assertEqual(spec.configmap_name,
                         "invenio-app-config-6dg2chdbh4")
        self.assertIn("ConfigMap/invenio-app-config-6dg2chdbh4",
                      [resource["id"] for resource in spec.resources])
        self.assertNotIn("ConfigMap/invenio-app-config-live",
                         [resource["id"] for resource in spec.resources])

    def test_observed_argo_revision_must_match_the_frozen_revision(self):
        frozen = declaration()
        drifted_app = application()
        drifted_app["status"]["sync"]["revision"] = "c" * 40
        live = observation(argo={
            "invenio-bootstrap": harness.application_state(drifted_app),
            "apps": harness.application_state(application("apps")),
        })
        with self.assertRaises(harness.InstrumentationError):
            contract(live, frozen)

    def test_sealed_secret_contract_is_metadata_only(self):
        spec = contract()
        sealed = next(resource for resource in spec.resources
                      if resource["kind"] == "SealedSecret")
        self.assertEqual(sealed["fields"], {
            "/metadata/annotations/" + harness.DRIFT_ANNOTATION: None})
        self.assertNotIn("spec", sealed["manifest"])
        self.assertNotIn("encryptedData", json.dumps(spec.as_dict()))


class DeclarationLoaderTests(unittest.TestCase):
    def setUp(self):
        self.data = json.dumps(declaration_bundle(), sort_keys=True).encode()
        self.digest = hashlib.sha256(self.data).hexdigest()

    def load(self, data=None, digest=None, revision=DECLARATION_REVISION,
             namespace="invenio"):
        return harness.load_declaration_bytes(
            self.data if data is None else data,
            self.digest if digest is None else digest,
            revision, namespace)

    def bundle_with(self, mutate):
        bundle = declaration_bundle()
        mutate(bundle)
        data = json.dumps(bundle, sort_keys=True).encode()
        return data, hashlib.sha256(data).hexdigest()

    def test_valid_bundle_selects_exactly_the_four_scoped_resources(self):
        selected = self.load()
        self.assertEqual(harness.RENDER_FORMAT, "invenio-frozen-render-v1")
        self.assertEqual(selected.format, harness.RENDER_FORMAT)
        self.assertEqual(selected.source_revision, DECLARATION_REVISION)
        self.assertEqual(selected.render_sha256, self.digest)
        self.assertEqual([resource["id"] for resource in selected.resources], [
            "Deployment/invenio-web",
            "ConfigMap/invenio-app-config-6dg2chdbh4",
            "Service/invenio-web",
            "SealedSecret/invenio-app-secrets",
        ])
        self.assertEqual(selected.configmap_name,
                         "invenio-app-config-6dg2chdbh4")
        payload = selected.as_dict()
        self.assertEqual(payload["format"], harness.RENDER_FORMAT)
        self.assertNotIn("objects", payload)
        self.assertNotIn("SECRET-VALUE-MUST-NOT-LEAK", json.dumps(payload))

    def test_hash_revision_and_format_mismatches_fail_closed(self):
        with self.assertRaises(harness.DeclarationError):
            self.load(digest="0" * 64)
        with self.assertRaises(harness.DeclarationError):
            self.load(revision="c" * 40)
        data, digest = self.bundle_with(
            lambda bundle: bundle.__setitem__("format", "other-format"))
        with self.assertRaises(harness.DeclarationError):
            self.load(data=data, digest=digest)
        data, digest = self.bundle_with(
            lambda bundle: bundle.__setitem__("source_revision", "B" * 40))
        with self.assertRaises(harness.DeclarationError):
            self.load(data=data, digest=digest)

    def test_malformed_duplicate_and_non_finite_json_are_rejected(self):
        cases = {
            "truncated": b'{"format":',
            "duplicate key": b'{"format":"a","format":"b"}',
            "non-object": b'[]',
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(harness.DeclarationError):
                    self.load(data=data, digest=hashlib.sha256(data).hexdigest())
        prefix = (b'{"format":"invenio-frozen-render-v1","source_revision":"'
                  + b"b" * 40 + b'","objects":[{"apiVersion":"v1",'
                  b'"kind":"ConfigMap","metadata":{"name":"x",'
                  b'"namespace":"invenio"},"data":{"x":')
        for label, literal in (("NaN", b"NaN"), ("Infinity", b"Infinity"),
                               ("overflow", b"1e999999")):
            data = prefix + literal + b"}}]}"
            with self.subTest(case=label):
                with self.assertRaises(harness.DeclarationError):
                    self.load(data=data,
                              digest=hashlib.sha256(data).hexdigest())

    def test_duplicate_missing_and_wrong_namespace_targets_are_rejected(self):
        cases = {
            "duplicate deployment": lambda bundle: bundle["objects"].append(
                copy.deepcopy(web_deployment())),
            "missing service": lambda bundle: bundle["objects"].pop(3),
            "wrong namespace": lambda bundle: bundle["objects"][3]["metadata"]
            .__setitem__("namespace", "other"),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                data, digest = self.bundle_with(mutate)
                with self.assertRaises(harness.DeclarationError):
                    self.load(data=data, digest=digest)

    def test_configmap_identity_comes_from_the_declared_envfrom_only(self):
        def add_unrelated(bundle):
            other = web_configmap(tagline="unrelated")
            other["metadata"]["name"] = "invenio-app-config-other"
            bundle["objects"].append(other)

        data, digest = self.bundle_with(add_unrelated)
        selected = self.load(data=data, digest=digest)
        self.assertEqual(selected.configmap_name,
                         "invenio-app-config-6dg2chdbh4")

        def ambiguous(bundle):
            deployment = bundle["objects"][0]
            deployment["spec"]["template"]["spec"]["containers"][0][
                "envFrom"].append({"configMapRef": {
                    "name": "invenio-app-config-other"}})
            other = web_configmap()
            other["metadata"]["name"] = "invenio-app-config-other"
            bundle["objects"].append(other)

        data, digest = self.bundle_with(ambiguous)
        with self.assertRaises(harness.DeclarationError):
            self.load(data=data, digest=digest)

        def missing(bundle):
            bundle["objects"][0]["spec"]["template"]["spec"]["containers"][0][
                "envFrom"] = [{"secretRef": {"name": "invenio-app-secrets"}}]

        data, digest = self.bundle_with(missing)
        with self.assertRaises(harness.DeclarationError):
            self.load(data=data, digest=digest)

    def test_missing_or_malformed_selected_fields_are_rejected(self):
        def remove_image(bundle):
            bundle["objects"][0]["spec"]["template"]["spec"]["containers"][0][
                "image"] = None

        def remove_limit(bundle):
            bundle["objects"][0]["spec"]["template"]["spec"]["containers"][0][
                "resources"]["limits"].pop("memory")

        def no_ports(bundle):
            bundle["objects"][3]["spec"]["ports"] = []

        def no_data(bundle):
            bundle["objects"][1]["data"] = {}

        def no_tagline(bundle):
            bundle["objects"][1]["data"].pop(harness.CONFIG_KEY)

        def bad_quantity(bundle):
            bundle["objects"][0]["spec"]["template"]["spec"]["containers"][0][
                "resources"]["requests"]["cpu"] = "not-a-quantity"

        def contaminated_sealed(bundle):
            bundle["objects"][2]["metadata"]["annotations"] = {
                harness.DRIFT_ANNOTATION: "contaminated"}

        for label, mutate in {
            "image": remove_image,
            "limit": remove_limit,
            "ports": no_ports,
            "data": no_data,
            "tagline": no_tagline,
            "quantity": bad_quantity,
            "sealed annotation": contaminated_sealed,
        }.items():
            with self.subTest(case=label):
                data, digest = self.bundle_with(mutate)
                with self.assertRaises(harness.DeclarationError):
                    self.load(data=data, digest=digest)

    def test_malformed_object_shapes_fail_closed(self):
        cases = {
            "deployment spec": lambda bundle: bundle["objects"][0].__setitem__(
                "spec", None),
            "service port": lambda bundle: bundle["objects"][3]["spec"].__setitem__(
                "ports", [None]),
            "configmap data": lambda bundle: bundle["objects"][1].__setitem__(
                "data", ["not-a-map"]),
            "sealed annotations": lambda bundle: bundle["objects"][2][
                "metadata"].__setitem__("annotations", ["not-a-map"]),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                data, digest = self.bundle_with(mutate)
                with self.assertRaises(harness.DeclarationError):
                    self.load(data=data, digest=digest)

    def test_malformed_object_entries_are_rejected_without_echoing_contents(self):
        cases = {
            "non-object": lambda bundle: bundle["objects"].append("bad-object"),
            "bare mapping": lambda bundle: bundle["objects"].append(
                {"foo": "SENSITIVE-VALUE"}),
            "missing name": lambda bundle: bundle["objects"].append(
                {"apiVersion": "v1", "kind": "ConfigMap",
                 "metadata": {"namespace": "invenio"}}),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                data, digest = self.bundle_with(mutate)
                with self.assertRaises(harness.DeclarationError) as caught:
                    self.load(data=data, digest=digest)
                self.assertNotIn("SENSITIVE-VALUE", str(caught.exception))
                self.assertNotIn("bad-object", str(caught.exception))

    def test_secret_material_never_enters_the_scoped_declaration(self):
        selected = self.load()
        text = json.dumps({"declaration": selected.as_dict(),
                           "resources": selected.resources})
        self.assertNotIn("SECRET-VALUE-MUST-NOT-LEAK", text)
        self.assertNotIn("PLAINTEXT-MUST-NOT-LEAK", text)
        self.assertNotIn("encryptedData", text)


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
        self.assertTrue({"snapshot", "pods", "nodes", "started", "finished",
                         "reads"}.issubset(acquisition))
        for segment in acquisition.values():
            if not isinstance(segment, dict) or "started_mono" not in segment:
                continue
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
        drifted["spec"]["template"]["spec"]["containers"][0]["resources"][
            "limits"]["memory"] = "1024Mi"
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
        self.assertEqual(repaired["spec"]["template"]["spec"]["containers"][0]
                         ["resources"]["limits"]["memory"], "2Gi")
        self.assertEqual(repaired["spec"]["replicas"], 1)
        memory_patches = [
            container["resources"]["limits"]["memory"]
            for _, _, _, patch, _ in fake.patches
            for container in patch.get("spec", {}).get("template", {}).get(
                "spec", {}).get("containers", [])
            if "resources" in container
        ]
        self.assertEqual(memory_patches, ["2Gi"])

    def test_equivalent_quantity_readback_is_verified_not_assumed(self):
        class EquivalentKubectl(FakeKubectl):
            def patch(self, kind, name, namespace, patch, patch_type="merge"):
                result = super().patch(
                    kind, name, namespace, patch, patch_type=patch_type)
                doc = self.objects.get((kind, name, namespace))
                for container in ((doc or {}).get("spec", {}).get("template", {})
                                  .get("spec", {}).get("containers", [])):
                    limits = (container.get("resources") or {}).get("limits") or {}
                    if limits.get("memory") == harness.MEMORY_LIMIT_DRIFT:
                        limits["memory"] = "1572864Ki"
                return result

        fake = EquivalentKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        })
        injected = harness.inject(fake, self.spec, "E", "run-1",
                                  harness.FakeClock([100.0, 100.1, 100.2]))
        self.assertTrue(injected.accepted)
        self.assertEqual(injected.changed[0]["actual"], "1572864Ki")
        self.assertEqual(
            harness._quantity_bytes(injected.changed[0]["actual"], "actual"),
            harness._quantity_bytes(harness.MEMORY_LIMIT_DRIFT, "expected"))

    def test_equivalent_quantity_noop_injection_is_rejected(self):
        fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        })
        fake.no_op_patch = True
        with self.assertRaises(harness.InjectionError):
            harness.inject(fake, self.spec, "E", "run-1", self.clock)

    def test_semantically_equal_baseline_gets_a_distinct_drift_quantity(self):
        frozen = declaration_from(
            lambda bundle: bundle["objects"][0]["spec"]["template"]["spec"]
            ["containers"][0]["resources"]["limits"].__setitem__(
                "memory", "1.5Gi"))
        spec = contract(decl=frozen)
        fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        })
        injected = harness.inject(fake, spec, "E", "run-1", self.clock)
        self.assertTrue(injected.accepted)
        self.assertEqual(injected.changed[0]["actual"], "1024Mi")
        self.assertNotEqual(
            harness._quantity_bytes(injected.changed[0]["actual"], "actual"),
            harness._quantity_bytes(injected.changed[0]["expected"],
                                    "baseline"))


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
                            "apps": harness.application_state(application("apps"))},
                        evaluated_at=101, evaluated_signal=True,
                        evaluated_reads=["Deployment/invenio-web"]),
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
            observation(101, deployment=web_deployment(image="drift:tag"),
                        evaluated_at=101, evaluated_signal=True,
                        evaluated_reads=["Deployment/invenio-web"]),
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


class CompletedObservationTimingTests(unittest.TestCase):
    def setUp(self):
        self.spec = contract()

    def run_timeline(self, samples, scenario="B", arm="gitops",
                     timeout=30, injected=None, baseline=None, evidence_at=None):
        return harness.analyze_timeline(
            contract=self.spec, samples=samples, injection=injected or injection(),
            arm=arm, scenario=scenario, timeout=timeout, baseline=baseline,
            evidence_at=evidence_at,
        )

    def test_capture_start_before_a_field_read_never_becomes_primary(self):
        sample = observation(
            100.0, deployment=web_deployment(image="drift:tag"),
            argo={"invenio-bootstrap": harness.application_state(
                      application(sync="OutOfSync")),
                  "apps": harness.application_state(application("apps"))},
            acquisition=acquisition_for(
                100.0, read_finish=100.2,
                starts={"Application/invenio-bootstrap": 100.15},
                finishes={"Application/invenio-bootstrap": 100.2}),
            evaluated_at=100.2, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"],
        )
        out = self.run_timeline([sample], injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertAlmostEqual(out["detection_seconds"], 0.2)
        self.assertAlmostEqual(out["evidence_seconds"], 0.2)

    def test_ineligible_earlier_evidence_candidate_is_skipped(self):
        early = observation(
            99.9, deployment=web_deployment(image="drift:tag"),
            acquisition=acquisition_for(
                99.9, read_finish=100.5,
                starts={"Deployment/invenio-web": 99.9}),
            evaluated_at=100.6, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        eligible = observation(
            101.0, deployment=web_deployment(image="drift:tag"),
            evaluated_at=101.5, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        out = self.run_timeline(
            [early, eligible], timeout=30, evidence_at=point(101.5))
        self.assertEqual(out["evidence_seconds"], 1.5)

    def test_late_earlier_evidence_candidate_is_skipped(self):
        late = observation(
            100.0, deployment=web_deployment(image="drift:tag"),
            acquisition=acquisition_for(
                100.0, read_finish=100.5),
            evaluated_at=131.0, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        eligible = observation(
            101.0, deployment=web_deployment(image="drift:tag"),
            evaluated_at=101.5, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        out = self.run_timeline(
            [late, eligible], timeout=30, evidence_at=point(101.5))
        self.assertEqual(out["evidence_seconds"], 1.5)

    def test_gitops_evidence_is_not_synthesized_from_read_completion(self):
        sample = observation(
            101.0, deployment=web_deployment(image="drift:tag"))
        out = self.run_timeline([sample], evidence_at=point(101.0))
        self.assertIsNone(out["evidence_seconds"])
        self.assertEqual(out["evidence_status"], "right_censored")

    def test_gitops_late_evaluation_is_not_backdated(self):
        sample = observation(
            101.0, deployment=web_deployment(image="drift:tag"),
            evaluated_at=131.0, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        out = self.run_timeline([sample], timeout=30, evidence_at=point(131.0))
        self.assertIsNone(out["evidence_seconds"])
        self.assertEqual(out["evidence_status"], "right_censored")

    def test_gitops_timely_evaluation_uses_its_completion(self):
        sample = observation(
            101.0, deployment=web_deployment(image="drift:tag"),
            evaluated_at=101.5, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        out = self.run_timeline([sample], timeout=30, evidence_at=point(101.5))
        self.assertEqual(out["evidence_seconds"], 1.5)

    def test_hpa_late_evaluation_is_not_backdated(self):
        drifted = web_deployment()
        drifted["spec"]["replicas"] = 1
        hpa = harness.hpa_state(
            web_hpa(desired=2, current=2), drifted)
        late = observation(
            101.0, deployment=drifted, hpa=hpa,
            evaluated_at=131.0, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web",
                             "HorizontalPodAutoscaler/invenio-web-hpa"])
        late_out = self.run_timeline(
            [late], scenario="A", timeout=30, evidence_at=point(131.0))
        self.assertIsNone(late_out["evidence_seconds"])
        timely = observation(
            101.0, deployment=drifted, hpa=hpa,
            evaluated_at=101.5, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web",
                             "HorizontalPodAutoscaler/invenio-web-hpa"])
        timely_out = self.run_timeline(
            [timely], scenario="A", timeout=30, evidence_at=point(101.5))
        self.assertEqual(timely_out["evidence_seconds"], 1.5)

    def test_transient_diff_without_evaluation_is_not_evidence(self):
        sample = observation(
            101.0, deployment=web_deployment(image="drift:tag"),
            evaluated_at=101.0, evaluated_signal=False,
            evaluated_reads=[])
        out = self.run_timeline([sample], evidence_at=point(101.0))
        self.assertIsNone(out["evidence_seconds"])

    def test_evidence_at_mismatching_sample_event_fails_closed(self):
        sample = observation(
            101.0, deployment=web_deployment(image="drift:tag"),
            evaluated_at=101.0, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"])
        with self.assertRaises(harness.InstrumentationError):
            self.run_timeline([sample], evidence_at=point(102.0))

    def test_read_starting_before_t0_is_excluded(self):
        sample = observation(
            99.9, deployment=web_deployment(image="drift:tag"),
            acquisition=acquisition_for(
                99.9, read_finish=100.2,
                starts={"Application/invenio-bootstrap": 99.9}),
        )
        out = self.run_timeline([sample], injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertIsNone(out["detection_seconds"])
        self.assertEqual(out["detection_status"], "right_censored")

    def test_read_finishing_after_the_deadline_is_excluded(self):
        sample = observation(
            100.0, deployment=web_deployment(image="drift:tag"),
            argo={"invenio-bootstrap": harness.application_state(
                      application(sync="OutOfSync")),
                  "apps": harness.application_state(application("apps"))},
            acquisition=acquisition_for(
                100.0, read_finish=101.0001,
                starts={"Application/invenio-bootstrap": 100.1}),
        )
        out = self.run_timeline([sample], timeout=1, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertIsNone(out["detection_seconds"])
        self.assertIsNone(out["evidence_seconds"])

    def test_read_completing_exactly_at_the_deadline_is_eligible(self):
        sample = observation(
            100.0, deployment=web_deployment(image="drift:tag"),
            argo={"invenio-bootstrap": harness.application_state(
                      application(sync="OutOfSync")),
                  "apps": harness.application_state(application("apps"))},
            acquisition=acquisition_for(
                100.0, read_finish=101.0,
                starts={"Application/invenio-bootstrap": 100.1},
                finishes={"Application/invenio-bootstrap": 101.0}),
        )
        out = self.run_timeline([sample], timeout=1, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertEqual(out["detection_seconds"], 1.0)

    def test_capture_entirely_after_the_deadline_is_diagnostic_only(self):
        sample = observation(
            102.0, deployment=web_deployment(image="drift:tag"),
            argo={"invenio-bootstrap": harness.application_state(
                      application(sync="OutOfSync")),
                  "apps": harness.application_state(application("apps"))},
            acquisition=acquisition_for(102.0, read_finish=102.2))
        out = self.run_timeline([sample], timeout=1, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertIsNone(out["detection_seconds"])
        self.assertIsNone(out["evidence_seconds"])
        self.assertIsNone(out["recovery_seconds"])
        self.assertIsNone(out["r1_first"])
        self.assertEqual(out["r1_first_reason"], "no_eligible_capture")
        self.assertEqual(out["status"], "right_censored")

    def test_a_valid_read_before_command_acknowledgement_is_eligible(self):
        sample = observation(
            100.0, deployment=web_deployment(image="drift:tag"),
            argo={"invenio-bootstrap": harness.application_state(
                      application(sync="OutOfSync")),
                  "apps": harness.application_state(application("apps"))},
            acquisition=acquisition_for(
                100.0, read_finish=100.2,
                starts={"Application/invenio-bootstrap": 100.1},
                finishes={"Application/invenio-bootstrap": 100.2}),
            evaluated_at=100.2, evaluated_signal=True,
            evaluated_reads=["Deployment/invenio-web"],
        )
        out = self.run_timeline([sample], injected=injection(
            started=100.0, ack=100.5, verified=100.6, accepted=True),
            evidence_at=point(100.2))
        self.assertAlmostEqual(out["detection_seconds"], 0.2)
        self.assertAlmostEqual(out["evidence_seconds"], 0.2)

    def test_late_confirmation_is_not_observed_recovery(self):
        first = observation(101.0)
        second = observation(
            102.0, acquisition=acquisition_for(
                102.0, read_finish=102.06))
        out = self.run_timeline([first, second], timeout=2, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertIsNone(out["recovery_seconds"])
        self.assertEqual(out["recovery_status"], "right_censored")
        self.assertEqual(out["t_r_first_seconds"], 1.0)
        self.assertIsNone(out["t_r_confirmed_seconds"])
        self.assertEqual(out["recovery_confirmation"], "late_confirmation")
        self.assertEqual(out["status"], "right_censored")

    def test_confirmation_uses_read_completion_not_capture_start(self):
        first = observation(
            101.0, acquisition=acquisition_for(101.0, read_finish=101.1))
        second = observation(
            102.0, acquisition=acquisition_for(102.0, read_finish=102.1))
        out = self.run_timeline([first, second], timeout=30, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertAlmostEqual(out["recovery_seconds"], 1.1)
        self.assertAlmostEqual(out["t_r_first_seconds"], 1.1)
        self.assertAlmostEqual(out["t_r_confirmed_seconds"], 2.1)
        self.assertEqual(out["recovery_pair"][0].mono, 101.1)
        self.assertEqual(out["recovery_pair"][1].mono, 102.1)
        self.assertEqual(out["recovery_confirmation"], "confirmed")

    def test_a_mismatch_breaks_the_confirmation_pair(self):
        samples = [
            observation(101.0),
            observation(102.0, deployment=web_deployment(image="drift:tag")),
            observation(103.0),
            observation(104.0),
        ]
        out = self.run_timeline(samples, timeout=30, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertEqual(out["recovery_seconds"], 3.0)
        self.assertEqual(out["t_r_first_seconds"], 3.0)
        self.assertEqual(out["t_r_confirmed_seconds"], 4.0)

    def test_r1_first_and_last_require_eligible_completed_reads(self):
        before = observation(99.9, acquisition=acquisition_for(
            99.9, read_finish=100.2,
            starts={"Deployment/invenio-web": 99.9}))
        eligible = observation(101.0)
        late = observation(105.0, acquisition=acquisition_for(
            105.0, read_finish=105.5))
        out = self.run_timeline([before, eligible, late], timeout=5,
                                injected=injection(
                                    started=100.0, ack=100.1, verified=100.2,
                                    accepted=True))
        self.assertEqual(out["r1_first"], 100)
        self.assertEqual(out["r1_last"], 100)
        self.assertEqual(out["r1_first_details"]["total"], 4)
        self.assertEqual(out["r1_last_details"]["total"], 4)

    def test_no_eligible_observation_leaves_r1_null_with_a_reason(self):
        sample = observation(99.9, acquisition=acquisition_for(
            99.9, read_finish=100.5,
            starts={"Deployment/invenio-web": 99.9}))
        out = self.run_timeline([sample], timeout=5, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertIsNone(out["r1_first"])
        self.assertIsNone(out["r1_last"])
        self.assertEqual(out["r1_first_reason"], "no_eligible_capture")
        self.assertEqual(out["r1_last_reason"], "no_eligible_capture")

    def test_malformed_acquisition_bounds_fail_closed(self):
        sample = observation(101.0, acquisition=acquisition_for(101.0))
        sample.acquisition["reads"]["Deployment/invenio-web"][
            "finished_mono"] = float("nan")
        with self.assertRaises(harness.InstrumentationError):
            self.run_timeline([sample])

    def test_missing_detection_with_confirmed_recovery_stays_unobserved(self):
        samples = [observation(101.0), observation(102.0)]
        out = self.run_timeline(samples, timeout=30, injected=injection(
            started=100.0, ack=100.1, verified=100.2, accepted=True))
        self.assertIsNone(out["detection_seconds"])
        self.assertEqual(out["detection_status"], "unobserved_before_stop")
        self.assertEqual(out["status"], "observed")
        self.assertEqual(out["recovery_seconds"], 1.0)

    def test_visibility_boundary_recovery_ignores_extra_objects(self):
        samples = [
            observation(101.0,
                        extras=["exp-invenio-drift/Deployment/invenio-web"]),
            observation(102.0),
            observation(103.0),
        ]
        out = self.run_timeline(samples, scenario="F", timeout=30,
                                injected=injection(
                                    started=100.0, ack=100.1, verified=100.2,
                                    accepted=True))
        self.assertEqual(out["status"], "observed")
        self.assertEqual(out["recovery_seconds"], 2.0)
        self.assertIsNone(out["detection_ref"])

    def test_imperative_evidence_is_not_inferred_without_the_checker(self):
        samples = [
            observation(101.0, deployment=web_deployment(image="drift:tag")),
            observation(102.0),
            observation(103.0),
        ]
        out = self.run_timeline(
            samples, arm="imperative", timeout=30,
            injected=injection(started=100.0, ack=100.1, verified=100.2,
                               accepted=True))
        self.assertIsNone(out["detection_seconds"])
        self.assertIsNone(out["evidence_seconds"])
        self.assertEqual(out["detection_status"], "unobserved_before_stop")
        self.assertEqual(out["evidence_status"], "unobserved_before_stop")
        self.assertEqual(out["status"], "observed")
        self.assertEqual(out["recovery_seconds"], 2.0)


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
    def __init__(self, capture, clock, interval, join_timeout=10.0,
                 guarded=False):
        self.capture = capture
        self.clock = clock
        self.interval = interval
        self.join_timeout = join_timeout
        self.guarded = guarded
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
        return {"joined": True, "in_flight": False, "error": None,
                "late_result": False, "late_result_at": None,
                "late_error": None, "stopped_at_deadline": False}


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
        clock = AdvancingClock()
        fake = FakeKubectl(apps=apps, objects=objects, clock=clock)
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "imperative", "--scenario", "B", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
                "--timeout", "5", "--sample-interval", "0.01",
                "--imperative-interval", "0.01", "--baseline-timeout", "5",
                "--reset-timeout", "5", "--out", directory, "--run-id",
                "live-1",
            ])
            frozen = harness.load_declaration(
                path, digest, "b" * 40, "invenio")
            runner = harness.LiveRunner(
                args, {"declaration": frozen}, fake, clock)
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
            self.assertTrue(row["postcondition"]["verified"])
            self.assertTrue(row["postcondition"]["acquisition"]["reads"])
            self.assertEqual(row["r1_baseline"], 100.0)
            self.assertEqual(row["timing_convention"],
                             harness.TIMING_CONVENTION)
            self.assertEqual(row["recovery_confirmation"], "confirmed")
            self.assertIsNotNone(row["t_r_first_mono"])
            self.assertIsNotNone(row["t_r_confirmed_mono"])
            self.assertIsNotNone(row["t_e_store_mono"])
            self.assertGreaterEqual(row["t_e_store_mono"], row["t_e_mono"])
            self.assertEqual(row["r1_baseline_details"]["score"], 100)
            self.assertEqual(row["r1_first_details"]["total"], 4)
            self.assertEqual(row["r1_last_details"]["total"], 4)
            self.assertTrue(all(item["matched"] for item in
                                row["r1_last_details"]["resources"]))
            self.assertFalse((Path(directory) / "live-1" / "commands.jsonl")
                             .read_text().strip() == "")
            samples = [json.loads(line) for line in
                       (Path(directory) / "live-1" / "samples.jsonl")
                       .read_text().splitlines()]
            self.assertTrue(samples)
            self.assertTrue(all("acquisition" in sample for sample in samples))
            self.assertTrue(all(sample["acquisition"]["reads"]
                                for sample in samples))
            sampler = json.loads(
                (Path(directory) / "live-1" / "sampler.json").read_text())
            self.assertTrue(sampler["joined"])
            self.assertFalse(sampler["in_flight"])
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
        clock = AdvancingClock()
        fake = FakeKubectl(apps=apps, objects=objects, clock=clock)
        fake.pods = lambda namespace: [dict(UNREADY_POD)]
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "B", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
                "--timeout", "1", "--sample-interval", "0.01",
                "--baseline-timeout", "0.2", "--reset-timeout", "1",
                "--out", directory, "--run-id", "baseline-failed",
            ])
            frozen = harness.load_declaration(
                path, digest, "b" * 40, "invenio")
            runner = harness.LiveRunner(
                args, {"declaration": frozen}, fake, clock)
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

    def test_live_runner_without_declaration_fails_closed(self):
        objects = {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }
        clock = AdvancingClock()
        fake = FakeKubectl(objects=objects, clock=clock)
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "B", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
                "--timeout", "1", "--sample-interval", "0.01",
                "--baseline-timeout", "1", "--reset-timeout", "1",
                "--out", directory, "--run-id", "no-declaration",
            ])
            runner = harness.LiveRunner(
                args, {}, fake, clock)
            with mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            row = json.loads(
                (Path(directory) / "no-declaration.jsonl").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "safety_refusal")
            self.assertIn("frozen render declaration", row["error"])
            self.assertIsNone(row.get("injection"))
            self.assertEqual(fake.patches, [])
            self.assertEqual(fake.applies, [])
            self.assertEqual(fake.deletes, [])

    def test_g_baseline_refusal_preserves_a_preexisting_annotation(self):
        sealed = sealed_secret({harness.DRIFT_ANNOTATION: "preexisting"})
        clock = AdvancingClock()
        fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed,
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }, clock=clock)
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "G", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
                "--timeout", "1", "--sample-interval", "0.01",
                "--baseline-timeout", "1", "--reset-timeout", "1",
                "--out", directory, "--run-id", "g-refused",
            ])
            frozen = harness.load_declaration(
                path, digest, "b" * 40, "invenio")
            runner = harness.LiveRunner(
                args, {"declaration": frozen}, fake, clock)
            with mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            row = json.loads(
                (Path(directory) / "g-refused.jsonl").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "baseline_failure")
            self.assertIn("drift annotation", row["error"])
            self.assertIsNone(row.get("injection"))
            self.assertEqual(fake.annotations, [])
            annotations = fake.objects[
                ("SealedSecret", "invenio-app-secrets", "invenio")][
                "metadata"]["annotations"]
            self.assertEqual(annotations[harness.DRIFT_ANNOTATION],
                             "preexisting")

    def test_g_partial_failed_injection_cleanup_is_retained(self):
        class FailedGAnnotationKubectl(FakeKubectl):
            def annotate(self, kind, name, namespace, key, value=None):
                result = super().annotate(
                    kind, name, namespace, key, value)
                if value is not None:
                    result.returncode = 1
                    result.stderr = "annotation rejected"
                return result

        clock = AdvancingClock()
        fake = FailedGAnnotationKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }, clock=clock)
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "G", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
                "--timeout", "1", "--sample-interval", "0.01",
                "--baseline-timeout", "5", "--reset-timeout", "1",
                "--out", directory, "--run-id", "g-partial",
            ])
            frozen = harness.load_declaration(
                path, digest, "b" * 40, "invenio")
            runner = harness.LiveRunner(
                args, {"declaration": frozen}, fake, clock)
            with mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            row = json.loads(
                (Path(directory) / "g-partial.jsonl").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "invalid_injection")
            self.assertEqual(row["cleanup_status"], "ok")
            self.assertTrue(fake.annotations)
            self.assertIsNotNone(fake.annotations[0][4])
            self.assertIsNone(fake.annotations[-1][4])
            annotations = fake.objects[
                ("SealedSecret", "invenio-app-secrets", "invenio")][
                "metadata"].get("annotations", {})
            self.assertNotIn(harness.DRIFT_ANNOTATION, annotations)

    def test_live_baseline_divergence_is_not_repaired_or_accepted(self):
        objects = {
            ("Deployment", "invenio-web", "invenio"):
                web_deployment(image="drift:tag"),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }
        clock = AdvancingClock()
        fake = FakeKubectl(objects=objects, clock=clock)
        with tempfile.TemporaryDirectory() as directory:
            path, digest = write_render(directory)
            args = harness.parse_args([
                "--arm", "gitops", "--scenario", "B", "--rep", "1",
                "--live", "--confirm-single-stack", "--namespace", "invenio",
                "--app", "invenio-bootstrap",
                "--render-file", str(path),
                "--source-revision", "b" * 40, "--render-sha256", digest,
                "--timeout", "1", "--sample-interval", "0.01",
                "--baseline-timeout", "5", "--reset-timeout", "1",
                "--out", directory, "--run-id", "diverged",
            ])
            frozen = harness.load_declaration(
                path, digest, "b" * 40, "invenio")
            runner = harness.LiveRunner(
                args, {"declaration": frozen}, fake, clock)
            with mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            row = json.loads(
                (Path(directory) / "diverged.jsonl").read_text())
            self.assertEqual(code, 1)
            self.assertEqual(row["status"], "baseline_failure")
            self.assertIn("frozen declaration", row["error"])
            self.assertIsNone(row.get("injection"))
            self.assertEqual(fake.patches, [])
            self.assertEqual(fake.applies, [])
            self.assertEqual(fake.deletes, [])
            self.assertEqual(
                fake.objects[("Deployment", "invenio-web", "invenio")][
                    "spec"]["template"]["spec"]["containers"][0]["image"],
                "drift:tag")
            readiness = json.loads(
                (Path(directory) / "diverged" / "readiness.json").read_text())
            self.assertEqual(readiness[-1]["reason"],
                             "declaration_mismatch")


class SamplerLifecycleTests(unittest.TestCase):
    def test_real_capture_stops_between_reads_after_stop(self):
        import threading

        class BlockingServiceKubectl(FakeKubectl):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.blocked = threading.Event()
                self.release = threading.Event()

            def read(self, kind, name=None, namespace=None, selector=None):
                if kind == "Service":
                    self.blocked.set()
                    self.release.wait(2)
                return super().read(kind, name, namespace, selector)

        clock = AdvancingClock()
        fake = BlockingServiceKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }, clock=clock)
        snapshotter = harness.Snapshotter(
            fake, "invenio", "exp-invenio-drift", clock,
            configmap_name="invenio-app-config-6dg2chdbh4")
        sampler = harness.Sampler(
            snapshotter.capture, clock, 0.01, join_timeout=0.01, guarded=True)
        sampler.start()
        self.assertTrue(fake.blocked.wait(2))
        state = sampler.stop()
        self.assertFalse(state["joined"])
        self.assertTrue(state["in_flight"])
        fake.release.set()
        sampler.join(timeout=2)
        self.assertEqual(sampler.snapshot(), [])
        self.assertIsNotNone(sampler.stopped_capture)
        self.assertIn("Service/invenio-web", sampler.stopped_capture["reads"])
        read_kinds = {record["kind"] for record in fake.reads}
        self.assertNotIn("HorizontalPodAutoscaler", read_kinds)
        self.assertNotIn("Application", read_kinds)

    def test_real_capture_stops_between_reads_at_deadline(self):
        import threading

        class BlockingServiceKubectl(FakeKubectl):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.blocked = threading.Event()
                self.release = threading.Event()

            def read(self, kind, name=None, namespace=None, selector=None):
                if kind == "Service":
                    self.blocked.set()
                    self.release.wait(2)
                return super().read(kind, name, namespace, selector)

        clock = AdvancingClock()
        fake = BlockingServiceKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }, clock=clock)
        snapshotter = harness.Snapshotter(
            fake, "invenio", "exp-invenio-drift", clock,
            configmap_name="invenio-app-config-6dg2chdbh4")
        sampler = harness.Sampler(
            snapshotter.capture, clock, 0.01, join_timeout=1, guarded=True)
        sampler.start()
        self.assertTrue(fake.blocked.wait(2))
        sampler.deadline = 0.0
        fake.release.set()
        sampler.join(timeout=2)
        self.assertTrue(sampler.stopped_at_deadline)
        self.assertEqual(sampler.snapshot(), [])
        self.assertIsNotNone(sampler.stopped_capture)
        read_kinds = {record["kind"] for record in fake.reads}
        self.assertNotIn("HorizontalPodAutoscaler", read_kinds)
        self.assertNotIn("Application", read_kinds)

    def test_sampler_stop_does_not_shadow_thread_stop(self):
        sampler = harness.Sampler(
            lambda: {"ok": True}, harness.FakeClock([1.0]), 0.01,
        )
        sampler.start()
        self.assertTrue(sampler.wait_ready(timeout=2))
        sampler.stop()
        self.assertFalse(sampler.is_alive())

    def test_stop_before_first_sample_reports_an_unfinished_join(self):
        import threading

        class BlockingCapture:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()

            def __call__(self):
                self.entered.set()
                self.release.wait(2)
                return {"ok": True}

        capture = BlockingCapture()
        sampler = harness.Sampler(capture, harness.FakeClock([1.0]), 0.01,
                                  join_timeout=0.01)
        sampler.start()
        self.assertTrue(capture.entered.wait(2))
        state = sampler.stop()
        self.assertFalse(state["joined"])
        self.assertTrue(state["in_flight"])
        capture.release.set()
        sampler.join(timeout=2)
        self.assertEqual(sampler.snapshot(), [])

    def test_completion_during_stop_is_retained_before_finalization(self):
        import threading

        class ReleaseCapture:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()

            def __call__(self):
                self.entered.set()
                self.release.wait(2)
                return {"ok": True}

        capture = ReleaseCapture()
        sampler = harness.Sampler(capture, harness.FakeClock([1.0]), 0.01,
                                  join_timeout=2)
        sampler.start()
        self.assertTrue(capture.entered.wait(2))
        capture.release.set()
        state = sampler.stop()
        self.assertTrue(state["joined"])
        self.assertFalse(state["in_flight"])
        self.assertEqual(sampler.snapshot(), [{"ok": True}])

    def test_late_exception_is_surfaced_and_never_appended(self):
        import threading

        class LateFailure:
            def __init__(self):
                self.entered = threading.Event()
                self.release = threading.Event()

            def __call__(self):
                self.entered.set()
                self.release.wait(2)
                raise RuntimeError("late read failure")

        capture = LateFailure()
        sampler = harness.Sampler(capture, harness.FakeClock([1.0]), 0.01,
                                  join_timeout=0.01)
        sampler.start()
        self.assertTrue(capture.entered.wait(2))
        state = sampler.stop()
        self.assertFalse(state["joined"])
        capture.release.set()
        sampler.join(timeout=2)
        self.assertEqual(sampler.snapshot(), [])
        self.assertIsNotNone(sampler.late_error)

    def test_deadline_stops_new_reads(self):
        calls = []

        def capture():
            calls.append(True)
            return {"ok": True}

        sampler = harness.Sampler(capture, harness.FakeClock([2.0]), 0.01)
        sampler.deadline = 1.0
        sampler.start()
        sampler.join(timeout=2)
        self.assertEqual(calls, [])
        self.assertTrue(sampler.stopped_at_deadline)


class AcquisitionBoundsTests(unittest.TestCase):
    def objects(self):
        return {
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }

    def test_capture_records_completed_read_bounds(self):
        clock = AdvancingClock()
        fake = FakeKubectl(objects=self.objects(), clock=clock)
        sample = harness.Snapshotter(
            fake, "invenio", "exp-invenio-drift", clock,
            configmap_name="invenio-app-config-6dg2chdbh4").capture()
        self.assertIn("reads", sample.acquisition)
        self.assertGreater(sample.acquisition["finished_mono"],
                           sample.at.mono)
        self.assertTrue(sample.acquisition["reads"])
        self.assertNotIn("stdout", json.dumps(sample.acquisition))

    def test_read_retry_keeps_the_successful_attempt_bounds(self):
        kubectl = harness.Kubectl(harness.FakeClock([10.0]))
        bad = result(code=1, stderr="Unexpected error when reading response body",
                     started=point(10), finished=point(11))
        good = result(stdout='{"kind":"ConfigMap","metadata":{"name":"x"}}',
                      started=point(12), finished=point(13))
        with mock.patch.object(kubectl, "run", side_effect=[bad, good]):
            payload, bounds = kubectl.read("ConfigMap", "x", "invenio")
        self.assertEqual(payload["metadata"]["name"], "x")
        self.assertEqual(bounds["started_mono"], 12)
        self.assertEqual(bounds["finished_mono"], 13)
        self.assertEqual(len(bounds["attempts"]), 2)
        self.assertFalse(bounds["attempts"][0]["ok"])
        self.assertTrue(bounds["attempts"][1]["ok"])

    def test_failed_read_retains_safe_partial_acquisition(self):
        clock = AdvancingClock()

        class FailingKubectl(FakeKubectl):
            def read(self, kind, name=None, namespace=None, selector=None):
                if kind == "Service":
                    started = self._now()
                    finished = self._now()
                    record = {
                        "kind": kind, "name": name, "namespace": namespace,
                        "started_utc": started.utc,
                        "started_mono": started.mono,
                        "finished_utc": finished.utc,
                        "finished_mono": finished.mono,
                        "ok": False, "present": False,
                        "attempts": [],
                    }
                    error = harness.InstrumentationError("service read failed")
                    error.read_bounds = record
                    raise error
                return super().read(kind, name, namespace, selector)

        fake = FailingKubectl(objects=self.objects(), clock=clock)
        snapshotter = harness.Snapshotter(
            fake, "invenio", "exp-invenio-drift", clock,
            configmap_name="invenio-app-config-6dg2chdbh4")
        with self.assertRaises(harness.InstrumentationError) as caught:
            snapshotter.capture()
        acquisition = caught.exception.acquisition
        self.assertFalse(acquisition["reads"]["Service/invenio-web"]["ok"])
        self.assertIn("Deployment/invenio-web", acquisition["reads"])
        serialized = json.dumps(acquisition)
        self.assertNotIn("PLAINTEXT-MUST-NOT-LEAK", serialized)


class PostconditionTimingTests(unittest.TestCase):
    def test_capture_completing_after_the_reset_deadline_is_not_accepted(self):
        clock = ReadinessClock()

        class LateSnapshotter:
            namespace = "invenio"

            def capture(self):
                clock.advance(2)
                return observation()

        args = harness.parse_args([
            "--arm", "gitops", "--scenario", "B", "--rep", "1",
            "--namespace", "invenio", "--app", "invenio-bootstrap",
            "--reset-timeout", "1", "--sample-interval", "0.01",
        ])
        runner = harness.LiveRunner(args, {}, FakeKubectl(), clock)
        postcondition = runner._postcondition(
            LateSnapshotter(), contract(), "B", "gitops")
        self.assertFalse(postcondition["verified"])
        self.assertEqual(postcondition["reason"], "deadline")
        self.assertIn("acquisition", postcondition)
        self.assertGreater(
            postcondition["acquisition"]["finished_mono"],
            postcondition["deadline_mono"])


class SamplerFailureLiveTests(unittest.TestCase):
    def runner(self, directory, sampler, run_id, arm="gitops", scenario="B",
               timeout="1"):
        path, digest = write_render(directory)
        args = harness.parse_args([
            "--arm", arm, "--scenario", scenario, "--rep", "1",
            "--live", "--confirm-single-stack", "--namespace", "invenio",
            "--app", "invenio-bootstrap", "--render-file", str(path),
            "--source-revision", "b" * 40, "--render-sha256", digest,
            "--timeout", timeout, "--sample-interval", "0.01",
            "--imperative-interval", "0.01", "--baseline-timeout", "5",
            "--reset-timeout", "1", "--out", directory, "--run-id", run_id,
        ])
        frozen = harness.load_declaration(
            path, digest, "b" * 40, "invenio")
        clock = AdvancingClock()
        fake = FakeKubectl(objects={
            ("Deployment", "invenio-web", "invenio"): web_deployment(),
            ("ConfigMap", "invenio-app-config-6dg2chdbh4", "invenio"):
                web_configmap(),
            ("SealedSecret", "invenio-app-secrets", "invenio"): sealed_secret(),
            ("Service", "invenio-web", "invenio"): web_service(),
            ("HorizontalPodAutoscaler", "invenio-web-hpa", "invenio"): web_hpa(),
        }, clock=clock)
        return harness.LiveRunner(
            args, {"declaration": frozen}, fake, clock), sampler

    def run_with(self, context, directory, run_id):
        runner, sampler = context
        with mock.patch("harness.Sampler", return_value=sampler), \
                mock.patch("time.sleep", lambda _: None), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            code = runner.run()
        row = json.loads(
            (Path(directory) / (run_id + ".jsonl")).read_text())
        return code, row

    def test_live_collector_stamps_evaluation_after_a_slow_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.runner(
                directory, None, "slow-evaluator", timeout="3")
            fake = runner.kubectl
            clock = runner.clock
            deployment_key = ("Deployment", "invenio-web", "invenio")

            def capture():
                at = clock.now().mono
                deployment = copy.deepcopy(fake.objects[deployment_key])
                return observation(
                    at, deployment=deployment,
                    acquisition=acquisition_for(at, read_finish=at))

            sampler = DeterministicSampler(capture, clock, 0.01)
            original = harness.field_diffs
            calls = {"count": 0}

            def slow(contract, sample):
                result = original(contract, sample)
                if calls["count"] == 0:
                    clock.value += 0.2
                calls["count"] += 1
                return result

            with mock.patch.object(harness, "field_diffs", side_effect=slow), \
                    mock.patch("harness.Sampler", return_value=sampler), \
                    mock.patch("time.sleep", lambda _: None), \
                    mock.patch("sys.stdout", new_callable=io.StringIO):
                code = runner.run()
            row = json.loads(
                (Path(directory) / "slow-evaluator.jsonl").read_text())
            samples = [json.loads(line) for line in
                       (Path(directory) / "slow-evaluator" / "samples.jsonl")
                       .read_text().splitlines()]
            signal = next(sample for sample in samples
                          if sample["evaluated_signal"])
            read_finish = max(record["finished_mono"]
                              for record in signal["acquisition"]["reads"].values())
            self.assertEqual(code, 1)
            self.assertGreater(signal["evaluated_at"]["mono"], read_finish)
            self.assertGreater(signal["evaluated_at"]["mono"],
                               signal["at"]["mono"])
            self.assertGreater(row["evidence_seconds"], 0)
            self.assertAlmostEqual(
                row["t_e_mono"], signal["evaluated_at"]["mono"])
            self.assertIsNotNone(row["t_e_store_mono"])

    def test_sampler_error_after_injection_is_an_instrumentation_failure(self):
        class ErroringSampler(DeterministicSampler):
            def snapshot(self):
                sample = super().snapshot()
                self.error = RuntimeError("late read failure")
                return sample

            def stop(self):
                return {"joined": True, "in_flight": False,
                        "error": str(self.error), "late_result": False,
                        "late_error": None, "stopped_at_deadline": False}

        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.runner(directory, None, "sampler-error")
            context = (runner, ErroringSampler(
                lambda: observation(1.0), runner.clock, 0.01))
            code, row = self.run_with(context, directory, "sampler-error")
        self.assertEqual(code, 1)
        self.assertEqual(row["status"], "instrumentation_failure")
        self.assertIn("late read failure", row["error"])
        self.assertNotEqual(row["status"], "right_censored")

    def test_initial_wait_failure_is_an_explicit_failure(self):
        class NoSampleSampler(DeterministicSampler):
            def wait_ready(self, timeout=10):
                return False

            def snapshot(self):
                return []

            def stop(self):
                return {"joined": True, "in_flight": False,
                        "error": None, "late_result": False,
                        "late_error": None, "stopped_at_deadline": False}

        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.runner(directory, None, "no-sample")
            context = (runner, NoSampleSampler(lambda: None,
                                               runner.clock, 0.01))
            code, row = self.run_with(context, directory, "no-sample")
        self.assertEqual(code, 1)
        self.assertEqual(row["status"], "instrumentation_failure")
        self.assertIn("initial sample", row["error"])

    def test_in_flight_collector_is_an_explicit_failure(self):
        class InFlightSampler(DeterministicSampler):
            def stop(self):
                return {"joined": False, "in_flight": True,
                        "error": None, "late_result": False,
                        "late_error": None, "stopped_at_deadline": False}

        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.runner(directory, None, "in-flight")
            context = (runner, InFlightSampler(lambda: observation(1.0),
                                               runner.clock, 0.01))
            code, row = self.run_with(context, directory, "in-flight")
        self.assertEqual(code, 1)
        self.assertEqual(row["status"], "instrumentation_failure")
        self.assertIn("did not join", row["error"])


if __name__ == "__main__":
    unittest.main()
