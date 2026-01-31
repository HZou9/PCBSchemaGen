from skidl import *

# Task 8: HB_TO2473_STAGE (Refactored)
# Structure: VBUS -> Q1 -> VSW -> Q2 -> PGND
# No Shunt. 8x Decoupling Caps.

# 1. Define Nets
vbus  = Net("VBUS+")
pgnd  = Net("PGND")
vsw   = Net("VSW")
pwm_h = Net("PWM_H")
pwm_l = Net("PWM_L")

# 2. Decoupling Capacitors (8x 100nF parallel)
caps = []
for i in range(8):
    c = Part("test", "C", value="100nF", footprint="test:C_0805")
    c[1] += vbus
    c[2] += pgnd
    caps.append(c)

# 3. MOSFETs (TO-247-3: 1=G, 2=D, 3=S)
# Strictly instantiate 2 parts
q1 = Part("test", "IMW65R015M2H", footprint="test:IMW65R015M2H", ref="Q1")
q2 = Part("test", "IMW65R015M2H", footprint="test:IMW65R015M2H", ref="Q2")

# 4. Connections

# High-Side (Q1)
q1[2] += vbus   # Drain
q1[3] += vsw    # Source
q1[1] += pwm_h  # Gate

# Low-Side (Q2)
q2[2] += vsw    # Drain
q2[3] += pgnd   # Source (Direct to PGND)
q2[1] += pwm_l  # Gate

ERC()
