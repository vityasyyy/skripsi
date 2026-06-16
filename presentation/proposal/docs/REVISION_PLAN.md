
# REVISION_PLAN.md

# Presentation Revision Plan

## Goal

Strengthen methodological rigor while reducing unnecessary attack surfaces during proposal defense.

Main principle:

> Focus on measuring operational differences between deployment paradigms under controlled drift scenarios.

Not:

> Proving GitOps is better.
>
> Establishing causal inference.
>
> Evaluating every possible operational characteristic.

---

# Priority 1 (Must Fix Before Defense)

## Remove Causal Language

Current wording:

* causal impact
* causal effect
* establish causality

Problem:

These terms invite questions about:

* random assignment
* counterfactuals
* causal inference
* experimental treatment assignment

which are outside the scope of the research.

### Replace With

* controlled systems experiment
* controlled empirical evaluation
* isolate the effect of deployment paradigm
* comparative experimental evaluation
* controlled comparison

### Example

Current:

"Dampak kausal paradigma deployment belum jelas."

Replace:

"Dampak operasional paradigma deployment dalam kondisi drift terkontrol belum terukur secara empiris."

---

## Reposition Research Gap

Current gap:

"GitOps is believed to be beneficial but controlled evidence is weak."

Stronger gap:

"Existing studies discuss GitOps benefits but rarely quantify the magnitude of operational differences under controlled drift scenarios."

Emphasize:

* effect magnitude
* operational characteristics
* controlled comparison

Not:

* proving GitOps works

---

# Priority 2 (Metric Revision)

## Remove R3 (Manual Intervention Count)

Current metric:

* Number of corrective kubectl commands

Problem:

Result is largely predetermined.

Manual:

* > 0 interventions

GitOps:

* ~0 interventions

Metric provides little new information.

### Recommendation

Remove R3 entirely.

Research becomes cleaner.

---

## Replace R4 Traceability Rubric

Current:

* Rubric 1–5
* Cohen's Kappa
* Auditability score

Problem:

Rubric appears subjective.

Potential attacks:

* Why 1–5?
* Why not another scale?
* Does the rubric actually measure traceability?

### New R4

Mean Time To Identify (MTTI)

Definition:

Time required to correctly identify:

* what changed
* where it changed
* root cause category

Formula:

MTTI = t_identification − t_detection

### Why Stronger

Measures operational diagnostic effort.

Produces objective timestamps.

Directly relates to incident response.

Easier to explain.

Easier to defend.

---

# Priority 3 (Research Questions)

## Revised Research Questions

R1:
Can the system return to desired state after drift?

R2:
How quickly can drift be detected and recovered?

R3:
How quickly can the source of drift be identified?

(Former R4 becomes R3.)

Result:

Only three metrics:

* Consistency
* Detection / Recovery Time
* Identification Time

Much cleaner.

---

# Priority 4 (Scenario Revision)

## Revisit Scenario F

Current issue:

Scenario F may not actually represent configuration drift.

Potential examiner attack:

"If ArgoCD does not manage the resource, is this drift?"

### Options

Option A (Preferred)

Rename:

"GitOps Visibility Boundary Scenario"

Purpose:

Evaluate observability limits of GitOps.

Not recovery.

Not reconciliation.

---

Option B

Remove Scenario F entirely.

Only keep scenarios representing genuine desired-state deviations.

---

# Priority 5 (Learning Effect Clarification)

Add explicit explanation.

Current wording:

"Scenario order randomized."

Insufficient.

### Clarify

Randomization applies to:

* scenario execution order

Not:

* drift type
* recovery procedure
* deployment paradigm

Example:

Instead of

A A A A A
B B B B B

Use

A F C B G A D ...

Purpose:

Distribute operator learning effects across scenarios.

---

# Priority 6 (Operator Skill Criticism)

Add backup explanation.

Expected question:

"Aren't you measuring operator skill?"

Response:

* Same operator across both environments
* Same runbook
* Same recovery procedures
* Same cluster
* Same scenarios

Operator skill remains a limitation but affects both paradigms equally.

Therefore comparison remains meaningful.

---

# Priority 7 (Statistics Simplification)

Keep:

* descriptive statistics
* confidence intervals
* effect size

Keep normality testing:

* Shapiro-Wilk

Keep:

* t-test (if normal)
* Mann-Whitney U (if non-normal)

BUT

De-emphasize hypothesis testing.

Emphasize:

* effect magnitude
* operational significance

Current message:

"Did we find statistical significance?"

New message:

"How large is the operational difference?"

---

## Statistical Interpretation Hierarchy

Primary:

1. Effect size
2. Confidence intervals

Secondary:

3. p-values

Reason:

Deployment decisions depend on practical impact, not merely statistical significance.

---

# Priority 8 (Novelty Clarification)

Current risk:

Examiner asks:

"What do we learn if GitOps wins?"

Recommended answer:

The contribution is not determining direction.

The contribution is quantifying magnitude.

Research output:

* how much faster
* how much more consistent
* how much easier to diagnose

under controlled drift conditions.

Not:

"GitOps good."

---

# Expected Final Structure

Metrics:

R1 Consistency

R2 Detection Time
R2 Recovery Time

R3 Mean Time To Identify (MTTI)

Analysis:

* Descriptive statistics
* Confidence intervals
* Effect size
* t-test / Mann-Whitney (supporting analysis)

Study Type:

Controlled systems experiment

Primary Contribution:

Quantification of operational differences under controlled drift scenarios.
