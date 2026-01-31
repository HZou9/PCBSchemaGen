from skidl import *

# --- 1. Global Nets ---
vin = Net("VIN")
vout = Net("VOUT")
vsw = Net("VSW")
pgnd = Net("PGND")
gnd_pri = Net("GND_PRI")
vcc_12v = Net("VCC_12V")  # Primary supply for isolated DC/DCs and drivers
pwm_h = Net("PWM_H")
pwm_l = Net("PWM_L")

# --- 2. MOSFETs (Half-Bridge) ---
# High-side MOSFET
q_h = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H")
q_h[1] += vin       # Drain
q_h[2] += vsw       # Source
# Low-side MOSFET
q_l = Part("test", "IMZA65R015M2H", footprint="test:IMZA65R015M2H")
q_l[1] += vsw       # Drain
q_l[2] += pgnd      # Source

# --- 3. VBUS Decoupling (Mandatory 8 caps) ---
for _ in range(8):
    c_dec = Part("test", "C", value="100nF", footprint="test:C_0805")
    c_dec[1] += vin
    c_dec[2] += pgnd

# --- 4. High-Side Gate Driver Section ---
vdd_hs = Net("VDD_HS")
vee_hs = Net("VEE_HS")
ks_hs = Net("KS_HS")  # Kelvin Source HS
ks_hs += q_h[3]

# Isolated Supply HS
iso_hs = Part("test", "MGJ2D121505SC", footprint="test:MGJ2D121505SC")
iso_hs[1] += vcc_12v
iso_hs[2] += gnd_pri
iso_hs[7] += vdd_hs
iso_hs[6] += ks_hs
iso_hs[5] += vee_hs

# Driver HS
drv_hs = Part("test", "UCC5390E", footprint="test:UCC5390E")
drv_hs[1] += vcc_12v
drv_hs[2] += pwm_h
drv_hs[3] += gnd_pri
drv_hs[4] += gnd_pri
drv_hs[5] += vdd_hs
drv_hs[7] += ks_hs
drv_hs[8] += vee_hs

# Gate Resistor Structure HS
r_gon_hs = Part("test", "R", value="10", footprint="test:R_0805")
r_goff_hs = Part("test", "R", value="4.7", footprint="test:R_0805")
d_hs = Part("test", "D", footprint="test:BAT165") # Anode to Gate, Cathode to Driver

drv_hs[6] += r_gon_hs[1], d_hs[1] # Driver Out
r_gon_hs[2] += q_h[4]            # To Gate
d_hs[2] += r_goff_hs[1]          # Diode cathode to Off resistor
r_goff_hs[2] += q_h[4]           # To Gate

# --- 5. Low-Side Gate Driver Section ---
vdd_ls = Net("VDD_LS")
vee_ls = Net("VEE_LS")
ks_ls = Net("KS_LS")   # Kelvin Source LS
ks_ls += q_l[3]

# Isolated Supply LS
iso_ls = Part("test", "MGJ2D121505SC", footprint="test:MGJ2D121505SC")
iso_ls[1] += vcc_12v
iso_ls[2] += gnd_pri
iso_ls[7] += vdd_ls
iso_ls[6] += ks_ls
iso_ls[5] += vee_ls

# Driver LS
drv_ls = Part("test", "UCC5390E", footprint="test:UCC5390E")
drv_ls[1] += vcc_12v
drv_ls[2] += pwm_l
drv_ls[3] += gnd_pri
drv_ls[4] += gnd_pri
drv_ls[5] += vdd_ls
drv_ls[7] += ks_ls
drv_ls[8] += vee_ls

# Gate Resistor Structure LS
r_gon_ls = Part("test", "R", value="10", footprint="test:R_0805")
r_goff_ls = Part("test", "R", value="4.7", footprint="test:R_0805")
d_ls = Part("test", "D", footprint="test:BAT165")

drv_ls[6] += r_gon_ls[1], d_ls[1]
r_gon_ls[2] += q_l[4]
d_ls[2] += r_goff_ls[1]
r_goff_ls[2] += q_l[4]

# --- 6. Output Filter ---
l_out = Part("test", "Inductor_power", footprint="test:Inductor_power")
l_out[1, 2, 3, 4, 5, 6] += vsw
l_out[7, 8, 9, 10, 11, 12] += vout

# Output Capacitors
for _ in range(4):
    c_out = Part("test", "C", value="22uF", footprint="test:C_0805")
    c_out[1] += vout
    c_out[2] += pgnd

# --- 7. Driver Decoupling ---
# HS Driver Decoupling
c_hs_vcc1 = Part("test", "C", value="100nF", footprint="test:C_0805")
c_hs_vcc1[1] += vcc_12v
c_hs_vcc1[2] += gnd_pri

c_hs_vcc2 = Part("test", "C", value="1uF", footprint="test:C_0805")
c_hs_vcc2[1] += vdd_hs
c_hs_vcc2[2] += ks_hs

# LS Driver Decoupling
c_ls_vcc1 = Part("test", "C", value="100nF", footprint="test:C_0805")
c_ls_vcc1[1] += vcc_12v
c_ls_vcc1[2] += gnd_pri

c_ls_vcc2 = Part("test", "C", value="1uF", footprint="test:C_0805")
c_ls_vcc2[1] += vdd_ls
c_ls_vcc2[2] += ks_ls

ERC()
