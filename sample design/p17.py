from skidl import *

# Task 17: CONV_BUCK_SYNC - Synchronous Buck Converter
# Complete Power Stage Structure:
#   VIN -> Input Caps -> Q1(HS) -> VSW -> L_buck -> VOUT -> Output Caps -> GND
#                             -> Q2(LS) -> PGND
#
# Features:
# - IMZA65R015M2H MOSFETs with Kelvin Source
# - UCC5390E isolated gate drivers (one per MOSFET)
# - MGJ2D121505SC isolated supplies (one per gate driver)
# - Separate turn-on/turn-off gate resistors
# - Buck inductor (Inductor_power)
# - Input and output decoupling capacitors

# ==============================================================================
# 1. Define Nets
# ==============================================================================

# Primary side (common)
vcc_pri = Net("VCC_PRI")       # 12V primary supply
gnd_pri = Net("GND_PRI")       # Primary ground
pwm_h   = Net("PWM_H")         # High-side PWM input
pwm_l   = Net("PWM_L")         # Low-side PWM input

# Power stage
vbus    = Net("VBUS")          # High voltage bus input
vsw     = Net("VSW")           # Switch node (between MOSFETs and inductor)
vout    = Net("VOUT")          # Output voltage (after inductor)
pgnd    = Net("PGND")          # Power ground

# High-side secondary domain (isolated from primary and low-side)
vdd_hs  = Net("VDD_HS")        # +15V for HS gate driver
vee_hs  = Net("VEE_HS")        # -5V for HS gate driver
com_hs  = Net("COM_HS")        # 0V reference for HS (connects to Q1 KS)
gate_h  = Net("GATE_H")        # HS gate net

# Low-side secondary domain
vdd_ls  = Net("VDD_LS")        # +15V for LS gate driver
vee_ls  = Net("VEE_LS")        # -5V for LS gate driver
com_ls  = Net("COM_LS")        # 0V reference for LS (connects to Q2 KS)
gate_l  = Net("GATE_L")        # LS gate net

# Gate driver output nets (before gate resistors)
gdrv_out_h = Net("GDRV_OUT_H")
gdrv_out_l = Net("GDRV_OUT_L")

# ==============================================================================
# 2. Component Templates
# ==============================================================================

R_0805 = Part("test", "R", TEMPLATE, footprint="test:R_0805")
C_0805 = Part("test", "C", TEMPLATE, footprint="test:C_0805")
D_SMA  = Part("test", "D", TEMPLATE, footprint="test:D_SMA")

# ==============================================================================
# 3. Input Decoupling Capacitors (VBUS)
# ==============================================================================

# 8x 100nF capacitors on VBUS for high dv/dt applications
for i in range(8):
    c = C_0805(value="100nF")
    c[1] += vbus
    c[2] += pgnd

# ==============================================================================
# 4. High-Side Channel
# ==============================================================================

# 4.1 Isolated DC/DC for HS gate driver
iso_hs = Part("test", "MGJ2D121505SC", footprint="test:MGJ2D121505SC", ref="U_ISO_HS")
iso_hs[1] += vcc_pri      # +VIN (primary 12V)
iso_hs[2] += gnd_pri      # -VIN (primary GND)
iso_hs[7] += vdd_hs       # +VOUT (+15V)
iso_hs[6] += com_hs       # 0V
iso_hs[5] += vee_hs       # -VOUT (-5V)

# Primary side decoupling for ISO supply HS
c_iso_hs_pri = C_0805(value="100nF")
c_iso_hs_pri[1] += vcc_pri
c_iso_hs_pri[2] += gnd_pri

# Secondary side decoupling for ISO supply HS
c_iso_hs_sec1 = C_0805(value="100nF")  # VDD to COM
c_iso_hs_sec1[1] += vdd_hs
c_iso_hs_sec1[2] += com_hs

c_iso_hs_sec2 = C_0805(value="100nF")  # COM to VEE
c_iso_hs_sec2[1] += com_hs
c_iso_hs_sec2[2] += vee_hs

c_iso_hs_sec3 = C_0805(value="1uF")    # VDD to VEE
c_iso_hs_sec3[1] += vdd_hs
c_iso_hs_sec3[2] += vee_hs

# 4.2 Gate driver for HS (UCC5390E)
gdrv_hs = Part("test", "UCC5390E", footprint="test:UCC5390E", ref="U_GDRV_HS")

# Primary side connections
gdrv_hs[1] += vcc_pri     # VCC1
gdrv_hs[2] += pwm_h       # IN+
gdrv_hs[3] += gnd_pri     # IN-
gdrv_hs[4] += gnd_pri     # GND1

# Secondary side connections
gdrv_hs[5] += vdd_hs      # VCC2 (+15V)
gdrv_hs[6] += gdrv_out_h  # OUT (to gate resistor network)
gdrv_hs[7] += com_hs      # GND2 (to Kelvin Source)
gdrv_hs[8] += vee_hs      # VEE2 (-5V)

# Primary side decoupling for gate driver HS
c_gdrv_hs_pri = C_0805(value="100nF")
c_gdrv_hs_pri[1] += vcc_pri
c_gdrv_hs_pri[2] += gnd_pri

# Secondary side decoupling for gate driver HS
c_gdrv_hs_sec = C_0805(value="100nF")
c_gdrv_hs_sec[1] += vdd_hs
c_gdrv_hs_sec[2] += com_hs

