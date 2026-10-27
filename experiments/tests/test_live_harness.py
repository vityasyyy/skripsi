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


def result(argv=None, code=0, stdout="", stderr=""):
    return harness.CommandResult(
        argv=argv or ["kubectl"], returncode=code, stdout=stdout,
        stderr=stderr, started=point(0), finished=point(0),
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

    def test_cleanup_failure_is_reported(self):
        fake = FakeKubectl(fail_delete=True)
        fake.objects[("Namespace", "exp-invenio-drift", None)] = {
            "apiVersion": "v1", "kind": "Namespace",
            "metadata": {"name": "exp-invenio-drift"},
        }
        cleanup = harness.cleanup_quarantine(fake, "exp-invenio-drift")
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
