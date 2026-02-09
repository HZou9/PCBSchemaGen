# PCBSchemaGen

LLM-based PCB schematic generation with automated topology verification.

# Installation

PCBSchemaGen requires:
- Python >= 3.10
- KiCad 9 (with pcbnew Python bindings)
- OpenAI-compatible API access

## Step 1: Install KiCad 9

Follow the official KiCad installation guide for your platform:

**https://www.kicad.org/download/**

After installation, verify KiCad and pcbnew:
```bash
kicad-cli --version
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
```

## Step 2: Install Python Dependencies

```bash
pip install openai pandas skidl networkx cairosvg Pillow
```

## Step 3: Environment Check

```bash
cd "sample design"
XDG_DATA_HOME=$(pwd)/../.xdg python3 run_samples_test.py
```

All 17 tasks should print `[PASS]`. If not, check your KiCad installation.

# Quick Start

```bash
cd task
XDG_DATA_HOME=$(pwd)/.. python3 run.py \
  --task_id 1 \
  --model gpt-4o \
  --api_key "YOUR_API_KEY" \
  --base_url https://openrouter.ai/api/v1
```

This generates a circuit for Task 1 (voltage divider).

# API Keys

Any OpenAI-compatible API works. We recommend [OpenRouter](https://openrouter.ai):
1. Create account at https://openrouter.ai
2. Get API key from dashboard
3. Use with `--base_url https://openrouter.ai/api/v1`

# Benchmark

- **Task definitions**: `benchmark.tsv` (23 tasks across 3 difficulty levels)
- **Reference designs**: `sample design/p*.py`
- **Component library**: `component.json`, `kg_component.json`
- **KiCad symbols/footprints**: `library/`

## Task Difficulty Levels

| Level | Tasks | Description |
|-------|-------|-------------|
| Easy | P1-P6 | Voltage dividers, LDOs, sensing circuits |
| Medium | P7-P16 | Half-bridge stages, gate drivers, isolated DC-DC |
| Hard | P17-P23 | Multi-switch converters (sync buck, DAB, LLC, 3-phase) |

# Example Output

The `example_output/` directory contains a successful run of Task 17 (Synchronous Buck Converter):

| File | Description |
|------|-------------|
| `attempt_1_skidl.py` | LLM-generated SKiDL code |
| `attempt_1.svg` | Circuit schematic visualization |
| `task_17_stats.json` | Run statistics (tokens, time, status) |
| `task_17_output.txt` | Full LLM output with chain-of-thought |
| `extracted_task_17.*` | Final artifacts (netlist, KiCad project) |

# Project Structure

```
PCBSchemaGen/
├── task/
│   ├── run.py                  # Single task runner
│   ├── run_feedback_trials.py  # Batch experiments
│   ├── topo/                   # Verification pipeline
│   └── prompt_template*.md     # LLM prompts
├── sample design/              # Ground truth implementations
├── library/                    # KiCad symbols & footprints
├── example_output/             # Example Task 17 output
├── benchmark.tsv               # Task definitions
├── component.json              # Component pin definitions
└── kg_component.json           # Component constraints
```

# Batch Experiments

To run multiple tasks with multiple trials:

```bash
cd task
XDG_DATA_HOME=$(pwd)/.. python3 run_feedback_trials.py \
  --task-range 1-16 \
  --trials 15 \
  --model gpt-4o \
  --api_key "YOUR_API_KEY" \
  --base_url https://openrouter.ai/api/v1 \
  --feedbacks full \
  --parallel-threads 8
```

Results are saved to `task/feedback_runs/`.

# Citation

If you find this work helpful, please cite our paper:

```bibtex
@misc{zou2026pcbschemagen,
      title={PCBSchemaGen: Constraint-Guided Schematic Design via LLM for Printed Circuit Boards (PCB)}, 
      author={Huanghaohe Zou and Peng Han and Emad Nazerian and Alex Q. Huang},
      year={2026},
      eprint={2602.00510},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={[https://arxiv.org/abs/2602.00510](https://arxiv.org/abs/2602.00510)}, 
}
