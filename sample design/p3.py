from skidl import *

# Task 3: DIFF2SE_VREF (simplified, no capacitors)
# Standard differential amplifier with VREF offset.
# Constraint: R1=R3, R2=R4, and choose gain so VOUT stays within 0..3V for VINP-VINN=±2V.

vinp = Net("VINP")
vinn = Net("VINN")
vref = Net("VREF")
vout = Net("VOUT")
vdd  = Net("VDD")   # assume 3.3V single-supply
gnd  = Net("GND")

# OPA328: pin 1 OUT, 2 V-, 3 IN+, 4 IN-, 5 V+
u1 = Part("test", "OPA328", footprint="test:OPA328")

# Power
vdd += u1[5]
gnd += u1[2]

# Mandatory decoupling capacitor (0805)
c1 = Part("test", "C", value="100nF", footprint="test:C_0805")
vdd += c1[1]
gnd += c1[2]

# Matched resistor pairs (0805, common values)
# Gain G = R2/R1 = 62k/100k = 0.62
r1 = Part("test", "R", value="100k", footprint="test:R_0805")  # VINN -> IN-
r2 = Part("test", "R", value="62k",  footprint="test:R_0805")  # VOUT -> IN- (feedback)
r3 = Part("test", "R", value="100k", footprint="test:R_0805")  # VINP -> IN+
r4 = Part("test", "R", value="62k",  footprint="test:R_0805")  # VREF -> IN+

# Output net
vout += u1[1]

# Inverting side: VINN -> R1 -> IN- ; VOUT -> R2 -> IN-
vinn += r1[1]
u1[4] += r1[2]

vout += r2[1]
u1[4] += r2[2]

# Non-inverting side: VINP -> R3 -> IN+ ; VREF -> R4 -> IN+
vinp += r3[1]
u1[3] += r3[2]

vref += r4[1]
u1[3] += r4[2]

ERC()
# generate_graph(file_="p3.dot", engine="dot")