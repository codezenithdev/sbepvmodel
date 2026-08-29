# Decision Agent local evals

This harness exercises the same `run_decision_agent_turn` path used by Autonomy. It
grades the structured schema, trace/audit envelope, tool-call boundary, typed
unavailable/timeout errors, and non-execution contract. It deliberately does not
grade exact prose.

Validate the dataset and local contracts without an API call:

```bash
python evals/decision_agent/run_local.py
```

Run the complete matrix against an existing durable case:

```bash
python evals/decision_agent/run_local.py --real --case-id <case-id>
```

Run the one-case opt-in smoke path:

```bash
python evals/decision_agent/run_local.py --smoke --case-id <case-id>
```

`--real` and `--smoke` require a usable `OPENAI_API_KEY` in the process or the
repository's existing local environment file. The harness checks only whether the
variable exists; it never prints, copies, writes, or records the value. A case ID may
instead be supplied through `DECISION_AGENT_EVAL_CASE_ID`.

The timeout and unavailable-model cases deliberately exercise the sanitized
`DecisionAgentError` boundary. All runs are read-only: the harness cannot create
prerequisites, accept evidence, draft or execute scenarios, queue TEA work, sign a
decision, or generate a report. Results are written to
`evals/decision_agent/results/latest.json`; generated results are ignored by Git.

State-sensitive cases use the supplied durable case as it exists. Their graders
accept the contractually valid answer categories and statuses rather than assuming a
particular fixture state.
