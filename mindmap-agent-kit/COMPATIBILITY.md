# Compatibility contract

| Kit | SMM | Tool contract | Result contract | Minimum runtime | Import trust |
| --- | --- | --- | --- | --- | --- |
| 1.0 | 2 | 1.0 | artifact only | Python 3.10 / ES2022 | `external_unverified` |
| 1.1+ | 2 | 1.0 | artifact + opt-in message | Python 3.10 / ES2022 | `external_unverified` |

Compatibility rules:

1. Readers reject an SMM major version they do not support. Writers emit only SMM v2.
2. Adding an optional manifest or node-data field is backward-compatible. Removing or changing the meaning of a field requires a new schema version.
3. Node UID uniqueness, RFC 8785 SHA-256 binding, the 2,000-node limit, the 32-level limit, and safe hyperlink rules are mandatory.
4. `validation.status=passed` means the standalone contract validator passed. It does not imply a platform job, platform identity, or trusted platform provenance.
5. Agents never provide final persistent UIDs to a platform proposal. The platform tool service owns UID assignment and repeats validation before import or apply.
6. A new Adapter must pass the fixed fixtures, lifecycle checks, cancellation behavior, structured output rules, and platform security policy before rollout.
7. Missing `manifest.resultTypes` always means `artifact` only. This default is permanent for compatibility with pre-1.1 Adapters.
8. An Adapter declaring `discuss` must opt in to the `message` result type. Discussion is routed only as `intent=discuss`, `target=message` and never produces an applicable artifact.
9. The `message_completed` envelope is closed. Its text limits and control-character policy match the platform Adapter base contract; relaxing either side requires coordinated compatibility testing.

Upgrade process:

1. Run the Kit fixtures against the candidate runtime.
2. Run the platform Adapter conformance endpoint.
3. Perform a health check with the configured server-side credential reference.
4. Roll out to a small stable percentage and inspect version-scoped metrics.
5. Increase rollout only after error, latency, cancellation, and artifact-validation results remain within the release threshold.