# 4.3 Gate resistor network for HS (separate Rg_on and Rg_off)
# Turn-on path: OUT -> Rg_on -> GATE
rg_on_hs = R_0805(value="10")
rg_on_hs[1] += gdrv_out_h
rg_on_hs[2] += gate_h

# Turn-off path: OUT <- D_off <- Rg_off <- GATE
# Diode cathode to OUT, anode to resistor, resistor to GATE
d_off_hs = D_SMA()
rg_off_hs = R_0805(value="4.7")
d_off_hs["K"] += gdrv_out_h
d_off_hs["A"] += rg_off_hs[1]
rg_off_hs[2] += gate_h

# 4.4 High-side MOSFET (Q1)
q1 = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H", ref="Q1")
q1[1] += vbus             # Drain to VBUS
q1[2] += vsw              # Source to VSW (switch node)
q1[3] += com_hs           # Kelvin Source to gate driver GND2
q1[4] += gate_h           # Gate

# ==============================================================================
# 5. Low-Side Channel
# ==============================================================================

# 5.1 Isolated DC/DC for LS gate driver
iso_ls = Part("test", "MGJ2D121505SC", footprint="test:MGJ2D121505SC", ref="U_ISO_LS")
iso_ls[1] += vcc_pri      # +VIN (primary 12V)
iso_ls[2] += gnd_pri      # -VIN (primary GND)
iso_ls[7] += vdd_ls       # +VOUT (+15V)
iso_ls[6] += com_ls       # 0V
iso_ls[5] += vee_ls       # -VOUT (-5V)

# Primary side decoupling for ISO supply LS
c_iso_ls_pri = C_0805(value="100nF")
c_iso_ls_pri[1] += vcc_pri
c_iso_ls_pri[2] += gnd_pri

# Secondary side decoupling for ISO supply LS
c_iso_ls_sec1 = C_0805(value="100nF")  # VDD to COM
c_iso_ls_sec1[1] += vdd_ls
c_iso_ls_sec1[2] += com_ls

c_iso_ls_sec2 = C_0805(value="100nF")  # COM to VEE
c_iso_ls_sec2[1] += com_ls
c_iso_ls_sec2[2] += vee_ls

c_iso_ls_sec3 = C_0805(value="1uF")    # VDD to VEE
c_iso_ls_sec3[1] += vdd_ls
c_iso_ls_sec3[2] += vee_ls

# 5.2 Gate driver for LS (UCC5390E)
gdrv_ls = Part("test", "UCC5390E", footprint="test:UCC5390E", ref="U_GDRV_LS")

# Primary side connections
gdrv_ls[1] += vcc_pri     # VCC1
gdrv_ls[2] += pwm_l       # IN+
gdrv_ls[3] += gnd_pri     # IN-
gdrv_ls[4] += gnd_pri     # GND1

# Secondary side connections
gdrv_ls[5] += vdd_ls      # VCC2 (+15V)
gdrv_ls[6] += gdrv_out_l  # OUT (to gate resistor network)
gdrv_ls[7] += com_ls      # GND2 (to Kelvin Source)
gdrv_ls[8] += vee_ls      # VEE2 (-5V)

# Primary side decoupling for gate driver LS
c_gdrv_ls_pri = C_0805(value="100nF")
c_gdrv_ls_pri[1] += vcc_pri
c_gdrv_ls_pri[2] += gnd_pri

# Secondary side decoupling for gate driver LS
c_gdrv_ls_sec = C_0805(value="100nF")
c_gdrv_ls_sec[1] += vdd_ls
c_gdrv_ls_sec[2] += com_ls

# 5.3 Gate resistor network for LS (separate Rg_on and Rg_off)
# Turn-on path: OUT -> Rg_on -> GATE
rg_on_ls = R_0805(value="10")
rg_on_ls[1] += gdrv_out_l
rg_on_ls[2] += gate_l

# Turn-off path: OUT <- D_off <- Rg_off <- GATE
d_off_ls = D_SMA()
rg_off_ls = R_0805(value="4.7")
d_off_ls["K"] += gdrv_out_l
d_off_ls["A"] += rg_off_ls[1]
rg_off_ls[2] += gate_l

# 5.4 Low-side MOSFET (Q2)
q2 = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H", ref="Q2")
q2[1] += vsw              # Drain to VSW (switch node)
q2[2] += pgnd             # Source to power ground
q2[3] += com_ls           # Kelvin Source to gate driver GND2
q2[4] += gate_l           # Gate

# ==============================================================================
# 6. Buck Inductor
# ==============================================================================

# Inductor_power: pins 1-6 are Terminal A (same net), pins 7-12 are Terminal B (same net)
l_buck = Part("test", "Inductor_power", footprint="test:Inductor_power", ref="L1")

# Terminal A (pins 1-6) -> VSW (switch node)
for p in range(1, 7):
    l_buck[p] += vsw

# Terminal B (pins 7-12) -> VOUT
for p in range(7, 13):
    l_buck[p] += vout

# ==============================================================================
# 7. Output Decoupling Capacitors (VOUT)
# ==============================================================================

# 8x 100nF capacitors on VOUT for output filtering
for i in range(8):
    c = C_0805(value="100nF")
    c[1] += vout
    c[2] += pgnd

# 2x 10uF bulk capacitors on VOUT
for i in range(2):
    c = C_0805(value="10uF")
    c[1] += vout
    c[2] += pgnd

ERC()
