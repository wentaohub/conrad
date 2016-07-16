from time import clock
from numpy import inf, array, squeeze, ones, zeros, copy as np_copy
from cvxpy import *

from conrad.compat import *
from conrad.medicine.dose import Constraint, PercentileConstraint, \
								 MinConstraint, MaxConstraint, \
								 MeanConstraint

GAMMA_DEFAULT = 1e-2
RELTOL_DEFAULT = 1e-3
ABSTOL_DEFAULT = 1e-4
VERBOSE_DEFAULT = 1
MAXITER_DEFAULT = 2000
INDIRECT_DEFAULT = False
GPU_DEFAULT = False

PRIORITY_1 = 9
PRIORITY_2 = 4
PRIORITY_3 = 1

def println(*msg):
	print(msg)

# TODO: unit test
"""
TODO: problem.py docstring
"""
class Solver(object):
	def __init__(self):
		self.use_2pass = False
		self.use_slack = True
		self.__x = None
		self.__gamma = GAMMA_DEFAULT
		self.dvh_vars = {}
		self.slack_vars = {}
		self.feasible = False

	@property
	def gamma(self):
		return self.__gamma

	@gamma.setter
	def gamma(self, gamma):
		self.__gamma = gamma if gamma is not None else GAMMA_DEFAULT

	@staticmethod
	def get_cd_from_wts(wt_over, wt_under):
		""" TODO: docstring """
		c = (wt_over + wt_under) / 2.
		d = (wt_over - wt_under) / 2.
		return c, d

	def gamma_prioritized(self, priority):
		if priority == 1:
			return self.gamma * PRIORITY_1
		elif priority == 2:
			return self.gamma * PRIORITY_2
		elif priority == 3:
			return self.gamma * PRIORITY_1
		else:
			Exception('priority 0 constraints should '
				'not have slack or associated slack penalties')

	def init_problem(self, n_beams, **options):
		pass

	def clear(self):
		pass

	def build(self, structures, exact=False):
		pass

	def get_slack_value(Self, constraint_id):
		pass

	def get_dvh_slope(self, constraint_id):
		pass

