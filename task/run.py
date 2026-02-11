from openai import OpenAI
import argparse
import os
import sys
import pandas as pd
import time
import signal
import json
import re
import subprocess
import shutil
import glob
import ast
import tempfile

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
os.environ.setdefault("PYTHONBREAKPOINT", "0")

from topo import (
    build_topology,
    kg_loader,
    phase2_checks,
    match_skeleton,
    report,
    rule_extractor,
    rule_checker,
    complex_task_validator,
)
# --- 1. Initialization & Configuration ---

class TimeoutException(Exception):
    pass

def signal_handler(signum, frame):
    raise TimeoutException("timeout")

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=str, default="google/gemini-3-flash-preview")
parser.add_argument('--temperature', type=float, default=0.5)
parser.add_argument('--num_of_retry', type=int, default=3) # Max retries for feedback loop
parser.add_argument("--task_id", type=int, default=None)
parser.add_argument(
    "--component_info_mode",
    type=str,
    default="kg+component",
    choices=["component", "kg", "kg+component", "none"],
    help="Prompt component info source: component (component.json), kg (kg_component.json), kg+component (component+kg), none (no component info).",
)
parser.add_argument(
    "--feedback",
    type=str,
    default="full",
    choices=["full", "weak", "none"],
    help="Feedback detail level: full (default), weak (syntax/ERC only), none (success/fail only).",
)
parser.add_argument("--base_url", type=str, default="https://openrouter.ai/api/v1")
parser.add_argument('--api_key', type=str)
parser.add_argument(
    "--generate-artifacts",
    dest="generate_artifacts",
    action="store_true",
    help="Generate netlist/PCB artifacts (default).",
)
parser.add_argument(
    "--no-artifacts",
    dest="generate_artifacts",
    action="store_false",
    help="Skip artifact generation; keep only last SVG and minimal files.",
)
parser.add_argument(
    "--prompt-mode",
    type=str,
    default="auto",
    choices=["auto", "simple"],
    help="Prompt template selection: auto (P1-16 simple, P17-23 complex), simple (always simple).",
)
parser.set_defaults(generate_artifacts=True)

args = parser.parse_args()

# Topology verification configuration
TASK_DIR = os.path.abspath(os.getcwd())
BASE_DIR = os.path.abspath(os.path.join(TASK_DIR, ".."))
LIBRARY_DIR = os.path.join(BASE_DIR, "library")
KG_STORE = kg_loader.KGStore(base_dir=BASE_DIR)
TOPO_CACHE_DIR = os.path.join(TASK_DIR, "topo_cache")
RULE_CACHE_DIR = os.path.join(TASK_DIR, "rule_cache")

# API Configuration
API_BASE_URL = args.base_url
API_KEY = (
    args.api_key
    or os.environ.get("OPENAI_API_KEY")
    or os.environ.get("LOCAL_LLM_API_KEY")
    or os.environ.get("OPENROUTER_API_KEY")
)
model_id = args.model

if not API_KEY:
    print("Warning: API key not found. API calls will fail.")

client = OpenAI(
    base_url=API_BASE_URL,
    api_key=API_KEY,
)

# --- 2. Helper Functions (LLM & Library) ---

def get_response(messages, model=model_id, temperature=args.temperature):
    """Wrapper to call OpenRouter API."""
    try:
        print(f"Sending request to {model}...")
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return completion.choices[0].message.content, completion.usage
    except Exception as e:
        print(f"API Error: {e}")
        return "", None

# Simple pricing map (Input/Output per 1M tokens)
PRICING = {
    "gemini-3-flash": (0.50, 3.0),
    "google/gemini-3-pro-preview": (2.0, 12.0),
    "google/gemini-3-flash-preview": (0.50, 3.0),
    "google/gemini-2.5-flash": (0.30, 2.50),
    "deepseek/deepseek-v3.2": (0.25, 0.38),
    "meta-llama/llama-3.3-70b-instruct:free": (0.0, 0.0),
    "meta-llama/llama-4-maverick": (0.15, 0.6),
    "z-ai/glm-4.5-air:free": (0.0, 0.0),
    "z-ai/glm-4.6": (0.35, 1.5),
    "z-ai/glm-4.7": (0.4, 1.5),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
    "openai/gpt-4o": (2.5, 10.0),
    "openai/gpt-5.2": (1.75, 14.0),
    "gpt-3.5-turbo": (0.5, 1.5)
}

def calculate_cost(model, prompt_toks, completion_toks):
    rates = PRICING.get(model, (0.0, 0.0)) # Default to 0 if unknown
    cost = (prompt_toks / 1_000_000 * rates[0]) + (completion_toks / 1_000_000 * rates[1])
    return cost

