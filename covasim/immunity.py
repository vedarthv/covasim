'''
Defines classes and methods for calculating immunity
'''

import numpy as np
import sciris as sc
from . import utils as cvu
from . import defaults as cvd
from . import parameters as cvpar
from . import interventions as cvi


# %% Define strain class

__all__ = ['Strain', 'Vaccine']


class Strain(sc.prettyobj):
    '''
    Add a new strain to the sim

    Args:
        strain (str/dict): name of strain, or dictionary of parameters specifying information about the strain
        label       (str): if strain is supplied as a dict, the name of the strain
        days   (int/list): day(s) on which new variant is introduced.
        n_imports   (int): the number of imports of the strain to be added
        rescale    (bool): whether the number of imports should be rescaled with the population
        kwargs     (dict): passed to Intervention()

    **Example**::

        b117    = cv.Strain('b117', days=10) # Make strain B117 active from day 10
        p1      = cv.Strain('p1', days=15) # Make strain P1 active from day 15
        my_var  = cv.Strain(strain={'rel_beta': 2.5}, label='My strain', days=20)
        sim     = cv.Sim(strains=[b117, p1, my_var]).run() # Add them all to the sim
    '''

    def __init__(self, strain=None, label=None, days=None, n_imports=1, rescale=True):
        self.days = days # Handle inputs
        self.n_imports = cvd.default_int(n_imports)
        self.parse_strain_pars(strain=strain, label=label) # Strains can be defined in different ways: process these here
        self.initialized = False
        return


    def parse_strain_pars(self, strain=None, label=None):
        ''' Unpack strain information, which may be given in different ways'''

        # Option 1: strains can be chosen from a list of pre-defined strains
        if isinstance(strain, str):

            choices, mapping = cvpar.get_strain_choices()
            pars = cvpar.get_strain_pars()
            choicestr = sc.newlinejoin(sc.mergelists(*choices.values()))

            normstrain = strain.lower()
            for txt in ['.', ' ', 'strain', 'variant', 'voc']:
                normstrain = normstrain.replace(txt, '')

            if normstrain in mapping:
                normstrain = mapping[normstrain]
                strain_pars = pars[normstrain]
            else:
                errormsg = f'The selected variant "{strain}" is not implemented; choices are:\n{choicestr}'
                raise NotImplementedError(errormsg)

        # Option 2: strains can be specified as a dict of pars
        elif isinstance(strain, dict):
            strain_pars = strain
            if label is None:
                label = 'Custom strain'

        else:
            errormsg = f'Could not understand {type(strain)}, please specify as a dict or a predefined strain:\n{choicestr}'
            raise ValueError(errormsg)

        # Set label
        self.label = label if label else normstrain
        self.p = sc.objdict(strain_pars) # Convert to an objdict and save

        return


    def initialize(self, sim):

        # Store the index of this strain, and increment the number of strains in the simulation
        self.index = sim['n_strains']
        sim['n_strains'] += 1

        # Update strain info
        defaults = cvpar.get_strain_pars()['wild']
        for key in cvd.strain_pars:
            if key not in self.p:
                self.p[key] = defaults[key]
            sim['strain_pars'][key].append(self.p[key])

        self.initialized = True

        return


    def apply(self, sim):
        for ind in cvi.find_day(self.days, sim.t, interv=self, sim=sim): # Time to introduce strain
            susceptible_inds = cvu.true(sim.people.susceptible)
            n_imports = sc.randround(self.n_imports/sim.rescale_vec[sim.t]) # Round stochastically to the nearest number of imports
            importation_inds = np.random.choice(susceptible_inds, n_imports)
            sim.people.infect(inds=importation_inds, layer='importation', strain=self.index)
        return


