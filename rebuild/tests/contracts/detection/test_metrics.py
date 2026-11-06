"""Synthetic offline metrics cases, loaded by exact path without package edits."""
from dataclasses import FrozenInstanceError, asdict
import importlib.util
import json
from pathlib import Path
import sys
import unittest


SOURCE = Path(__file__).resolve().parents[3] / 'packages/contracts/detection/metrics.py'
SPEC = importlib.util.spec_from_file_location('offline_detection_metrics_contract', SOURCE)
metrics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = metrics
SPEC.loader.exec_module(metrics)


def dataset(labels, *, version='dataset-1', split='held_out'):
    return metrics.Dataset(version, split,
        tuple(metrics.Event.from_features(key, {'message': 'synthetic ' + key}) for key in labels),
        tuple(metrics.Label(key, label) for key, label in labels.items() if label is not None))


def evaluate(data, observations, **versions):
    return metrics.evaluate(data, tuple(observations), mapping_version=versions.get('mapping', 'mapping-1'),
                            rule_version=versions.get('rule', 'rule-1'))


class MetricsProof(unittest.TestCase):
    def test_known_fixture_counts_and_real_denominators(self):
        # Three detected positives, one missed positive, two false alarms, four
        # quiet negatives: precision3/5, recall3/4, FPR2/6.
        labels = {str(i): 'positive' if i < 4 else 'negative' for i in range(10)}
        data = dataset(labels)
        result = evaluate(data, [metrics.Observation(str(i), i in (0, 1, 2, 4, 5)) for i in range(10)])
        self.assertEqual((result.tp, result.fp, result.tn, result.fn), (3, 2, 4, 1))
        self.assertEqual(result.precision, .6)
        self.assertEqual(result.recall, .75)
        self.assertAlmostEqual(result.fpr, 1 / 3)
        self.assertEqual(result.coverage.evaluated_fraction, 1)
        self.assertEqual(result.coverage.evaluated_known_fraction, 1)

    def test_zero_denominators_are_none_not_perfect_or_zero(self):
        empty = evaluate(dataset({}), [])
        self.assertEqual((empty.precision, empty.recall, empty.fpr), (None, None, None))
        self.assertIsNone(empty.coverage.evaluated_fraction)
        self.assertIsNone(empty.coverage.evaluated_known_fraction)
        self.assertIsNone(empty.coverage.known_label_fraction)
        quiet = evaluate(dataset({'a': 'negative'}), [metrics.Observation('a', False)])
        self.assertEqual((quiet.precision, quiet.recall, quiet.fpr), (None, None, 0))
        missed = evaluate(dataset({'a': 'positive'}), [metrics.Observation('a', False)])
        self.assertEqual((missed.precision, missed.recall, missed.fpr), (None, 0, None))
        self.assertIn('null', json.dumps({'precision': empty.precision}))

    def test_unknown_unsupported_and_incomplete_never_become_negatives(self):
        data = dataset({'ok': 'positive', 'u': 'unknown', 'absent-label': None,
                        'unsupported': 'negative', 'partial': 'positive', 'missing': 'negative',
                        'overlapping': 'unknown', 'no-match': 'negative'})
        result = evaluate(data, [metrics.Observation('ok', True), metrics.Observation('u', False),
            metrics.Observation('absent-label', False), metrics.Observation('unsupported', False, supported=False),
            metrics.Observation('partial', False, complete=False),
            metrics.Observation('overlapping', None, supported=False, complete=False),
            metrics.Observation('no-match', None)])
        self.assertEqual((result.tp, result.fp, result.tn, result.fn), (1, 0, 0, 0))
        self.assertEqual(asdict(result.coverage), {'total': 8, 'known_labels': 5, 'unknown_labels': 3,
            'unsupported': 2, 'incomplete': 4, 'missing_observations': 1, 'evaluated': 1})
        self.assertEqual(result.coverage.evaluated_fraction, 1 / 8)
        self.assertEqual(result.coverage.evaluated_known_fraction, 1 / 5)
        self.assertEqual(result.coverage.known_label_fraction, 5 / 8)
        self.assertIsNone(result.fpr)

    def test_unknown_coverage_uses_entire_dataset(self):
        result = evaluate(dataset({'a': 'unknown', 'b': None}), [metrics.Observation('a', True)])
        self.assertEqual(result.coverage.evaluated_fraction, 0)
        self.assertIsNone(result.coverage.evaluated_known_fraction)
        self.assertEqual(result.coverage.missing_observations, 1)
        self.assertEqual((result.tp, result.fp, result.tn, result.fn), (0, 0, 0, 0))

    def test_overlap_uses_id_even_if_payload_label_and_version_change(self):
        tuning = dataset({'same': 'positive'}, split='tuning', version='v1')
        held = metrics.Dataset('v2', 'held_out',
            (metrics.Event.from_features('same', {'entirely': 'different'}),), (metrics.Label('same', 'negative'),))
        with self.assertRaisesRegex(metrics.MetricsError, '^dataset_split_overlap$'):
            metrics.validate_splits(tuning, held)
        metrics.validate_splits(tuning, dataset({'different': 'positive'}))
        with self.assertRaisesRegex(metrics.MetricsError, '^invalid_split_pair$'):
            metrics.validate_splits(held, tuning)

    def test_duplicate_ids_fail_without_partial_result(self):
        event = metrics.Event.from_features('a', {})
        with self.assertRaisesRegex(metrics.MetricsError, '^duplicate_event_identity$'):
            metrics.Dataset('d', 'held_out', (event, event))
        with self.assertRaisesRegex(metrics.MetricsError, '^duplicate_label_identity$'):
            metrics.Dataset('d', 'held_out', (event,), (metrics.Label('a', 'positive'), metrics.Label('a', 'negative')))
        data = dataset({'a': 'positive', 'b': 'negative'})
        with self.assertRaisesRegex(metrics.MetricsError, '^duplicate_observation_identity$'):
            evaluate(data, [metrics.Observation('a', True), metrics.Observation('b', False), metrics.Observation('a', False)])
        with self.assertRaisesRegex(metrics.MetricsError, '^observation_event_missing$'):
            evaluate(data, [metrics.Observation('a', True), metrics.Observation('foreign', False)])
        with self.assertRaisesRegex(metrics.MetricsError, '^label_event_missing$'):
            metrics.Dataset('d', 'held_out', (event,), (metrics.Label('foreign', 'positive'),))

    def test_changed_versions_and_content_are_incompatible(self):
        data = dataset({'a': 'positive'})
        observation = [metrics.Observation('a', True)]
        baseline = evaluate(data, observation)
        metrics.require_equivalent(baseline, evaluate(data, [metrics.Observation('a', False)]))
        alternatives = [evaluate(data, observation, mapping='mapping-2'), evaluate(data, observation, rule='rule-2'),
            evaluate(dataset({'a': 'positive'}, version='dataset-2'), observation),
            evaluate(dataset({'a': 'negative'}), observation),
            evaluate(metrics.Dataset('dataset-1', 'held_out', (metrics.Event.from_features('a', {'message': 'changed'}),),
                (metrics.Label('a', 'positive'),)), observation),
            evaluate(dataset({'a': 'positive'}, split='tuning'), observation)]
        for other in alternatives:
            with self.subTest(identity=other.identity):
                self.assertNotEqual(other.identity.digest, baseline.identity.digest)
                with self.assertRaisesRegex(metrics.MetricsError, '^incompatible_comparison_identity$'):
                    metrics.require_equivalent(baseline, other)

    def test_order_does_not_change_identity_results_or_projection(self):
        left = dataset({'c': 'positive', 'a': 'negative', 'b': None})
        right = metrics.Dataset(left.version, left.split, tuple(reversed(left.events)), tuple(reversed(left.labels)))
        observed = [metrics.Observation('c', True), metrics.Observation('a', False)]
        self.assertEqual(evaluate(left, observed), evaluate(right, reversed(observed)))
        self.assertEqual(left.fingerprint, right.fingerprint)
        self.assertEqual(left.model_projection(), right.model_projection())
        self.assertEqual([x['event_id'] for x in left.model_projection()], ['a', 'b', 'c'])

    def test_projection_excludes_labels_and_split_and_cannot_mutate_input(self):
        features = {'nested': {'message': ['synthetic']}}
        event = metrics.Event.from_features('a', features)
        features['nested']['message'].append('later')
        positive = metrics.Dataset('v1', 'held_out', (event,), (metrics.Label('a', 'positive'),))
        negative = metrics.Dataset('v2', 'tuning', (event,), (metrics.Label('a', 'negative'),))
        projected = positive.model_projection()
        self.assertEqual(projected, negative.model_projection())
        self.assertEqual(projected, ({'event_id': 'a', 'fields': {'nested': {'message': ['synthetic']}}},))
        projected[0]['fields']['nested']['message'].clear()
        self.assertEqual(positive.model_projection()[0]['fields']['nested']['message'], ['synthetic'])
        with self.assertRaises(FrozenInstanceError): event.event_id = 'changed'
        for key in ('label', 'LABELS', 'ground_truth', 'held_out', 'split_membership'):
            with self.subTest(key=key):
                with self.assertRaises(metrics.MetricsError):
                    metrics.Event.from_features('a', {'nested': [{key: 'secret'}]})

    def test_strict_input_rejects_truthiness_and_invalid_labels(self):
        for value in (0, 1, 'false', [], {}):
            with self.subTest(value=value):
                with self.assertRaises(metrics.MetricsError): metrics.Observation('a', value)
        for kwargs in ({'supported': 0}, {'complete': 'false'}):
            with self.assertRaises(metrics.MetricsError): metrics.Observation('a', False, **kwargs)
        for label in (True, 'benign', '', None):
            with self.assertRaises(metrics.MetricsError): metrics.Label('a', label)
        for identity in ('', ' a', 'a\n', 1):
            with self.assertRaises(metrics.MetricsError): metrics.Event.from_features(identity, {})
        with self.assertRaises(metrics.MetricsError): evaluate(dataset({}), [], mapping='')

    def test_feature_and_count_limits_reject_explicitly(self):
        for value in (float('nan'), float('inf'), object(), (1, 2)):
            with self.assertRaises(metrics.MetricsError): metrics.Event.from_features('a', {'x': value})
        with self.assertRaises(metrics.MetricsError): metrics.Event('a', '{"x":1, "x":2}')
        with self.assertRaises(metrics.MetricsError): metrics.Event('a', '[]')
        with self.assertRaises(metrics.MetricsError): metrics.Event.from_features('a', {'x': 'z' * metrics.MAX_FEATURE_BYTES})
        with self.assertRaises(metrics.MetricsError):
            metrics.Dataset('d', 'held_out', tuple(metrics.Event.from_features(str(i), {}) for i in range(metrics.MAX_EVENTS + 1)))


if __name__ == '__main__':
    unittest.main()
