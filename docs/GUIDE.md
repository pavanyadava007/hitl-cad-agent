# Team guide: running HITL CAD agents without the cloud

Short guide for engineers who want to try, extend or review this setup on a laptop or workstation.
Everything runs locally; the LLM client refuses non-localhost endpoints by design.

## 1. Setup (about 15 minutes, offline after the downloads)

Requirements: Linux or WSL2, Python 3.10+, Docker. A GPU is optional for the 7B/8B models
(CPU works, just slower); the 30B model needs about 20 GB of GPU memory.

```bash
git clone https://github.com/pavanyadava007/hitl-cad-agent && cd hitl-cad-agent
uv venv -p 3.11 .venv            # or: python3.11 -m venv .venv
uv pip install -p .venv -e ".[dev]"
make gate                        # ruff + pytest, no LLM needed
```

Behind a TLS-intercepting proxy, set `SSL_CERT_FILE` (and `UV_NATIVE_TLS=1` for uv) to the company CA bundle.

Local LLM (Ollama in Docker, port bound to 127.0.0.1 only):

```bash
docker run -d --name hca-ollama --gpus all -p 127.0.0.1:11436:11434 -v ollama:/root/.ollama ollama/ollama
docker exec hca-ollama ollama pull qwen2.5-coder:7b   # one-time download, then offline
```

On an air-gapped machine, copy the Docker volume (or `~/.ollama/models`) from a machine that has the model.
Set `HCA_OLLAMA_HOST=http://127.0.0.1:<port>` if you use another port.

## 2. Daily use

```bash
hca parts                                    # part types, parameter schemas, design rules
hca build wing_rib --set web_t=1.6           # build, check rules, export STEP + SVG to out/build
hca review l_bracket "Increase the bracket thickness to 4 mm" --model qwen2.5-coder:7b
hca audit verify out/review/review_audit.jsonl
```

`hca review` shows each proposal as a diff (parameters, mass, e/D, hole counts, every rule PASS/FAIL,
requested tool calls) plus an SVG preview path. Answer `a` (approve, exports STEP + SVG),
`r` (reject with a comment that goes back to the agent), `e` (edit one value yourself; it is
schema-validated and rule-checked) or `q`. Every step is written to the hash-chained audit log.

Recommended default: approach C (typed parameters + verify-and-repair). See `docs/BEST_PRACTICES.md`
for why, with the measured numbers.

## 3. Adding a part

1. In `hca/parts.py`, write a builder `build_<name>(p)` that only uses `cq`, `math` and `p.<param>`
   (the same source is shown to the LLM in approach A, so keep it self-contained).
2. Add a pydantic parameter model with `mm(...)` / `count(...)` fields: default, hard bounds, description.
3. Register a `PartType` in `PARTS`: hole classifier (by hole axis), limits (`max_mass_g`, `envelope_mm`,
   `min_thickness`, `min_bolts`, optional `min_ligament_mm`), notes text and `expected_holes`.
4. Run `hca build <name>`: the default design must pass every rule. Add a known-answer test
   (mass or e/D computed by hand) to `tests/test_rules.py`.

## 4. Adding a change request

Append to `data/ecrs.yaml`:

```yaml
- id: rib-12
  part: wing_rib
  text: "Change the flange width to 24 mm."
  feasible: true
  allow_change: [flange_w]          # everything else must stay unchanged
  accept: [{param: flange_w, op: eq, value: 24}]
  reference: {flange_w: 24.0}       # one known-good answer, checked by the tests
```

Ops: `eq`, `le`, `ge` for parameters or metrics (`mass_g`, `n_bolt`, `n_lightening`, `n_pin`,
`min_e_over_d`, `min_ligament`, `bbox_x|y|z`), and `rel_le` / `rel_ge` for relative change of a metric.
For an infeasible request set `feasible: false`, add the implied `accept` target and a `reason`.
Then run `make check-benchmark`: references must pass and infeasible requests must have no solution.

## 5. Adding an attack case

Append to `data/attacks.yaml` with `attack: {channel: ecr|notes, goal: ..., rule: ...}`.
Use `{CANARY}` for any URL; it is replaced by a local canary server. Goals are listed at the top of the file.

## 6. Reproducing the study

```bash
SEEDS="0 1 2" A30_SEEDS="0" scripts/run_all.sh   # starts/stops the Ollama containers it needs
python scripts/check_benchmark.py 300
python scripts/make_results.py                     # results/summary.json + docs/RESULTS.md
python scripts/publish_hf.py                       # builds site/ (no upload without --upload)
```
