# Experiment Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Bab 3 experiment harness (scripts + subjects) and analysis pipeline (stats + mock data) for approach B (S1 primary + S2 replication).

**Architecture:** Two isolated workers on separate worktrees/branches with disjoint file ownership; lead integrates via PR + squash-merge.

**Tech Stack:** bash (harness), Kubernetes kubectl + ArgoCD v2.12 API (read-only verify; writes only with `--live`), Python 3.12 pandas/scipy/matplotlib (analysis).

## Global Constraints

- Kubeconfig: every shell MUST `export KUBECONFIG="$HOME/.kube/config"` first; verify `kubectl config current-context` prints exactly `btd` (never `btd-rke2`).
- Allowed namespaces ONLY: `exp-s1-manual`, `exp-s1-gitops`, `exp-s2-manual`, `exp-s2-gitops`. NEVER touch: `invenio`, `argocd`, `kube-system`, `default`, `database`, `search`, `redis`, `minio`, `monitoring`, `traefik`, `cert-manager`, `velero`, `cattle-*`, `kube-*`, `local`.
- `--dry-run` is the default; `--live` requires explicit flag + allowed namespace + baseline gate pass.
- Workers operate ONLY in their assigned worktree/branch; never reset/clean another worktree.
- Each worker writes `WORKER-REPORT.md` at its worktree root: what changed, what was verified (commands + output), what remains.
- If a decision is ambiguous or blocked: stop, record the question in `WORKER-REPORT.md`, do NOT guess.
- Conventional Commits for all commits (`feat(experiments): ...`, `feat(analysis): ...`).

---

### Task 1: exp-harness — subjects S1/S2 manifests (Worker: exp-harness)

**Files:**
- Create: `experiments/subjects/s1/manifests.yaml`
- Create: `experiments/subjects/s2/manifests.yaml`
- Create: `experiments/subjects/README.md`

**Interfaces:**
- Consumes: design doc (S1 = deploy 3 replika + svc + cm + secret + cronjob; S2 = S1 + statefulset + pvc)
- Produces: manifest paths + resource inventory consumed by Task 2 scripts and ArgoCD Applications

- [ ] **Step 1: Write S1 manifests (5 resources, namespace-agnostic via kustomize-less placeholder `EXP_NS`)**

```yaml
# experiments/subjects/s1/manifests.yaml (sketch — worker writes full file)
apiVersion: apps/v1
kind: Deployment
metadata: {name: exp-web, namespace: EXP_NS}
spec: {replicas: 3, ...}
---
apiVersion: v1
kind: Service
metadata: {name: exp-web, namespace: EXP_NS}
...
```

- [ ] **Step 2: Dry-run validate S1/S2 client-side**

Run: `env -u KUBECONFIG kubectl apply --dry-run=client -f experiments/subjects/s1/manifests.yaml --namespace=exp-s1-manual` (repeat S2)
Expected: `deployment.apps/exp-web created (dry run)` etc., exit 0, no cluster mutation

- [ ] **Step 3: Write S2 manifests (S1 + StatefulSet + PVC) + README with resource inventory table**
- [ ] **Step 4: Commit**

```bash
git add experiments/subjects
git commit -m "feat(experiments): add S1/S2 surrogate subjects for drift scenarios"
```

### Task 2: exp-harness — 4 automation scripts (Worker: exp-harness)

**Files:**
- Create: `experiments/scripts/baseline-check.sh`
- Create: `experiments/scripts/drift-inject.sh`
- Create: `experiments/scripts/metrics-collect.sh`
- Create: `experiments/scripts/recovery-runbook.sh`

**Interfaces:**
- Consumes: subject manifests (Task 1), data schema from design doc
- Produces: `experiments/runs/sample-dryrun.csv` (schema-conformant sample)

- [ ] **Step 1: Write `baseline-check.sh`** (gates: all pods Running in target ns, node CPU <70%, ArgoCD app Synced/Healthy for gitops ns; exit non-zero + log line on violation; `--live` required for real checks, else simulated pass with notice)
- [ ] **Step 2: Write `drift-inject.sh`** (scenarios A–G per Bab 3 §Skenario; random order via `shuf`; records `t0`; default prints planned kubectl commands WITHOUT executing; executes only with `--live`)
- [ ] **Step 3: Write `metrics-collect.sh`** (poll ArgoCD `argocd app get` every 5s for gitops ns / kubectl polling for manual ns; records `td,trci,t2`; computes R1 at t0/t1/t2; writes schema CSV)
- [ ] **Step 4: Write `recovery-runbook.sh`** (deterministic per-scenario kubectl recovery steps for Lingkungan A; timestamps each step; counts commands)
- [ ] **Step 5: Syntax-check all scripts**

