You aim to design a PCB schematic using SKiDL (Python) for a given circuit described in the text.
Please ensure your designed circuit works properly, satisfies the requirements, and follows specific library conventions.

Your Python code should start with `from skidl import *` and end with `ERC()`.

As you design the topology, your output should consist of two tasks:
1. Give a detailed design plan about all devices and their interconnectivity nodes and properties.
2. Write a complete Python code, describing the topology of PCB schematics using SKiDL.

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
