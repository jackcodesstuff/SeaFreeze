from collections import namedtuple
from itertools import repeat
import warnings
import os.path as op
import numpy as np
from mlbspline import load
from lbftd import evalGibbs as eg
from lbftd.statevars import iP, iT, iM

defpath = op.join(op.dirname(op.abspath(__file__)), 'SeaFreeze_Gibbs.mat')


def seafreeze(PTm, phase, path=defpath):
    """ Calculates thermodynamic quantities for H2O water or ice polymorphs Ih, II, III, V, and VI for all phases
        (see lbftd documentation for full list)
        for solid phases only:
            - Vp (compressional wave velocity, in m/s)
            - Vs (shear wave velocity, in m/s)
            - shear (shear modulus, in MPa)
    Requires the SeaFreeze_Gibbs.mat library containing the Gibbs LBF parametrization (installed with this module).

    NOTE:  The authors recommend the use of 'water1' for any application in the 200-355 K range and up to 2300 MPa.
    The ice Gibbs parametrizations are optimized for use with the 'water1' phase for phase equilibrium calculations.
    Using other water parametrizations will lead to incorrect melting curves -- 'water2' and 'water_IAPWS95'
    parametrizations are provided for HP extension up to 100 GPa and comparison only.

    :param PTm:     The pressure (MPa) and temperature (K) conditions at which the thermodynamic quantities should be
                    calculated -- the specified units are required, as conversions are built into several calculations.
                    For solutes, molality (concentration in mol solute/kg solvent) is also required.
                    This parameter can have one of the following formats:
                        - Scatter-type input: a 1-dimensional numpy array of tuples with one or more
                          (P,T) or (P,T,m) tuples, e.g.
                                PTm = np.empty((3,), dtype=object)
                                PTm[0] = (441.0858, 313.95)
                                PTm[1] = (478.7415, 313.96)
                                PTm[2] = (444.8285, 313.78)
                            OR
                                PTm = np.empty((3,), dtype=object)
                                PTm[0] = (441.0858, 313.95, 24.9)
                                PTm[1] = (478.7415, 313.96, 22.3)
                                PTm[2] = (444.8285, 313.78, 23.7)                            
                        - Grid-type input: a numpy array with 2 or 3 nested numpy arrays, the first with
                          pressures, the second with temperatures, and the optional third with molality -- 
                          each inner array must be sorted from low to high values. A grid will be constructed
                          from the P and T arrays such that each row of the output will correspond to a
                          pressure and each column to a temperature, e.g.
                                P = np.arange(0.1, 1000.2, 10)
                                T = np.arange(240, 501, 2)
                                PTm = np.array([P, T], dtype=object)
                            OR
                                m = np.arange(1, 10, 0.5)
                                PTm = np.array([P, T, m], dtype=object)
                          PT grids (for pure water or ices) must have axes of different lengths, or a quirk
                          of numpy calculation handling will cause an error. Arrays of length 1 are permitted
                          for grids across 2 input axes. Using np.squeeze() on the output is recommended to
                          get a 2D grid as output, instead of a 3D grid with one axis of length 1.
    :param phase:   One of the keys of the phases dict (bottom of this file), indicating the phase of H2O to
                    be evaluated. Name of solute in the case of non-pure-H2O.
    :param path:    An optional path to the SeaFreeze_Gibbs.mat file
                    The default value assumes the spline distributed along with the project
    :return:        SF output class object containing the calculated thermodynamic quantities (as named attributes),
                    as well as a PTm property (a copy of PTm).
    """
    try:
        phasedesc = phases[phase]
    except KeyError:
        raise ValueError('The specified phase is not recognized.  Supported phases are ' +
                         ', '.join(phases.keys()) + '.')
    sp = load.loadSpline(path, phasedesc.sp_name)
    sp['MW'] = phasedesc.MW
    # calc density and isentropic bulk modulus
    isscatter = _is_scatter(PTm)
    if sp['ndT']:
        # Dimensionless temperature is used, convert input T to dimensionless
        if isscatter:
            PTm[:, iT] = np.log(PTm[:, iT] / sp['Tc'])
        else:
            PTm[iT] = np.log(PTm[iT] / sp['Tc'])
    tdvs = _get_tdvs(sp, PTm, isscatter)
    if phasedesc.shear_mod_parms:
        smg = _get_shear_mod_GPa(phasedesc.shear_mod_parms, tdvs.rho, _get_T(PTm, isscatter))
        tdvs.shear = 1e3 * smg  # convert to MPa for consistency with other measures
        tdvs.Vp = _get_Vp(smg, tdvs.rho, tdvs.Ks)
        tdvs.Vs = _get_Vs(smg, tdvs.rho)
    return tdvs