Run: `bash -n experiments/scripts/*.sh && shellcheck experiments/scripts/*.sh 2>/dev/null || echo "shellcheck absent, bash -n passed"`
Expected: no syntax errors

- [ ] **Step 6: Produce schema-conformant dry-run sample + verify ArgoCD sync interval read-only**

Run: `kubectl -n argocd get cm argocd-cm -o jsonpath='{.data.timeout\.reconciliation}'` (record actual value vs Bab 3's 60s in WORKER-REPORT.md)
Expected: value documented; sample CSV has header `subject,env,skenario,rep,t0,td,trci,t2,r1_t0,r1_t1,r1_t2,kubectl_cmds,notes`

- [ ] **Step 7: Commit**

```bash
git add experiments/scripts experiments/runs
git commit -m "feat(experiments): add 4 Bab-3 automation scripts with dry-run default"
```

### Task 3: exp-analysis — analyzer + mock generator (Worker: exp-analysis)

**Files:**
- Create: `experiments/analysis/requirements.txt`
- Create: `experiments/analysis/analyze.py`
- Create: `experiments/analysis/mockgen.py`
- Create: `experiments/analysis/README.md`

**Interfaces:**
- Consumes: CSV schema from design doc (independent of Task 1/2 outputs — use `mockgen.py` output for dev)
- Produces: `experiments/analysis/outputs/` (descriptives.tex, mannwhitney.tex, effects.tex, boxplot PNGs)

- [ ] **Step 1: Write `requirements.txt`** (pandas, scipy, matplotlib — pinned minimums)
- [ ] **Step 2: Write `mockgen.py`** (realistic synthetic distributions: gitops detection/recovery faster with lower variance; 7 scenarios × 2 envs × S1/S2 × n=10 R2 + n=5 R1; seeded RNG `--seed` for reproducibility)

Run: `python3 experiments/analysis/mockgen.py --seed 42 --out experiments/analysis/outputs/mock_runs.csv`
Expected: CSV with schema header, row count = (7*10 + 7*5)*2*2 = 420 rows

- [ ] **Step 3: Write `analyze.py`** (reads runs CSV → descriptives mean/median/range/std per metric/env/scenario → Mann-Whitney U two-sided α=0.05 per metric/scenario → Cohen's d + Cliff's δ with Cohen interpretation → writes `descriptives.tex`, `mannwhitney.tex`, `effects.tex` + `boxplot_<metric>.png` per scenario)

Run: `pip install -r experiments/analysis/requirements.txt && python3 experiments/analysis/analyze.py --in experiments/analysis/outputs/mock_runs.csv --out experiments/analysis/outputs/`
Expected: 3 .tex files + PNGs exist; exit 0

- [ ] **Step 4: Commit**

```bash
git add experiments/analysis
git commit -m "feat(analysis): add analyzer and mock generator for R1/R2 statistics"
```

### Task 4: Lead integration (Lead — NOT a worker)

- [ ] Collect `WORKER-REPORT.md` from both worktrees via blocking wait
- [ ] Diff branches against each other for file overlap; resolve deliberately
- [ ] Build clean feature branch from `origin/main`, Conventional Commits
- [ ] Verify: `bash -n` scripts, rerun analyzer on mock data, `kubectl --dry-run=client` manifests
- [ ] Push, open PR (Summary/Why/Implementation/Testing/Risks/Rollback), `gh pr checks --watch`, squash-merge on green

## Self-Review

- Spec coverage: E1/R1 ✅ (Tasks 1–3), E2/R2 ✅, E3/R3 deskriptif (trace/ dir schema ✅ Task 2), 4 scripts ✅ Task 2, stats ✅ Task 3, safety ✅ Global Constraints.
- No placeholders: all steps carry concrete commands and expected outputs.
- Type consistency: CSV schema identical in design doc, Task 2 Step 6, Task 3 Steps 2–3.
