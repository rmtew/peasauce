"""
    Peasauce - interactive disassembler
    Copyright (C) 2012  Richard Tew

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

"""
Unit testing.
"""

import logging
import random
import sys
import unittest


import disassembly
import qtui


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)


class QTUI_UncertainReferenceModification_TestCase(unittest.TestCase):
    def setUp(self):
        class Model(object):
            _row_data = None
            _addition_rows = None
            _removal_rows = None

            def _get_row_data(self):
                return self._row_data

            def _set_row_data(self, _row_data, addition_rows=None, removal_rows=None):
                self._row_data = _row_data
                self._addition_rows = addition_rows
                self._removal_rows = removal_rows

        class DisassemblyModule(object):
            DATA_TYPE_CODE = disassembly.DATA_TYPE_CODE
            DATA_TYPE_LONGWORD = disassembly.DATA_TYPE_LONGWORD
            _next_uncertain_references = None

            def get_uncertain_references_by_address(self, program_data, address):
                result = self._next_uncertain_references
                self._next_uncertain_references = None
                return result

        class DisassemblyData(object):
            pass

        self.disassembly_data = DisassemblyData()
        self.uncertain_code_references_model = Model()
        self.uncertain_data_references_model = Model()
        if False:
            # Some address rages
            block_address = 0
            code_rows, data_rows = [], []
            while len(code_rows) < 10 or len(data_rows) < 10:
                flags = 0
                block_length = random.randint(10, 30)
                if random.random() > 0.7:
                    if random.random() > 0.5:
                        code_rows.append((block_address, block_length, flags | self.CODE_F))
                    else:
                        data_rows.append((block_address, block_length, flags | self.DATA_F))
                block_address += block_length
            self.uncertain_code_references_model._row_data = code_rows
            self.uncertain_data_references_model._row_data = data_rows
            self.code_rows = set(code_rows)
            self.data_rows = set(data_rows)

        self.code_rows = [ [1], [2], [5], [9], [10] ]
        self.uncertain_code_references_model._row_data = self.code_rows[:]
        self.data_rows = [ [3], [7], [8], [11] ]
        self.uncertain_data_references_model._row_data = self.data_rows[:]

        self.fake_disassembly_module = DisassemblyModule()
        self.disassembly_uncertain_reference_modification = qtui.MainWindow.disassembly_uncertain_reference_modification.im_func
        self.disassembly_uncertain_reference_modification.__globals__["disassembly"] = self.fake_disassembly_module

    # TODO: Try edge cases.  Remove and readd first and last entries.  Verify works.
    # TODO: Try switch type cases.  Go from code to data and back.  Manually set flag to force.
    # TODO: Try only one type case.  Disappears from it's type list, and reappears.

    def test_leading_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 1, 1)

        self.assertEqual(self.code_rows[1:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 1, 3)

        self.assertEqual(self.code_rows[2:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 10, 1)

        self.assertEqual(self.code_rows[:-1], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 7, 4)

        self.assertEqual(self.code_rows[:-2], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 5, 3)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:3] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 5, 5)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:4] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[0:1]
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 1, 1)

        self.assertEqual(self.code_rows[1:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.code_rows[0:1] + self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[0:2]
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 1, 3)

        self.assertEqual(self.code_rows[2:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.code_rows[0:2] + self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[-1:]
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 10, 1)

        self.assertEqual(self.code_rows[:-1], self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[-1:]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[-2:]
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 7, 4)

        self.assertEqual(self.code_rows[:-2], self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[-2:]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[2:3]
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 5, 3)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:3] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[2:3]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[2:4]
        self.disassembly_uncertain_reference_modification(self, disassembly.DATA_TYPE_CODE, disassembly.DATA_TYPE_LONGWORD, 5, 5)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:4] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[2:4]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)


if __name__ == "__main__":
    unittest.main()