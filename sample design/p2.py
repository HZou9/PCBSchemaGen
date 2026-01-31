from skidl import *

# Task 2: ISO_AMP_HV_SENSE (minimal)
# VIN = 400.0 V -> divider -> AMC1350 input
# Output is differential: OUTP/OUTN
# Pin access uses pin numbers for robustness.

vin  = Net("VIN")

# Primary side.
vdd1 = Net("VDD1")   # 3.3V or 5V supply
gnd1 = Net("GND1")
vin_div = Net("VIN_DIV")

# Secondary side.
vdd2 = Net("VDD2")   # 3.3V or 5V supply
gnd2 = Net("GND2")
outp = Net("OUTP")
outn = Net("OUTN")

# AMC1350 symbol and footprint names should match your local libs.
u1 = Part("test", "AMC1350", footprint="test:AMC1350")

# Input divider (0805, common values).
r1 = Part("test", "R", value="1.21M", footprint="test:R_0805")
r2 = Part("test", "R", value="10.0k", footprint="test:R_0805")

vin += r1[1]
vin_div += r1[2], r2[1]
gnd1 += r2[2]

# AMC1350 primary-side connections by pin number:
# 1 VDD1, 2 INP, 3 INN, 4 GND1
vdd1   += u1[1]
vin_div += u1[2]
gnd1   += u1[3]
gnd1   += u1[4]

# Decoupling caps (0805, common).
c1 = Part("test", "C", value="100nF", footprint="test:C_0805")
c2 = Part("test", "C", value="100nF", footprint="test:C_0805")

vdd1 += c1[1]
gnd1 += c1[2]

# AMC1350 secondary-side connections by pin number:
# 5 GND2, 6 OUTN, 7 OUTP, 8 VDD2
gnd2 += u1[5]
outn += u1[6]
outp += u1[7]
vdd2 += u1[8]

vdd2 += c2[1]
gnd2 += c2[2]

ERC()

# generate_graph(file_="p2.dot", engine="dot")
