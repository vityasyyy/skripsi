"""Edge coverage for frozen render declaration validation; all bundles are synthetic."""

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "live"
sys.path.insert(0, str(LIVE))

import declaration  # noqa: E402

REVISION = "a" * 40
NAMESPACE = "exp-a"


def render_bundle():
    return {
        "format": declaration.FORMAT,
        "source_revision": REVISION,
        "objects": [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "invenio-web", "namespace": NAMESPACE},
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "web",
                                    "image": "ghcr.io/example/invenio:1",
                                    "envFrom": [
                                        {"configMapRef": {"name": "invenio-app-config-abc123"}}
                                    ],
                                    "resources": {
                                        "requests": {"cpu": "250m", "memory": "512Mi"},
                                        "limits": {"cpu": "1", "memory": "2Gi"},
                                    },
                                }
                            ]
                        }
                    }
                },
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "invenio-app-config-abc123", "namespace": NAMESPACE},
                "data": {"INSTANCE_TAGLINE": "frozen"},
            },
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "invenio-web", "namespace": NAMESPACE},
                "spec": {
                    "selector": {"app.kubernetes.io/name": "invenio-web"},
                    "ports": [{"port": 8000, "targetPort": "http"}],
                },
            },
            {
                "apiVersion": "bitnami.com/v1alpha1",
                "kind": "SealedSecret",
                "metadata": {"name": "invenio-app-secrets", "namespace": NAMESPACE},
                "spec": {"encryptedData": {"key": "SECRET-MUST-NOT-LEAK"}},
            },
        ],
    }


def object_of(bundle, kind):
    return next(item for item in bundle["objects"] if item["kind"] == kind)


def load(bundle, *, sha=None, revision=REVISION, namespace=NAMESPACE):
    data = json.dumps(bundle, sort_keys=True).encode()
    digest = hashlib.sha256(data).hexdigest()
    return declaration.loads(data, sha or digest, revision, namespace)


class DeclarationEdgesTest(unittest.TestCase):
    def test_valid_bundle_selects_four_resources(self):
        frozen = load(render_bundle())
        self.assertEqual(len(frozen.resources), 4)
        self.assertEqual(frozen.configmap_name, "invenio-app-config-abc123")

    def test_parse_float_accepts_finite_values(self):
        bundle = render_bundle()
        bundle["extra"] = 1.5
        self.assertEqual(load(bundle).source_revision, REVISION)

    def test_load_reports_unreadable_file(self):
        with self.assertRaisesRegex(declaration.DeclarationError, "cannot read render bundle"):
            declaration.load("/nonexistent/render.json", "a" * 64, REVISION, NAMESPACE)

    def test_invalid_expected_identity_digests_are_rejected(self):
        bundle = render_bundle()
        data = json.dumps(bundle, sort_keys=True).encode()
        digest = hashlib.sha256(data).hexdigest()
        with self.assertRaisesRegex(declaration.DeclarationError, "render SHA-256"):
            declaration.loads(data, "not-a-digest", REVISION, NAMESPACE)
        with self.assertRaisesRegex(declaration.DeclarationError, "frozen source revision"):
            declaration.loads(data, digest, "not-a-revision", NAMESPACE)

    def test_objects_must_be_an_array(self):
        bundle = render_bundle()
        bundle["objects"] = {"kind": "Deployment"}
        with self.assertRaisesRegex(declaration.DeclarationError, "objects must be an array"):
            load(bundle)

    def test_selected_fields_return_empty_for_missing_web_container(self):
        doc = {"kind": "Deployment", "spec": {"template": {"spec": {"containers": []}}}}
        self.assertEqual(declaration.selected_fields(doc), {})
        doc["spec"]["template"]["spec"]["containers"] = "not-a-list"
        self.assertEqual(declaration.selected_fields(doc), {})

    def test_deployment_must_have_exactly_one_web_container(self):
        bundle = render_bundle()
        containers = object_of(bundle, "Deployment")["spec"]["template"]["spec"]["containers"]
        containers.append(copy.deepcopy(containers[0]))
        with self.assertRaisesRegex(declaration.DeclarationError, "exactly one web container"):
            load(bundle)

    def test_env_from_shape_is_validated(self):
        bundle = render_bundle()
        container = object_of(bundle, "Deployment")["spec"]["template"]["spec"]["containers"][0]
        container["envFrom"] = {"configMapRef": {"name": "invenio-app-config-abc123"}}
        with self.assertRaisesRegex(declaration.DeclarationError, "no envFrom"):
            load(bundle)
        container["envFrom"] = ["ignored", {"configMapRef": {"name": "other-config"}}]
        with self.assertRaisesRegex(declaration.DeclarationError, "exactly one generated"):
            load(bundle)

    def test_render_objects_require_kind_and_metadata(self):
        for change, message in (
            (lambda item: item.pop("kind"), "without kind"),
            (lambda item: item.pop("metadata"), "without metadata"),
        ):
            bundle = render_bundle()
            change(bundle["objects"][0])
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(declaration.DeclarationError, message),
            ):
                load(bundle)

    def test_deployment_fields_must_be_non_empty_strings(self):
        bundle = render_bundle()
        container = object_of(bundle, "Deployment")["spec"]["template"]["spec"]["containers"][0]
        container["image"] = " "
        with self.assertRaisesRegex(declaration.DeclarationError, "non-empty string"):
            load(bundle)

    def test_configmap_values_must_be_strings(self):
        bundle = render_bundle()
        object_of(bundle, "ConfigMap")["data"]["INSTANCE_TAGLINE"] = 7
        with self.assertRaisesRegex(declaration.DeclarationError, "must be a string"):
            load(bundle)

    def test_service_type_selector_and_ports_are_validated(self):
        cases = (
            (lambda spec: spec.update(type=7), "field /spec/type must be a string"),
            (
                lambda spec: spec.update(selector={"app.kubernetes.io/name": ""}),
                "no app.kubernetes.io/name selector",
            ),
            (lambda spec: spec["ports"][0].update(port=0), "port must be an integer"),
            (lambda spec: spec["ports"][0].update(targetPort=70000), "targetPort is outside"),
            (lambda spec: spec["ports"][0].update(targetPort=["bad"]), "integer or name"),
        )
        for change, message in cases:
            bundle = render_bundle()
            change(object_of(bundle, "Service")["spec"])
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(declaration.DeclarationError, message),
            ):
                load(bundle)

    def test_sealed_secret_rejects_a_preexisting_drift_annotation(self):
        bundle = render_bundle()
        object_of(bundle, "SealedSecret")["metadata"]["annotations"] = {
            declaration.DRIFT_ANNOTATION: "present"
        }
        with self.assertRaisesRegex(declaration.DeclarationError, "already carries"):
            load(bundle)

    def test_selected_fields_cover_non_deployment_kinds(self):
        self.assertEqual(declaration.selected_fields({"kind": "Secret", "data": {}}), {})
        self.assertEqual(declaration.selected_fields({"kind": "ConfigMap"}), {})
        service = render_bundle()["objects"][2]
        self.assertIn("/spec/ports/0/targetPort", declaration.selected_fields(service))

    def test_as_dict_exposes_declared_identity(self):
        payload = load(render_bundle()).as_dict()
        self.assertEqual(payload["format"], declaration.FORMAT)
        self.assertEqual(len(payload["resources"]), 4)


if __name__ == "__main__":
    unittest.main()