def get_all_component_info():
    """Retrieves component info for prompt injection."""
    if args.component_info_mode == "none":
        return ""
    try:
        with open('../component.json', 'r') as f:
            component_lib = json.load(f)['components']
    except FileNotFoundError:
        print("Warning: ../component.json not found.")
        component_lib = None

    kg_components = {}
    if args.component_info_mode in ("kg", "kg+component"):
        try:
            with open("../kg_component.json", "r") as f:
                kg_data = json.load(f)
            kg_components = {c["id"]: c for c in kg_data.get("components", [])}
        except FileNotFoundError:
            print("Warning: ../kg_component.json not found.")
            kg_components = {}

    def format_constraint(constraint):
        ctype = constraint.get("type", "")
        if ctype == "supply_pair":
            return f"supply_pair(vdd_pin={constraint.get('vdd_pin')}, gnd_pin={constraint.get('gnd_pin')})"
        if ctype in ("must_be_connected", "differential_pair_must_be_distinct"):
            return f"{ctype}(pins={constraint.get('pins')})"
        if ctype == "driving_pair":
            return f"driving_pair(gate_pin={constraint.get('gate_pin')}, source_pin={constraint.get('source_pin')})"
        return ctype or str(constraint)

    info_str = ""
    if args.component_info_mode == "component":
        if not component_lib:
            return "Standard discrete components"
        for found in component_lib:
            category = found.get("category", "Unknown")
            note = found.get("note", "")
            footprint = found.get("footprint", "")
            info_str += f"> Component: {found['id']} ({category}) | Note: {note} | Footprint: {footprint}\n"
            pin_list = []
            for pin in found["pins"]:
                desc = f"({pin['description']})" if pin.get("description") else ""
                pin_list.append(f"[{pin['num']}:{pin['name']}{desc}]")
            info_str += "> Pins: " + " ".join(pin_list) + "\n\n"
        return info_str if info_str else "Standard discrete components"

    if args.component_info_mode == "kg":
        if not kg_components:
            return "Standard discrete components"
        for comp_id, found in kg_components.items():
            category = found.get("category", "Unknown")
            footprint = found.get("footprint", "")
            info_str += f"> Component: {comp_id} ({category}) | Footprint: {footprint}\n"
            pins = found.get("pins", [])
            if pins:
                pin_list = [f"[{p.get('num')}:{p.get('name')}]" for p in pins]
                info_str += "> Pins: " + " ".join(pin_list) + "\n"
            pin_roles = found.get("pin_roles", {})
            if pin_roles:
                roles_str = ", ".join([f"{k}->{v}" for k, v in pin_roles.items()])
                info_str += f"> PinRoles: {roles_str}\n"
            constraints = found.get("generic_constraints", [])
            if constraints:
                constraint_str = "; ".join([format_constraint(c) for c in constraints])
                info_str += f"> Constraints: {constraint_str}\n"
            info_str += "\n"
        return info_str if info_str else "Standard discrete components"

    if not component_lib:
        return "Standard discrete components"
    for found in component_lib:
        comp_id = found["id"]
        category = found.get("category", "Unknown")
        note = found.get("note", "")
        footprint = found.get("footprint", "")
        info_str += f"> Component: {comp_id} ({category}) | Note: {note} | Footprint: {footprint}\n"
        pin_list = []
        for pin in found["pins"]:
            desc = f"({pin['description']})" if pin.get("description") else ""
            pin_list.append(f"[{pin['num']}:{pin['name']}{desc}]")
        info_str += "> Pins: " + " ".join(pin_list) + "\n"

        kg_found = kg_components.get(comp_id)
        if kg_found:
            pin_roles = kg_found.get("pin_roles", {})
            if pin_roles:
                roles_str = ", ".join([f"{k}->{v}" for k, v in pin_roles.items()])
                info_str += f"> PinRoles: {roles_str}\n"
            constraints = kg_found.get("generic_constraints", [])
            if constraints:
                constraint_str = "; ".join([c.get("type", "") for c in constraints])
                info_str += f"> Constraints: {constraint_str}\n"
        info_str += "\n"
    return info_str if info_str else "Standard discrete components"

def extract_code_block(content):
    match = re.search(r"```python\s+(.*?)```", content, re.DOTALL)
    if not match:
        match = re.search(r"```\s+(.*?)```", content, re.DOTALL)
    return match.group(1) if match else None

# --- 2.6. Feedback Helpers ---

def _format_feedback_message(error_type, detail):
    if args.feedback == "none":
        return "Attempt failed. Please try again."

    if args.feedback == "weak":
        if error_type == "code_block":
            return "Error: Missing Python code block. Please provide the full SKiDL code in a python block."
        if error_type == "syntax":
            return f"Syntax error:\n{detail}\nPlease fix the syntax and output the full code again."
        if error_type == "erc":
            return f"ERC/Runtime failure:\n{detail}\nPlease fix these errors and provide the corrected code."
        if error_type == "topology":
            return "Topology verification failed. Please fix these issues and provide the corrected code."
        return "Attempt failed. Please try again."

    # full
    if error_type == "code_block":
        return f"Error: {detail}. Please provide the full SKiDL code in a python block."
    if error_type == "syntax":
        return f"The code had syntax errors:\n{detail}\nPlease fix the syntax and output the full code again."
    if error_type == "erc":
        return f"The code failed verification with the following errors:\n{detail}\nPlease fix these errors and provide the corrected code."
    if error_type == "topology":
        return f"{detail}\nPlease fix these topology issues and provide the corrected code."
    return "Attempt failed. Please try again."