class Vaccine(sc.prettyobj):
    '''
    Add a new vaccine to the sim (called by interventions.py vaccinate()

    stores number of doses for vaccine and a dictionary to pass to init_immunity for each dose

    Args:
        vaccine (dict or str): dictionary of parameters specifying information about the vaccine or label for loading pre-defined vaccine
        label (str): if supplying a dictionary, a label for the vaccine must be supplied

    **Example**::

        moderna    = cv.Vaccine('moderna') # Create Moderna vaccine
        pfizer     = cv.Vaccine('pfizer) # Create Pfizer vaccine
        j&j        = cv.Vaccine('jj') # Create J&J vaccine
        az         = cv.Vaccine('az) # Create AstraZeneca vaccine
        interventions += [cv.vaccinate(vaccines=[moderna, pfizer, j&j, az], days=[1, 10, 10, 30])] # Add them all to the sim
        sim = cv.Sim(interventions=interventions)
    '''

    def __init__(self, vaccine=None, label=None):
        self.label = label
        # self.rel_imm = None # list of length n_strains with relative immunity factor
        # self.doses = None
        # self.interval = None
        # self.nab_init = None
        # self.nab_boost = None
        # self.nab_eff = {'sus': {'slope': 2.5, 'n_50': 0.55}} # Parameters to map nabs to efficacy
        self.vaccine_strain_info = cvpar.get_vaccine_strain_pars()
        self.parse_vaccine_pars(vaccine=vaccine)
        # for par, val in self.vaccine_pars.items():
        #     setattr(self, par, val)
        return


    def parse_vaccine_pars(self, vaccine=None):
        ''' Unpack vaccine information, which may be given in different ways'''

        # Option 1: vaccines can be chosen from a list of pre-defined strains
        if isinstance(vaccine, str):

            choices, mapping = cvpar.get_vaccine_choices()
            strain_pars = cvpar.get_vaccine_strain_pars()
            dose_pars = cvpar.get_vaccine_dose_pars()
            choicestr = sc.newlinejoin(sc.mergelists(*choices.values()))

            normvacc = vaccine.lower()
            for txt in ['.', ' ', '&', '-', 'vaccine']:
                normvacc = normvacc.replace(txt, '')

            if normvacc in mapping:
                normvacc = mapping[normvacc]
                vaccine_pars = sc.mergedicts(strain_pars[normvacc], dose_pars[normvacc])
            else: # pragma: no cover
                errormsg = f'The selected vaccine "{vaccine}" is not implemented; choices are:\n{choicestr}'
                raise NotImplementedError(errormsg)

            if self.label is None:
                self.label = normvacc

        # Option 2: strains can be specified as a dict of pars
        elif isinstance(vaccine, dict):
            vaccine_pars = vaccine
            if self.label is None:
                self.label = 'Custom vaccine'

        else: # pragma: no cover
            errormsg = f'Could not understand {type(vaccine)}, please specify as a string indexing a predefined vaccine or a dict.'
            raise ValueError(errormsg)

        self.p = sc.objdict(vaccine_pars)
        return


#%% nab methods

def init_nab(people, inds, prior_inf=True, vacc_info=None):
    '''
    Draws an initial nab level for individuals.
    Can come from a natural infection or vaccination and depends on if there is prior immunity:
    1) a natural infection. If individual has no existing nab, draw from distribution
    depending upon symptoms. If individual has existing nab, multiply booster impact
    2) Vaccination. If individual has no existing nab, draw from distribution
    depending upon vaccine source. If individual has existing nab, multiply booster impact
    '''

    if vacc_info is None:
        # print('Note: using default vaccine dosing information')
        vacc_info = cvpar.get_vaccine_dose_pars()['default']

    nab_arrays = people.nab[inds]
    prior_nab_inds = cvu.idefined(nab_arrays, inds) # Find people with prior nabs
    no_prior_nab_inds = np.setdiff1d(inds, prior_nab_inds) # Find people without prior nabs

    # prior_nab = people.nab[prior_nab_inds] # Array of nab levels on this timestep for people with some nabs
    peak_nab = people.init_nab[prior_nab_inds]

    # nabs from infection
    if prior_inf:
        nab_boost = people.pars['nab_boost']  # Boosting factor for natural infection
        # 1) No prior nab: draw nab from a distribution and compute
        if len(no_prior_nab_inds):
            init_nab = cvu.sample(**people.pars['nab_init'], size=len(no_prior_nab_inds))
            prior_symp = people.prior_symptoms[no_prior_nab_inds]
            no_prior_nab = (2**init_nab) * prior_symp
            people.init_nab[no_prior_nab_inds] = no_prior_nab

        # 2) Prior nab: multiply existing nab by boost factor
        if len(prior_nab_inds):
            init_nab = peak_nab * nab_boost
            people.init_nab[prior_nab_inds] = init_nab

    # nabs from a vaccine
    else:
        nab_boost = vacc_info['nab_boost']  # Boosting factor for vaccination
        # 1) No prior nab: draw nab from a distribution and compute
        if len(no_prior_nab_inds):
            init_nab = cvu.sample(**vacc_info['nab_init'], size=len(no_prior_nab_inds))
            people.init_nab[no_prior_nab_inds] = 2**init_nab

        # 2) Prior nab (from natural or vaccine dose 1): multiply existing nab by boost factor
        if len(prior_nab_inds):
            init_nab = peak_nab * nab_boost
            people.init_nab[prior_nab_inds] = init_nab

    return


