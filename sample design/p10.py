from skidl import *

# Task 10: HB_TOLL_STAGE (Refactored)
# Structure: VBUS -> Q1 -> VSW -> Q2 -> PGND
# TOLL Package: Parallel pins handled. Kelvin Source exposed. No Shunt.

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

# 3. MOSFETs (TOLL: G=1, KS=2, S=3-9, D=10-12)
q1 = Part("test", "IMT65R033M2H", footprint="test:IMT65R033M2H", ref="Q1")
q2 = Part("test", "IMT65R033M2H", footprint="test:IMT65R033M2H", ref="Q2")

# 4. Connections

# High-Side (Q1)
# Drain -> VBUS+
for p in range(10, 13):
    q1[p] += vbus
# Source -> VSW
for p in range(3, 10):
    q1[p] += vsw
# Gate & KS
q1[1] += pwm_h
q1[2] += ks_h

# Low-Side (Q2)
# Drain -> VSW
for p in range(10, 13):
    q2[p] += vsw
# Source -> PGND (Direct)
for p in range(3, 10):
    q2[p] += pgnd
# Gate & KS
q2[1] += pwm_l
q2[2] += ks_l

ERC()
