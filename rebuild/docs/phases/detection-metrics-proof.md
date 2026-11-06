# Offline detection metrics contract — OF-P08-METRICS-A

6 November 2026. Implemented with focused synthetic verification; independent
review and Main delivery remain pending. Phase 8 is incomplete. This slice is a
pure standard-library contract over supplied events, labels and observations.

`Event.from_features(id, fields)` takes a JSON-compatible object and freezes a
canonical snapshot. `Dataset(version, split, events, labels)` holds immutable
tuples; labels (`positive`, `negative`, `unknown`) and split (`tuning`, `held_out`)
are separate from event features. An absent label means unknown. `Observation`
requires a strict boolean prediction or None and strict supported/complete flags.
No rule semantics are executed or approximated here. Unsupported evaluation is an
explicit input from the eventual evaluator.

`evaluate(dataset, observations, mapping_version=..., rule_version=...)` calculates
TP/FP/TN/FN only for known labels with a supported, complete, non-None prediction.
Precision is TP/(TP+FP), recall TP/(TP+FN), FPR FP/(FP+TN). A zero denominator gives
Python None (JSON null), including an empty dataset. A missing observation counts
as incomplete; a None prediction is incomplete even if complete=True was supplied.
Unknown labels, unsupported observations and incomplete observations are counted
independently, so their counts can overlap. They are never synthesized as TN/FN.
Missing observations have a separate subset count and are not inferred unsupported.

Coverage includes total, known/unknown labels, unsupported, incomplete, missing
observations and evaluated counts. evaluated_fraction uses the entire dataset;
evaluated_known_fraction uses known labels; known_label_fraction uses the entire
dataset. Empty denominators remain None. Thus a perfect score on one evaluable
item cannot conceal seven excluded observations. For example, the synthetic
eight-event exclusion fixture yields TP1/FP0/TN0/FN0, unknown3, unsupported2,
incomplete4 (including one missing), evaluated coverage1/8 and known coverage1/5.

`validate_splits(tuning, held_out)` rejects overlapping stable event IDs regardless
of changed content, labels or dataset version. The caller must invoke this pair
gate before using the two sets together; evaluating a supplied set alone cannot
infer another split. Duplicate event, label and observation IDs reject. Labels or
observations for absent events reject, and invalid inputs return no partial result.
IDs are caller-supplied stable identities, not generated hashes; aliases for the
same real event cannot be detected without an upstream identity policy.

ComparisonIdentity binds the metrics contract, mapping, rule and dataset versions
plus a SHA256 dataset fingerprint. The fingerprint includes sorted event IDs,
canonical features, effective labels and split. Missing and explicit unknown labels
have equivalent effective semantics. Reordering events, labels or observations
does not change the result/context. Reusing a version string with changed content
still changes identity. `require_equivalent(left, right)` rejects differing contexts.
Identical contexts may have different observations/scores; passing this gate means
the evaluation contexts match, not that outcomes or executions are identical. This
slice provides no cross-version score-migration or causal comparison policy.

`model_projection()` emits only sorted event IDs and fresh copies of event fields;
changing labels/split/version cannot expose them in that projection. Common label
and split metadata keys are rejected recursively, case-insensitively. This blocks
structural label inclusion, not semantic encoding in arbitrary messages/IDs or
unrecognized field names. Upstream feature curation remains responsible for those
cases. The evaluator Dataset/identity/result objects are private evaluation inputs,
not model-visible projections, and should not be supplied to a model as a shortcut.

Dataset size is limited to1000 events and2MiB combined canonical feature bytes;
feature nesting is limited to16. Inputs use exact JSON-compatible types and finite
numbers. Snapshots and returned projection copies prevent mutation through retained
input dictionaries. Canonical JSON spelling is required for direct Event construction.
Errors use fixed contract strings rather than copying feature or label values.
These are already materialized in-memory inputs, not a streaming parser or a limit
on allocations that occurred before calling the contract.

## Actual verification

The existing pinned CPython environment ran only the new detection module:

```text
python -B -X faulthandler -m unittest discover -s tests/contracts/detection -p test_metrics.py -v
```

From the rebuild root, the command above is equivalent to the actual workspace
invocation using its detection directory. **11 tests passed in0.047s**, exit0,
no skips or failures. No failed/retried test invocation or existing suite rerun.
Tests load metrics.py by exact file path; no package markers or dependencies added.

The hand-counted ten-event fixture produces TP3/FP2/TN4/FN1, precision0.6,
recall0.75, FPR1/3. Other fixtures exercise empty/one-class denominators, overlapping
unknown/unsupported/incomplete categories, missing labels/observations, overlap
despite changed payload/version, duplicate/foreign identities, strict prediction
types, changed mapping/rule/dataset/content/split identity, deterministic ordering,
projection separation and mutation resistance, malformed/oversized features and
event-count rejection. All fixtures are synthetic and in memory.

No DuckDB, native rule/executor, database, live source, model/provider or network
operation occurred. Persistence, APIs/UI, rule execution, temporal/late-event
normalization, integrated dataset provenance and held-out workflow enforcement
remain later gates. Independent review and intended-head CI are still required.