def whichphase(PTm, solute='water1', path=defpath):
    """ Determines the most likely phase of water at each pressure/temperature

    :param PTm:     The pressure (MPa) and temperature (K) conditions at which the thermodynamic quantities should be
                    calculated -- the specified units are required, as conversions are built into several calculations.
                    For solutes, molality (concentration in mol solute/kg solvent) is also required.
                    This parameter can have one of the following formats:
                        - Scatter-type input: a 1-dimensional numpy array of tuples with one or more
                          (P,T) or (P,T,m) tuples, e.g.
                                PTm = np.empty((3,), dtype=object)
                                PTm[0] = (441.0858, 313.95)
                                PTm[1] = (478.7415, 313.96)
                                PTm[2] = (444.8285, 313.78)
                            OR
                                PTm = np.empty((3,), dtype=object)
                                PTm[0] = (441.0858, 313.95, 24.9)
                                PTm[1] = (478.7415, 313.96, 22.3)
                                PTm[2] = (444.8285, 313.78, 23.7)                            
                        - Grid-type input: a numpy array with 2 or 3 nested numpy arrays, the first with
                          pressures, the second with temperatures, and the optional third with molality -- 
                          each inner array must be sorted from low to high values. A grid will be constructed
                          from the P and T arrays such that each row of the output will correspond to a
                          pressure and each column to a temperature, e.g.
                                P = np.arange(0.1, 1000.2, 10)
                                T = np.arange(240, 501, 2)
                                PTm = np.array([P, T], dtype=object)
                            OR
                                m = np.arange(1, 10, 0.5)
                                PTm = np.array([P, T, m], dtype=object)
                          PT grids (for pure water or ices) must have axes of different lengths, or a quirk
                          of numpy calculation handling will cause an error. Arrays of length 1 are permitted
                          for grids across 2 input axes. Using np.squeeze() on the output is recommended to
                          get a 2D grid as output, instead of a 3D grid with one axis of length 1.
    :param solute:  An optional dissolved solute in the liquid phase.
                    The default is pure water (water1).
    :param path:    An optional path to the SeaFreeze_Gibbs.mat file --
                    The default value assumes the spline distributed along with the project
    :return:        A numpy.ndarray the same size as PTm, with the phase of each pressure/temperature represented by
                    an integer, as shown in phasenum2phase
    """

    isscatter = _is_scatter(PTm)
    phase_sp = {v.phase_num: load.loadSpline(path, v.sp_name) for pcomp, v in phases.items() if
                v.phase_num > 0 or pcomp == solute}
    ptsh = (PTm.size,) if isscatter else (PTm[iP].size, PTm[iT].size)  # reference shape based on PTm
    comp = np.full(ptsh + (max_phase_num + 1,), np.nan)  # comparison matrix
    for p in phase_sp.keys():
        if phase_sp[p]['ndT']:
            # Dimensionless temperature is used, convert input T to dimensionless
            if isscatter:
                PTm[:, iT] = np.log(PTm[:, iT] / phase_sp[p]['Tc'])
            else:
                PTm[iT] = np.log(PTm[iT] / phase_sp[p]['Tc'])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sl = tuple(repeat(slice(None), 1 if isscatter else 2)) + (p,)  # slice for this phase
            sp = phase_sp[p]
            if p == 0:
                phase_sp[p]['MW'] = phases[solute].MW
                if 'water' in solute:
                    tdvs = _get_tdvs(sp, _get_PT(PTm, isscatter), isscatter, 'G').G * phase_sp[p]['MW']
                else:
                    tdvs = _get_tdvs(sp, PTm, isscatter, 'G', 'muw').muw
            else:
                phase_sp[p]['MW'] = phases[phasenum2phase[p]].MW
                tdvs = _get_tdvs(sp, _get_PT(PTm, isscatter), isscatter, 'G').G * phase_sp[p]['MW']
            # wipe out G for PTm values that fall outside the knot sequence
            if isscatter:
                extrap = [(pt[iP] < sp['knots'][iP].min()) + (pt[iP] > sp['knots'][iP].max()) +
                          (pt[iT] < sp['knots'][iT].min()) + (pt[iT] > sp['knots'][iT].max()) for pt in PTm]
            else:
                pt = np.logical_or(PTm[iP] < sp['knots'][iP].min(), PTm[iP] > sp['knots'][iP].max())
                tt = np.logical_or(PTm[iT] < sp['knots'][iT].min(), PTm[iT] > sp['knots'][iT].max())
                extrap = np.logical_or(*np.meshgrid(pt, tt, indexing='ij'))
            tdvs[extrap] = np.nan
            comp[sl] = np.squeeze(tdvs)
    # output for all-nan slices should be nan
    all_nan_sl = np.all(np.isnan(comp), -1)  # find slices where all values are nan along the innermost axis
    out = np.full(ptsh, np.nan)  # initialize output to nan
    out[~all_nan_sl] = np.nanargmin(comp[~all_nan_sl], -1)  # find min values for other slices
    return out


