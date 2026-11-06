"""Pure offline binary detection metrics; no rule execution or persistence."""
from dataclasses import dataclass
import hashlib
import json
import math


MAX_EVENTS = 1000
MAX_FEATURE_BYTES = 2 * 1024 * 1024
_SUPERVISION_KEYS = frozenset({
    "label", "labels", "ground_truth", "groundtruth", "expected_match",
    "held_out", "heldout", "split", "split_membership",
})


class MetricsError(ValueError):
    """Fixed contract failures never include supplied features or labels."""


def _identifier(value):
    if type(value) is not str or not 1 <= len(value) <= 200 or value != value.strip():
        raise MetricsError("invalid_identity")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise MetricsError("invalid_identity")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _features(value, depth=0):
    if depth > 16:
        raise MetricsError("feature_depth_exceeded")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or key.casefold() in _SUPERVISION_KEYS:
                raise MetricsError("invalid_feature_key")
            _features(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _features(item, depth + 1)
    elif value is None or type(value) in (str, int, bool):
        return
    elif type(value) is float and math.isfinite(value):
        return
    else:
        raise MetricsError("invalid_feature_value")


@dataclass(frozen=True)
class Event:
    """Immutable canonical feature snapshot; supervision is a separate object."""
    event_id: str
    features_json: str

    @classmethod
    def from_features(cls, event_id, features):
        if type(features) is not dict:
            raise MetricsError("features_must_be_object")
        _features(features)
        return cls(event_id, _json(features))

    def __post_init__(self):
        _identifier(self.event_id)
        if type(self.features_json) is not str or len(self.features_json.encode("utf-8")) > MAX_FEATURE_BYTES:
            raise MetricsError("feature_size_exceeded")
        invalid = False
        try:
            value = json.loads(self.features_json)
            if type(value) is not dict:
                invalid = True
            else:
                _features(value)
                invalid = _json(value) != self.features_json
        except (ValueError, TypeError, RecursionError):
            invalid = True
        if invalid:
            raise MetricsError("invalid_canonical_features")

    def model_projection(self):
        # Always a fresh copy; dataset labels and split are never accessed here.
        return {"event_id": self.event_id, "fields": json.loads(self.features_json)}


@dataclass(frozen=True)
class Label:
    event_id: str
    value: str  # positive, negative, unknown; absent labels are also unknown.

    def __post_init__(self):
        _identifier(self.event_id)
        if type(self.value) is not str or self.value not in ("positive", "negative", "unknown"):
            raise MetricsError("invalid_label")


def _unique(items, kind):
    result = {}
    for item in items:
        if item.event_id in result:
            raise MetricsError("duplicate_" + kind + "_identity")
        result[item.event_id] = item
    return result


@dataclass(frozen=True)
class Dataset:
    version: str
    split: str  # tuning or held_out, intentionally excluded from projections.
    events: tuple[Event, ...]
    labels: tuple[Label, ...] = ()

    def __post_init__(self):
        _identifier(self.version)
        if type(self.split) is not str or self.split not in ("tuning", "held_out"):
            raise MetricsError("invalid_split")
        if type(self.events) is not tuple or len(self.events) > MAX_EVENTS or any(type(x) is not Event for x in self.events):
            raise MetricsError("invalid_events")
        if type(self.labels) is not tuple or len(self.labels) > MAX_EVENTS or any(type(x) is not Label for x in self.labels):
            raise MetricsError("invalid_labels")
        events = _unique(self.events, "event")
        labels = _unique(self.labels, "label")
        if not labels.keys() <= events.keys():
            raise MetricsError("label_event_missing")
        if sum(len(x.features_json.encode("utf-8")) for x in self.events) > MAX_FEATURE_BYTES:
            raise MetricsError("dataset_size_exceeded")

    def model_projection(self):
        return tuple(event.model_projection() for event in sorted(self.events, key=lambda x: x.event_id))

    @property
    def fingerprint(self):
        labels = {label.event_id: label.value for label in self.labels}
        content = {"schema": "detection-dataset-v1", "version": self.version, "split": self.split,
                   "events": [[event.event_id, event.features_json, labels.get(event.event_id, "unknown")]
                              for event in sorted(self.events, key=lambda x: x.event_id)]}
        return hashlib.sha256(_json(content).encode("ascii")).hexdigest()


def validate_splits(tuning, held_out):
    """Reject overlap by stable ID even when payloads/versions/labels differ."""
    if type(tuning) is not Dataset or type(held_out) is not Dataset:
        raise MetricsError("invalid_dataset")
    if tuning.split != "tuning" or held_out.split != "held_out":
        raise MetricsError("invalid_split_pair")
    if {x.event_id for x in tuning.events} & {x.event_id for x in held_out.events}:
        raise MetricsError("dataset_split_overlap")


@dataclass(frozen=True)
class Observation:
    event_id: str
    matched: bool | None
    supported: bool = True
    complete: bool = True

    def __post_init__(self):
        _identifier(self.event_id)
        if self.matched is not None and type(self.matched) is not bool:
            raise MetricsError("invalid_match")
        if type(self.supported) is not bool or type(self.complete) is not bool:
            raise MetricsError("invalid_observation_status")


@dataclass(frozen=True)
class ComparisonIdentity:
    mapping_version: str
    rule_version: str
    dataset_version: str
    dataset_fingerprint: str
    contract_version: str = "detection-metrics-v1"

    def __post_init__(self):
        for value in (self.mapping_version, self.rule_version, self.dataset_version):
            _identifier(value)
        if self.contract_version != "detection-metrics-v1":
            raise MetricsError("unsupported_metrics_contract")
        if type(self.dataset_fingerprint) is not str or len(self.dataset_fingerprint) != 64 or any(c not in "0123456789abcdef" for c in self.dataset_fingerprint):
            raise MetricsError("invalid_dataset_fingerprint")

    @property
    def digest(self):
        return hashlib.sha256(_json([
            self.contract_version, self.mapping_version, self.rule_version,
            self.dataset_version, self.dataset_fingerprint,
        ]).encode("ascii")).hexdigest()


@dataclass(frozen=True)
class Coverage:
    total: int
    known_labels: int
    unknown_labels: int
    unsupported: int
    incomplete: int
    missing_observations: int
    evaluated: int

    @property
    def evaluated_fraction(self):
        return _ratio(self.evaluated, self.total)

    @property
    def known_label_fraction(self):
        return _ratio(self.known_labels, self.total)

    @property
    def evaluated_known_fraction(self):
        return _ratio(self.evaluated, self.known_labels)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


@dataclass(frozen=True)
class Evaluation:
    identity: ComparisonIdentity
    tp: int
    fp: int
    tn: int
    fn: int
    coverage: Coverage

    @property
    def precision(self):
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self):
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def fpr(self):
        return _ratio(self.fp, self.fp + self.tn)


