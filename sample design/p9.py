from skidl import *

# Task 9: HB_TO2474K_SIC_STAGE (Refactored)
# Structure: VBUS -> Q1 -> VSW -> Q2 -> PGND
# Kelvin Source pins exposed. No Shunt.

# 1. Define Nets
vbus   = Net("VBUS+")
pgnd   = Net("PGND")
vsw    = Net("VSW")
pwm_h  = Net("PWM_H")
pwm_l  = Net("PWM_L")
ks_h   = Net("KS_H")   # High-Side Kelvin Source
ks_l   = Net("KS_L")   # Low-Side Kelvin Source

# 2. Decoupling Capacitors
caps = []
for i in range(8):
    c = Part("test", "C", value="100nF", footprint="test:C_0805")
    c[1] += vbus
    c[2] += pgnd
    caps.append(c)

# 3. MOSFETs (TO-247-4: 1=D, 2=S, 3=KS, 4=G)
q1 = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H", ref="Q1")
q2 = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H", ref="Q2")

# 4. Connections

# High-Side (Q1)
q1[1] += vbus   # Drain
q1[2] += vsw    # Source (Power)
q1[3] += ks_h   # Kelvin Source
q1[4] += pwm_h  # Gate

# Low-Side (Q2)
q2[1] += vsw    # Drain
q2[2] += pgnd   # Source (Power) -> Direct to PGND
q2[3] += ks_l   # Kelvin Source
q2[4] += pwm_l  # Gate

ERC()
