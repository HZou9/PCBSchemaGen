from skidl import *

# Task 14: DRV_BOOTSTRAP_HB
# UCC27211 (SOIC-8) pin map (corrected):
# 1 VDD, 2 HB, 3 HO, 4 HS, 5 HI, 6 LI, 7 VSS, 8 LO

pwm_h = Net("PWM_H")
pwm_l = Net("PWM_L")
vcc   = Net("VCC")       # 12V
pgnd  = Net("PGND")

ho = Net("HO")
lo = Net("LO")
vb = Net("VB")           # export HB node
vs = Net("VS")           # export HS node

R_0805 = Part("test", "R", TEMPLATE, footprint="test:R_0805")
C_0805 = Part("test", "C", TEMPLATE, footprint="test:C_0805")

u1 = Part("test", "UCC27211", footprint="test:UCC27211")

# Power
vcc  += u1[1]   # VDD
pgnd += u1[7]   # VSS

# VDD decoupling: 4.7uF + 100nF
c1 = C_0805(value="4.7uF")
c2 = C_0805(value="100nF")
vcc  += c1[1], c2[1]
pgnd += c1[2], c2[2]

# Switch node
vs += u1[4]     # HS

# Bootstrap node
vb += u1[2]     # HB

# Bootstrap capacitor only (internal diode assumed): HB <-> HS
c3 = C_0805(value="220nF")
vb += c3[1]
vs += c3[2]

# Inputs (series resistors optional but recommended for robustness)
r1 = R_0805(value="100")
r2 = R_0805(value="100")

pwm_h += r1[1]
u1[5] += r1[2]   # HI

pwm_l += r2[1]
u1[6] += r2[2]   # LI

# Outputs with small gate resistors (simple, keeps task bounded)
r3 = R_0805(value="1")
r4 = R_0805(value="1")

u1[3] += r3[1]   # HO
ho    += r3[2]

u1[8] += r4[1]   # LO
lo    += r4[2]

ERC()