class SolverCVXPY(Solver):
	""" TODO: docstring """

	def __init__(self):
		""" TODO: docstring """
		Solver.__init__(self)
		self.objective = None
		self.constraints = None
		self.problem = None
		self.__x = Variable(0)
		self.dvh_vars = {}
		self.slack_vars = {}
		self.__constraint_indices = {}
		self.constraint_dual_vars = {}
		self.gamma = GAMMA_DEFAULT

	# methods:
	def init_problem(self, n_beams, use_slack=True, use_2pass=False,
					 **options):
		""" TODO: docstring """
		self.use_slack = use_slack
		self.use_2pass = use_2pass
		self.__x = Variable(n_beams)
		self.objective = Minimize(0)
		self.constraints = [self.__x >= 0]
		self.dvh_vars = {}
		self.slack_vars = {}
		self.problem = Problem(self.objective, self.constraints)
		self.gamma = options.pop('gamma', GAMMA_DEFAULT)

	@property
	def n_beams(self):
		return self.__x.size[0]

	def clear(self):
		""" TODO: docstring """
		self.constraints = [self.__x >= 0]
		self.objective = Minimize(0)
		self.problem = Problem(self.objective, self.constraints)

	def build(self, structures, exact=False):
		print "\n SolverCVXPY.BUILD CALL: EXACT=", exact

		self.__check_dimensions(structures)

		rows = sum([s.size if not s.collapsable else 1 for s in structures])
		cols = self.n_beams
		A = zeros((rows, cols))
		b = zeros(rows)
		c = zeros(rows)
		d = zeros(rows)
		ptr = 0
		for s in structures:
			if s.collapsable:
				A[ptr, :] = s.A_mean[:]
				c[ptr] = s.size * s.w_over
				d[ptr] = 0
				ptr += 1
			else:
				print A[ptr : ptr + s.size, :].shape
				print s.A_full.shape
				A[ptr : ptr + s.size, :] += s.A_full
				if s.is_target:
					c_, d_ = self.get_cd_from_wts(s.w_over, s.w_under)
					b[ptr : ptr + s.size] = s.dose
					c[ptr : ptr + s.size] = c_
					d[ptr : ptr + s.size] = d_
				else:
					b[ptr : ptr + s.size] = 0
					c[ptr : ptr + s.size] = s.w_over
					d[ptr : ptr + s.size] = 0
				ptr += s.size

		self.problem.objective = Minimize(
				c.T*abs(A*self.__x - b) + d.T*(A*self.__x - b))

		for s in structures:
			self.__add_constraints(s, exact=exact)

		return self.__construction_report(structures)

	def __check_dimensions(self, structures):
		columns = [s.A.shape[1] for s in structures]
		if not all([col == self.n_beams for col in columns]):
			raise ValueError('all structures in plan must have full dose '
							 'matrices with # columns that match # beams in '
							 'the plan. \n # beams: {}\n provided matrix '
							 'shapes: {}'.format(n_beams,
							 [(s.name, s.A.shape) for s in structures]))
		columns = [s.A_mean.size for s in structures]
		if not all([col == self.n_beams for col in columns]):
			raise ValueError('all structures in plan must have mean dose '
							 'vectors with # columns that match # beams in the'
							 ' plan. \n # beams: {}\n provided matrix shapes: '
							 '{}'.format(n_beams,
							 [(s.name, s.A_mean.sisze) for s in structures]))

	def __construction_report(self, structures):
		report = []
		for structure in structures:
			A = structure.A
			matrix_info = str('using dose matrix, dimensions {}x{}'.format(
							  *structure.A.shape))
			if structure.is_target:
				reason  = 'structure is target'
			else:
				if structure.collapsable:
					A = structure.A_mean
					matrix_info = str('using mean dose, dimensions '
									  '1x{}'.format(structure.A_mean.size))
					reason = 'structure does NOT have min/max/percentile dose constraints'
				else:
					reason = 'structure has min/max/percentile dose constraints'

			report.append('structure {} (label = {}): {} (reason: {})'.format(
						  structure.name, structure.label, matrix_info,
						  reason))
		return report

	@staticmethod
	def __percentile_constraint_restriction(A, x, constr, beta, slack = None):
		""" Form the upper (or lower) DVH constraint:

			upper constraint:

				\sum (beta + (Ax - (b + slack)))_+ <= beta * vox_limit

			lower constraint:

				\sum (beta - (Ax - (b - slack)))_+ <= beta * vox_limit

		"""

		print "\nADDING RESTRICTED CONSTRAINT"

		if not isinstance(constr, PercentileConstraint):
			TypeError('parameter constr must be of type '
				'conrad.dose.PercentileConstraint. '
				'Provided: {}'.format(type(constr)))

		sign = 1 if constr.upper else -1
		fraction = constr.percentile / 100. if constr.upper else 1. - constr.percentile / 100.
		p = fraction * A.shape[0]
		b = constr.dose
		if slack is None: slack = 0.
		return sum_entries(pos( beta + sign * (A * x - (b + sign * slack)) )) <= beta * p

	@staticmethod
	def __percentile_constraint_exact(A, x, y, constr, had_slack = False):
		""" TODO: docstring """

		print "\nADDING EXACT CONSTRAINT"

		if not isinstance(constr, Constraint):
			TypeError('parameter constr must be of type '
				'conrad.dose.PercentileConstraint. '
				'Provided: {}'.format(type(constr)))

		sign = 1 if constr.upper else -1
		b = constr.dose_achieved if had_slack else constr.dose
		idx_exact = constr.get_maxmargin_fulfillers(y, had_slack)
		A_exact = np_copy(A[idx_exact, :])
		return sign * (A_exact * x - b) <= 0

	def __add_constraints(self, structure, exact=False):
		""" TODO: docstring """

		print "\n SolverCVXPY.__ADD_CONSTRAINTS CALL: EXACT=", exact

		# extract dvh constraint from structure,
		# make slack variable (if self.use_slack), add
		# slack to self.objective and slack >= 0 to constraints
		if exact:
			if not self.use_2pass or structure.y is None:
				raise RuntimeError('exact constraints requested, but cannot '
								   'be built. \nrequirements:\n'
								   'input flag "use_2pass" must be "True"\n'
								   '(provided: {})\n'
								   'structure dose must be calculated\n'
								   '(structure dose: {}\n'.format(
								   self.use_2pass, structure.y))

		no_slack = not self.use_slack

		for cid in structure.constraints:
			c = structure.constraints[cid]
			cslack = not exact and self.use_slack and c.priority > 0
			if cslack:
				gamma = self.gamma_prioritized(c.priority)
				slack = Variable(1)
				self.slack_vars[cid] = slack
				self.problem.objective += Minimize(gamma * slack)
				self.problem.constraints += [slack >= 0]
			else:
				slack = 0.
				self.slack_vars[cid] = None

			if isinstance(c, MeanConstraint):
				if c.upper:
					self.problem.constraints += \
						[structure.A_mean * self.__x - slack <= c.dose]
				else:
					self.problem.constraints += \
						[structure.A_mean * self.__x + slack >= c.dose]

			elif isinstance(c, MinConstraint):
				self.problem.constarints += \
					[structure.A * self.__x >= c.dose]

			elif isinstance(c, MaxConstraint):
				self.problem.constarints += \
					[structure.A * self.x <= c.dose]

			elif isinstance(c, PercentileConstraint):
				if exact:
					print "\n SolverCVXPY.__ADD_CONSTRAINTS CALL: EXACT BRANCH"

					# build exact constraint
					dvh_constr = self.__percentile_constraint_exact(
						structure.A, self.__x, structure.y,
						c, had_slack = self.use_slack)

					print dvh_constr

					# add it to problem
					self.problem.constraints += [ dvh_constr ]

				else:
					print "\n SolverCVXPY.__ADD_CONSTRAINTS CALL: RESTRICTION BRANCH"

					# beta = 1 / slope for DVH constraint approximation
					beta = Variable(1)
					self.dvh_vars[cid] = beta
					self.problem.constraints += [ beta >= 0 ]

					# build convex restriction to constraint
					dvh_constr = self.__percentile_constraint_restriction(
						structure.A, self.__x, c, beta, slack)

					print dvh_constr

					# add it to problem
					self.problem.constraints += [ dvh_constr ]

	def get_slack_value(self, constr_id):
		if constr_id in self.slack_vars:
			return self.slack_vars[constr_id].value
		else:
			return None

	def get_dual_value(self, constr_id):
		if constr_id in self.__constraint_indices:
			return self.problem.constraints[
					self.__constraint_indices[constr_id]].dual_value[0]
		else:
			return None

	def get_dvh_slope(self, constr_id):
		beta = self.dvh_vars[constr_id].value if constr_id in self.dvh_vars else None
		return 1. / beta if beta is not None else None

	@property
	def x(self):
		return squeeze(array(self.__x.value))

	@property
	def x_dual(self):
		try:
			return squeeze(array(self.problem.constraints[0].dual_value))
		except:
			return None

	@property
	def solvetime(self):
		# TODO: time run
	    return 'n/a'

	@property
	def status(self):
		return self.problem.status

	@property
	def objective_value(self):
		return self.problem.value

	@property
	def solveiters(self):
		# TODO: get solver iters
		return 'n/a'

	def solve(self, **options):
		""" TODO: docstring """

		# set verbosity level
		VERBOSE = bool(options.pop('verbose', VERBOSE_DEFAULT))
		PRINT = println if VERBOSE else lambda : None

		# solver options
		solver = options.pop('solver', ECOS)
		reltol = options.pop('reltol', RELTOL_DEFAULT)
		maxiter = options.pop('maxiter', MAXITER_DEFAULT)
		use_gpu = options.pop('gpu', GPU_DEFAULT)
		use_indirect = options.pop('use_indirect', INDIRECT_DEFAULT)

		# solve
		PRINT('running solver...')
		if solver == ECOS:
			ret = self.problem.solve(
					solver=ECOS,
					verbose=VERBOSE,
					max_iters=maxiter,
					reltol=reltol,
					reltol_inacc=reltol,
					feastol=reltol,
					feastol_inacc=reltol)
		elif solver == SCS:
			if use_gpu:
				ret = self.problem.solve(
						solver=SCS,
						verbose=VERBOSE,
						max_iters=maxiter,
						eps=reltol,
						gpu=use_gpu)
			else:
				ret = self.problem.solve(
						solver=SCS,
						verbose=VERBOSE,
						max_iters=maxiter,
						eps=reltol,
						use_indirect=use_indirect)
		else:
			raise ValueError('invalid solver specified: {}\n'
							 'no optimization performed'.format(solver))

		PRINT("status: {}".format(self.problem.status))
		PRINT("optimal value: {}".format(self.problem.value))

		return ret != inf and not isinstance(ret, str)

