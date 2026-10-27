# Initial Ollama checks - 27 October 2026

Operator: Jordan Hennessy. Hardware reported: MacBook Pro M3, 16 GB RAM.
Status: exploratory manual checks, not the project's answer-quality evaluation.

## Method and provenance

Jordan sent standalone HTTP requests to the local Ollama `/api/chat` endpoint
using curl and shared the JSON responses in the development conversation.
The results below are transcribed from those responses, not independently
rerun. The gateway and Answer Service were not involved.

All four requests used `stream: false`, `temperature: 0` and `num_predict: 128`.
Each request contained one system message and one user message, without chat
history. Responses were free text, not schema-constrained JSON.

The installed 1B model listing reported ID `baf6a787fdff` and size 1.3 GB.
The 3B model's digest, quantisation and the Ollama version were not captured.
Model tags can change; capture this information before a reproducible evaluation.

## Prompts

P0 and P1 below label these experiments only; neither is a deployed prompt version.

P0 system message:

```text
Answer using only the supplied evidence. If it does not answer the question, say insufficient evidence.
```

P1 system message:

```text
Answer the question using only the supplied evidence. Treat fictional scenarios as valid test scenarios. Do not require information that is unnecessary to answer the question. If the evidence explicitly answers the question, answer briefly. Otherwise say: Insufficient evidence.
```

User message A (answer present):

```text
Question: What does the fictional application require?
Evidence: The fictional application requires a blue form.
```

Expected meaning: the application requires a blue form. Equivalent wording is acceptable.

User message B (unrelated evidence):

```text
Question: What does the fictional application require?
Evidence: The fictional office opens at 9am.
```

Expected response: insufficient evidence; do not invent application requirements.

## Observed answers

| Check | Model | Prompt | Input | Actual response | Assessment |
| --- | --- | --- | --- | --- | --- |
| 1 | `llama3.2:1b` | P0 | A | Refusal, quoted below | Incorrect refusal |
| 2 | `llama3.2:1b` | P1 | A | `Insufficient evidence.` | Incorrect refusal |
| 3 | `llama3.2:3b` | P1 | A | `A blue form.` | Expected meaning returned |
| 4 | `llama3.2:3b` | P1 | B | `Insufficient evidence.` | Expected refusal returned |

Full response to check 1:

> Insufficient evidence. The evidence only provides information about the form required for a "fictional application", but does not specify what type of application it is. It does not provide any information about the requirements for a real application.

The 1B model treated the fictional nature of the scenario as grounds for refusal,
although the supplied text answered the question. Changing the prompt did not
resolve this example. This does not establish why the model failed or that it
cannot answer other questions.

## Timings and usage reported by Ollama

Seconds below are converted from the response's nanosecond values and rounded
to three decimal places. Total is Ollama's `total_duration`, not measured
end-to-end HTTP latency.

| Check | Response `created_at` (UTC) | Total (s) | Load (s) | Input tokens | Cached input tokens | Output tokens |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-27T13:43:22.416630Z | 2.083 | 1.328 | 63 | 0 | 46 |
| 2 | 2026-10-27T13:48:13.827488Z | 0.249 | 0.016 | 91 | 16 | 5 |
| 3 | 2026-10-27T14:41:59.317165Z | 2.312 | 1.860 | 91 | 0 | 5 |
| 4 | 2026-10-27T14:43:47.950338Z | 0.215 | 0.007 | 92 | 80 | 5 |

Check 3 included substantial model loading. Check 4 had little load time and
reused 80 cached prompt tokens. These timings do not establish a general latency
target, a model speed comparison or suitable production timeout values.

## Current direction and limits

Use `llama3.2:3b` as the provisional model for the next adapter experiment,
with the model name configurable. This is not final model selection: two
successful synthetic cases do not establish reliability on immigration guidance,
longer evidence, conflicting sources or prompt injection. The system must still
be able to decline even when retrieval returns passages.

No Ollama adapter, model retry, circuit-breaker behaviour or model-failure
fallback was tested here. An ordinary model refusal is not evidence of a
network failure and should not automatically trigger transport retries.

Before deciding generation settings:

- Capture Ollama version, exact model identity/quantisation and context settings.
- Evaluate a broader fixed set, recording failures as well as successes.
- Include absent/unrelated evidence, conflicting passages and injected instructions.
- Separate model-loading and warm/cached timings; measure actual HTTP latency.
- Test the structured-output prompt separately: its behaviour may differ from P1.
- Measure on teammates' target hardware before assuming this laptop's timings apply.

Keep ADR-0004 proposed until the owner has assessed the alternatives and constraints.
