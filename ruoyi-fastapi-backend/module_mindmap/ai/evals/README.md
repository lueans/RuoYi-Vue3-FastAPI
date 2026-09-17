# AI mind-map quality evaluation

This package implements the reproducible evaluation infrastructure required by
PRD section 22.2. The checked-in `dataset-v1.json` freezes the fixture prompts,
source snapshots, expected concepts, structure bounds, duplicate-content limit,
and per-case tool allowlist.

The built-in command never calls a provider by default. A run without a
deployment-owned executor writes a `blocked` report with
`providerExecution=not_run` and `releaseEligible=false`:

```bash
python -m module_mindmap.ai.evals.cli \
  --agent codex \
  --model gpt-5.6-terra \
  --output reports/codex-quality.json
```

Real execution is supplied through the
`ruoyi.mindmap_ai_eval_executors` Python entry-point group. An executor must
return an `EvalExecution` including the immutable artifact and the ordered tool
names observed by the platform. Only an executor declaring
`evidence_kind=real_provider`, a full dataset run, all hard gates passing, and
all scores meeting the requested threshold can produce
`releaseEligible=true`. Replay and synthetic executors remain non-release
evidence even if their fixtures pass.

`releaseEligible` means only that this immutable report is eligible as the
**quality-dataset input** to a release review. It never means the Adapter or
product has been approved for release. Deterministic conformance, sandbox and
permission tests, security fault injection, lifecycle recovery, and the other
PRD release gates remain separate required evidence. Reports carry
`assessmentScope=agent_quality_dataset` to keep that boundary machine-readable.

Reports intentionally contain no fixture prompt, node text, artifact, provider
response, credential, local path, or hidden reasoning.