def check_nab(t, people, inds=None):
    ''' Determines current nabs based on date since recovered/vaccinated.'''

    # Indices of people who've had some nab event
    rec_inds = cvu.defined(people.date_recovered[inds])
    vac_inds = cvu.defined(people.date_vaccinated[inds])
    both_inds = np.intersect1d(rec_inds, vac_inds)

    # Time since boost
    t_since_boost = np.full(len(inds), np.nan, dtype=cvd.default_int)
    t_since_boost[rec_inds] = t-people.date_recovered[inds[rec_inds]]
    t_since_boost[vac_inds] = t-people.date_vaccinated[inds[vac_inds]]
    t_since_boost[both_inds] = t-np.maximum(people.date_recovered[inds[both_inds]],people.date_vaccinated[inds[both_inds]])

    # Set current nabs
    people.nab[inds] = people.pars['nab_kin'][t_since_boost] * people.init_nab[inds]

    return


def nab_to_efficacy(nab, ax, function_args):
    '''
    Convert nab levels to immunity protection factors, using the functional form
    given in this paper: https://doi.org/10.1101/2021.03.09.21252641

    Args:
        nab (arr): an array of nab levels
        ax (str): can be 'sus', 'symp' or 'sev', corresponding to the efficacy of protection against infection, symptoms, and severe disease respectively

    Returns:
        an array the same size as nab, containing the immunity protection factors for the specified axis
     '''

    if ax not in ['sus', 'symp', 'sev']:
        errormsg = f'Choice {ax} not in list of choices'
        raise ValueError(errormsg)
    args = function_args[ax]

    if ax == 'sus':
        slope = args['slope']
        n_50 = args['n_50']
        efficacy = 1 / (1 + np.exp(-slope * (np.log10(nab) - np.log10(n_50))))  # from logistic regression computed in R using data from Khoury et al
    else:
        efficacy = np.full(len(nab), fill_value=args)
    return efficacy



# %% Immunity methods

def init_immunity(sim, create=False):
    ''' Initialize immunity matrices with all strains that will eventually be in the sim'''

    # Don't use this function if immunity is turned off
    if not sim['use_waning']:
        return

    ts = sim['n_strains']
    immunity = {}

    # Pull out all of the circulating strains for cross-immunity
    circulating_strains = ['wild']
    rel_imms =  dict()
    for strain in sim['strains']:
        circulating_strains.append(strain.label)
        rel_imms[strain.label] = strain.p.rel_imm

    # If immunity values have been provided, process them
    if sim['immunity'] is None or create:
        # Initialize immunity
        for ax in cvd.immunity_axes:
            if ax == 'sus':  # Susceptibility matrix is of size sim['n_strains']*sim['n_strains']
                immunity[ax] = np.full((ts, ts), sim['cross_immunity'], dtype=cvd.default_float)  # Default for off-diagnonals
                np.fill_diagonal(immunity[ax], 1)  # Default for own-immunity
            else:  # Progression and transmission are matrices of scalars of size sim['n_strains']
                immunity[ax] = np.ones(ts, dtype=cvd.default_float)

        cross_immunity = cvpar.get_cross_immunity()
        known_strains = cross_immunity.keys()
        for i in range(ts):
            for j in range(ts):
                if i != j:
                    if circulating_strains[i] in known_strains and circulating_strains[j] in known_strains:
                        immunity['sus'][j][i] = cross_immunity[circulating_strains[j]][circulating_strains[i]]
        sim['immunity'] = immunity

    # Next, precompute the nab kinetics and store these for access during the sim
    sim['nab_kin'] = precompute_waning(length=sim['n_days'], pars=sim['nab_decay'])

    return


