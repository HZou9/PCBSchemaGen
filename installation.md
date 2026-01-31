# Installation (Step-by-Step)

This guide is the minimum, correct setup to run:
- `task/run.py`
- `task/run_feedback_trials.py`
- `sample design/run_samples_test.py` (must PASS)

## 1) System Requirements (Ubuntu 22.04+ / WSL2)

**Required system packages**
- Python 3.10+ (with `pip`)
- KiCad 9 (includes `kicad-cli` and `pcbnew`)
- KiCad symbol/footprint libraries
- Cairo/Pango libraries (for SVG rendering)

## 2) Step-by-Step Installation (Ubuntu/WSL)

### Step 1: System packages
```bash
sudo apt-get update
sudo apt-get install -y \
  git curl build-essential pkg-config \
  python3 python3-pip \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev
```

### Step 2: Install KiCad 9 + libraries
```bash
sudo add-apt-repository --yes ppa:kicad/kicad-9.0-releases
sudo apt-get update
sudo apt-get install -y kicad kicad-libraries
```

**Verify KiCad + pcbnew**
```bash
kicad-cli --version
python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())"
```

### Step 3: Python dependencies
```bash
cd /path/to/PCBSchemaGen
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## 3) Installation Verification (Required)

Run the sample test suite. It must PASS to consider the install successful.
```bash
cd "/path/to/PCBSchemaGen/sample design"
XDG_DATA_HOME=$(pwd)/../.xdg python3 run_samples_test.py
```

Expected: all tasks print `[PASS]` and exit code is 0.

## 4) How to Run the Main Scripts

### run.py (single task)
```bash
cd /path/to/PCBSchemaGen/task
export OPENAI_API_KEY="YOUR_API_KEY"
XDG_DATA_HOME=$(pwd)/.. python3 run.py \
  --model google/gemini-3-flash-preview \
  --task_id 1 \
  --num_of_retry 3 \
  --feedback full \
  --component_info_mode kg+component \
  --base_url https://openrouter.ai/api/v1 \
  --no-artifacts
```

### run_feedback_trials.py (batch trials)
```bash
cd /path/to/PCBSchemaGen/task
export OPENAI_API_KEY="YOUR_API_KEY"
XDG_DATA_HOME=$(pwd)/.. python3 run_feedback_trials.py \
  --model google/gemini-3-flash-preview \
  --num-of-retry 3 \
  --component-info-mode kg+component \
  --trials 15 \
  --feedbacks full,weak,none \
  --task-range 1-16 \
  --parallel-threads 15 \
  --base-url https://openrouter.ai/api/v1 \
  --artifacts
```

Notes:
- `run.py` defaults to generating artifacts; use `--no-artifacts` to skip.
- `run_feedback_trials.py` defaults to **no artifacts**; pass `--artifacts` if needed.
- You can pass `--api_key` instead of `OPENAI_API_KEY`.
- `XDG_DATA_HOME` prevents SKiDL from writing to system directories.

## 5) Optional (Analysis Only)
These are not required to run the pipeline, only for plotting/analysis:
- `numpy`, `scipy`, `matplotlib`
