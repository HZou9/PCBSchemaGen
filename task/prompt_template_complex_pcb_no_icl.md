You aim to design a complex PCB schematic using SKiDL (Python) for a given circuit described in the text.
This is a **Hard** level task that requires combining multiple functional blocks (power stage, gate driver, isolated power supply).
Please ensure your designed circuit works properly, satisfies the requirements, and follows library conventions.

Your Python code should start with `from skidl import *` and end with `ERC()`.

## Question
Design [TASK].

Input node name: [INPUT].
Output node name: [OUTPUT].
Input voltage: [INPUT_VOLTAGE]V.
Output voltage: [OUTPUT_VOLTAGE]V.

## Available Functional Blocks (Choose what you need)

You may use components from the following categories. **You decide which ones to use based on the design requirements.**

### Half-Bridge Power Stage Options
| Part | Package | Kelvin Source | Max VBUS | Notes |
|------|---------|---------------|----------|-------|
| IMW65R015M2H | TO-247-3 | No | 450V | 3-pin, no KS |
| IMZA65R015M2H | TO-247-4 | Yes (pin 3) | 450V | 4-pin with KS, **recommended for high-side** |
| IMT65R033M2H | TOLL | Yes (pin 2) | 450V | SMD, 12-pin |
| IMLT65R015M2H | TOLT | Yes (pin 7) | 450V | Top-cooled SMD, 16-pin |
| BSC052N08NS5 | QFN | No | 60V | Low voltage only |

### Isolated Gate Driver Options
| Part | Type | Features | Primary Pins | Secondary Pins |
|------|------|----------|--------------|----------------|
| UCC5390E | Isolated | Basic isolated driver | 1-4 | 5-8 |
| UCC21710 | Isolated | DESAT, Miller clamp, OC protection | 9-16 (primary) | 1-8 (secondary) |

### Non-Isolated Gate Driver Options
| Part | Type | Notes |
|------|------|-------|
| UCC27511 | Low-side | Single channel, non-isolated |
| UCC27211 | Bootstrap | Half-bridge with integrated bootstrap diode, **max 100V VBUS** |

### Isolated Power Supply
| Part | Output | Notes |
|------|--------|-------|
| MGJ2D121505SC | +15V/-9V | For isolated gate driver secondary side |

### Passive Components
| Part | Type | Footprint |
|------|------|-----------|
| R | Resistor | R_0805 |
| C | Capacitor (MLCC) | C_0805 |
| C_film | Film Capacitor | C_film (for resonant applications) |
| L | Inductor (SMD) | L_0805 |
| Inductor_power | Power Inductor | Inductor_power (pins 1-6 = A, 7-12 = B) |
| transformer_PQ5050 | Transformer | transformer_PQ5050 (Pri_1: 1-3, Pri_2: 4-6, Sec_1: 7-9, Sec_2: 10-12) |

## ⚠️ CRITICAL Design Rules

### 1. Net Naming (MOST IMPORTANT!)
Multiple instances MUST use unique net names to avoid unintended shorts!
Isolation domains MUST have separate GND nets!

### 2. Gate Driver Connections
- Gate Resistor Required: Gate driver output → Resistor → MOSFET gate
- Kelvin Source: Gate driver return (GND2/VS) MUST connect to Kelvin Source (KS) pin, NOT power Source
- Turn-on/Turn-off Separation: Use separate resistors with anti-parallel diodes for speed control

### 3. Isolated Power Supply
- Primary side connects to main power domain
- Secondary side connects to gate driver power
- Polarity: +VOUT → VDD (VCC2), 0V → GND2, -VOUT → VEE

### 4. Decoupling Capacitors
- Every IC needs 100nF decoupling between VDD and GND
- VBUS high dv/dt loop needs at least 8 decoupling capacitors
- Place caps close to power pins

### 5. MOSFET Pin Connections
ALL parallel pins must be explicitly connected!

## Available Components (Detailed)
[COMPONENT_INFO]

## Output Format
Your answer must contain:
1. A concise design plan explaining:
   - Which functional blocks you chose and why
   - How they interconnect
   - Net naming strategy for multiple instances
2. Complete runnable SKiDL Python code

**Hard Constraints:**
- Code must end with `ERC()`
- Do NOT include `generate_netlist()` or `generate_pcb()`
- Do NOT write anything after the code block
- Use pin numbers, not pin names (more robust)
- Use "test" library for all parts: `Part("test", "PartName", ...)`
- Use footprint format: `footprint="test:FootprintName"`

## Answer
