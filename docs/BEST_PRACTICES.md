# Best practices for local, secure human-in-the-loop design agents

Derived from the measurements in [RESULTS.md](RESULTS.md) (NVIDIA L4 24 GB, Ollama, temperature 0, 36 change
requests and 24 attacks per seed, measured 2026-10-04). Each practice names the result it rests on. Rates are
`percent [Wilson 95% CI] (k/n)`; small cells have wide intervals, so read them as direction, not decimals.

## 1. Let the model edit typed parameters, not geometry code

Give the LLM a bounded parameter schema and build the geometry with trusted code (approach B/C) instead of asking
it to write CAD scripts (approach A).

- Free code never refused an infeasible request, for any model: qwen2.5-coder:7b 0% [0-30] (0/9),
  llama3.1:8b 0% [0-30] (0/9), qwen3-coder:30b 0% [0-30] (0/9). It rewrote the script and produced something.
- With defences off, free code was the most exposed design: attack success 50% [31-69] (12/24) for llama3.1:8b and
  46% [28-65] (11/24) for qwen3-coder:30b, against 29% [20-41] (21/72) and 24% [15-35] (17/72) for typed tools.
- Free code is also about 8 to 9 times slower per step on the same GPU (qwen3-coder:30b step p50 7.29 s for A vs.
  0.84 s for B/C), because the model writes a full script instead of a short JSON patch.

## 2. Verify on the real geometry and feed failures back before a human sees the proposal

Run the design rules on the built solid and return failed rules to the agent (approach C, at most 3 rounds).

- Rule-violating first proposals dropped from 25% [18-34] (27/108) to 0% [0-3] (0/108) for qwen2.5-coder:7b,
  from 33% [25-43] (36/108) to 0% [0-3] (0/108) for llama3.1:8b and from 14% [9-22] (15/108) to 2% [1-7] (2/108)
  for qwen3-coder:30b.
- Autonomous task success rose from 69% [60-77] (75/108) to 86% [78-91] (93/108) (qwen2.5-coder:7b) and from
  58% [49-67] (63/108) to 81% [72-87] (87/108) (llama3.1:8b), mainly because the checker turns impossible requests
  into refusals: infeasible requests refused went from 33% [19-52] (9/27) to 100% [88-100] (27/27) for
  qwen2.5-coder:7b and from 0% [0-12] (0/27) to 89% [72-96] (24/27) for llama3.1:8b.
- Cost: on average 0.24 to 0.38 extra repair rounds per step, and some over-caution. False refusals of feasible
  requests rose to 15% [9-24] (12/81) for the 7B/8B models, so a reviewer must still be able to push back.
- Measure rules on the geometry, not only on parameters: hole counts, edge distance and ligaments come from the
  B-rep. Overlapping cutters in CadQuery silently produced two solids and lost holes in a unit test case; only the
  geometric checks caught it.

## 3. Keep the human gate, and give it a diff it can judge quickly

A rule checker cannot know intent. Proposals that pass every design rule but do the wrong thing (wrong parameter,
unrequested side change, "fixing" an infeasible request) are only caught by the reviewer.

- Wrong changes that would have been merged without the human gate: 3% [1-8] (3/108) for qwen2.5-coder:7b C,
  8% [4-15] (9/108) for llama3.1:8b C and qwen3-coder:30b C, 11% [4-25] (4/36) for qwen3-coder:30b A.
- The gate is cheap when the agent is good: 1.09 to 1.14 reviews per accepted change for approach C, and up to three
  reviews lift acceptance to 92% [85-96] (99/108) for qwen2.5-coder:7b C and qwen3-coder:30b C.
- Show the reviewer parameter deltas, mass and e/D deltas, every rule PASS/FAIL, requested tool calls and an SVG
  preview (what `hca review` prints). The reason for a rejection goes back to the agent in plain words.
- Caveat: the reviewer in these numbers is an oracle. Real reviewers will need more rounds and will miss some errors.

## 4. Deny by default and run side effects only after approval

Only `export_step` exists for the agent; anything else it asks for (`shell`, `http_post`, `write_file`,
`set_rule_limit`, `approve_merge`) is denied and logged. Exports go through a path jail.

- With the security layer on, attack success was 0% for every model and approach without any human gate, for example
  0% [0-5] (0/72) for qwen3-coder:30b B and C, with no false blocks on benign requests (0% [0-6] (0/66) for
  qwen3-coder:30b C).
- Typed tools still need the path jail and the tool policy: with defences off, injected export paths and file
  writes escaped the output folder in 27% [16-41] (12/45) of file-escape attacks for both B and C, and calls to the
  canary URL succeeded in 25% [14-41] (9/36) of network attacks.
- Rule feedback alone (C) already stopped every injected rule override (param_violation 0% [0-5] (0/72) with
  defences off), but it does nothing against tool and path attacks. Combine both.

## 5. If generated code must run, sandbox it before the review

In approach A the script has to run to produce the geometry the reviewer looks at, so a human gate cannot stop what
the code does while it runs.

- With defences off and the oracle gate in place, free-code attacks still succeeded: code execution 33% [12-65] (3/9),
  network 25% [9-53] (3/12), secret leak 100% [44-100] (3/3), all pooled over the three models. The gate only stopped
  what happens after approval (exports, merged rule violations).
- With the AST allowlist (only `cadquery` and `math`, no dunders, no exporters, no `open`), a fresh network namespace,
  rlimits and an environment without secrets, all of these went to 0 for every model with no false blocks
  (for example 0% [0-15] (0/21) for qwen3-coder:30b A).

## 6. Treat change requests and PLM metadata as untrusted input

Injected text in part metadata is a real channel, not a theoretical one. With defences off, attacks hidden in the
part notes succeeded in 33% [17-55] (7/21) of free-code cases and 13% [7-23] (8/63) of typed-tool cases (requests:
43% [31-57] (22/51) and 25% [19-33] (39/153)). Notes reach the model with less emphasis than the request, but
any field the agent reads can carry instructions. Do not rely on the model to ignore them: the defences above work
at execution level, independent of what the model decided. Prompt-level defences were not tested in this study.

## 7. Make every step auditable

Write proposals, checker results, denied tool calls, reviews and merges to an append-only JSONL log where every
record carries the sha256 of the previous one. `hca audit verify` detects edited, deleted and reordered records
(see `tests/test_audit.py`); every evaluation run in this study produced such a log under `out/audit/`.

## 8. Choose the model for the loop, not the leaderboard

- On the L4, qwen3-coder:30b (mixture of experts) generated about 90 output tokens/s against about 50 for the
  7B/8B models, so the larger model was also the fastest per step for B/C (0.84 s p50).
- With approach C the three models ended close together after review (91% to 92% accepted), while their autonomous
  differences were larger. The architecture moved the results more than the model choice did.
- At temperature 0 the first proposal was identical across three seeds for 34 to 36 of 36 requests, so repeated runs
  add little; spend evaluation time on more requests and attacks instead.
