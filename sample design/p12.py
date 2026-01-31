from skidl import *

# Task 12: HB_QFN_INTEGRATED_STAGE (Refactored)
# Structure: VBUS -> Q1 -> VSW -> Q2 -> PGND
# TDSON-8: No separate Kelvin Source pin usually. Shared Source. No Shunt.

# 1. Define Nets
vbus  = Net("VBUS+")
pgnd  = Net("PGND")
vsw   = Net("VSW")
pwm_h = Net("PWM_H")
pwm_l = Net("PWM_L")

# 2. Decoupling Capacitors
caps = []
for i in range(8):
    c = Part("test", "C", value="100nF", footprint="test:C_0805")
    c[1] += vbus
    c[2] += pgnd
    caps.append(c)

# 3. MOSFETs (BSC052N08NS5 TDSON-8: S=1-3, G=4, D=5-9)
q1 = Part("test", "BSC052N08NS5", footprint="test:BSC052N08NS5", ref="Q1")
q2 = Part("test", "BSC052N08NS5", footprint="test:BSC052N08NS5", ref="Q2")

# 4. Connections

# High-Side (Q1)
# Drain -> VBUS+
for p in range(5, 10):
    q1[p] += vbus
# Source -> VSW
for p in range(1, 4):
    q1[p] += vsw
# Gate
q1[4] += pwm_h

# Low-Side (Q2)
# Drain -> VSW
for p in range(5, 10):
    q2[p] += vsw
# Source -> PGND
for p in range(1, 4):
    q2[p] += pgnd
# Gate
q2[4] += pwm_l

ERC()
