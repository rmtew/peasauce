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
import editor_state
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
            _next_uncertain_references = None

            def get_uncertain_references_by_address(self, program_data, address):
                result = self._next_uncertain_references
                self._next_uncertain_references = None
                return result

        class DisassemblyData(object):
            pass

        self.fake_disassembly_module = fake_disassembly_module = DisassemblyModule()
        self.disassembly_data = disassembly_data = DisassemblyData()

        if False:
            class EditorState(object):
                def get_uncertain_references_by_address(self, address):
                    return fake_disassembly_module.get_uncertain_references_by_address(disassembly_data, address)

        class EditorClient(object):
            def reset_state(self):
                pass

        self.editor_state = editor_state.EditorState(EditorClient())
        self.editor_state.get_uncertain_references_by_address.func_globals["disassembly"] = self.fake_disassembly_module

        self.uncertain_code_references_model = Model()
        self.uncertain_data_references_model = Model()

        self.code_rows = [ [1], [2], [5], [9], [10] ]
        self.uncertain_code_references_model._row_data = self.code_rows[:]
        self.data_rows = [ [3], [7], [8], [11] ]
        self.uncertain_data_references_model._row_data = self.data_rows[:]

        self.disassembly_uncertain_reference_modification = qtui.MainWindow.disassembly_uncertain_reference_modification.im_func

    def test_leading_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 1, 1)

        self.assertEqual(self.code_rows[1:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 1, 3)

        self.assertEqual(self.code_rows[2:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 10, 1)

        self.assertEqual(self.code_rows[:-1], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 7, 4)

        self.assertEqual(self.code_rows[:-2], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 5, 3)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:3] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 5, 5)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:4] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[0:1]
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 1, 1)

        self.assertEqual(self.code_rows[1:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.code_rows[0:1] + self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[0:2]
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 1, 3)

        self.assertEqual(self.code_rows[2:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.code_rows[0:2] + self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[-1:]
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 10, 1)

        self.assertEqual(self.code_rows[:-1], self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[-1:]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[-2:]
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 7, 4)

        self.assertEqual(self.code_rows[:-2], self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[-2:]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[2:3]
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 5, 3)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:3] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[2:3]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[2:4]
        self.disassembly_uncertain_reference_modification(self, "CODE", "DATA", 5, 5)

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:4] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[2:4]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)


if __name__ == "__main__":
    unittest.main()