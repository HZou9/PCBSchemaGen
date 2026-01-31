from skidl import *

pwm_in = Net("PWM_IN")
vcc    = Net("VCC")
gate   = Net("GATE")
pgnd   = Net("PGND")

R_0805 = Part("test", "R", TEMPLATE, footprint="test:R_0805")
C_0805 = Part("test", "C", TEMPLATE, footprint="test:C_0805")

u1 = Part("test", "UCC27511", footprint="test:UCC27511_SOIC6")
# 1 VDD, 2 OUTH, 3 OUTL, 4 GND, 5 IN-, 6 IN+

vcc  += u1[1]
pgnd += u1[4]
pwm_in += u1[6]
pgnd   += u1[5]

# VCC decoupling
c1 = C_0805(value='100nF')
c2 = C_0805(value='1uF')
vcc  += c1[1], c2[1]
pgnd += c1[2], c2[2]

r1 = R_0805(value='4.7')
r2 = R_0805(value='2.2')
u1[2] += r1[1]; gate += r1[2]
u1[3] += r2[1]; gate += r2[2]

ERC()