def _get_tdvs(sp, PTm, is_scatter, *tdvSpec):
    """ peeks into PTm to see if the PTm data is for grid or scatter and calls the appropriate evalGibbs function

    :param sp:          the Gibbs LBF
    :param PTm:         the PTm data
    :param is_scatter:  Boolean indicating whether the PTm data is scatter or not (if not, it is a grid)
    :param tdvSpec:     optional list of thermodynamic variables to calculate (see lbftd documentation)
    :return:            tdv object (see lbftd documentation)
    """
    fn = eg.evalSolutionGibbsScatter if is_scatter else eg.evalSolutionGibbsGrid
    return fn(sp, PTm, *tdvSpec, failOnExtrapolate=False, MWu=sp['MW'])


def _get_shear_mod_GPa(sm, rho, T):
    return None if sm is None else sm[0] + sm[1] * (rho - sm[4]) + sm[2] * (rho - sm[4]) ** 2 + sm[3] * (T - sm[5])


def _get_Vp(smg, rho, Ks):
    return 1e3 * np.sqrt((Ks / 1e3 + 4 / 3 * smg) / rho / 1e-3)


def _get_Vs(smg, rho):
    return 1e3 * np.sqrt(smg / rho / 1e-3)


def _is_scatter(PTm):
    return isinstance(PTm[0], tuple) or (PTm.shape == (1, 2) and np.isscalar(PTm[0]) and np.isscalar(PTm[1])) \
           or (PTm.shape == (1, 3) and np.isscalar(PTm[0]) and np.isscalar(PTm[1]) and np.isscalar(PTm[2]))


def _get_T(PTm, is_scatter):
    if is_scatter:
        if len(PTm[0]) < 3:
            return np.array([T for P, T in PTm])
        else:
            return np.array([T for P, T, m in PTm])
    else:
        return PTm[1]


def _get_PT(PTm, is_scatter):
    if is_scatter:
        if len(PTm[0]) < 3:
            return PTm
        else:
            return np.array([(P, T) for P, T, m in PTm])
    else:
        return PTm[:2]


#########################################
## Constants
#########################################
mH2O_kgmol = 18.01528e-3
PhaseDesc = namedtuple('PhaseDesc', 'sp_name shear_mod_parms phase_num MW')
phases = {"Ih": PhaseDesc("G_iceIh", [3.04, -0.00462, 0, -0.00607, 1000, 273.15], 1, mH2O_kgmol),  # Feistel and Wagner, 2006
          "II": PhaseDesc("G_iceII", [4.1, 0.0175, 0, -0.014, 1100, 273], 2, mH2O_kgmol),  # Journaux et al, 2019
          "III": PhaseDesc("G_iceIII", [2.57, 0.0175, 0, -0.014, 1100, 273], 3, mH2O_kgmol),  # Journaux et al, 2019
          "V": PhaseDesc("G_iceV", [2.57, 0.0175, 0, -0.014, 1100, 273], 5, mH2O_kgmol),  # Journaux et al, 2019
          "VI": PhaseDesc("G_iceVI", [2.57, 0.0175, 0, -0.014, 1100, 273], 6, mH2O_kgmol),  # Journaux et al, 2019
          "water1": PhaseDesc("G_H2O_2GPa_500K", None, 0, mH2O_kgmol),  # extends to 500 K and 2300 MPa; Bollengier et al 2019
          "water2": PhaseDesc("G_H2O_100GPa_10000K", None, np.nan, mH2O_kgmol),  # extends to 100 GPa; Brown 2018
          "water_IAPWS95": PhaseDesc("G_H2O_IAPWS", None, np.nan, mH2O_kgmol),
          # LBF representation of IAPWS 95; Wagner and Pruß, 2002
          "NH3": PhaseDesc("LBF_NH3_H2O_SSdev_v1", None, 0, 17.031e-3),
          # LBF representation of unpublished NH3 data from B Journaux and JM Brown
          "NaCl": PhaseDesc("NaCl_LBF_8000MPa", None, 0, 58.44e-3)
          # WIP LBF representation of NaCl data from B Journaux, JM Brown, and O Bollengier
          }
max_phase_num = max([p.phase_num for p in phases.values()])
phasenum2phase = {v.phase_num: k for (k, v) in phases.items()}
