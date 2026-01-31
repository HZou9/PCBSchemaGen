from skidl import *

# Task 6: BUCK_AUX_LOGIC
# TPS54302 buck: 12V -> 5V
# EN set by divider (R4/R5) following datasheet style.

vin  = Net("VIN")
vout = Net("VOUT")
gnd  = Net("GND")

sw   = Net("SW")
boot = Net("BOOT")
fb   = Net("FB")
en   = Net("EN")

# Templates (0805 as requested)
R_0805 = Part("test", "R", TEMPLATE, footprint="test:R_0805")
C_0805 = Part("test", "C", TEMPLATE, footprint="test:C_0805")
L_0805 = Part("test", "L", TEMPLATE, footprint="test:L_0805")

# IC: TPS54302 (pin order per your component.json)
# 1 GND, 2 SW, 3 VIN, 4 FB, 5 EN, 6 BOOT
u1 = Part("test", "TPS54302", footprint="test:TPS54302")

# --- Input capacitors (VIN to GND) ---
c1 = C_0805(value="10uF")
c2 = C_0805(value="0.1uF")
vin += c1[1], c2[1]
gnd += c1[2], c2[2]

# --- Bootstrap capacitor (BOOT to SW) ---
c3 = C_0805(value="0.1uF")
boot += c3[1]
sw   += c3[2]

# --- Power inductor (SW to VOUT) ---
l1 = L_0805(value="10uH")
sw   += l1[1]
vout += l1[2]

# --- Output capacitors (VOUT to GND) ---
c4 = C_0805(value="22uF")
c5 = C_0805(value="22uF")
vout += c4[1], c5[1]
gnd  += c4[2], c5[2]

# --- Feedback divider for 5V ---
# Rtop=100k (VOUT->FB), Rbot=13.3k (FB->GND)
r1 = R_0805(value="100k")
r2 = R_0805(value="13.3k")
vout += r1[1]
fb   += r1[2], r2[1]
gnd  += r2[2]

# --- EN divider (datasheet style): R4=511k VIN->EN, R5=105k EN->GND ---
r4 = R_0805(value="511k")
r5 = R_0805(value="105k")
vin += r4[1]
en  += r4[2], r5[1]
gnd += r5[2]

# --- Wire IC pins by number ---
gnd  += u1[1]
sw   += u1[2]
vin  += u1[3]
fb   += u1[4]
en   += u1[5]
boot += u1[6]

ERC()

