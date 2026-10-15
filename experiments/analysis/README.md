# Experiment Analysis

The analyzer has two isolated input modes. Schema-v2 JSON is the only path for
structured run records. The legacy CSV path is explicitly synthetic and must
not be used to analyze empirical runs.

## Schema-v2 JSON

Use one run-summary JSON file or a directory containing direct `.json` run
summaries. Directory input is not recursive. Every selected file must match the
schema in `experiments/schema-v2.md`; validation completes before any report is
written.

```bash
python3 experiments/analysis/analyze.py \
  --schema-version 2 --phase fixture \
  --in /path/to/run.json --out /tmp/analysis-fixture
```

The required `--phase` is `fixture`, `pilot`, or `formal`, and must match every
record. Fixture reports are labeled **SYNTHETIC FIXTURE — NOT EMPIRICAL**;
pilot reports are pilot-only. The known surrogate subjects `s1` and `s2` are
rejected in formal mode. Other nonempty formal subject labels are accepted as
future input capability only: the analyzer does not establish that collection
was authorized.

The report `analysis-v2.json` contains separate subject/scenario/environment
groups, run-status counts, event observation/censoring counts, and observed-only
duration summaries. Detection, evidence, and recovery durations are respectively
`td_mono_s - t0_mono_s`, `te_mono_s - t0_mono_s`, and
`tr_mono_s - t0_mono_s`. UTC audit timestamps and API acknowledgement (`ta`)
are not durations; a detection may precede acknowledgement. Missing events are
never zero. Failures remain in counts, and censored/not-evaluable runs are not
silently dropped from the report. R1 percentages use the expected inventory
only and stay on the schema's `[0, 100]` scale; health is a separate measure.
Scenario F is reported in a separate
visibility-boundary section, not as managed-drift recovery.

Detection, evidence, and restoration are independently observed events: the
analyzer imposes no order among `td`, `te`, and `tr`. Each observed `td`, `te`,
or `tr` must still be at/after dispatch and within the observation cutoff.
Observed evidence must link to a stored evidence item at `te`; observed
restoration requires `r1_recovered_pct` to equal 100. A run may therefore
retain observed restoration while detection or evidence is right-censored.

Validation follows the schema's failure precedence (`baseline_failed`,
`injection_failed`, `instrumentation_failed`, `correction_failed`, then
`timeout`). A timeout must contain at least one right-censored event;
instrumentation failures are not censored misses; and a failed correction
cannot claim observed recovery. Complete managed scenarios require observed
detection, evidence, and recovery. Scenario F requires recovery to remain
not-evaluable.

Reports are descriptive by default and contain no figures. Output refuses to
overwrite an existing `analysis-v2.json`. Use a temporary output directory for
fixture checks; never treat fixture or pilot output as thesis results.

### Optional exploratory comparisons

Comparisons require formal phase, explicit opt-in, and an approved policy:

```bash
python3 experiments/analysis/analyze.py \
  --schema-version 2 --phase formal --exploratory-comparisons \
  --policy approved-policy.json --in /path/to/formal-runs \
  --out /path/to/analysis
```

The policy must contain exactly these fields: `policy_id`, `approved: true`,
`approval_reference`, `prespecified: true`, `independence_confirmed: true`,
`independence_basis`, `collection_run_ids`, and a nonempty `holm_family` array.
Each family entry names one `subject`, non-F `scenario`, and R2 `metric`
(`detection`, `evidence`, or `recovery`). The listed run IDs must exactly match
the input collection. Both arms must have only complete, observed runs for each
listed comparison. The output reports two-sided Mann–Whitney p-values, Holm
adjustments for that prespecified family, and Cliff's delta in the direction
manual minus GitOps. It does not emit a significance decision. No R1, health,
R3, censored, invalid, or F comparison is supported. An approval reference is
an input gate, not verification of thesis or supervisor authorization.

## Legacy synthetic CSV

The old analyzer remains available only with an explicit synthetic opt-in:

```bash
python3 experiments/analysis/analyze.py \
  --legacy-synthetic-csv \
  --in experiments/analysis/outputs/mock_runs.csv \
  --out /tmp/analysis-legacy-mock
```

All generated tables, plots, and console output are marked **SYNTHETIC — NOT
EMPIRICAL**. This mode retains the old `rep <= 10` / `rep >= 11` family
heuristics and pooled legacy statistics only to reproduce mock examples. It
does not accept schema-v2 records and must not be used for empirical CSV data.
Existing mock generator files and outputs are preserved.

## Offline tests

Run the stdlib suite without cluster access or generated files in the
repository:

```bash
python3 -m unittest discover -s experiments/analysis/tests -v
```

Tests use temporary directories and fixture-labeled schema-v2 records. No
dependencies were added.
