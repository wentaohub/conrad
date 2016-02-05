import conrad
import numpy as np
import unittest
import cvxpy

from conrad import Case

# some tests should be here
class TestExamples(unittest.TestCase):
	""" Unit tests using example problems. """
	def setUp(self):
		self.m_targ = 100
		self.m_oar = 400
		self.m = self.m_targ + self.m_oar
		self.n = 200
		
		# Construct dose matrix
		A_targ = np.random.rand(self.m_targ, self.n)
		A_oar = 0.5 * np.random.rand(self.m_oar, self.n)
		self.A = np.vstack((A_targ, A_oar))
	
	def test_basic(self):
		# Prescription for each structure
		lab_tum = 0
		lab_oar = 1
		rx = [{'label': lab_tum, 'name': 'tumor', 'is_target': True,  'dose': 1., 'constraints': None},
			  {'label': lab_oar,  'name': 'oar',   'is_target': False, 'dose': 0., 'constraints': None}]
		
		# Construct and solve case
		label_order = [lab_tum, lab_oar]
		voxel_labels = [lab_tum] * self.m_targ + [lab_oar] * self.m_oar
		cs = Case(self.A, voxel_labels, label_order, rx)
		cs.plan("ECOS", verbose = 1)
		
		# Add DVH constraints and re-solve
		cs.add_dvh_constraint(lab_tum, 1.05, 30., '<')
		cs.add_dvh_constraint(lab_tum, 0.8, 20., '>')
		cs.add_dvh_constraint(lab_oar, 0.5, 50, '<')
		cs.add_dvh_constraint(lab_oar, 0.55, 10, '>')
		cs.plan("SCS", verbose = 1)
