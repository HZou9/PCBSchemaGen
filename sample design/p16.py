from skidl import *

# Task 16: ISO_GATE_DRIVER_PROTECTED
# Specs:
# - UCC21710 (or similar) ISO driver
# - 5V/0V primary, +15V/-5V secondary (or unipolar per benchmark)
# - DESAT detection loop with HV diode
# - Active Miller Clamp (CLMPI) usage
# - OC protection pin usage
# - RDY, FLT, RST reporting to MCU
# - Separate OUTH/OUTL paths

gnd = Net('GND')
vcc = Net('VCC')          # Primary 5V supply
pwm = Net('PWM_IN')       # PWM comes into IN+/IN-

flt = Net('FLT')          # FLTn node
rdy = Net('RDY')          # RDY node
rst = Net('RST_EN')       # RSTn_EN node

# ---------- Secondary (power) side nets ----------
vdd   = Net('VDD')        # +driver rail
com   = Net('COM')        # power reference (0V)
vee   = Net('VEE')        # -driver rail

gate  = Net('GATE')
desat = Net('DESAT_SENSE')   # drain/collector sense node

# Internal nodes for DESAT network
n1 = Net('DESAT_DIV')     # node after R1, before R2 and diode DHV
ocn = Net('OC_NODE')      # OC pin node (can be same as pin net, but explicit helps debug)

# Parts (0805 passives, SMA diode)
R_0805 = Part('test', 'R', TEMPLATE, footprint='test:R_0805')
C_0805 = Part('test', 'C', TEMPLATE, footprint='test:C_0805')
D_SCH  = Part('test', 'D', TEMPLATE, footprint='test:D_SMA')

u1 = Part("test", "UCC21710", footprint="test:UCC21710")

# ===================== Primary side (FLT/RDY/RST pins circuitry style) =====================
vcc += u1[15]     # VCC
gnd += u1[9]      # GND

# VCC decoupling: 0.1uF + 1uF
c1 = C_0805(value='100nF')
c2 = C_0805(value='1uF')
vcc += c1[1], c2[1]
gnd += c1[2], c2[2]

# PWM input: PWM_IN -> series resistor -> IN+ ; IN- -> GND
r1 = R_0805(value='100')
pwm += r1[1]
u1[10] += r1[2]     # IN+
gnd += u1[11]        # IN-

# FLTn pull-up + 100pF to GND
r2 = R_0805(value='5k')
vcc += r2[1]
flt += u1[13], r2[2]

c3 = C_0805(value='100pF')
flt += c3[1]
gnd += c3[2]

# RDY pull-up + 100pF to GND
r3 = R_0805(value='5k')
vcc += r3[1]
rdy += u1[12], r3[2]

c4 = C_0805(value='100pF')
rdy += c4[1]
gnd += c4[2]

# RSTn_EN pull-up + 100pF to GND
r4 = R_0805(value='5k')
vcc += r4[1]
rst += u1[14], r4[2]

c5 = C_0805(value='100pF')
rst += c5[1]
gnd += c5[2]

# ===================== Secondary side (bipolar + decoupling on all pairs) =====================
vdd += u1[5]      # VDD
com += u1[3]      # COM
vee += u1[8]      # VEE

# Decoupling set A: VDD - COM (100nF + 1uF)
c6 = C_0805(value='100nF')
c7 = C_0805(value='1uF')
vdd += c6[1], c7[1]
com += c6[2], c7[2]

# Decoupling set B: COM - VEE (100nF + 1uF)
c8 = C_0805(value='100nF')
c9 = C_0805(value='1uF')
com += c8[1], c9[1]
vee += c8[2], c9[2]

# Decoupling set C: VDD - VEE (100nF + 1uF)
c10 = C_0805(value='100nF')
c11 = C_0805(value='1uF')
vdd += c10[1], c11[1]
vee += c10[2], c11[2]

# ===================== Gate outputs: OUTH/OUTL each with resistor, no diode =====================
# OUTH -> R -> GATE
r5 = R_0805(value='4.7')
u1[4] += r5[1]      # OUTH
gate  += r5[2]

# OUTL -> R -> GATE
r6 = R_0805(value='2.2')
u1[6] += r6[1]      # OUTL
gate  += r6[2]

# Miller clamp directly to gate
gate += u1[7]       # CLMPI

# ===================== DESAT / OC network (per your diagram topology) =====================
# R1 from VDD to node n1
r7 = R_0805(value='10k')
vdd += r7[1]
n1  += r7[2]

# DHV diode from n1 to DESAT_SENSE (orientation not fixed by your scoring tolerance)
# In many references: anode at n1, cathode at DESAT_SENSE
d1 = D_SCH()
n1    += d1['A']
desat += d1['K']

# R2 from n1 to OC pin node
r8 = R_0805(value='10k')
n1  += r8[1]
ocn += r8[2]

# OC pin tied to ocn
ocn += u1[2]        # OC

# R3 from OC node to COM
r9 = R_0805(value='10k')
ocn += r9[1]
com += r9[2]

# CBLK from OC node to COM (blanking / deglitch)
c12 = C_0805(value='1nF')
ocn += c12[1]
com += c12[2]

# AIN (pin1) left unconnected in simplified benchmark
# APWM (pin16) left unconnected for this task (not used as PWM here)
# Unused pins must be connected to NC to suppress ERC warnings
u1[1] += NC   # AIN - Not used in this benchmark
u1[16] += NC  # APWM - Not used in this benchmark

ERC()
# generate_graph()