# --- 2.6.1 Retry Prompt Helper ---

def _format_feedback_with_retry(error_type, detail, retry_hint):
    base = _format_feedback_message(error_type, detail)
    if args.feedback == "none":
        return f"{base}\nPlease output the full code again."
    if retry_hint and retry_hint not in base:
        return f"{base}\n{retry_hint}"
    return base

# --- 2.5. Topology Snapshot Helpers ---

def _ensure_topo_cache_dir():
    if not os.path.exists(TOPO_CACHE_DIR):
        os.makedirs(TOPO_CACHE_DIR, exist_ok=True)


def _extract_skidl_snippet(code_string):
    start_idx = code_string.find("from skidl import *")
    if start_idx == -1:
        return code_string

    matches = list(re.finditer(r"(?i)\berc\s*\(\s*\)", code_string))
    if matches:
        end_idx = matches[-1].end()
        return code_string[start_idx:end_idx]
    return code_string[start_idx:]


def _save_attempt_code(results_dir, attempt_idx, code_string):
    snippet = _extract_skidl_snippet(code_string)
    filename = os.path.join(results_dir, f"attempt_{attempt_idx}_skidl.py")
    with open(filename, "w") as f:
        f.write(snippet)
        if not snippet.endswith("\n"):
            f.write("\n")


def _parse_snapshot_from_output(output):
    start_tag = "TOPOLOGY_JSON_START"
    end_tag = "TOPOLOGY_JSON_END"
    if start_tag not in output or end_tag not in output:
        return None, "Topology snapshot markers not found."

    start_idx = output.index(start_tag) + len(start_tag)
    end_idx = output.index(end_tag)
    payload = output[start_idx:end_idx].strip()
    try:
        snapshot = json.loads(payload)
    except json.JSONDecodeError as e:
        return None, f"Topology snapshot JSON parse error: {e}"
    return snapshot, ""


def _parse_artifact_errors(output):
    start_tag = "ARTIFACT_ERROR_START"
    end_tag = "ARTIFACT_ERROR_END"
    if start_tag not in output or end_tag not in output:
        return []
    start_idx = output.index(start_tag) + len(start_tag)
    end_idx = output.index(end_tag)
    payload = output[start_idx:end_idx].strip()
    if not payload:
        return []
    return [line.strip() for line in payload.splitlines() if line.strip()]


def extract_topology_snapshot(task_id, code_string, label):
    script_name = f"temp_topo_{task_id}_{label}.py"

    header = f"""
import sys
import os
import logging

kicad_sym_dir = "/usr/share/kicad/symbols"
if os.path.exists(kicad_sym_dir):
    os.environ["KICAD_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD9_SYMBOL_DIR"] = kicad_sym_dir

from skidl import *
from skidl import lib_search_paths, KICAD

sys.path.append(r"{TASK_DIR}")

lib_path = r"{LIBRARY_DIR}"
if os.path.exists(lib_path):
    if KICAD in lib_search_paths:
        if lib_path not in lib_search_paths[KICAD]:
            lib_search_paths[KICAD].append(lib_path)
    else:
        lib_search_paths[KICAD] = [lib_path]

class ERCTagFilter(logging.Filter):
    def filter(self, record):
        return "Tag" not in record.getMessage()

skidl_logger = logging.getLogger('skidl')
skidl_logger.addFilter(ERCTagFilter())

def _noop(*args, **kwargs):
    return None

generate_netlist = _noop
generate_svg = _noop
generate_pcb = _noop
"""

    footer = """
from topo import extract_skidl_design

snapshot = extract_skidl_design.snapshot_from_default_circuit()
print("TOPOLOGY_JSON_START")
print(extract_skidl_design.serialize_snapshot(snapshot))
print("TOPOLOGY_JSON_END")
"""

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, script_name)
        with open(script_path, "w") as f:
            f.write(header + "\n" + code_string + "\n" + footer)

        env = os.environ.copy()
        if os.path.exists("/usr/share/kicad/symbols"):
            env["KICAD_SYMBOL_DIR"] = "/usr/share/kicad/symbols"

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            env=env,
            cwd=temp_dir,
            stdin=subprocess.DEVNULL,
        )

        full_output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        return None, f"Topology extraction failed (exit {result.returncode})"

    snapshot, err = _parse_snapshot_from_output(full_output)
    if err:
        return None, err
    return snapshot, ""


