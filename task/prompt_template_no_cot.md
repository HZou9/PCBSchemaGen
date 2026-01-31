You aim to design a PCB schematic using SKiDL (Python) for a given circuit described in the text.
Please ensure your designed circuit works properly, satisfies the requirements, and follows specific library conventions.

Here is an example:

## Question
Design an isolated voltage sensing front-end using a resistor divider with an isolated amplifier to measure a high-voltage bus and output an isolated differential low-voltage sense signal.

Input node name: VIN.
Output node name: OUTP, OUTN.

## Answer

```python
from skidl import *

# 1. Define Nets
vin  = Net("VIN")
outp = Net("OUTP")
outn = Net("OUTN")

vdd1 = Net("VDD1") # High-side floating supply
gnd1 = Net("GND1") # High-side ground
vdd2 = Net("VDD2") # Low-side supply
gnd2 = Net("GND2") # Low-side ground

# 2. Instantiate Components
# Use "test" library for all parts.
# Footprints must follow "test:FootprintName" format.

# AMC1350: 8-pin Isolated Amplifier
# Pin 1: VDD1, 2: VINP, 3: VINN, 4: GND1
# Pin 5: GND2, 6: VOUTN, 7: VOUTP, 8: VDD2
u1 = Part("test", "AMC1350", footprint="test:SOIC-8")

# Resistor Divider (3x 100k + 1x 200R for ~250mV scaling from 400V)
# Using 0805 for standard spacing (1206 not available in lib)
r1 = Part("test", "R", value="100k", footprint="test:R_0805")
r2 = Part("test", "R", value="100k", footprint="test:R_0805")
r3 = Part("test", "R", value="100k", footprint="test:R_0805")
r_sense = Part("test", "R", value="200R", footprint="test:R_0805")

# Decoupling Capacitors (0805)
c1 = Part("test", "C", value="100nF", footprint="test:C_0805") # For VDD1
c2 = Part("test", "C", value="100nF", footprint="test:C_0805") # For VDD2

# 3. Connections

# High Voltage Divider Path
# VIN -> R1 -> R2 -> R3 -> R_sense -> GND1
vin += r1[1]
r1[2] += r2[1]
r2[2] += r3[1]
r3[2] += r_sense[1]
r_sense[2] += gnd1

# AMC1350 High Side (Pins 1-4)
u1[1] += vdd1
u1[2] += r_sense[1] # VINP connects to top of sense resistor
u1[3] += gnd1       # VINN connects to GND1 (Single-ended sensing config)
u1[4] += gnd1

# Decoupling High Side
c1[1] += vdd1
c1[2] += gnd1

# AMC1350 Low Side (Pins 5-8)
u1[5] += gnd2
u1[6] += outn
u1[7] += outp
u1[8] += vdd2

# Decoupling Low Side
c2[1] += vdd2
c2[2] += gnd2

# 4. ERC Check
ERC()
```

Directly give me Python code. Start with `from skidl import *` and end with `ERC()`.
Do not provide any design rationale or intermediate reasoning. Directly output the SKiDL code.

Please make sure your Python code is compatible with the `skidl` library.
Please give the runnable code without any placeholders.

**Crucial Rules:**
1. **Library**: ALWAYS use the `"test"` library for all parts (e.g., `Part("test", "Name", ...)`).
2. **Footprints**: ALWAYS specify proper footprints using the format `footprint="test:FootprintName"`. Common ones: `test:R_0805`, `test:C_0805`, for ic, always use ic chip model as footprint name (e.g. for UCC27211, it should be `footprint="test:UCC27211"`).
3. **Naming**: Use numeric refdes suffix (e.g. `R1`, `C1`, `U1`). Do NOT use letters in refdes numbering.
4. **Pin Grouping**: For Power MOSFETs (TOLL/QFN), explicitly connect **ALL** physical pins (e.g., `u1[1, 2, 3] += net`).
5. **NC Handling**: If a pin is unused, explicitly connect it to NC (e.g., `u1[1] += NC`).
6. **Decoupling**: Always add 100nF decoupling capacitors (`C_0805`) for every power pin pair of ICs.
7. **No Generation**: Do NOT include `generate_netlist()` or `generate_pcb()` at the end. Only `ERC()`.
9. **Code Only**: Do not write redundant text after the code block.
10. **Standard Values**: Use E24 series standard values for Resistors and Capacitors whenever possible (e.g., 10k, 4.7k, 2.2k, not 6k or 9k).
11. **Pin Names with Symbols**: If a pin name contains `/`, `+`, `-`, or spaces, access it with brackets (e.g., `u1["ADJ/GND"]`, `u1["+IN"]`) or by pin number. Do NOT use dot-notation for those pins.
12. **Voltage Ratings**: Strictly check component voltage ratings against BOTH Input and Output voltages. If the maximum voltage (Input or Output) exceeds a component's rating (e.g., UCC27211 is max 120V), do NOT use that component.

## Question

Design [TASK].

Input node name: [INPUT].

Output node name: [OUTPUT].

## Available Components
[COMPONENT_INFO]

## Answer
