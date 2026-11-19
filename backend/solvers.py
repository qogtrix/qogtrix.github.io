"""AI Engineering Laboratory — analytical solvers (Stage 6).

Pure Python, stdlib only. These are ANALYTICAL engineering
calculations (closed-form beam theory, 1-D conduction, etc.),
not finite-element or CFD results. Every result carries
"method": "analytical" and its assumptions, so the UI can label
it correctly and never present it as validated FEA.

Units: the API works in SI (metres, newtons, pascals, watts,
kelvin). The browser UI converts from the model's millimetres.

Material properties come from the Stage 4 database. A missing
required property is an ERROR naming the property — never a
silent substitution or a guessed value.
"""
import math

# ---------------------------------------------------------------- solvers
SOLVER_REGISTRY = {
    "cantilever_beam": {
        "label": "Cantilever beam (point load at free end)",
        "method": "analytical",
        "engine": "python-analytical (Euler-Bernoulli beam theory)",
        "status": "available",
        "inputs": ["length_m", "load_N", "section", "material_id"],
        "outputs": ["deflection_m", "slope_rad", "max_stress_Pa",
                    "safety_factor", "bending_moment_Nm"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": [
            "Euler-Bernoulli beam theory (small deflections, linear elasticity)",
            "Point load at the free end; self-weight ignored",
            "Material is homogeneous and isotropic",
        ],
    },
    "simply_supported_beam": {
        "label": "Simply supported beam (centre point load)",
        "method": "analytical",
        "engine": "python-analytical (Euler-Bernoulli beam theory)",
        "status": "available",
        "inputs": ["length_m", "load_N", "section", "material_id"],
        "outputs": ["deflection_m", "max_stress_Pa", "safety_factor",
                    "bending_moment_Nm"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": [
            "Euler-Bernoulli beam theory (small deflections, linear elasticity)",
            "Point load at mid-span; self-weight ignored",
        ],
    },
    "axial_bar": {
        "label": "Axial bar (tension / compression)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["length_m", "force_N", "section", "material_id"],
        "outputs": ["stress_Pa", "strain", "elongation_m", "safety_factor"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": ["Uniform axial stress; linear elasticity"],
    },
    "torsion_shaft": {
        "label": "Torsion of a circular shaft",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["length_m", "torque_Nm", "diameter_m", "material_id"],
        "outputs": ["shear_stress_Pa", "angle_rad", "safety_factor"],
        "requires": ["elastic_modulus_gpa", "poisson_ratio",
                     "yield_strength_mpa"],
        "assumptions": [
            "Circular cross-section; linear elasticity",
            "Shear modulus G = E / (2(1+nu))",
            "Yield in shear estimated as yield / sqrt(3) (von Mises)",
        ],
    },
    "thermal_conduction": {
        "label": "Steady 1-D heat conduction through a slab",
        "method": "analytical",
        "engine": "python-analytical (Fourier's law)",
        "status": "available",
        "inputs": ["thickness_m", "area_m2", "t_hot_C", "t_cold_C",
                   "material_id"],
        "outputs": ["heat_flow_W", "thermal_resistance_K_W",
                    "temperature_profile_C"],
        "requires": ["thermal_conductivity_w_mk"],
        "assumptions": [
            "Steady state, one-dimensional conduction, constant k",
            "No heat generation inside the slab",
        ],
    },
    "lumped_thermal": {
        "label": "Lumped-capacitance cooling / heating",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["volume_m3", "area_m2", "h_W_m2K", "t0_C", "t_inf_C",
                   "duration_s", "material_id"],
        "outputs": ["time_constant_s", "temperature_series_C"],
        "requires": ["density_kg_m3", "specific_heat_j_kgk"],
        "assumptions": [
            "Uniform body temperature (Biot number assumed small — "
            "check it for your geometry before trusting the result)",
            "Constant heat-transfer coefficient h",
        ],
    },
    "drag": {
        "label": "Drag and lift (steady flow)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["velocity_m_s", "area_m2", "cd", "cl", "fluid"],
        "outputs": ["drag_N", "lift_N", "reynolds", "dynamic_pressure_Pa"],
        "requires": [],
        "assumptions": [
            "Steady, incompressible flow",
            "Cd / Cl are supplied by the user (not computed here)",
            "Fluid: air (rho 1.225 kg/m3, mu 1.81e-5) or water "
            "(rho 1000, mu 1.0e-3) at ~20 C",
        ],
    },
    "free_fall": {
        "label": "Free fall (analytical kinematics)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["height_m", "mass_kg", "g_m_s2"],
        "outputs": ["fall_time_s", "impact_velocity_m_s",
                    "impact_kinetic_energy_J"],
        "requires": [],
        "assumptions": ["No air resistance; constant gravity"],
    },
    "circuit_dc": {
        "label": "Circuit simulation — DC operating point (MNA)",
        "method": "numerical",
        "engine": "python-mna (Modified Nodal Analysis, own implementation)",
        "status": "available",
        "inputs": ["circuit", "analysis"],
        "outputs": ["voltages", "branch_currents", "power"],
        "requires": [],
        "assumptions": [
            "Modified Nodal Analysis with Newton-Raphson for diodes, BJTs and MOSFETs",
            "BJT is a simplified Ebers-Moll model (active region); MOSFET is Level-1; op-amp is an ideal VCVS",
            "Run through POST /api/v1/circuits/simulate, not the scalar solver endpoint",
        ],
    },
    "circuit_transient": {
        "label": "Circuit simulation — transient (backward Euler)",
        "method": "numerical",
        "engine": "python-mna (Modified Nodal Analysis, own implementation)",
        "status": "available",
        "inputs": ["circuit", "analysis"],
        "outputs": ["t", "voltages", "branch_currents"],
        "requires": [],
        "assumptions": [
            "Backward-Euler time stepping with companion models for capacitors and inductors",
            "Capacitors start uncharged, inductors start with no current",
            "Run through POST /api/v1/circuits/simulate, not the scalar solver endpoint",
        ],
    },
    "circuit_ac": {
        "label": "Circuit simulation — AC frequency sweep (small-signal)",
        "method": "numerical",
        "engine": "python-mna (Modified Nodal Analysis, own implementation)",
        "status": "available",
        "inputs": ["circuit", "analysis"],
        "outputs": ["frequencies_hz", "magnitude_v", "phase_deg"],
        "requires": [],
        "assumptions": [
            "Small-signal analysis: nonlinear devices are linearised at the DC operating point",
            "Run through POST /api/v1/circuits/simulate, not the scalar solver endpoint",
        ],
    },
    "ohm_law": {
        "label": "Ohm's law (V = I x R)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["voltage_V", "current_A", "resistance_ohm"],
        "outputs": ["voltage_V", "current_A", "resistance_ohm", "power_W"],
        "requires": [],
        "assumptions": ["Give exactly two of voltage, current, resistance; the third is solved", "Resistive, DC steady state"],
    },
    "series_parallel": {
        "label": "Series / parallel equivalent (R, C or L)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["kind", "mode", "values"],
        "outputs": ["equivalent"],
        "requires": [],
        "assumptions": ["Resistors and inductors add in series and reciprocate in parallel; capacitors are the other way round"],
    },
    "rc_time_constant": {
        "label": "RC time constant and step response",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["resistance_ohm", "capacitance_F", "voltage_V"],
        "outputs": ["tau_s", "cutoff_hz", "voltage_at_tau_V", "settle_5tau_s"],
        "requires": [],
        "assumptions": ["First-order RC, step input from 0 V, capacitor initially uncharged"],
    },
    "rlc_resonance": {
        "label": "RLC series resonance",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["resistance_ohm", "inductance_H", "capacitance_F"],
        "outputs": ["resonant_freq_hz", "angular_freq_rad_s", "quality_factor", "bandwidth_hz"],
        "requires": [],
        "assumptions": ["Series RLC, ideal components, resonance at minimum impedance"],
    },
    "ac_power": {
        "label": "AC power (P, Q, S, power factor)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["voltage_rms_V", "current_rms_A", "power_factor"],
        "outputs": ["apparent_power_VA", "real_power_W", "reactive_power_var", "phase_angle_deg"],
        "requires": [],
        "assumptions": ["Sinusoidal steady state, single phase, power factor is cos(phi)"],
    },
    "transformer": {
        "label": "Ideal transformer",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["primary_voltage_V", "turns_primary", "turns_secondary", "efficiency", "load_power_W"],
        "outputs": ["secondary_voltage_V", "turns_ratio", "secondary_current_A", "primary_current_A"],
        "requires": [],
        "assumptions": ["Ideal transformer (no losses in the core or windings) except the given efficiency applied to power transfer"],
    },
    "dc_motor": {
        "label": "DC motor (steady state)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["voltage_V", "resistance_ohm", "kt_Nm_per_A", "ke_V_per_rad_s", "load_torque_Nm"],
        "outputs": ["stall_current_A", "stall_torque_Nm", "no_load_speed_rpm", "current_A", "speed_rpm", "power_in_W", "power_out_W", "efficiency"],
        "requires": [],
        "assumptions": ["Steady state, constant field, armature resistance only (no iron or friction losses)", "Torque constant and back-EMF constant are numerically equal in SI but are given separately"],
    },
    "battery_config": {
        "label": "Battery series / parallel configuration",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["cell_voltage_V", "cell_capacity_Ah", "series", "parallel", "load_current_A"],
        "outputs": ["total_voltage_V", "total_capacity_Ah", "energy_Wh", "runtime_h"],
        "requires": [],
        "assumptions": ["Identical cells, no imbalance, capacity is independent of discharge rate (no Peukert effect)"],
    },
    "motor_gearbox": {
        "label": "DC motor driving a gearbox (Stage 7 integration)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["voltage_V", "resistance_ohm", "kt_Nm_per_A", "ke_V_per_rad_s", "load_torque_Nm", "gear_ratio", "gear_efficiency"],
        "outputs": ["motor_speed_rpm", "motor_torque_Nm", "output_speed_rpm", "output_torque_Nm", "power_in_W", "power_out_W", "efficiency"],
        "requires": [],
        "assumptions": ["Steady state DC motor (see dc_motor) driving an ideal gear pair with the given efficiency", "Load torque is the torque demanded at the gearbox output shaft"],
    },
    "solenoid": {
        "label": "Solenoid / coil (inductance and field)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["turns", "length_m", "area_m2", "mu_r", "current_A"],
        "outputs": ["inductance_H", "field_T", "flux_Wb", "energy_J"],
        "requires": [],
        "assumptions": ["Long solenoid (length >> diameter), uniform field, relative permeability given by the user — no permeability is recorded in the material database"],
    },
    "wire_resistance": {
        "label": "Wire / conductor resistance from material data",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["material_id", "length_m", "area_mm2", "current_A"],
        "outputs": ["resistance_ohm", "resistivity_ohm_m", "voltage_drop_V", "power_loss_W"],
        "requires": ["electrical_resistivity_ohm_m"],
        "assumptions": ["Uniform conductor, resistivity at the recorded test conditions (temperature dependence is not modelled)"],
    },
    "rigid_body": {
        "label": "Rigid-body dynamics (Rapier, in the browser)",
        "method": "numerical",
        "engine": "Rapier 0.14.0 (WASM, in-browser)",
        "status": "browser",
        "inputs": ["project_id", "gravity_m_s2", "duration_s",
                   "bodies", "forces", "springs", "joints"],
        "outputs": ["time_series", "final_state", "contacts"],
        "requires": [],
        "assumptions": [
            "Rigid bodies only; collision shapes are bounding boxes "
            "(or ball/cylinder for sphere/cylinder parts)",
            "Fixed timestep 1/60 s; validated against analytical "
            "benchmarks in docs/VALIDATION_STAGE6.md",
        ],
    },
    "gear_train": {
        "label": "Gear train (ratio, speed, torque, tooth forces)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["z1", "z2", "module_mm", "input_speed_rpm",
                   "input_torque_Nm", "efficiency", "pressure_angle_deg"],
        "outputs": ["gear_ratio", "output_speed_rpm", "output_torque_Nm",
                    "power_in_W", "power_out_W", "pitch_diameter_1_m",
                    "pitch_diameter_2_m", "centre_distance_m",
                    "tangential_force_N", "radial_force_N"],
        "requires": [],
        "assumptions": [
            "Spur gears, module in mm, pressure angle 20 deg by default",
            "Efficiency is a single user-supplied number for the mesh",
            "Tooth forces from the input torque and pitch diameter",
        ],
    },
    "shaft_combined": {
        "label": "Shaft under combined bending and torsion",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["diameter_m", "length_m", "torque_Nm",
                   "bending_moment_Nm", "material_id"],
        "outputs": ["bending_stress_Pa", "shear_stress_Pa",
                    "von_mises_stress_Pa", "safety_factor",
                    "angle_of_twist_rad", "deflection_m"],
        "requires": ["elastic_modulus_gpa", "poisson_ratio",
                     "yield_strength_mpa"],
        "assumptions": [
            "Solid circular shaft; linear elasticity",
            "von Mises equivalent stress vs yield strength",
            "Deflection estimated as a simply supported beam with a "
            "centre load equivalent to the given bending moment",
        ],
    },
    "bearing_load": {
        "label": "Bearing load and required dynamic rating",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["radial_load_N", "axial_load_N", "speed_rpm", "life_h"],
        "outputs": ["equivalent_load_N", "life_million_rev",
                    "required_rating_N"],
        "requires": [],
        "assumptions": [
            "Deep-groove ball bearing factors: e = 0.22; "
            "Fa/Fr <= e -> X = 1, Y = 0; otherwise X = 0.56, Y = 1.4",
            "Basic rating life L10 = (C/P)^3 (ball bearings)",
        ],
    },
    "belt_drive": {
        "label": "Open belt drive (length, tensions, ratio)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["d1_m", "d2_m", "centre_m", "input_speed_rpm",
                   "power_W", "mu"],
        "outputs": ["gear_ratio", "output_speed_rpm", "belt_speed_m_s",
                    "belt_length_m", "wrap_angle_rad",
                    "tension_ratio", "tight_tension_N", "slack_tension_N"],
        "requires": [],
        "assumptions": [
            "Open belt (not crossed); capstan equation T1/T2 = e^(mu*beta)",
            "No slip, no belt stretch, no centrifugal tension",
        ],
    },
    "spring_helical": {
        "label": "Helical compression spring",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["wire_d_m", "coil_d_m", "coils", "load_N", "material_id"],
        "outputs": ["spring_rate_N_m", "deflection_m", "shear_stress_Pa",
                    "wahl_factor", "solid_length_m"],
        "requires": ["elastic_modulus_gpa", "poisson_ratio"],
        "assumptions": [
            "Wahl correction factor for curvature and direct shear",
            "Shear modulus G = E / (2(1+nu))",
            "Ends squared and ground assumed for the solid length",
        ],
    },
    "flywheel": {
        "label": "Flywheel (inertia, stored energy, rim stress)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["outer_d_m", "inner_d_m", "thickness_m", "speed_rpm",
                   "material_id"],
        "outputs": ["mass_kg", "inertia_kg_m2", "energy_J",
                    "rim_speed_m_s", "rim_stress_Pa"],
        "requires": ["density_kg_m3"],
        "assumptions": [
            "Annular disc; inertia I = 1/2 m (Ro^2 + Ri^2)",
            "Rim stress approximated as rho * v^2 (thin-rim estimate)",
        ],
    },
    "hydraulic_cylinder": {
        "label": "Hydraulic cylinder (force and speed)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["bore_d_m", "rod_d_m", "pressure_Pa", "flow_m3_s"],
        "outputs": ["extend_force_N", "retract_force_N",
                    "extend_speed_m_s", "retract_speed_m_s"],
        "requires": [],
        "assumptions": ["Ideal cylinder: no friction, no leakage, incompressible fluid"],
    },
    "crank_slider": {
        "label": "Crank-slider kinematics (position, velocity, acceleration)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["crank_r_m", "rod_l_m", "speed_rpm"],
        "outputs": ["stroke_m", "max_velocity_m_s", "max_acceleration_m_s2",
                    "mean_piston_speed_m_s", "series"],
        "requires": [],
        "assumptions": [
            "Rigid crank and rod, constant crank speed, no clearance",
            "Position measured from the crank centre along the cylinder axis",
        ],
    },
    "fatigue_shaft": {
        "label": "Shaft fatigue check (modified Goodman)",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["diameter_m", "bending_moment_Nm", "torque_Nm",
                   "material_id"],
        "outputs": ["alternating_stress_Pa", "mean_stress_Pa",
                    "goodman_safety_factor", "static_safety_factor"],
        "requires": ["tensile_strength_mpa", "fatigue_limit_mpa",
                     "yield_strength_mpa"],
        "assumptions": [
            "Rotating shaft: bending fully reversed, torsion steady",
            "Modified Goodman: 1/SF = sigma_a'/Se + sigma_m'/Sut",
            "Endurance limit taken as recorded; no surface/size factors applied",
        ],
    },
    "vibration_1dof": {
        "label": "Single-degree-of-freedom vibration",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["stiffness_N_m", "mass_kg"],
        "outputs": ["natural_frequency_Hz", "natural_frequency_rad_s",
                    "period_s", "critical_speed_rpm"],
        "requires": [],
        "assumptions": ["Undamped, linear spring-mass system"],
    },
    "power_transmission": {
        "label": "Power from torque and speed",
        "method": "analytical",
        "engine": "python-analytical",
        "status": "available",
        "inputs": ["torque_Nm", "speed_rpm"],
        "outputs": ["angular_velocity_rad_s", "power_W", "power_kW", "power_hp"],
        "requires": [],
        "assumptions": ["Steady rotation; P = T * omega"],
    },
    "fea": {
        "label": "Finite element analysis (CalculiX / Code_Aster)",
        "method": "numerical",
        "engine": "not installed",
        "status": "not_implemented",
        "inputs": [],
        "outputs": [],
        "requires": [],
        "assumptions": [
            "No FEA solver is installed in this environment "
            "(checked 19 Nov 2026: ccx, Code_Aster, OpenFOAM all absent). "
            "The job system accepts FEA jobs and records them as "
            "not_implemented instead of faking results.",
        ],
    },
    "structural_static": {
        "label": "Structural analysis (direct stiffness method)",
        "method": "numerical",
        "engine": "python-dsm (direct stiffness method, own implementation)",
        "status": "available",
        "inputs": ["structure", "combination"],
        "outputs": ["nodes", "elements", "max_displacement_m",
                    "max_utilization", "warnings"],
        "requires": [],
        "assumptions": [
            "Linear elasticity, small deflections (Euler-Bernoulli beam theory)",
            "Runs through POST /api/v1/structures/analyze, not the scalar solver endpoint",
        ],
    },
    "structural_modal": {
        "label": "Structural modal analysis (natural frequencies)",
        "method": "numerical",
        "engine": "python-dsm (consistent mass + Jacobi eigenvalues)",
        "status": "available",
        "inputs": ["structure", "n_modes"],
        "outputs": ["modes"],
        "requires": [],
        "assumptions": [
            "Undamped free vibration; consistent mass matrices",
            "Runs through POST /api/v1/structures/analyze, not the scalar solver endpoint",
        ],
    },
    "structural_buckling": {
        "label": "Member buckling check (Euler / Johnson)",
        "method": "analytical",
        "engine": "python-analytical (Euler column theory)",
        "status": "available",
        "inputs": ["structure"],
        "outputs": ["elements"],
        "requires": [],
        "assumptions": [
            "Per-member Euler/Johnson buckling, not system (eigenvalue) buckling",
            "Runs through POST /api/v1/structures/analyze, not the scalar solver endpoint",
        ],
    },
    "column_buckling": {
        "label": "Column buckling (Euler / Johnson parabola)",
        "method": "analytical",
        "engine": "python-analytical (Euler column theory)",
        "status": "available",
        "inputs": ["length_m", "k_factor", "section", "material_id", "load_N"],
        "outputs": ["critical_load_N", "critical_stress_Pa", "slenderness",
                    "regime", "utilization"],
        "requires": ["elastic_modulus_gpa"],
        "assumptions": [
            "Concentric axial load; prismatic column; pinned-pinned unless k_factor says otherwise",
            "Euler for long columns, Johnson parabola for intermediate columns (uses yield or compressive strength when recorded)",
            "No eccentricity, no initial imperfection, no second-order effects",
        ],
    },
    "fixed_beam": {
        "label": "Fixed-fixed beam (centre point load)",
        "method": "analytical",
        "engine": "python-analytical (Euler-Bernoulli beam theory)",
        "status": "available",
        "inputs": ["length_m", "load_N", "section", "material_id"],
        "outputs": ["deflection_m", "max_stress_Pa", "safety_factor",
                    "end_moment_Nm", "mid_moment_Nm"],
        "requires": ["elastic_modulus_gpa", "yield_strength_mpa"],
        "assumptions": [
            "Euler-Bernoulli beam theory (small deflections, linear elasticity)",
            "Both ends fully fixed; point load at mid-span; self-weight ignored",
        ],
    },
    "natural_frequency_beam": {
        "label": "Beam natural frequency (first mode)",
        "method": "analytical",
        "engine": "python-analytical (Euler-Bernoulli vibration)",
        "status": "available",
        "inputs": ["length_m", "section", "material_id", "support"],
        "outputs": ["frequency_hz", "angular_frequency_rad_s", "period_s"],
        "requires": ["elastic_modulus_gpa", "density_kg_m3"],
        "assumptions": [
            "Uniform prismatic beam; first bending mode only",
            "Support: cantilever (beta*L 1.875), simply supported (pi), fixed-fixed or free-free (4.730)",
            "No damping, no added masses",
        ],
    },
    "wind_load_is875": {
        "label": "Wind load (IS 875 Part 3: 2015 formula)",
        "method": "analytical",
        "engine": "python-analytical (IS 875-3:2015 design wind pressure)",
        "status": "available",
        "inputs": ["basic_wind_speed_m_s", "k1", "k2", "k3", "area_m2",
                   "force_coefficient"],
        "outputs": ["design_wind_speed_m_s", "design_pressure_Pa", "wind_force_N"],
        "requires": [],
        "assumptions": [
            "IS 875 (Part 3): 2015 — Vz = Vb * k1 * k2 * k3; pz = 0.6 * Vz^2",
            "k1 (risk), k2 (terrain/height) and k3 (topography) are supplied by the user from the code tables — the lab does not look them up",
            "Force = pz * area * Cf; this is a pressure calculation, not a full wind design or a code compliance check",
        ],
    },
    "seismic_base_shear_is1893": {
        "label": "Seismic base shear (IS 1893 Part 1: 2016 formula)",
        "method": "analytical",
        "engine": "python-analytical (IS 1893-1:2016 design horizontal seismic coefficient)",
        "status": "available",
        "inputs": ["seismic_weight_N", "zone_factor", "importance_factor",
                   "response_reduction_factor", "sa_g"],
        "outputs": ["design_coefficient", "base_shear_N"],
        "requires": [],
        "assumptions": [
            "IS 1893 (Part 1): 2016 — Ah = (Z/2) * (I/R) * (Sa/g); Vb = Ah * W",
            "Sa/g is supplied by the user from the code response spectrum for the building period and soil type",
            "This is the base-shear formula only, not a full seismic design, ductile detailing or code compliance check",
        ],
    },
    "load_combination": {
        "label": "Factored load combination (IS 800 / IS 456 factor sets)",
        "method": "analytical",
        "engine": "python-analytical (load combination arithmetic)",
        "status": "available",
        "inputs": ["combination", "dead_N", "live_N", "wind_N", "seismic_N",
                   "snow_N", "thermal_N"],
        "outputs": ["factored_total_N", "factors"],
        "requires": [],
        "assumptions": [
            "Combination factors from IS 800:2007 Table 4 / IS 456:2000 (limit state): 1.5(DL+LL), 1.2(DL+LL+WL/EL), 1.5(DL+WL/EL), 0.9DL+1.5WL/EL, 1.5(DL+SL)",
            "Only the arithmetic is computed — choosing the governing combination and checking the design is the engineer's job",
        ],
    },
    "cfd": {
        "label": "Computational fluid dynamics (OpenFOAM)",
        "method": "numerical",
        "engine": "not installed",
        "status": "not_implemented",
        "inputs": [],
        "outputs": [],
        "requires": [],
        "assumptions": [
            "No CFD solver is installed in this environment "
            "(checked 19 Nov 2026). Analytical drag/lift is the "
            "available substitute, labelled as such.",
        ],
    },
}