def load_standard_snapshot(task_id):
    _ensure_topo_cache_dir()
    cache_path = os.path.join(TOPO_CACHE_DIR, f"p{task_id}_standard.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f), ""

    std_file = os.path.join("..", "sample design", f"p{task_id}.py")
    if not os.path.exists(std_file):
        return None, f"Standard answer not found: {std_file}"

    with open(std_file, "r") as f:
        code_string = f.read()

    snapshot, err = extract_topology_snapshot(task_id, code_string, "standard")
    if err:
        return None, err

    with open(cache_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    return snapshot, ""


def _ensure_rule_cache_dir():
    os.makedirs(RULE_CACHE_DIR, exist_ok=True)


def load_standard_rules(task_id, std_snapshot):
    _ensure_rule_cache_dir()
    cache_path = os.path.join(RULE_CACHE_DIR, f"p{task_id}_rules.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            return json.load(f), ""

    rules = rule_extractor.build_rules(std_snapshot)
    with open(cache_path, "w") as f:
        json.dump(rules, f, indent=2)
    return rules, ""

# --- 3. Verification Logic ---

def check_syntax(code_string):
    """Checks for Python syntax errors."""
    try:
        ast.parse(code_string)
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"

def generate_intermediate_svg(task_id, code_string, attempt_idx):
    """Generates an SVG for a specific attempt to visualize progress/failure."""
    results_dir = f"p{task_id}_results"
    if not os.path.exists(results_dir): os.makedirs(results_dir)
    
    svg_filename = f"attempt_{attempt_idx}.svg"
    
    header = f"""
import sys
import os
import logging

kicad_sym_dir = "/usr/share/kicad/symbols"
if os.path.exists(kicad_sym_dir):
    os.environ["KICAD_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD9_SYMBOL_DIR"] = kicad_sym_dir

from skidl import *
from skidl import lib_search_paths, KICAD

# Add library path
lib_path = r"{LIBRARY_DIR}"
if os.path.exists(lib_path):
    if KICAD in lib_search_paths:
        if lib_path not in lib_search_paths[KICAD]:
            lib_search_paths[KICAD].append(lib_path)
    else:
         lib_search_paths[KICAD] = [lib_path]

# Silence logs
class ERCTagFilter(logging.Filter):
    def filter(self, record):
        return "Tag" not in record.getMessage()

skidl_logger = logging.getLogger('skidl')
skidl_logger.addFilter(ERCTagFilter())
"""
    
    footer = f"""
# Intermediate SVG Generation
try:
    generate_svg()
except Exception as e:
    print(f"Intermediate SVG Failed: {{e}}")
"""
    
    script_name = f"temp_svg_{task_id}_{attempt_idx}.py"
    expected_default_svg = f"temp_svg_{task_id}_{attempt_idx}.svg"
    
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, script_name)
        with open(script_path, 'w') as f:
            f.write(header + "\n" + code_string + "\n" + footer)

        env = os.environ.copy()
        if os.path.exists("/usr/share/kicad/symbols"):
            env["KICAD_SYMBOL_DIR"] = "/usr/share/kicad/symbols"

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            env=env,
            cwd=temp_dir,
            stdin=subprocess.DEVNULL,
        )

        expected_svg_path = os.path.join(temp_dir, expected_default_svg)
        alt_svg_path = os.path.join(temp_dir, svg_filename)

        if os.path.exists(expected_svg_path):
            shutil.move(expected_svg_path, os.path.join(results_dir, svg_filename))
            print(f"Generated Intermediate SVG: {svg_filename}")
        elif os.path.exists(alt_svg_path):
            shutil.move(alt_svg_path, os.path.join(results_dir, svg_filename))
            print(f"Generated Intermediate SVG: {svg_filename}")
        else:
            print(f"Warning: Failed to generate {svg_filename}")
            print(f"SVG STDERR: {result.stderr[:500]}")

def check_erc_and_runtime(task_id, code_string):
    """
    Runs the code purely for ERC check. 
    Returns: (passed: bool, output_log: str, failure_reason: str)
    """
    # 1. Create temp script for Verification
    header = f"""
import sys
import os
import logging

kicad_sym_dir = "/usr/share/kicad/symbols"
if os.path.exists(kicad_sym_dir):
    os.environ["KICAD_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD9_SYMBOL_DIR"] = kicad_sym_dir

from skidl import *
from skidl import lib_search_paths, KICAD

lib_path = r"{LIBRARY_DIR}"
if os.path.exists(lib_path):
    if KICAD in lib_search_paths:
        if lib_path not in lib_search_paths[KICAD]:
            lib_search_paths[KICAD].append(lib_path)
    else:
         lib_search_paths[KICAD] = [lib_path]

class ERCTagFilter(logging.Filter):
    def filter(self, record):
        return "Tag" not in record.getMessage()

skidl_logger = logging.getLogger('skidl')
skidl_logger.addFilter(ERCTagFilter())
"""
    
    footer = """
# Verification Footer
try:
    ERC()
except Exception as e:
    print(f"RUNTIME_ERROR: {e}")
"""
    
    script_name = f"temp_verify_{task_id}.py"
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, script_name)
        with open(script_path, 'w') as f:
            f.write(header + "\n" + code_string + "\n" + footer)

        # 2. Run it
        env = os.environ.copy()
        if os.path.exists("/usr/share/kicad/symbols"):
            env["KICAD_SYMBOL_DIR"] = "/usr/share/kicad/symbols"

        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            env=env,
            cwd=temp_dir,
            stdin=subprocess.DEVNULL,
        )

    full_output = result.stdout + "\n" + result.stderr

    # 3. Analyze Output
    if result.returncode != 0:
        return False, full_output, "Runtime Error (Script crashed)"
    
    if "RUNTIME_ERROR:" in full_output:
        return False, full_output, "Runtime Error (Exception caught)"

    # ERC Filtering Logic
    erc_failures = []

    def _ignore_erc_warning(line):
        if "Unconnected pin:" in line:
            if "VREF of ACS37010" in line:
                return True
            if "/KS of" in line or " KS of " in line:
                return True
        if "Merging two named nets" in line:
            return True
        return False

    for line in full_output.splitlines():
        if "ERC ERROR" in line:
            erc_failures.append(line)
        elif "ERC WARNING" in line:
            # Check ignored warnings
            if "Only one pin" in line and "attached to net" in line:
                continue # Ignore "Only one pin..."
            if _ignore_erc_warning(line):
                continue
            if "No pins attached to net" in line and "GND" in line:
                 erc_failures.append(line)
            else:
                erc_failures.append(line)

    if erc_failures:
        unique_errors = sorted(list(set(erc_failures)))
        return False, full_output, "ERC Check Failed:\n" + "\n".join(unique_errors)

    return True, full_output, ""


