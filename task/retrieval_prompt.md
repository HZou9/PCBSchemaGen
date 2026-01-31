# PCBSchemaCoder Retrieval Prompt (Two-Stage - Stage 1)

You are performing **Stage 1: Sub-circuit Retrieval/Selection** (for subsequent Stage 2 SKiDL generation).

Given the target task description, select **as few as possible** but **sufficient to cover the task** verified sub-circuits (SubModules) from the table below.

## Output Format (Strict)
- Output only a Python list (elements are integer IDs), e.g., `[6, 14, 10]`
- Do not output any additional text

## Selection Rules
- Prefer higher-level sub-modules (e.g., Driver / PowerStage) to reduce combination complexity.
- If the task itself corresponds to a SubModule with a specific Id and you see the hint `NO_DIRECT_REUSE`, do not select that same Id.
- If no suitable sub-module can be reused, output `[]`.

## Available SubModule Index (Benchmark 1–23)

| Id | Level | Type | SubModuleName | InputNodes | OutputNodes | Components |
|---:|---|---|---|---|---|---|
| 1 | Easy | Sensing | VDIV_BUS_SENSE | VIN | VSENSE | Resistors |
| 2 | Easy | Sensing | ISO_AMP_HV_SENSE | VIN | OUTP, OUTN | AMC1350 |
| 3 | Easy | Sensing | DIFF2SE_VREF | VINP, VINN, VREF | VOUT | OPA328 |
| 4 | Easy | Sensing | ISENSE_HALL_ISO | LINE_IN | ISNS_ISO | ACS37010 |
| 5 | Easy | AuxPower | LDO_AUX_LOGIC | VIN | VOUT | TLV1117-33 |
| 6 | Easy | AuxPower | BUCK_AUX_LOGIC | VIN | VOUT | TPS54302 |
| 7 | Medium | AuxPower | MJISO_DCDC_GATE_SUPPLY | VIN | VISO+, VISO- | MGJ2D121505 |
| 8 | Medium | PowerStage | HB_TO2473_STAGE | VBUS+, GATE_H, GATE_L | VSW | IMW65R015M2H |
| 9 | Medium | PowerStage | HB_TO2474K_SIC_STAGE | VBUS+, GATE_H, GATE_L | VSW, KELVIN | IMZA65R015M2H |
| 10 | Medium | PowerStage | HB_TOLL_STAGE | VBUS+, GATE_H, GATE_L | VSW, KELVIN | IMT65R033M2H |
| 11 | Medium | PowerStage | HB_TOLT_TOPCOOL_STAGE | VBUS+, GATE_H, GATE_L | VSW, KELVIN | IMLT65R015M2H |
| 12 | Medium | PowerStage | HB_QFN_INTEGRATED_STAGE | VBUS+, GATE_H, GATE_L | VSW | BSC052N08NS5 |
| 13 | Medium | Driver | DRV_LOW_SIDE | PWM, VCC | GATE | UCC27511 |
| 14 | Medium | Driver | DRV_BOOTSTRAP_HB | PWM_H, PWM_L, VCC | HO, LO, VB, VS | UCC27211 |
| 15 | Medium | Driver | DRV_ISOLATED_GATE | PWM, VCC1, VCC2, VEE2 | OUT | UCC5390E |
| 16 | Medium | Driver | DRV_PROTECTED_DESAT | PWM, VCC, EN/FLT, VDD, VEE | OUT, FLT, DESAT, CLAMP | UCC21710 |
| 17 | Hard | DC-DC | CONV_BUCK_SYNC | VIN, PWM_H, PWM_L | VOUT | IMZA65R015M2H |
| 18 | Hard | DC-DC | CONV_BOOST_SYNC | VIN, PWM_H, PWM_L | VOUT | IMZA65R015M2H |
| 19 | Hard | DC-DC | CONV_4SW_BUCKBOOST | VIN, PWM_1_H, PWM_1_L, PWM_2_H, PWM_2_L | VOUT | IMZA65R015M2H |
| 20 | Hard | DC-DC | CONV_DAB_ISOLATED | VIN, PWM_PRI_H, PWM_PRI_L, PWM_SEC_H, PWM_SEC_L | VSW_1, VSW_2 | IMZA65R015M2H |
| 21 | Hard | DC-DC | CONV_LLC_RESONANT | VIN, PWM_H, PWM_L | VSW_1, VSW_2 | IMZA65R015M2H |
| 22 | Hard | DC-AC | DRIVE_3PH_MOTOR | VIN, PWM_1_H, PWM_1_L, PWM_2_H, PWM_2_L, PWM_3_H, PWM_3_L | VSW_1, VSW_2, VSW_3 | IMZA65R015M2H |
| 23 | Hard | DC-AC | INV_GRID_1PH | VIN, GRID_L, GRID_N, PWM_1_H, PWM_1_L, PWM_2_H, PWM_2_L | VSW_1, VSW_2 | IMZA65R015M2H |

## Task Input

[TASK]

