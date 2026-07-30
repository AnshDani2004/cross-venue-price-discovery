# Experiment Log

No experiments have been run. Phases 00 and 01 intentionally produce no statistical or
trading conclusions.

This log is append-only. Failed, null, and inconclusive experiments must remain in the
record because they constrain future interpretation and reduce hindsight bias.

## Rules

- Do not overwrite historical experiment records.
- Every experiment must reference the Git commit used to generate it.
- Every experiment must reference a data manifest, not an informal file path.
- Final test-period results must not be repeatedly rerun for tuning.
- Negative and null results must be interpreted as carefully as positive results.
- Trading relevance must distinguish statistical significance from economic significance.

## Experiment Record Template

```markdown
## EXP-YYYYMMDD-NNN

- experiment_id:
- date:
- git_commit:
- research_question:
- hypothesis:
- data_manifest:
- data_period:
- training_period:
- validation_period:
- test_period:
- features:
- target:
- baseline:
- model:
- parameters:
- random_seed:
- metrics:
- results:
- confidence_intervals:
- interpretation:
- limitations:
- decision:
```

## Field Definitions

| Field | Required | Description |
| --- | --- | --- |
| `experiment_id` | Yes | Stable identifier such as `EXP-20260730-001`. |
| `date` | Yes | Date the experiment was run. |
| `git_commit` | Yes | Exact code commit used for the run. |
| `research_question` | Yes | Research question ID from the protocol. |
| `hypothesis` | Yes | Hypothesis ID and exact statement tested. |
| `data_manifest` | Yes | Manifest identifying raw and normalized inputs. |
| `data_period` | Yes | Full data interval considered. |
| `training_period` | Conditional | Training window, if a model is trained. |
| `validation_period` | Conditional | Validation window, if model choices are tuned. |
| `test_period` | Conditional | Final untouched evaluation period. |
| `features` | Yes | Point-in-time inputs used. |
| `target` | Yes | Label or response definition. |
| `baseline` | Yes | Predefined comparison baseline. |
| `model` | Yes | Statistic or model family. Use `descriptive` when no model exists. |
| `parameters` | Yes | Horizon, thresholds, costs, filters, and model parameters. |
| `random_seed` | Conditional | Seed when randomness is used. |
| `metrics` | Yes | Predefined statistical and economic metrics. |
| `results` | Yes | Actual outputs, with no fabricated values. |
| `confidence_intervals` | Conditional | Uncertainty estimates where applicable. |
| `interpretation` | Yes | Plain-English conclusion supported by the result. |
| `limitations` | Yes | Data, model, and execution caveats. |
| `decision` | Yes | Keep, reject, revise, or defer the hypothesis/model. |