def run_topology_verification(task_id, code_string, input_nodes, output_nodes, attempt_idx):
    std_snapshot, std_err = load_standard_snapshot(task_id)
    if std_err:
        return False, f"Standard snapshot error: {std_err}"

    gen_snapshot, gen_err = extract_topology_snapshot(task_id, code_string, f"attempt{attempt_idx}")
    if gen_err:
        return False, f"Generated snapshot error: {gen_err}"

    build_topology.augment_snapshot(std_snapshot, KG_STORE)
    build_topology.augment_snapshot(gen_snapshot, KG_STORE)

    phase2_errors = phase2_checks.run_phase2_checks(gen_snapshot, KG_STORE, task_id=task_id)
    if phase2_errors:
        return False, report.format_errors(phase2_errors)

    rules, rule_err = load_standard_rules(task_id, std_snapshot)
    if rule_err:
        return False, f"Rule extraction error: {rule_err}"

    nx_messages = match_skeleton.check_graph_similarity(std_snapshot, gen_snapshot, task_id=task_id)
    rule_errors = rule_checker.check_rules(gen_snapshot, rules, task_id=task_id)
    rule_errors.extend(rule_checker.check_driver_gate_links(std_snapshot, gen_snapshot))

    all_errors = []
    if rule_errors:
        all_errors.extend(rule_errors)
    if nx_messages:
        all_errors.extend(nx_messages)
    if all_errors:
        return False, report.format_errors(all_errors)

    return True, ""


def run_complex_task_verification(task_id, code_string, attempt_idx):
    """
    Run verification for complex tasks (P17-P23).
    Uses soft validation without standard snapshot comparison.
    """
    gen_snapshot, gen_err = extract_topology_snapshot(task_id, code_string, f"attempt{attempt_idx}")
    if gen_err:
        return False, f"Generated snapshot error: {gen_err}"

    build_topology.augment_snapshot(gen_snapshot, KG_STORE)

    passed, errors, warnings = complex_task_validator.validate_complex_task(
        gen_snapshot, task_id, KG_STORE
    )

    if not passed:
        feedback = complex_task_validator.get_validation_feedback_for_llm(errors, warnings)
        return False, feedback

    # Even if passed, show warnings
    if warnings:
        print("Complex task validation passed with warnings:")
        for w in warnings:
            print(f"  - {w}")

    return True, ""


# --- 4. Generation & Loop Logic ---

