from skidl import *

# Task 1: VDIV_BUS_SENSE
# VIN = 60.0 V, VSENSE = 3.3 V

vin = Net("VIN")
vsense = Net("VSENSE")
gnd = Net("GND")

r1 = Part("test", "R", value="953k", footprint="test:R_0805")
r2 = Part("test", "R", value="56.0k", footprint="test:R_0805")

# optional: place a capacitor across the sensing resistor for noise cancelling
c1 = Part("test", "C", value="10nF", footprint="test:C_0805")

vin += r1[1]
vsense += r1[2], r2[1], c1[1]
gnd += r2[2], c1[2]

ERC()
# generate_graph(file_="p1.dot", engine="dot")