FLUIDS = {
    "air": {"rho": 1.225, "mu": 1.81e-5, "label": "Air at ~20 C"},
    "water": {"rho": 1000.0, "mu": 1.0e-3, "label": "Water at ~20 C"},
}


def section_properties(section):
    """Return (area_m2, I_m4, J_m4, c_m) for a cross-section dict.
    Section dimensions are in metres."""
    if not isinstance(section, dict):
        raise ValueError("section must be an object")
    t = section.get("type")
    if t == "rectangle":
        b, h = section["b_m"], section["h_m"]
        return b * h, b * h ** 3 / 12, None, h / 2
    if t == "circle":
        d = section["d_m"]
        return (math.pi * d ** 2 / 4, math.pi * d ** 4 / 64,
                math.pi * d ** 4 / 32, d / 2)
    if t == "ibeam":
        h = section["height_m"]
        bf, tf, tw = (section["flange_width_m"],
                      section["flange_thickness_m"], section["web_thickness_m"])
        area = 2 * bf * tf + (h - 2 * tf) * tw
        I = (bf * h ** 3 - (bf - tw) * (h - 2 * tf) ** 3) / 12
        return area, I, None, h / 2
    if t == "box":
        b, h, th = section["b_m"], section["h_m"], section["t_m"]
        area = b * h - (b - 2 * th) * (h - 2 * th)
        I = (b * h ** 3 - (b - 2 * th) * (h - 2 * th) ** 3) / 12
        return area, I, None, h / 2
    raise ValueError(f"unknown section type: {t}")