def generate_netlist_svg_artifacts(task_id, code_string):
    """Final step to generate artifacts after verification passes (or retries exhausted)."""
    print(f"--- Generating Final Artifacts for Task {task_id} ---")
    
    header = f"""
import sys
import os
import logging
kicad_sym_dir = "/usr/share/kicad/symbols"
if os.path.exists(kicad_sym_dir):
    os.environ["KICAD_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD9_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD8_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD7_SYMBOL_DIR"] = kicad_sym_dir
    os.environ["KICAD6_SYMBOL_DIR"] = kicad_sym_dir

kicad_fp_dir = "/usr/share/kicad/footprints"
if os.path.exists(kicad_fp_dir):
    os.environ["KICAD_FOOTPRINT_DIR"] = kicad_fp_dir
    os.environ["KICAD9_FOOTPRINT_DIR"] = kicad_fp_dir
    os.environ["KICAD8_FOOTPRINT_DIR"] = kicad_fp_dir
    os.environ["KICAD7_FOOTPRINT_DIR"] = kicad_fp_dir
    os.environ["KICAD6_FOOTPRINT_DIR"] = kicad_fp_dir

from skidl import *
from skidl import lib_search_paths, footprint_search_paths, KICAD

TASK_ID = {task_id}
lib_path = r"{LIBRARY_DIR}"
if os.path.exists(lib_path):
    if KICAD in lib_search_paths:
        if lib_path not in lib_search_paths[KICAD]:
            lib_search_paths[KICAD].append(lib_path)
    else:
         lib_search_paths[KICAD] = [lib_path]
    fp_paths = footprint_search_paths.get(KICAD, [])
    if isinstance(fp_paths, list):
        if lib_path not in fp_paths:
            fp_paths.append(lib_path)
            footprint_search_paths[KICAD] = fp_paths
    else:
        if fp_paths:
            if lib_path != fp_paths:
                footprint_search_paths[KICAD] = [fp_paths, lib_path]
        else:
            footprint_search_paths[KICAD] = [lib_path]
"""
    footer = """
# Artifact Generation
import os
errors = []

try:
    ERC()
except Exception:
    pass # Already checked

try:
    generate_netlist(tool=KICAD9)
except Exception as e:
    errors.append(f"NETLIST: {e}")

try:
    generate_svg()
except Exception as e:
    errors.append(f"SVG: {e}")

try:
    fp_libs = []
    test_pretty = os.path.join(lib_path, "test.pretty")
    if os.path.isdir(test_pretty):
        fp_libs.append(test_pretty)
    if os.path.isdir(lib_path):
        fp_libs.append(lib_path)
    pcb_file = f"extracted_task_{TASK_ID}.kicad_pcb"
    generate_pcb(pcb_file=pcb_file, fp_libs=fp_libs or None)
except Exception as e:
    errors.append(f"PCB: {e}")

if errors:
    print("ARTIFACT_ERROR_START")
    for msg in errors:
        print(msg)
    print("ARTIFACT_ERROR_END")
    raise SystemExit(1)
"""
    script_name = f"extracted_task_{task_id}.py"
    results_dir = f"p{task_id}_results"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, script_name)
        with open(script_path, 'w') as f:
            f.write(header + "\n" + code_string + "\n" + footer)

        env = os.environ.copy()
        if os.path.exists("/usr/share/kicad/symbols"):
            env["KICAD_SYMBOL_DIR"] = "/usr/share/kicad/symbols"

        # Execution for artifacts
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            env=env,
            cwd=temp_dir,
            stdin=subprocess.DEVNULL,
        )

        def move_file(pattern, dest, source_dir):
            for f in glob.glob(os.path.join(source_dir, pattern)):
                try:
                    dst_path = os.path.join(dest, os.path.basename(f))
                    if os.path.exists(dst_path):
                        os.remove(dst_path)
                    shutil.move(f, dst_path)
                except:
                    pass

        # Move files from temp dir
        move_file(f"extracted_task_{task_id}*", results_dir, temp_dir)
        move_file("*.kicad_pcb", results_dir, temp_dir)
        move_file("*.net", results_dir, temp_dir)

        full_output = result.stdout + "\n" + result.stderr

        # Save Log
        with open(os.path.join(results_dir, f"extracted_task_{task_id}.log"), "w") as f:
            f.write(full_output)

        # Cleanup unwanted in results
        for f in glob.glob(os.path.join(results_dir, "*_sklib.py")):
            os.remove(f)
        for f in glob.glob(os.path.join(results_dir, "*_skin.svg")):
            os.remove(f)

    artifact_errors = _parse_artifact_errors(full_output)
    missing = []
    if not glob.glob(os.path.join(results_dir, "*.net")):
        missing.append("NETLIST: missing .net artifact")
    if not glob.glob(os.path.join(results_dir, "*.kicad_pcb")):
        missing.append("PCB: missing .kicad_pcb artifact")
    if not os.path.exists(os.path.join(results_dir, f"extracted_task_{task_id}.svg")):
        missing.append("SVG: missing extracted_task svg")

    artifact_errors.extend(missing)

    svg_errors = [e for e in artifact_errors if e.startswith("SVG:")]
    non_svg_errors = [e for e in artifact_errors if not e.startswith("SVG:")]

    if result.returncode != 0 and not non_svg_errors and not svg_errors:
        non_svg_errors.append("Artifact generation failed with non-zero exit.")

    if svg_errors:
        print("SVG generation warnings:")
        print("\n".join(svg_errors))

    print(f"Artifacts saved to {results_dir}")
    return len(non_svg_errors) == 0, "\n".join(non_svg_errors)