def check_immunity(people, strain, sus=True, inds=None, vacc_info=None):
    '''
    Calculate people's immunity on this timestep from prior infections + vaccination

    There are two fundamental sources of immunity:

           (1) prior exposure: degree of protection depends on strain, prior symptoms, and time since recovery
           (2) vaccination: degree of protection depends on strain, vaccine, and time since vaccination

    Gets called from sim before computing trans_sus, sus=True, inds=None
    Gets called from people.infect() to calculate prog/trans, sus=False, inds= inds of people being infected
    '''
    if vacc_info is None:
        # print('Note: using default vaccine dosing information')
        vacc_info   = cvpar.get_vaccine_dose_pars()['default']
        vacc_strain = cvpar.get_vaccine_strain_pars()['default']


    was_inf = cvu.true(people.t >= people.date_recovered)  # Had a previous exposure, now recovered
    is_vacc = cvu.true(people.vaccinated)  # Vaccinated
    date_rec = people.date_recovered  # Date recovered
    immunity = people.pars['immunity'] # cross-immunity/own-immunity scalars to be applied to nab level before computing efficacy
    nab_eff_pars = people.pars['nab_eff']

    # If vaccines are present, extract relevant information about them
    vacc_present = len(is_vacc)
    if vacc_present:
        vx_nab_eff_pars = vacc_info['nab_eff']

    # PART 1: Immunity to infection for susceptible individuals
    if sus:
        is_sus = cvu.true(people.susceptible)  # Currently susceptible
        was_inf_same = cvu.true((people.recovered_strain == strain) & (people.t >= date_rec))  # Had a previous exposure to the same strain, now recovered
        was_inf_diff = np.setdiff1d(was_inf, was_inf_same)  # Had a previous exposure to a different strain, now recovered
        is_sus_vacc = np.intersect1d(is_sus, is_vacc)  # Susceptible and vaccinated
        is_sus_vacc = np.setdiff1d(is_sus_vacc, was_inf)  # Susceptible, vaccinated without prior infection
        is_sus_was_inf_same = np.intersect1d(is_sus, was_inf_same)  # Susceptible and being challenged by the same strain
        is_sus_was_inf_diff = np.intersect1d(is_sus, was_inf_diff)  # Susceptible and being challenged by a different strain

        if len(is_sus_vacc):
            vaccine_source = cvd.default_int(people.vaccine_source[is_sus_vacc])
            vaccine_scale = vacc_strain[strain] # TODO: handle this better
            current_nabs = people.nab[is_sus_vacc]
            people.sus_imm[strain, is_sus_vacc] = nab_to_efficacy(current_nabs * vaccine_scale, 'sus', vx_nab_eff_pars)

        if len(is_sus_was_inf_same):  # Immunity for susceptibles with prior exposure to this strain
            current_nabs = people.nab[is_sus_was_inf_same]
            people.sus_imm[strain, is_sus_was_inf_same] = nab_to_efficacy(current_nabs * immunity['sus'][strain, strain], 'sus', nab_eff_pars)

        if len(is_sus_was_inf_diff):  # Cross-immunity for susceptibles with prior exposure to a different strain
            prior_strains = people.recovered_strain[is_sus_was_inf_diff]
            prior_strains_unique = cvd.default_int(np.unique(prior_strains))
            for unique_strain in prior_strains_unique:
                unique_inds = is_sus_was_inf_diff[cvu.true(prior_strains == unique_strain)]
                current_nabs = people.nab[unique_inds]
                people.sus_imm[strain, unique_inds] = nab_to_efficacy(current_nabs * immunity['sus'][strain, unique_strain], 'sus', nab_eff_pars)

    # PART 2: Immunity to disease for currently-infected people
    else:
        is_inf_vacc = np.intersect1d(inds, is_vacc)
        was_inf = np.intersect1d(inds, was_inf)

        if len(is_inf_vacc):  # Immunity for infected people who've been vaccinated
            vaccine_source = cvd.default_int(people.vaccine_source[is_inf_vacc])
            vaccine_scale = vacc_strain[strain] # TODO: handle this better
            current_nabs = people.nab[is_inf_vacc]
            people.symp_imm[strain, is_inf_vacc] = nab_to_efficacy(current_nabs * vaccine_scale * immunity['symp'][strain], 'symp', nab_eff_pars)
            people.sev_imm[strain, is_inf_vacc] = nab_to_efficacy(current_nabs * vaccine_scale * immunity['sev'][strain], 'sev', nab_eff_pars)

        if len(was_inf):  # Immunity for reinfected people
            current_nabs = people.nab[was_inf]
            people.symp_imm[strain, was_inf] = nab_to_efficacy(current_nabs * immunity['symp'][strain], 'symp', nab_eff_pars)
            people.sev_imm[strain, was_inf] = nab_to_efficacy(current_nabs * immunity['sev'][strain], 'sev', nab_eff_pars)

    return



