from skidl import *

# Task 11: HB_TOLT_TOPCOOL_STAGE (Refactored)
# Structure: VBUS -> Q1 -> VSW -> Q2 -> PGND
# TOLT Package: Top-side cooling. Kelvin Source exposed. No Shunt.

# 1. Define Nets
vbus   = Net("VBUS+")
pgnd   = Net("PGND")
vsw    = Net("VSW")
pwm_h  = Net("PWM_H")
pwm_l  = Net("PWM_L")
ks_h   = Net("KS_H")
ks_l   = Net("KS_L")

# 2. Decoupling Capacitors
caps = []
for i in range(8):
    c = Part("test", "C", value="100nF", footprint="test:C_0805")
    c[1] += vbus
    c[2] += pgnd
    caps.append(c)

# 3. MOSFETs (TOLT: S=1-6, KS=7, G=8, D=9-16)
q1 = Part("test", "IMLT65R015M2H", footprint="test:IMLT65R015M2H", ref="Q1")
q2 = Part("test", "IMLT65R015M2H", footprint="test:IMLT65R015M2H", ref="Q2")

# 4. Connections

# High-Side (Q1)
# Drain -> VBUS+
for p in range(9, 17):
    q1[p] += vbus
# Source -> VSW
for p in range(1, 7):
    q1[p] += vsw
# Gate & KS
q1[8] += pwm_h
q1[7] += ks_h

# Low-Side (Q2)
# Drain -> VSW
for p in range(9, 17):
    q2[p] += vsw
# Source -> PGND
for p in range(1, 7):
    q2[p] += pgnd
# Gate & KS
q2[8] += pwm_l
q2[7] += ks_l

ERC()