def run_task_flow(task, input_nodes, output_nodes, task_id, it, flog):
    start_time = time.time()
    print(f"\n=== Starting Task {task_id} ===")
    
    # Stats trackers
    total_prompt_tokens = 0
    total_completion_tokens = 0
    stage_times = {
        "t_llm_request": 0.0,
        "t_parse_extract": 0.0,
        "t_syntax_check": 0.0,
        "t_erc_runtime": 0.0,
        "t_topology_verify": 0.0,
        "t_svg_generate": 0.0,
        "t_artifacts_generate": 0.0,
        "t_write_outputs": 0.0,
    }
    results_dir = f"p{task_id}_results"
    os.makedirs(results_dir, exist_ok=True)

    # Pre-clean: Remove stale files from previous runs to avoid confusion
    # This ensures the results directory only contains files from the current run
    stale_patterns = [
        "attempt_*.py",
        "attempt_*.svg",
        "extracted_task_*",
        "*_log.txt",
        "*.erc",
        "*.log",
        "*.net",
        "*.json",
        "*.kicad_*",
    ]
    for pattern in stale_patterns:
        for stale_file in glob.glob(os.path.join(results_dir, pattern)):
            try:
                os.remove(stale_file)
            except OSError:
                pass

    # Prepare Initial Prompt
    # Prompt mode: "simple" forces simple prompt for all tasks
    #              "auto" uses simple for P1-16, complex for P17-23
    if args.prompt_mode == "simple":
        prompt_file = "prompt_template.md"
    else:  # auto mode
        if complex_task_validator.is_complex_task(task_id):
            prompt_file = "prompt_template_complex_pcb.md"
        else:
            prompt_file = "prompt_template.md"

    # Validation type is always determined by task complexity, not prompt mode
    # P17-23 use complex validation (no reference needed), P1-16 use standard validation
    is_complex = complex_task_validator.is_complex_task(task_id)

    try:
        with open(prompt_file, "r") as f:
            template = f.read()
    except FileNotFoundError:
        print(f"Error: {prompt_file} not found!")
        return

    comp_info = get_all_component_info()
    prompt = template.replace("[TASK]", task)
    prompt = prompt.replace("[INPUT]", input_nodes)
    prompt = prompt.replace("[OUTPUT]", output_nodes)
    prompt = prompt.replace("[COMPONENT_INFO]", comp_info)

    messages = [
        {"role": "system", "content": "You are a PCB design expert using SKiDL."},
        {"role": "user", "content": prompt}
    ]

    best_code = None
    attempts_made = 0
    passed = False
    final_failure_reason = ""
    
    # Retry Loop
    for attempt in range(max(1, args.num_of_retry)):
        attempts_made += 1
        print(f"\n--- Attempt {attempt + 1}/{args.num_of_retry} ---")
        flog.write(f"\n--- Attempt {attempt + 1} ---\n")
        
        # 1. Generate
        t0 = time.monotonic()
        response, usage = get_response(messages)
        stage_times["t_llm_request"] += time.monotonic() - t0
        
        if usage:
            total_prompt_tokens += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens
            
        flog.write(f"Response:\n{response}\n")
        
        # Save output for current attempt
        if args.generate_artifacts:
            output_path = os.path.join(results_dir, f"task_{task_id}_output.txt")
            t0 = time.monotonic()
            with open(output_path, "w") as f:
                f.write(response)
            stage_times["t_write_outputs"] += time.monotonic() - t0
            
        t0 = time.monotonic()
        code = extract_code_block(response)
        stage_times["t_parse_extract"] += time.monotonic() - t0
        if not code:
            error_msg = "No Python code block found in response."
            print(f"Verification Failed: {error_msg}")
            final_failure_reason = error_msg
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": _format_feedback_message("code_block", error_msg)})
            continue

        best_code = code # Update candidate code
        # Always persist per-attempt code so batch runners can retain attempt_*.py even with --no-artifacts.
        t0 = time.monotonic()
        _save_attempt_code(results_dir, attempt + 1, code)
        stage_times["t_write_outputs"] += time.monotonic() - t0

        # 2. Verify: Syntax
        t0 = time.monotonic()
        valid_syntax, syntax_msg = check_syntax(code)
        stage_times["t_syntax_check"] += time.monotonic() - t0
        if not valid_syntax:
            print(f"Verification Failed: Syntax Error")
            final_failure_reason = syntax_msg
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": _format_feedback_with_retry(
                    "syntax",
                    syntax_msg,
                    "Please fix the syntax and output the full code again.",
                ),
            })
            continue

        # 3. Generate Intermediate SVG (Progress Visualization)
        if args.generate_artifacts:
            t0 = time.monotonic()
            generate_intermediate_svg(task_id, code, attempt + 1)
            stage_times["t_svg_generate"] += time.monotonic() - t0

        # 4. Verify: ERC
        t0 = time.monotonic()
        passed_erc, erc_log, erc_error_msg = check_erc_and_runtime(task_id, code)
        stage_times["t_erc_runtime"] += time.monotonic() - t0
        
        if passed_erc:
            t0 = time.monotonic()
            if is_complex:
                # Use complex task validation (soft validation)
                topo_ok, topo_msg = run_complex_task_verification(
                    task_id, code, attempt + 1
                )
            else:
                # Use standard topology verification
                topo_ok, topo_msg = run_topology_verification(
                    task_id, code, input_nodes, output_nodes, attempt + 1
                )
            stage_times["t_topology_verify"] += time.monotonic() - t0
            if topo_ok:
                print("Verification PASSED!")
                passed = True
                final_failure_reason = ""
                break # Success, exit loop
            else:
                print("Verification Failed: Topology Verification")
                print(topo_msg)
                final_failure_reason = topo_msg
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": _format_feedback_with_retry(
                        "topology",
                        topo_msg,
                        "Please fix the topology issues and output the full code again.",
                    ),
                })
                continue
        else:
            print(f"Verification Failed: ERC/Runtime Errors")
            print(erc_error_msg)
            final_failure_reason = erc_error_msg
            messages.append({"role": "assistant", "content": response})
            messages.append({
                "role": "user",
                "content": _format_feedback_with_retry(
                    "erc",
                    erc_error_msg,
                    "Please fix the ERC/runtime errors and output the full code again.",
                ),
            })

    # End of Loop - Generate Artifacts for whatever code we have (even if failed)
    if best_code:
        if args.generate_artifacts:
            t0 = time.monotonic()
            artifact_ok, artifact_msg = generate_netlist_svg_artifacts(task_id, best_code)
            stage_times["t_artifacts_generate"] += time.monotonic() - t0
            # Log file stays where it was created
            if not artifact_ok:
                if final_failure_reason:
                    final_failure_reason = f"{final_failure_reason}\n{artifact_msg}"
                else:
                    final_failure_reason = f"Artifact generation failed:\n{artifact_msg}"
                passed = False
        else:
            t0 = time.monotonic()
            _save_attempt_code(results_dir, attempts_made, best_code)
            stage_times["t_write_outputs"] += time.monotonic() - t0
            t0 = time.monotonic()
            generate_intermediate_svg(task_id, best_code, attempts_made)
            stage_times["t_svg_generate"] += time.monotonic() - t0
        
    if not final_failure_reason and not passed:
        final_failure_reason = "Unknown failure"

    status = "PASS" if passed else "FAIL"
    end_time = time.time()
    duration = end_time - start_time
    cost = calculate_cost(args.model, total_prompt_tokens, total_completion_tokens)

    stats = {
        "task_id": task_id,
        "model": args.model,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(end_time)),
        "total_duration_seconds": round(duration, 2),
        "attempts": attempts_made,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "estimated_cost_usd": round(cost, 6),
        "status": status,
        "failure_reason": final_failure_reason,
        "t_llm_request": round(stage_times["t_llm_request"], 4),
        "t_parse_extract": round(stage_times["t_parse_extract"], 4),
        "t_syntax_check": round(stage_times["t_syntax_check"], 4),
        "t_erc_runtime": round(stage_times["t_erc_runtime"], 4),
        "t_topology_verify": round(stage_times["t_topology_verify"], 4),
        "t_svg_generate": round(stage_times["t_svg_generate"], 4),
        "t_artifacts_generate": round(stage_times["t_artifacts_generate"], 4),
        "t_write_outputs": round(stage_times["t_write_outputs"], 4),
    }

    stats_file = os.path.join(results_dir, f"task_{task_id}_stats.json")
    t0 = time.monotonic()
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=4)
    stage_times["t_write_outputs"] += time.monotonic() - t0
    updated_write = round(stage_times["t_write_outputs"], 4)
    if updated_write != stats["t_write_outputs"]:
        stats["t_write_outputs"] = updated_write
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=4)
    print(f"Stats saved to {stats_file}")

# --- 5. Main Loop ---

def main():
    data_path = '../benchmark.tsv'
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found!")
        return

    df = pd.read_csv(data_path, delimiter='\t')
    strftime = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())
    
    # Pre-clean
    for f in glob.glob("skidl_repl*"): 
        if os.path.isfile(f): os.remove(f)

    for index, row in df.iterrows():
        circuit_id = row['Id']
        if args.task_id is not None and circuit_id != args.task_id:
            continue
            
        safe_model_name = args.model.replace("/", "_")
        results_dir = f"p{circuit_id}_results"
        os.makedirs(results_dir, exist_ok=True)
        log_filename = os.path.join(results_dir, f'{strftime}_{safe_model_name}_{circuit_id}_log.txt')

        flog = open(log_filename, 'w')
        try:
            run_task_flow(
                task=row['Task'], 
                input_nodes=row['InputNodes'], 
                output_nodes=row['OutputNodes'], 
                task_id=circuit_id, 
                it=0, 
                flog=flog
            )
        finally:
            flog.close()

if __name__ == "__main__":
    main()
