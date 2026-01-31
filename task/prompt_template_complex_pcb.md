You aim to design a complex PCB schematic using SKiDL (Python) for a given circuit described in the text.
This is a **Hard** level task that requires combining multiple functional blocks (power stage, gate driver, isolated power supply).
Please ensure your designed circuit works properly, satisfies the requirements, and follows library conventions.

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

## Two Implementation Approaches (Choose One)

### Approach A: Direct Implementation (Flat)
Write all components directly without subcircuit abstraction. Suitable for simpler combinations.

```python
from skidl import *

# Define ALL nets with UNIQUE names
vin = Net("VIN")
vout = Net("VOUT")
vbus_p = Net("VBUS_P")
pgnd = Net("PGND")
vsw = Net("VSW")

# Gate driver 1 nets (high-side) - use suffixes to avoid conflicts!
vdd_drv1 = Net("VDD_DRV1")
gnd_drv1 = Net("GND_DRV1")
vee_drv1 = Net("VEE_DRV1")

# Gate driver 2 nets (low-side) - different names!
vdd_drv2 = Net("VDD_DRV2")
gnd_drv2 = Net("GND_DRV2")
vee_drv2 = Net("VEE_DRV2")

# Isolated power supply 1 nets
vin_iso1 = Net("VIN_ISO1")
gnd_iso1_pri = Net("GND_ISO1_PRI")

# ... instantiate components and connect ...
```

### Approach B: Subcircuit Encapsulation
Use `@subcircuit` decorator for reusable blocks. Recommended when using multiple identical structures.

```python
from skidl import *

@subcircuit
def half_bridge_with_driver(vbus_p, pgnd, vsw, gate_h, gate_l, ks_h, ks_l, vdd_drv, vee_drv, gnd_drv):
    """Half-bridge power stage with isolated gate drivers"""
    # High-side MOSFET
    q_h = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H")
    # Low-side MOSFET
    q_l = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H")

    # Connect MOSFETs
    q_h[1] += vbus_p        # Drain
    q_h[2] += vsw           # Source
    q_h[3] += ks_h          # Kelvin Source
    q_h[4] += gate_h        # Gate

    q_l[1] += vsw           # Drain
    q_l[2] += pgnd          # Source
    q_l[3] += ks_l          # Kelvin Source
    q_l[4] += gate_l        # Gate

    # Gate resistors (turn-on and turn-off)
    r_gon_h = Part("test", "R", value="10R", footprint="test:R_0805")
    r_goff_h = Part("test", "R", value="2.2R", footprint="test:R_0805")
    # ... more components ...

# Instantiate multiple half-bridges
hb1_vsw = Net("HB1_VSW")
hb2_vsw = Net("HB2_VSW")
# Each subcircuit call creates isolated internal nets
half_bridge_with_driver(vbus_p, pgnd, hb1_vsw, ...)
half_bridge_with_driver(vbus_p, pgnd, hb2_vsw, ...)
```

## ⚠️ CRITICAL Design Rules

### 1. Net Naming (MOST IMPORTANT!)
**Multiple instances MUST use unique net names to avoid unintended shorts!**

❌ **WRONG** - Both half-bridges share same net names:
```python
vsw = Net("VSW")  # Used by both HB1 and HB2 - WRONG!
```

✅ **CORRECT** - Each instance has unique names:
```python
vsw_1 = Net("VSW_1")  # Half-bridge 1
vsw_2 = Net("VSW_2")  # Half-bridge 2
```

**Isolation domains MUST have separate GND nets!**

❌ **WRONG** - Primary and secondary share GND:
```python
gnd = Net("GND")  # Used for both primary and secondary - WRONG!
```

✅ **CORRECT** - Separate GND for each domain:
```python
gnd_pri = Net("GND_PRI")           # Primary side (controller)
gnd_sec_h = Net("GND_SEC_H")       # High-side driver secondary
gnd_sec_l = Net("GND_SEC_L")       # Low-side driver secondary
```

### 2. Gate Driver Connections
- **Gate Resistor Required**: Gate driver output → Resistor → MOSFET gate
- **Kelvin Source**: Gate driver return (GND2/VS) MUST connect to **Kelvin Source (KS)** pin, NOT power Source
- **Turn-on/Turn-off Separation**: Use separate resistors with anti-parallel diodes for speed control

```python
# Gate driver to MOSFET connection (correct)
drv[6] += r_gate[1]      # Driver OUT → Gate resistor
r_gate[2] += q[4]        # Gate resistor → MOSFET Gate
drv[7] += q[3]           # Driver GND2 → MOSFET Kelvin Source (NOT pin 2!)
```

### 3. Isolated Power Supply
- Primary side connects to main power domain
- Secondary side connects to gate driver power
- **Polarity**: +VOUT → VDD (VCC2), 0V → GND2, -VOUT → VEE

```python
# Isolated DC-DC connection
iso_dcdc[1] += vin_12v        # Primary +VIN
iso_dcdc[2] += gnd_pri        # Primary -VIN (GND)
iso_dcdc[7] += vdd_drv        # Secondary +VOUT (+15V)
iso_dcdc[6] += gnd_sec        # Secondary 0V (GND2)
iso_dcdc[5] += vee_drv        # Secondary -VOUT (-9V)
```

### 4. Decoupling Capacitors
- **Every IC** needs 100nF decoupling between VDD and GND
- **VBUS high dv/dt loop** needs at least 8 decoupling capacitors
- Place caps close to power pins

```python
# Decoupling for isolated gate driver
c_vdd = Part("test", "C", value="100nF", footprint="test:C_0805")
c_vdd[1] += vdd_drv
c_vdd[2] += gnd_drv

# VBUS decoupling (multiple caps for high dv/dt)
for i in range(8):
    c = Part("test", "C", value="100nF", footprint="test:C_0805")
    c[1] += vbus_p
    c[2] += pgnd
```

**Half-Bridge Power Stage Rule**: For tasks with power stage (P17-P23), each half-bridge MUST have at least 8 decoupling capacitors on VBUS. This is verified by the topology checker.

### 5. MOSFET Pin Connections
**ALL parallel pins must be explicitly connected!**

```python
# TO-247-4 (IMZA65R015M2H) - 4 pins, straightforward
q[1] += drain_net    # Drain
q[2] += source_net   # Source
q[3] += ks_net       # Kelvin Source
q[4] += gate_net     # Gate

# TOLL (IMT65R033M2H) - 12 pins, connect all parallel pins
q[1] += gate_net              # Gate
q[2] += ks_net                # Kelvin Source
q[3,4,5,6,7,8,9] += source_net  # All Source pins
q[10,11,12] += drain_net      # All Drain pins
```

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