class PlanningProblem(object):
	""" TODO: docstring """

	def __init__(self):
		""" TODO: docstring """
		self.solver = SolverCVXPY()
		self.use_slack = None
		self.use_2pass = None

	def __update_constraints(self, structure):
		""" TODO: docstring """
		for cid in structure.constraints:
			slack_var = self.solver.slack_vars[cid]
			slack = 0 if slack_var is None else slack_var.value
			structure.constraints[cid].slack = slack

	def __update_structure(self, structure, exact = False):
		""" TODO: docstring """
		structure.calc_y(self.solver.x)
		if not exact:
			self.__update_constraints(structure)

	def __gather_solver_info(self, run_output, exact = False):
		keymod = '_exact' if exact else ''
		run_output.solver_info['status' + keymod] = self.solver.status
		run_output.solver_info['time' + keymod] = self.solver.solvetime
		run_output.solver_info['objective' + keymod] = self.solver.objective_value
		run_output.solver_info['iters' + keymod] = self.solver.solveiters

	def __gather_solver_vars(self, run_output, exact = False):
		keymod = '_exact' if exact else ''
		run_output.optimal_variables['x' + keymod] = self.solver.x
		run_output.optimal_variables['lambda' + keymod] = self.solver.x_dual

	def __gather_dvh_slopes(self, run_output, structure_dict):
		# recover dvh constraint slope variables
		for s in structure_dict.itervalues():
			for cid in s.constraints:
				run_output.optimal_dvh_slopes[cid] = self.solver.get_dvh_slope(cid)

	def solve(self, structure_dict, run_output, **options):
		""" TODO: docstring """
		# TODO: change this to reading an environment variable?
		PRINT_PROBLEM_CONSTRUCTION = True

		# get number of beams from dose matrix
		n_beams = structure_dict.values()[0].A.shape[1]

		# initialize problem with size and options
		self.use_slack = options.pop('dvh_slack', True)
		self.use_2pass = options.pop('dvh_exact', False)
		self.solver.init_problem(n_beams, use_slack=self.use_slack,
								 use_2pass=self.use_2pass, **options)

		# build problem
		construction_report = self.solver.build(structure_dict.values())

		if PRINT_PROBLEM_CONSTRUCTION:
			print '\nPROBLEM CONSTRUCTION:'
			for cr in construction_report:
				print cr

		# solve
		start = clock()
		run_output.feasible = self.solver.solve(**options)
		runtime = clock() - start

		# relay output to run_output object
		self.__gather_solver_info(run_output)
		self.__gather_solver_vars(run_output)
		self.__gather_dvh_slopes(run_output, structure_dict)
		run_output.solver_info['time'] = runtime

		if not run_output.feasible:
			return

		# relay output to structures
		for s in structure_dict.values():
			self.__update_structure(s)

		# second pass, if applicable
		if self.use_2pass and run_output.feasible:

			self.solver.clear()
			self.solver.build(structure_dict.values(), exact=True)

			start = clock()
			self.solver.solve(**options)
			runtime = clock() - start

			self.__gather_solver_info(run_output, exact = True)
			self.__gather_solver_vars(run_output, exact = True)
			run_output.solver_info['time_exact'] = runtime

			for s in structure_dict.values():
				self.__update_structure(s, exact = True)