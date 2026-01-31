from skidl import *

# Task 7: MJISO_DCDC_GATE_SUPPLY
# Isolated DC/DC module: 12V in -> isolated +15V and -15V rails (relative to secondary 0V)

vin    = Net("VIN")        # 12V input rail
pgnd   = Net("PGND")       # primary return
viso_p = Net("VISO+")      # isolated + rail
viso_n = Net("VISO-")      # isolated - rail
iso_0v = Net("ISO_0V")     # secondary reference (0V)

C_0805 = Part("test", "C", TEMPLATE, footprint="test:C_0805")

# MGJ2D121505SC pin mapping:
# 1 +VIN, 2 -VIN, 3 -VOUT, 4 0V, 5 +VOUT
u1 = Part("test", "MGJ2D121505SC", footprint="test:MGJ2D121505SC")

# Primary connections
vin  += u1[1]     # +VIN
pgnd += u1[2]     # -VIN

# Primary decoupling: 4.7uF + 100nF
c1 = C_0805(value="4.7uF")
c2 = C_0805(value="100nF")
vin  += c1[1], c2[1]
pgnd += c1[2], c2[2]

# Secondary connections
viso_n += u1[5]   # -VOUT
iso_0v += u1[6]   # 0V
viso_p += u1[7]   # +VOUT

# Secondary decoupling requirements:
# - VISO+ to ISO_0V: 10uF + 100nF
# - ISO_0V to VISO-: 10uF + 100nF
# - VISO+ to VISO-: 1uF

# VISO+ -> ISO_0V
c3 = C_0805(value="10uF")
c4 = C_0805(value="100nF")
viso_p += c3[1], c4[1]
iso_0v += c3[2], c4[2]

# ISO_0V -> VISO-
c5 = C_0805(value="10uF")
c6 = C_0805(value="100nF")
iso_0v += c5[1], c6[1]
viso_n += c5[2], c6[2]

# VISO+ -> VISO- (cross-rail cap)
c7 = C_0805(value="1uF")
viso_p += c7[1]
viso_n += c7[2]

ERC()

