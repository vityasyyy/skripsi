"""Independent frozen-render declaration for the scoped R1 oracle.

The bundle is a JSON export of the GitOps render at a frozen revision. Only the
four scoped resources are selected; every other rendered object is ignored.
Secret values and SealedSecret ciphertext are never selected or emitted.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

FORMAT = "invenio-frozen-render-v1"
WEB_DEPLOYMENT = "invenio-web"
WEB_SERVICE = "invenio-web"
SEALED_SECRET = "invenio-app-secrets"
CONFIG_PREFIX = "invenio-app-config-"
CONFIG_KEY = "INSTANCE_TAGLINE"
DRIFT_ANNOTATION = "experiment.invenio.ugm/drift"
DEPLOYMENT_CONTAINER = "web"
REVISION = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
DEPLOYMENT_FIELDS = (
    "/spec/template/spec/containers/web/image",
    "/spec/template/spec/containers/web/resources/requests/cpu",
    "/spec/template/spec/containers/web/resources/requests/memory",
    "/spec/template/spec/containers/web/resources/limits/cpu",
    "/spec/template/spec/containers/web/resources/limits/memory",
)


class DeclarationError(ValueError):
    pass


@dataclass(frozen=True)
class Declaration:
    source_revision: str
    render_sha256: str
    configmap_name: str
    resources: tuple
    format: str = FORMAT

    def as_dict(self) -> dict:
        return {
            "format": self.format,
            "source_revision": self.source_revision,
            "render_sha256": self.render_sha256,
            "configmap_name": self.configmap_name,
            "resources": [
                {key: copy.deepcopy(resource[key])
                 for key in ("id", "kind", "name", "namespace", "fields")}
                for resource in self.resources
            ],
        }


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DeclarationError("render bundle has duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(value):
    raise DeclarationError("render bundle contains a non-finite number")


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise DeclarationError("render bundle contains a non-finite number")
    return value


def load(path, expected_sha256: str, expected_revision: str,
         namespace: str) -> Declaration:
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise DeclarationError(
            f"cannot read render bundle: {error.strerror or type(error).__name__}"
        ) from None
    return loads(data, expected_sha256, expected_revision, namespace)


def loads(data: bytes, expected_sha256: str, expected_revision: str,
          namespace: str) -> Declaration:
    if (not isinstance(expected_sha256, str)
            or not SHA256.fullmatch(expected_sha256)):
        raise DeclarationError("render SHA-256 must be 64 lowercase hex")
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise DeclarationError("render bundle SHA-256 does not match --render-sha256")
    if (not isinstance(expected_revision, str)
            or not REVISION.fullmatch(expected_revision)):
        raise DeclarationError("frozen source revision must be 40 lowercase hex")
    try:
        bundle = json.loads(
            data,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except DeclarationError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DeclarationError("render bundle is not valid JSON") from None
    if not isinstance(bundle, dict):
        raise DeclarationError("render bundle is not a JSON object")
    if bundle.get("format") != FORMAT:
        raise DeclarationError(f"render bundle format must be {FORMAT!r}")
    revision = bundle.get("source_revision")
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise DeclarationError("render bundle source_revision must be 40 lowercase hex")
    if revision != expected_revision:
        raise DeclarationError(
            "render bundle revision does not match --source-revision")
    objects = bundle.get("objects")
    if not isinstance(objects, list):
        raise DeclarationError("render bundle objects must be an array")
    _validate_objects(objects)
    index = _index_objects(objects)
    deployment = _target(index, "Deployment", WEB_DEPLOYMENT, namespace)
    container = _web_container(deployment)
    configmap_name = _configmap_reference(container)
    configmap = _target(index, "ConfigMap", configmap_name, namespace)
    service = _target(index, "Service", WEB_SERVICE, namespace)
    sealed = _target(index, "SealedSecret", SEALED_SECRET, namespace)

    resources = (
        _resource(deployment, namespace),
        _resource(configmap, namespace),
        _resource(service, namespace),
        _resource(sealed, namespace),
    )
    _validate_fields(resources)
    return Declaration(
        source_revision=revision,
        render_sha256=digest,
        configmap_name=configmap_name,
        resources=resources,
    )


def selected_fields(doc: dict) -> dict:
    """Return the scoped measured fields of one observed or declared object."""
    kind = doc.get("kind")
    if kind == "Deployment":
        container = _container(doc)
        if container is None:
            return {}
        resources = _mapping(container.get("resources"))
        requests = _mapping(resources.get("requests"))
        limits = _mapping(resources.get("limits"))
        return {
            "/spec/template/spec/containers/web/image": container.get("image"),
            "/spec/template/spec/containers/web/resources/requests/cpu":
                requests.get("cpu"),
            "/spec/template/spec/containers/web/resources/requests/memory":
                requests.get("memory"),
            "/spec/template/spec/containers/web/resources/limits/cpu":
                limits.get("cpu"),
            "/spec/template/spec/containers/web/resources/limits/memory":
                limits.get("memory"),
        }
    if kind == "ConfigMap":
        data = doc.get("data")
        if not isinstance(data, dict):
            return {}
        return {"/data/" + str(key): value for key, value in data.items()}
    if kind == "SealedSecret":
        metadata = _mapping(doc.get("metadata"))
        annotations = _mapping(metadata.get("annotations"))
        return {"/metadata/annotations/" + DRIFT_ANNOTATION:
                annotations.get(DRIFT_ANNOTATION)}
    if kind == "Service":
        spec = _mapping(doc.get("spec"))
        ports = spec.get("ports")
        first = (ports[0] if isinstance(ports, list) and ports
                 and isinstance(ports[0], dict) else {})
        selector = _mapping(spec.get("selector"))
        return {
            "/spec/type": spec.get("type"),
            "/spec/selector/app.kubernetes.io/name":
                selector.get("app.kubernetes.io/name"),
            "/spec/ports/0/port": first.get("port"),
            "/spec/ports/0/targetPort": first.get("targetPort"),
        }
    return {}


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _container(doc: dict):
    spec = _mapping(doc.get("spec"))
    template = _mapping(spec.get("template"))
    pod_spec = _mapping(template.get("spec"))
    containers = pod_spec.get("containers", [])
    if not isinstance(containers, list):
        return None
    return next((item for item in containers
                 if isinstance(item, dict)
                 and item.get("name") == DEPLOYMENT_CONTAINER), None)


def _web_container(deployment: dict) -> dict:
    spec = _mapping(deployment.get("spec"))
    template = _mapping(spec.get("template"))
    pod_spec = _mapping(template.get("spec"))
    containers = pod_spec.get("containers")
    if not isinstance(containers, list):
        raise DeclarationError("declared Deployment has no containers")
    matches = [item for item in containers
               if isinstance(item, dict)
               and item.get("name") == DEPLOYMENT_CONTAINER]
    if len(matches) != 1:
        raise DeclarationError(
            "declared Deployment must have exactly one web container")
    return matches[0]


def _configmap_reference(container: dict) -> str:
    sources = container.get("envFrom")
    if not isinstance(sources, list):
        raise DeclarationError("declared web container has no envFrom")
    names = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        reference = source.get("configMapRef")
        if not isinstance(reference, dict):
            continue
        name = reference.get("name")
        if isinstance(name, str) and name.startswith(CONFIG_PREFIX):
            names.append(name)
    if len(names) != 1:
        raise DeclarationError(
            "declared web envFrom must reference exactly one generated ConfigMap")
    return names[0]


def _validate_objects(objects) -> None:
    for item in objects:
        if not isinstance(item, dict):
            raise DeclarationError(
                "render bundle objects must be object dictionaries")
        if not isinstance(item.get("apiVersion"), str) or not item["apiVersion"]:
            raise DeclarationError(
                "render bundle contains an object without apiVersion")
        if not isinstance(item.get("kind"), str) or not item["kind"]:
            raise DeclarationError(
                "render bundle contains an object without kind")
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            raise DeclarationError(
                "render bundle contains an object without metadata")
        if not isinstance(metadata.get("name"), str) or not metadata["name"]:
            raise DeclarationError(
                "render bundle contains an object without a name")


def _index_objects(objects):
    index = {}
    for item in objects:
        index.setdefault(
            (item["kind"], item["metadata"]["name"]), []).append(item)
    return index


def _target(index, kind: str, name: str, namespace: str) -> dict:
    matches = index.get((kind, name), [])
    if not matches:
        raise DeclarationError(f"frozen render is missing {kind}/{name}")
    if len(matches) != 1:
        raise DeclarationError(f"frozen render has duplicate {kind}/{name}")
    item = matches[0]
    observed = (item.get("metadata") or {}).get("namespace")
    if observed != namespace:
        raise DeclarationError(
            f"{kind}/{name} is not in namespace {namespace!r}")
    return item


def _resource(doc: dict, namespace: str) -> dict:
    name = (doc.get("metadata") or {}).get("name")
    return {
        "id": f"{doc.get('kind')}/{name}",
        "kind": doc.get("kind"),
        "name": name,
        "namespace": namespace,
        "fields": selected_fields(doc),
        "manifest": copy.deepcopy(doc),
    }


def _validate_fields(resources) -> None:
    for resource in resources:
        fields = resource["fields"]
        kind = resource["kind"]
        metadata = _mapping(resource["manifest"].get("metadata"))
        annotations = metadata.get("annotations")
        if annotations is not None and not isinstance(annotations, dict):
            raise DeclarationError(
                f"{resource['id']} metadata.annotations must be an object")
        if kind == "Deployment":
            _require_fields(fields, DEPLOYMENT_FIELDS, resource["id"])
            for path in DEPLOYMENT_FIELDS:
                if not isinstance(fields[path], str) or not fields[path].strip():
                    raise DeclarationError(
                        f"{resource['id']} field {path} must be a non-empty string")
        elif kind == "ConfigMap":
            if not fields:
                raise DeclarationError(
                    f"{resource['id']} has no data fields")
            if "/data/" + CONFIG_KEY not in fields:
                raise DeclarationError(
                    f"{resource['id']} is missing /data/{CONFIG_KEY}")
            for path, value in fields.items():
                if not isinstance(value, str):
                    raise DeclarationError(
                        f"{resource['id']} field {path} must be a string")
        elif kind == "Service":
            paths = (
                "/spec/selector/app.kubernetes.io/name",
                "/spec/ports/0/port",
                "/spec/ports/0/targetPort",
            )
            _require_fields(fields, paths, resource["id"])
            kind_value = fields.get("/spec/type")
            if kind_value is not None and (
                    not isinstance(kind_value, str) or not kind_value):
                raise DeclarationError(
                    f"{resource['id']} field /spec/type must be a string")
            selector = fields["/spec/selector/app.kubernetes.io/name"]
            if not isinstance(selector, str) or not selector:
                raise DeclarationError(
                    f"{resource['id']} has no app.kubernetes.io/name selector")
            port = fields["/spec/ports/0/port"]
            if type(port) is not int or not 1 <= port <= 65535:
                raise DeclarationError(
                    f"{resource['id']} port must be an integer in 1..65535")
            target = fields["/spec/ports/0/targetPort"]
            if type(target) is int:
                if not 1 <= target <= 65535:
                    raise DeclarationError(
                        f"{resource['id']} targetPort is outside 1..65535")
            elif not isinstance(target, str) or not target:
                raise DeclarationError(
                    f"{resource['id']} targetPort must be an integer or name")
        elif kind == "SealedSecret":
            if not fields:
                raise DeclarationError(
                    f"{resource['id']} has no selected annotation field")
            if fields.get("/metadata/annotations/" + DRIFT_ANNOTATION) is not None:
                raise DeclarationError(
                    f"{resource['id']} already carries the drift annotation")


def _require_fields(fields: dict, paths, identity: str) -> None:
    for path in paths:
        if path not in fields or fields[path] is None:
            raise DeclarationError(f"{identity} is missing required field {path}")
