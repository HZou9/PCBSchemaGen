from skidl import *

# Task 5: LDO_AUX_LOGIC
# LDO: VIN = 12V -> VOUT = 3.3V using TLV1117-33
# Pins: 1 ADJ/GND, 2 OUT (TAB=OUT), 3 IN

vin  = Net("VIN")
vout = Net("VOUT")
gnd  = Net("GND")

u1 = Part("test", "TLV1117-33", footprint="test:TLV1117-33")

# Pin connections (by number)
gnd  += u1[1]   # ADJ/GND
vout += u1[2], u1[4] # OUT
vin  += u1[3]   # IN

# Input/output capacitors (0805)
# Common LDO practice: bulk + high-frequency bypass at output.
c1 = Part("test", "C", value="10uF",  footprint="test:C_0805")   # CIN
c2 = Part("test", "C", value="10uF",  footprint="test:C_0805")   # COUT
c3 = Part("test", "C", value="100nF", footprint="test:C_0805")   # HF bypass at OUT

vin += c1[1]
gnd += c1[2]

vout += c2[1], c3[1]
gnd  += c2[2], c3[2]

ERC()

