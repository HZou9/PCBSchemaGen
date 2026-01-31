from skidl import *

# Task 4: ISENSE_HALL_ISO
# Hall-effect current sensor module (ACS37010):
# - Current path: LINE_IN -> IP+ -> IP- -> LINE_OUT
# - Supply: VDD(3.3V) and GND with 100nF decoupling
# - Output: VOUT -> ISNS_ISO
# - VREF (if available) exported as VREF net for future conditioning

line_in  = Net("LINE_IN")
line_out = Net("LINE_OUT")     # downstream continuation of the current path
isns_iso = Net("ISNS_ISO")

vdd = Net("VDD")               # 3.3V supply rail
gnd = Net("GND")
vref = Net("VREF")             # exported reference pin (optional use later)

# ACS37010 pin mapping: 1 IP+, 2 IP+, 3 IP-, 4 IP-, 5 GND, 6 VREF, 7 VOUT, 8 VCC
u1 = Part("test", "ACS37010", footprint="test:ACS37010")

# Current conduction path.
line_in  += u1[1]              # IP+
line_out += u1[4]              # IP-

# Power pins.
gnd += u1[5]
vdd += u1[8]

# Mandatory decoupling capacitor (common SMD value, 0805).
c1 = Part("test", "C", value="100nF", footprint="test:C_0805")
vdd += c1[1]
gnd += c1[2]

# Analog output.
isns_iso += u1[7]              # VOUT

# Reference output (kept for future stages; if your symbol has no VREF pin, delete this line).
vref += u1[6]                  # VREF

ERC()