def evaluate(dataset, observations, *, mapping_version, rule_version):
    """Return no partial result on invalid input. Exclusion counts can overlap."""
    if type(dataset) is not Dataset:
        raise MetricsError("invalid_dataset")
    if type(observations) is not tuple or len(observations) > MAX_EVENTS or any(type(x) is not Observation for x in observations):
        raise MetricsError("invalid_observations")
    observed = _unique(observations, "observation")
    if not observed.keys() <= {event.event_id for event in dataset.events}:
        raise MetricsError("observation_event_missing")
    identity = ComparisonIdentity(mapping_version, rule_version, dataset.version, dataset.fingerprint)
    labels = {label.event_id: label.value for label in dataset.labels}
    tp = fp = tn = fn = unknown = unsupported = incomplete = missing = 0
    for event in dataset.events:
        label = labels.get(event.event_id, "unknown")
        unknown += label == "unknown"
        observation = observed.get(event.event_id)
        if observation is None:
            missing += 1
            incomplete += 1
            continue
        unsupported += not observation.supported
        is_incomplete = not observation.complete or observation.matched is None
        incomplete += is_incomplete
        if label == "unknown" or not observation.supported or is_incomplete:
            continue
        if label == "positive":
            tp += observation.matched
            fn += not observation.matched
        else:
            fp += observation.matched
            tn += not observation.matched
    coverage = Coverage(len(dataset.events), len(dataset.events) - unknown, unknown,
                        unsupported, incomplete, missing, tp + fp + tn + fn)
    return Evaluation(identity, tp, fp, tn, fn, coverage)


def require_equivalent(left, right):
    """Only identical evaluation contexts can be treated as equivalent."""
    if type(left) is not Evaluation or type(right) is not Evaluation:
        raise MetricsError("invalid_evaluation")
    if left.identity != right.identity:
        raise MetricsError("incompatible_comparison_identity")