def _need_number(inputs, key, positive=True):
    v = inputs.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool) \
            or (positive and v <= 0) or (not positive and v < 0):
        raise ValueError(f"{key} must be a {'positive ' if positive else ''}number")
    return float(v)


def _safety_factor(yield_pa, stress_pa):
    if stress_pa == 0:
        return None
    return yield_pa / abs(stress_pa)


def run_solver(solver, inputs, material_props):
    """Run an analytical solver. material_props maps property key ->
    value (or None when the database has no value).
    Returns a results dict. Raises ValueError on bad input or a
    missing required material property — never substitutes one."""
    if solver not in SOLVER_REGISTRY:
        raise ValueError(f"unknown solver: {solver}")
    meta = SOLVER_REGISTRY[solver]
    if meta["status"] == "not_implemented":
        raise ValueError(f"{solver} is not implemented: no solver "
                         "installed in this environment")
    if meta["status"] == "browser":
        raise ValueError("rigid_body runs in the browser workspace, "
                         "not on the backend")
    if solver.startswith("circuit_"):
        raise ValueError("circuit solvers run through "
                         "POST /api/v1/circuits/simulate, not the scalar "
                         "solver endpoint")
    if solver.startswith("structural_"):
        raise ValueError("structural solvers run through "
                         "POST /api/v1/structures/analyze, not the scalar "
                         "solver endpoint")
    # Material requirements.
    props = {}
    for key in meta["requires"]:
        v = (material_props or {}).get(key)
        if v is None:
            raise ValueError(
                f"material property '{key}' is not on record for this "
                "material — refusing to substitute a guessed value")
        props[key] = float(v)

    if solver == "cantilever_beam":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "load_N", positive=False)
        area, I, _J, c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        delta = F * L ** 3 / (3 * E * I)
        slope = F * L ** 2 / (2 * E * I)
        moment = F * L
        stress = moment * c / I
        return {"deflection_m": delta, "slope_rad": slope,
                "bending_moment_Nm": moment, "max_stress_Pa": stress,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area, "second_moment_m4": I}
    if solver == "simply_supported_beam":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "load_N", positive=False)
        area, I, _J, c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        delta = F * L ** 3 / (48 * E * I)
        moment = F * L / 4
        stress = moment * c / I
        return {"deflection_m": delta, "bending_moment_Nm": moment,
                "max_stress_Pa": stress,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area, "second_moment_m4": I}
    if solver == "axial_bar":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "force_N", positive=False)
        area, _I, _J, _c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        stress = F / area
        strain = stress / E
        return {"stress_Pa": stress, "strain": strain,
                "elongation_m": strain * L,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area}
    if solver == "torsion_shaft":
        L = _need_number(inputs, "length_m")
        T = _need_number(inputs, "torque_Nm", positive=False)
        d = _need_number(inputs, "diameter_m")
        E = props["elastic_modulus_gpa"] * 1e9
        nu = props["poisson_ratio"]
        yld = props["yield_strength_mpa"] * 1e6
        G = E / (2 * (1 + nu))
        J = math.pi * d ** 4 / 32
        tau = T * (d / 2) / J
        phi = T * L / (G * J)
        return {"shear_stress_Pa": tau, "angle_rad": phi,
                "shear_modulus_Pa": G,
                "safety_factor": _safety_factor(yld / math.sqrt(3), tau)}
    if solver == "thermal_conduction":
        th = _need_number(inputs, "thickness_m")
        area = _need_number(inputs, "area_m2")
        t_hot = inputs.get("t_hot_C")
        t_cold = inputs.get("t_cold_C")
        if not isinstance(t_hot, (int, float)) or not isinstance(t_cold, (int, float)):
            raise ValueError("t_hot_C and t_cold_C must be numbers")
        k = props["thermal_conductivity_w_mk"]
        R = th / (k * area)
        Q = (t_hot - t_cold) / R
        profile = [{"x_m": th * i / 10,
                    "t_C": t_hot + (t_cold - t_hot) * i / 10}
                   for i in range(11)]
        return {"heat_flow_W": Q, "thermal_resistance_K_W": R,
                "temperature_profile_C": profile}
    if solver == "lumped_thermal":
        vol = _need_number(inputs, "volume_m3")
        area = _need_number(inputs, "area_m2")
        h = _need_number(inputs, "h_W_m2K")
        t0 = inputs.get("t0_C")
        t_inf = inputs.get("t_inf_C")
        dur = _need_number(inputs, "duration_s")
        if not isinstance(t0, (int, float)) or not isinstance(t_inf, (int, float)):
            raise ValueError("t0_C and t_inf_C must be numbers")
        rho = props["density_kg_m3"]
        cp = props["specific_heat_j_kgk"]
        tau = rho * vol * cp / (h * area)
        series = [{"t_s": dur * i / 20,
                   "t_C": t_inf + (t0 - t_inf) * math.exp(-dur * i / 20 / tau)}
                  for i in range(21)]
        return {"time_constant_s": tau, "temperature_series_C": series,
                "final_temperature_C": series[-1]["t_C"]}
    if solver == "drag":
        v = _need_number(inputs, "velocity_m_s", positive=False)
        area = _need_number(inputs, "area_m2")
        cd = inputs.get("cd")
        if not isinstance(cd, (int, float)) or cd < 0:
            raise ValueError("cd must be a number >= 0")
        cl = inputs.get("cl", 0)
        if not isinstance(cl, (int, float)):
            raise ValueError("cl must be a number")
        fluid = FLUIDS.get(inputs.get("fluid", "air"))
        if fluid is None:
            raise ValueError("fluid must be 'air' or 'water'")
        L = inputs.get("length_m", 1.0)
        if not isinstance(L, (int, float)) or isinstance(L, bool) or L <= 0:
            raise ValueError("length_m must be a positive number")
        L = float(L)
        q = 0.5 * fluid["rho"] * v * v
        Re = fluid["rho"] * abs(v) * L / fluid["mu"]
        return {"drag_N": q * cd * area, "lift_N": q * cl * area,
                "dynamic_pressure_Pa": q, "reynolds": Re,
                "fluid": inputs.get("fluid", "air")}
    if solver == "free_fall":
        h = _need_number(inputs, "height_m")
        m = _need_number(inputs, "mass_kg")
        g = inputs.get("g_m_s2", 9.81)
        if not isinstance(g, (int, float)) or g <= 0:
            raise ValueError("g_m_s2 must be a positive number")
        t = math.sqrt(2 * h / g)
        v = g * t
        return {"fall_time_s": t, "impact_velocity_m_s": v,
                "impact_kinetic_energy_J": 0.5 * m * v * v}
    if solver == "gear_train":
        z1 = inputs.get("z1"); z2 = inputs.get("z2")
        if not isinstance(z1, int) or isinstance(z1, bool) or z1 < 6:
            raise ValueError("z1 must be an integer >= 6")
        if not isinstance(z2, int) or isinstance(z2, bool) or z2 < 6:
            raise ValueError("z2 must be an integer >= 6")
        mod = _need_number(inputs, "module_mm") / 1000
        n1 = _need_number(inputs, "input_speed_rpm", positive=False)
        T1 = _need_number(inputs, "input_torque_Nm", positive=False)
        eta = inputs.get("efficiency", 0.95)
        if not isinstance(eta, (int, float)) or not 0 < eta <= 1:
            raise ValueError("efficiency must be in (0, 1]")
        alpha = math.radians(inputs.get("pressure_angle_deg", 20))
        ratio = z2 / z1
        d1, d2 = mod * z1, mod * z2
        n2 = n1 / ratio
        T2 = T1 * ratio * eta
        w1 = n1 * 2 * math.pi / 60
        Ft = 2 * T1 / d1 if d1 else 0
        return {"gear_ratio": ratio, "output_speed_rpm": n2,
                "output_torque_Nm": T2, "power_in_W": T1 * w1,
                "power_out_W": T1 * w1 * eta,
                "pitch_diameter_1_m": d1, "pitch_diameter_2_m": d2,
                "centre_distance_m": (d1 + d2) / 2,
                "tangential_force_N": Ft,
                "radial_force_N": Ft * math.tan(alpha)}
    if solver == "shaft_combined":
        d = _need_number(inputs, "diameter_m")
        L = _need_number(inputs, "length_m")
        T = _need_number(inputs, "torque_Nm", positive=False)
        M = _need_number(inputs, "bending_moment_Nm", positive=False)
        E = props["elastic_modulus_gpa"] * 1e9
        nu = props["poisson_ratio"]
        yld = props["yield_strength_mpa"] * 1e6
        G = E / (2 * (1 + nu))
        sigma = 32 * M / (math.pi * d ** 3)
        tau = 16 * T / (math.pi * d ** 3)
        vm = math.sqrt(sigma ** 2 + 3 * tau ** 2)
        J = math.pi * d ** 4 / 32
        I = math.pi * d ** 4 / 64
        phi = T * L / (G * J)
        F_eq = 4 * M / L  # simply supported centre load giving moment M
        delta = F_eq * L ** 3 / (48 * E * I)
        return {"bending_stress_Pa": sigma, "shear_stress_Pa": tau,
                "von_mises_stress_Pa": vm,
                "safety_factor": _safety_factor(yld, vm),
                "angle_of_twist_rad": phi, "deflection_m": delta}
    if solver == "bearing_load":
        Fr = _need_number(inputs, "radial_load_N", positive=False)
        Fa = _need_number(inputs, "axial_load_N", positive=False)
        n = _need_number(inputs, "speed_rpm", positive=False)
        Lh = _need_number(inputs, "life_h")
        ratio_f = Fa / Fr if Fr else 0
        if ratio_f <= 0.22:
            X, Y = 1.0, 0.0
        else:
            X, Y = 0.56, 1.4
        P = X * Fr + Y * Fa
        L10 = 60 * n * Lh / 1e6
        return {"equivalent_load_N": P, "life_million_rev": L10,
                "required_rating_N": P * L10 ** (1 / 3)}
    if solver == "belt_drive":
        d1 = _need_number(inputs, "d1_m"); d2 = _need_number(inputs, "d2_m")
        C = _need_number(inputs, "centre_m")
        n1 = _need_number(inputs, "input_speed_rpm", positive=False)
        Pwr = _need_number(inputs, "power_W", positive=False)
        mu = inputs.get("mu", 0.3)
        if not isinstance(mu, (int, float)) or mu <= 0:
            raise ValueError("mu must be a positive number")
        ratio = d2 / d1
        v = math.pi * d1 * n1 / 60
        Lb = 2 * C + math.pi / 2 * (d1 + d2) + (d2 - d1) ** 2 / (4 * C)
        beta = math.pi - 2 * math.asin(min(1, (d2 - d1) / (2 * C)))
        tr = math.exp(mu * beta)
        dT = Pwr / v if v else 0
        T1 = dT * tr / (tr - 1) if tr > 1 else dT
        return {"gear_ratio": ratio, "output_speed_rpm": n1 / ratio,
                "belt_speed_m_s": v, "belt_length_m": Lb,
                "wrap_angle_rad": beta, "tension_ratio": tr,
                "tight_tension_N": T1, "slack_tension_N": T1 - dT}
    if solver == "spring_helical":
        dw = _need_number(inputs, "wire_d_m")
        Dc = _need_number(inputs, "coil_d_m")
        n = inputs.get("coils")
        if not isinstance(n, (int, float)) or n < 1:
            raise ValueError("coils must be >= 1")
        F = _need_number(inputs, "load_N", positive=False)
        E = props["elastic_modulus_gpa"] * 1e9
        nu = props["poisson_ratio"]
        G = E / (2 * (1 + nu))
        k = G * dw ** 4 / (8 * Dc ** 3 * n)
        Cidx = Dc / dw
        Kw = (4 * Cidx - 1) / (4 * Cidx - 4) + 0.615 / Cidx
        tau = Kw * 8 * F * Dc / (math.pi * dw ** 3)
        return {"spring_rate_N_m": k, "deflection_m": F / k if k else 0,
                "shear_stress_Pa": tau, "wahl_factor": Kw,
                "solid_length_m": n * dw}
    if solver == "flywheel":
        Do = _need_number(inputs, "outer_d_m")
        Di = inputs.get("inner_d_m", 0) or 0
        if not isinstance(Di, (int, float)) or Di < 0 or Di >= Do:
            raise ValueError("inner_d_m must be >= 0 and smaller than outer_d_m")
        th = _need_number(inputs, "thickness_m")
        n = _need_number(inputs, "speed_rpm", positive=False)
        rho = props["density_kg_m3"]
        mass = rho * math.pi / 4 * (Do ** 2 - Di ** 2) * th
        I = 0.5 * mass * ((Do / 2) ** 2 + (Di / 2) ** 2)
        w = n * 2 * math.pi / 60
        v = w * Do / 2
        return {"mass_kg": mass, "inertia_kg_m2": I,
                "energy_J": 0.5 * I * w * w, "rim_speed_m_s": v,
                "rim_stress_Pa": rho * v * v}
    if solver == "hydraulic_cylinder":
        bore = _need_number(inputs, "bore_d_m")
        rod = _need_number(inputs, "rod_d_m")
        p = _need_number(inputs, "pressure_Pa")
        Q = _need_number(inputs, "flow_m3_s", positive=False)
        if rod >= bore:
            raise ValueError("rod_d_m must be smaller than bore_d_m")
        A_ext = math.pi / 4 * bore ** 2
        A_ret = math.pi / 4 * (bore ** 2 - rod ** 2)
        return {"extend_force_N": p * A_ext, "retract_force_N": p * A_ret,
                "extend_speed_m_s": Q / A_ext if A_ext else 0,
                "retract_speed_m_s": Q / A_ret if A_ret else 0}
    if solver == "crank_slider":
        r = _need_number(inputs, "crank_r_m")
        l = _need_number(inputs, "rod_l_m")
        n = _need_number(inputs, "speed_rpm", positive=False)
        if l <= r:
            raise ValueError("rod_l_m must be larger than crank_r_m")
        w = n * 2 * math.pi / 60
        series = []
        max_v = 0.0; max_a = 0.0
        for deg in range(0, 721, 10):
            th = math.radians(deg)
            s_, c_ = math.sin(th), math.cos(th)
            root = math.sqrt(max(l * l - r * r * s_ * s_, 0))
            x = r * c_ + root
            ds = -r * s_ - (r * r * s_ * c_) / root if root else -r * s_
            d2s = -r * c_ - ((r * r * (2 * c_ * c_ - 1)) / root
                             + (r ** 4 * s_ * s_ * c_ * c_) / (root ** 3)) if root else -r * c_
            v = w * ds; a = w * w * d2s
            max_v = max(max_v, abs(v)); max_a = max(max_a, abs(a))
            series.append({"angle_deg": deg, "position_m": round(x, 6),
                           "velocity_m_s": round(v, 4),
                           "acceleration_m_s2": round(a, 3)})
        return {"stroke_m": 2 * r, "max_velocity_m_s": round(max_v, 4),
                "max_acceleration_m_s2": round(max_a, 3),
                "mean_piston_speed_m_s": 2 * (2 * r) * n / 60,
                "series": series}
    if solver == "fatigue_shaft":
        d = _need_number(inputs, "diameter_m")
        M = _need_number(inputs, "bending_moment_Nm", positive=False)
        T = _need_number(inputs, "torque_Nm", positive=False)
        Sut = props["tensile_strength_mpa"] * 1e6
        Se = props["fatigue_limit_mpa"] * 1e6
        yld = props["yield_strength_mpa"] * 1e6
        sigma_a = 32 * M / (math.pi * d ** 3)
        tau_m = 16 * T / (math.pi * d ** 3)
        sigma_m = math.sqrt(3) * tau_m
        sf_goodman = 1 / (sigma_a / Se + sigma_m / Sut) if (sigma_a or sigma_m) else None
        sigma_static = math.sqrt(sigma_a ** 2 + 3 * tau_m ** 2)
        return {"alternating_stress_Pa": sigma_a, "mean_stress_Pa": sigma_m,
                "goodman_safety_factor": sf_goodman,
                "static_safety_factor": _safety_factor(yld, sigma_static)}
    if solver == "vibration_1dof":
        k = _need_number(inputs, "stiffness_N_m")
        m = _need_number(inputs, "mass_kg")
        wn = math.sqrt(k / m)
        fn = wn / (2 * math.pi)
        return {"natural_frequency_Hz": fn, "natural_frequency_rad_s": wn,
                "period_s": 1 / fn if fn else 0, "critical_speed_rpm": fn * 60}
    if solver == "power_transmission":
        T = _need_number(inputs, "torque_Nm", positive=False)
        n = _need_number(inputs, "speed_rpm", positive=False)
        w = n * 2 * math.pi / 60
        P = T * w
        return {"angular_velocity_rad_s": w, "power_W": P,
                "power_kW": P / 1000, "power_hp": P / 745.7}

    if solver == "ohm_law":
        given = [k for k in ("voltage_V", "current_A", "resistance_ohm")
                 if inputs.get(k) is not None]
        if len(given) != 2:
            raise ValueError("ohm_law needs exactly two of voltage_V, "
                             "current_A, resistance_ohm")
        V = inputs.get("voltage_V")
        I = inputs.get("current_A")
        R = inputs.get("resistance_ohm")
        if V is None:
            V = I * R
        elif I is None:
            I = V / R
        else:
            R = V / I
        return {"voltage_V": float(V), "current_A": float(I),
                "resistance_ohm": float(R), "power_W": float(V * I)}
    if solver == "series_parallel":
        kind = str(inputs.get("kind", "resistor"))
        mode = str(inputs.get("mode", "series"))
        vals = inputs.get("values")
        if kind not in ("resistor", "capacitor", "inductor"):
            raise ValueError("kind must be resistor, capacitor or inductor")
        if mode not in ("series", "parallel"):
            raise ValueError("mode must be series or parallel")
        if not isinstance(vals, list) or len(vals) < 2 or \
                any(not isinstance(x, (int, float)) or x <= 0 for x in vals):
            raise ValueError("values must be a list of at least two positive numbers")
        if (kind == "capacitor") == (mode == "series"):
            # capacitors in series (or R/L in parallel): reciprocals
            eq = 1.0 / sum(1.0 / x for x in vals)
        else:
            eq = sum(vals)
        return {"equivalent": eq, "kind": kind, "mode": mode}
    if solver == "rc_time_constant":
        R = _need_number(inputs, "resistance_ohm")
        C = _need_number(inputs, "capacitance_F")
        V = _need_number(inputs, "voltage_V", positive=False)
        tau = R * C
        return {"tau_s": tau, "cutoff_hz": 1.0 / (2 * math.pi * tau),
                "voltage_at_tau_V": V * (1 - math.exp(-1)),
                "settle_5tau_s": 5 * tau}
    if solver == "rlc_resonance":
        R = _need_number(inputs, "resistance_ohm")
        L = _need_number(inputs, "inductance_H")
        C = _need_number(inputs, "capacitance_F")
        w0 = 1.0 / math.sqrt(L * C)
        Q = (1.0 / R) * math.sqrt(L / C)
        return {"resonant_freq_hz": w0 / (2 * math.pi),
                "angular_freq_rad_s": w0, "quality_factor": Q,
                "bandwidth_hz": w0 / (2 * math.pi * Q),
                "damping": "underdamped" if Q > 0.5 else
                           ("critically damped" if Q == 0.5 else "overdamped")}
    if solver == "ac_power":
        V = _need_number(inputs, "voltage_rms_V")
        I = _need_number(inputs, "current_rms_A")
        pf = _need_number(inputs, "power_factor", positive=False)
        if not (0 < pf <= 1):
            raise ValueError("power_factor must be in (0, 1]")
        S = V * I
        phi = math.acos(pf)
        return {"apparent_power_VA": S, "real_power_W": S * pf,
                "reactive_power_var": S * math.sin(phi),
                "phase_angle_deg": math.degrees(phi)}
    if solver == "transformer":
        V1 = _need_number(inputs, "primary_voltage_V")
        N1 = _need_number(inputs, "turns_primary")
        N2 = _need_number(inputs, "turns_secondary")
        eta = _need_number(inputs, "efficiency", positive=False)
        P = _need_number(inputs, "load_power_W", positive=False)
        if not (0 < eta <= 1):
            raise ValueError("efficiency must be in (0, 1]")
        V2 = V1 * N2 / N1
        I2 = P / V2 if V2 else 0.0
        I1 = P / (eta * V1) if V1 else 0.0
        return {"secondary_voltage_V": V2, "turns_ratio": N2 / N1,
                "secondary_current_A": I2, "primary_current_A": I1}
    if solver == "dc_motor":
        V = _need_number(inputs, "voltage_V")
        Ra = _need_number(inputs, "resistance_ohm")
        Kt = _need_number(inputs, "kt_Nm_per_A")
        Ke = _need_number(inputs, "ke_V_per_rad_s")
        Tl = _need_number(inputs, "load_torque_Nm", positive=False)
        I_stall = V / Ra
        T_stall = Kt * I_stall
        w0 = V / Ke
        I = Tl / Kt
        if I > I_stall:
            raise ValueError("load torque exceeds the stall torque "
                             f"({T_stall:.3f} N·m) — the motor cannot turn this load")
        w = (V - I * Ra) / Ke
        pin = V * I
        pout = Tl * w
        return {"stall_current_A": I_stall, "stall_torque_Nm": T_stall,
                "no_load_speed_rpm": w0 * 60 / (2 * math.pi),
                "current_A": I, "speed_rpm": w * 60 / (2 * math.pi),
                "power_in_W": pin, "power_out_W": pout,
                "efficiency": (pout / pin) if pin > 0 else 0.0}
    if solver == "battery_config":
        Vc = _need_number(inputs, "cell_voltage_V")
        Ah = _need_number(inputs, "cell_capacity_Ah")
        s = inputs.get("series")
        p = inputs.get("parallel")
        if not isinstance(s, int) or not isinstance(p, int) or s < 1 or p < 1:
            raise ValueError("series and parallel must be integers >= 1")
        I = _need_number(inputs, "load_current_A", positive=False)
        Vt, At = Vc * s, Ah * p
        return {"total_voltage_V": Vt, "total_capacity_Ah": At,
                "energy_Wh": Vt * At,
                "runtime_h": (At / I) if I > 0 else None}
    if solver == "motor_gearbox":
        V = _need_number(inputs, "voltage_V")
        Ra = _need_number(inputs, "resistance_ohm")
        Kt = _need_number(inputs, "kt_Nm_per_A")
        Ke = _need_number(inputs, "ke_V_per_rad_s")
        Tl = _need_number(inputs, "load_torque_Nm", positive=False)
        i = _need_number(inputs, "gear_ratio")
        eta = _need_number(inputs, "gear_efficiency", positive=False)
        if not (0 < eta <= 1):
            raise ValueError("gear_efficiency must be in (0, 1]")
        Tm = Tl / (i * eta)  # load torque reflected to the motor shaft
        I = Tm / Kt
        I_stall = V / Ra
        if I > I_stall:
            raise ValueError("reflected load torque exceeds the motor stall "
                             f"torque ({Kt * I_stall:.3f} N·m) — the motor cannot turn this load")
        wm = (V - I * Ra) / Ke
        pin = V * I
        pout = Tl * (wm / i)
        return {"motor_speed_rpm": wm * 60 / (2 * math.pi),
                "motor_torque_Nm": Tm,
                "output_speed_rpm": wm / i * 60 / (2 * math.pi),
                "output_torque_Nm": Tl,
                "power_in_W": pin, "power_out_W": pout,
                "efficiency": (pout / pin) if pin > 0 else 0.0,
                "motor_current_A": I}
    if solver == "solenoid":
        N = _need_number(inputs, "turns")
        l = _need_number(inputs, "length_m")
        A = _need_number(inputs, "area_m2")
        mu_r = _need_number(inputs, "mu_r")
        I = _need_number(inputs, "current_A", positive=False)
        mu0 = 4 * math.pi * 1e-7
        mu = mu0 * mu_r
        L = mu * N * N * A / l
        B = mu * N * I / l
        return {"inductance_H": L, "field_T": B, "flux_Wb": B * A,
                "energy_J": 0.5 * L * I * I}
    if solver == "wire_resistance":
        length = _need_number(inputs, "length_m")
        area_mm2 = _need_number(inputs, "area_mm2")
        I = _need_number(inputs, "current_A", positive=False)
        rho = props["electrical_resistivity_ohm_m"]
        R = rho * length / (area_mm2 * 1e-6)
        return {"resistance_ohm": R, "resistivity_ohm_m": rho,
                "voltage_drop_V": I * R, "power_loss_W": I * I * R}

    if solver == "column_buckling":
        L = _need_number(inputs, "length_m")
        kf = inputs.get("k_factor", 1.0)
        if not isinstance(kf, (int, float)) or isinstance(kf, bool) or kf <= 0:
            raise ValueError("k_factor must be a positive number")
        area, I, _J, _c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        # Second moment about the weak axis needs both Iy and Iz.
        import structure as _struct
        sec2 = _struct.section_properties_2d(inputs.get("section") or {})
        Imin = min(sec2["Iy_m4"], sec2["Iz_m4"])
        r = math.sqrt(Imin / area)
        Le = kf * L
        lam = Le / r
        Pcr = math.pi ** 2 * E * Imin / Le ** 2
        sig_cr_euler = Pcr / area
        strength = (props.get("yield_strength_mpa")
                    or props.get("compressive_strength_mpa"))
        load = inputs.get("load_N")
        if load is not None and (not isinstance(load, (int, float))
                                 or isinstance(load, bool)):
            raise ValueError("load_N must be a number")
        if strength is not None:
            sy = float(strength) * 1e6
            lam_c = math.sqrt(2 * math.pi ** 2 * E / sy)
            if lam >= lam_c:
                sig_cr, regime = sig_cr_euler, "euler"
            else:
                sig_cr = sy * (1 - sy * lam ** 2 / (4 * math.pi ** 2 * E))
                regime = "johnson"
        else:
            sig_cr, regime = sig_cr_euler, "euler"
        out = {"critical_load_N": Pcr, "critical_stress_Pa": sig_cr,
               "slenderness": lam, "effective_length_m": Le,
               "regime": regime, "radius_of_gyration_m": r}
        if load is not None:
            out["utilization"] = abs(float(load)) / Pcr
        return out
    if solver == "fixed_beam":
        L = _need_number(inputs, "length_m")
        F = _need_number(inputs, "load_N", positive=False)
        area, I, _J, c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        yld = props["yield_strength_mpa"] * 1e6
        delta = F * L ** 3 / (192 * E * I)
        moment = F * L / 8
        stress = moment * c / I
        return {"deflection_m": delta, "end_moment_Nm": moment,
                "mid_moment_Nm": moment, "max_stress_Pa": stress,
                "safety_factor": _safety_factor(yld, stress),
                "section_area_m2": area, "second_moment_m4": I}
    if solver == "natural_frequency_beam":
        L = _need_number(inputs, "length_m")
        area, I, _J, _c = section_properties(inputs.get("section") or {})
        E = props["elastic_modulus_gpa"] * 1e9
        rho = props["density_kg_m3"]
        support = inputs.get("support", "cantilever")
        beta = {"cantilever": 1.87510407,
                "simply_supported": math.pi,
                "fixed_fixed": 4.73004074,
                "free_free": 4.73004074}.get(support)
        if beta is None:
            raise ValueError("support must be cantilever, simply_supported, "
                             "fixed_fixed or free_free")
        m_per_m = rho * area
        # Weak-axis bending gives the lowest frequency; report both.
        import structure as _struct
        sec2 = _struct.section_properties_2d(inputs.get("section") or {})
        Imin = min(sec2["Iy_m4"], sec2["Iz_m4"])
        Imax = max(sec2["Iy_m4"], sec2["Iz_m4"])
        f_min = beta ** 2 / (2 * math.pi) * math.sqrt(E * Imin / (m_per_m * L ** 4))
        f_max = beta ** 2 / (2 * math.pi) * math.sqrt(E * Imax / (m_per_m * L ** 4))
        return {"frequency_hz": f_min,
                "frequency_weak_axis_hz": f_min,
                "frequency_strong_axis_hz": f_max,
                "angular_frequency_rad_s": 2 * math.pi * f_min,
                "period_s": 1 / f_min if f_min else None}
    if solver == "wind_load_is875":
        Vb = _need_number(inputs, "basic_wind_speed_m_s")
        k1 = _need_number(inputs, "k1", positive=False)
        k2 = _need_number(inputs, "k2", positive=False)
        k3 = _need_number(inputs, "k3", positive=False)
        area = _need_number(inputs, "area_m2")
        cf = inputs.get("force_coefficient", 1.0)
        if not isinstance(cf, (int, float)) or isinstance(cf, bool) or cf < 0:
            raise ValueError("force_coefficient must be a number >= 0")
        Vz = Vb * k1 * k2 * k3
        pz = 0.6 * Vz ** 2
        return {"design_wind_speed_m_s": Vz, "design_pressure_Pa": pz,
                "wind_force_N": pz * area * cf}
    if solver == "seismic_base_shear_is1893":
        W = _need_number(inputs, "seismic_weight_N")
        Z = _need_number(inputs, "zone_factor", positive=False)
        I = _need_number(inputs, "importance_factor", positive=False)
        R = _need_number(inputs, "response_reduction_factor")
        sa_g = _need_number(inputs, "sa_g", positive=False)
        Ah = (Z / 2) * (I / R) * sa_g
        return {"design_coefficient": Ah, "base_shear_N": Ah * W}
    if solver == "load_combination":
        combos = {
            "1.5(DL+LL)": {"dead": 1.5, "live": 1.5},
            "1.2(DL+LL+WL)": {"dead": 1.2, "live": 1.2, "wind": 1.2},
            "1.2(DL+LL+EL)": {"dead": 1.2, "live": 1.2, "seismic": 1.2},
            "1.5(DL+WL)": {"dead": 1.5, "wind": 1.5},
            "1.5(DL+EL)": {"dead": 1.5, "seismic": 1.5},
            "0.9DL+1.5WL": {"dead": 0.9, "wind": 1.5},
            "0.9DL+1.5EL": {"dead": 0.9, "seismic": 1.5},
            "1.5(DL+SL)": {"dead": 1.5, "snow": 1.5},
        }
        name = inputs.get("combination")
        if name not in combos:
            raise ValueError("combination must be one of: "
                             + ", ".join(combos))
        factors = combos[name]
        total = 0.0
        for case, fac in factors.items():
            v = inputs.get(case + "_N", 0)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError(f"{case}_N must be a number")
            total += fac * float(v)
        return {"factored_total_N": total, "factors": factors,
                "combination": name}
    raise ValueError(f"no implementation for solver: {solver}")