#%% Methods for computing waning

def precompute_waning(length, pars=None):
    '''
    Process functional form and parameters into values:

        - 'nab_decay'   : specific decay function taken from https://doi.org/10.1101/2021.03.09.21252641
        - 'exp_decay'   : exponential decay. Parameters should be init_val and half_life (half_life can be None/nan)
        - 'linear_decay': linear decay

    Args:
        length (float): length of array to return, i.e., for how long waning is calculated
        pars (dict): passed to individual immunity functions

    Returns:
        array of length 'length' of values
    '''

    pars = sc.dcp(pars)
    form = pars.pop('form')
    choices = [
        'nab_decay', # Default if no form is provided
        'exp_decay',
        'linear_growth',
        'linear_decay'
    ]

    # Process inputs
    if form is None or form == 'nab_decay':
        output = nab_decay(length, **pars)

    elif form == 'exp_decay':
        if pars['half_life'] is None: pars['half_life'] = np.nan
        output = exp_decay(length, **pars)

    elif form == 'linear_growth':
        output = linear_growth(length, **pars)

    elif form == 'linear_decay':
        output = linear_decay(length, **pars)

    else:
        errormsg = f'The selected functional form "{form}" is not implemented; choices are: {sc.strjoin(choices)}'
        raise NotImplementedError(errormsg)

    return output


def nab_decay(length, decay_rate1, decay_time1, decay_rate2):
    '''
    Returns an array of length 'length' containing the evaluated function nab decay
    function at each point.

    Uses exponential decay, with the rate of exponential decay also set to exponentially
    decay (!) after 250 days.

    Args:
        length (int): number of points
        decay_rate1 (float): initial rate of exponential decay
        decay_time1 (float): time on the first exponential decay
        decay_rate2 (float): the rate at which the decay decays
    '''
    def f1(t, decay_rate1):
        ''' Simple exponential decay '''
        return np.exp(-t*decay_rate1)

    def f2(t, decay_rate1, decay_time1, decay_rate2):
        ''' Complex exponential decay '''
        return np.exp(-t*(decay_rate1*np.exp(-(t-decay_time1)*decay_rate2)))

    t  = np.arange(length, dtype=cvd.default_int)
    y1 = f1(cvu.true(t<=decay_time1), decay_rate1)
    y2 = f2(cvu.true(t>decay_time1), decay_rate1, decay_time1, decay_rate2)
    y  = np.concatenate([y1,y2])

    return y


def exp_decay(length, init_val, half_life, delay=None):
    '''
    Returns an array of length t with values for the immunity at each time step after recovery
    '''
    decay_rate = np.log(2) / half_life if ~np.isnan(half_life) else 0.
    if delay is not None:
        t = np.arange(length-delay, dtype=cvd.default_int)
        growth = linear_growth(delay, init_val/delay)
        decay = init_val * np.exp(-decay_rate * t)
        result = np.concatenate([growth, decay], axis=None)
    else:
        t = np.arange(length, dtype=cvd.default_int)
        result = init_val * np.exp(-decay_rate * t)
    return result


def linear_decay(length, init_val, slope):
    ''' Calculate linear decay '''
    t = np.arange(length, dtype=cvd.default_int)
    result = init_val - slope*t
    result = np.maximum(result, 0)
    return result


def linear_growth(length, slope):
    ''' Calculate linear growth '''
    t = np.arange(length, dtype=cvd.default_int)
    return (slope * t)