"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

"""
Unit testing.
"""

import logging
import new
import os
import random
import sys
import types
import unittest

from PySide import QtCore, QtGui

import disassembly
import disassembly_data
import editor_state
import qtui
import toolapi
import loaderlib


class CORE_ProgramData_TestCase(unittest.TestCase):
    def setUp(self):
        self.program_data = disassembly_data.ProgramData()

    def test_state_initialisation(self):
        """Program data requires a program to be loaded, so starts in the loading state."""
        self.assertEqual(self.program_data.state, disassembly_data.STATE_LOADING)

    def test_state_modification(self):
        """Program data gets it's state set to loaded when the program is finished loading."""
        disassembly_data.program_data_set_state(self.program_data, disassembly_data.STATE_LOADED)
        self.assertEqual(self.program_data.state, disassembly_data.STATE_LOADED)


class TOOL_ProjectCompatibility_TestCase(unittest.TestCase):
    def setUp(self):
        self.toolapiob = toolapi.ToolAPI()

    def tearDown(self):
        self.toolapiob.on_app_exit()

    def test_upgrade_v2_to_vCURRENT(self):
        if "TESTDATA_PATH" not in os.environ:
            self.fail("TESTDATA_PATH environment variable required")

        FILE_NAME = os.path.join(os.environ["TESTDATA_PATH"], "amiga", "project-compatibility", "gdbstop2.psproj")
        INPUT_FILE_NAME = os.path.join(os.environ["TESTDATA_PATH"], "amiga", "gdbstop")

        if not os.path.exists(FILE_NAME):
            self.fail("missing project file '%s'" % FILE_NAME)
        if not os.path.exists(INPUT_FILE_NAME):
            self.fail("missing input file '%s'" % INPUT_FILE_NAME)

        result = self.toolapiob.load_file(FILE_NAME, INPUT_FILE_NAME)
        if type(result) in types.StringTypes:
            self.fail("loading error ('%s')" % result)
        if type(result) is not tuple:
            self.fail("did not get correct load return value")

        # At this point, the project has been upgraded and loaded successfully.



class TOOL_ReferringAddresses_TestCase(unittest.TestCase):
    def setUp(self):
        self.toolapiob = toolapi.ToolAPI()

    def tearDown(self):
        self.toolapiob.on_app_exit()

    def test_bug_monam302_00004_reference(self):
        FILE_NAME = "samples/amiga-executable/MonAm302"
        if not os.path.exists(FILE_NAME):
            self.fail("binary file dependency not available")

        result = self.toolapiob.load_file(FILE_NAME)
        if type(result) in types.StringTypes:
            self.fail("loading error ('%s')" % result)
        if type(result) is not tuple:
            self.fail("did not get correct load return value")

        TARGET_ADDRESS = 0x4
        code_string = self.toolapiob.get_source_code_for_address(TARGET_ADDRESS)
        self.assertEqual("DC.L $4D4F4E20", code_string)

        referring_addresses = self.toolapiob.get_source_code_for_address(TARGET_ADDRESS)
        self.assertNotEqual(0, len(referring_addresses))

        for address in self.toolapiob.get_referring_addresses_for_address(TARGET_ADDRESS):
            code_string = self.toolapiob.get_source_code_for_address(address)
            self.assertNotEqual("MOVEA.L ($4).W, A6", code_string, "ExecBase absolute address being misinterpreted as a program segment reference")


class TOOL_UncertainReferenceModification_TestCase(unittest.TestCase):
    def setUp(self):
        self.toolapiob = toolapi.ToolAPI()

    def tearDown(self):
        self.toolapiob.on_app_exit()

    def test_bug_conqueror_4e0f6_data_to_code_leak_4e144_data_reference(self):
        FILE_NAME = "samples/amiga-binary/conqueror-game-load21000-entrypoint57B8A"
        if not os.path.exists(FILE_NAME):
            self.skipTest("binary file dependency not available")

        result = self.toolapiob.load_binary_file(FILE_NAME, loaderlib.constants.PROCESSOR_M680x0, 0x21000, 0x57B8A-0x21000)
        if type(result) in types.StringTypes:
            self.fail("loading error ('%s')" % result)
        if type(result) is not tuple:
            self.fail("did not get correct load return value")

        # At this point, we are ready to test the bug.
        TYPE_CHANGE_ADDRESS = 0x4e0f6
        LEAKED_REFERENCE_ADDRESS = 0x4e144

        self.assertNotEqual("code", self.toolapiob.get_data_type_for_address(TYPE_CHANGE_ADDRESS))

        # Verify that 0x4e144 is correctly in the list of uncertain data references.
        data_references = self.toolapiob.get_uncertain_data_references()
        for entry in data_references:
            if entry[0] == LEAKED_REFERENCE_ADDRESS:
                break
        else:
            self.fail("Unable to find a data reference at 0x%X", LEAKED_REFERENCE_ADDRESS)

        self.toolapiob.set_datatype(TYPE_CHANGE_ADDRESS, "code")
        self.assertEqual("code", self.toolapiob.get_data_type_for_address(TYPE_CHANGE_ADDRESS))

        # Is the given address still in the uncertain data reference list?
        data_references = self.toolapiob.get_uncertain_data_references()
        for entry in data_references:
            if entry[0] == LEAKED_REFERENCE_ADDRESS:
                self.fail("Found leaked data reference %s" % str(entry))
                break


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

            _sort_order = QtCore.Qt.SortOrder.AscendingOrder
            _sort_column1 = 0
            _sort_column2 = 0

            def _sort_list(self, _row_data):
                qtui.CustomItemModel._sort_list.im_func(self, _row_data)

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

        self.editor_client = EditorClient()
        self.editor_state = editor_state.EditorState()
        self.editor_state.register_client(self.editor_client)
        self.editor_state.get_uncertain_references_by_address.func_globals["disassembly"] = self.fake_disassembly_module

        self.uncertain_code_references_model = Model()
        self.uncertain_data_references_model = Model()

        self.code_rows = [ [1], [2], [5], [9], [10] ]
        self.uncertain_code_references_model._row_data = self.code_rows[:]
        self.data_rows = [ [3], [7], [8], [11] ]
        self.uncertain_data_references_model._row_data = self.data_rows[:]

        self.on_uncertain_reference_modification = qtui.MainWindow.on_uncertain_reference_modification.im_func
        self._remove_address_range_from_model = new.instancemethod(qtui.MainWindow._remove_address_range_from_model.im_func, self, self.__class__)
        self._add_rows_to_model = new.instancemethod(qtui.MainWindow._add_rows_to_model.im_func, self, self.__class__)
        # self._sort_list = new.instancemethod(qtui.MainWindow._sort_list.im_func, self, self.__class__)

    def tearDown(self):
        self.editor_state.get_uncertain_references_by_address.func_globals["disassembly"] = disassembly
        self.editor_state = None
        self.editor_client = None

    def test_leading_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 1, 1))

        self.assertEqual(self.code_rows[1:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 1, 3))

        self.assertEqual(self.code_rows[2:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 10, 1))

        self.assertEqual(self.code_rows[:-1], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 7, 4))

        self.assertEqual(self.code_rows[:-2], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_block_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 5, 3))

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:3] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_blocks_not_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = []
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 5, 5))

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:4] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        self.assertEqual(self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[0:1]
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 1, 1))

        self.assertEqual(self.code_rows[1:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.code_rows[0:1] + self.data_rows, self.uncertain_data_references_model._row_data)

    def test_leading_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[0:2]
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 1, 3))

        self.assertEqual(self.code_rows[2:], self.uncertain_code_references_model._row_data)
        self.assertEqual(self.code_rows[0:2] + self.data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[-1:]
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 10, 1))

        self.assertEqual(self.code_rows[:-1], self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[-1:]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_trailing_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[-2:]
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 7, 4))

        self.assertEqual(self.code_rows[:-2], self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[-2:]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_block_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[2:3]
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 5, 3))

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:3] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[2:3]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)

    def test_mid_blocks_bidirectional(self):
        self.fake_disassembly_module._next_uncertain_references = self.code_rows[2:4]
        self.on_uncertain_reference_modification(self, ("CODE", "DATA", 5, 5))

        ideal_code_rows = [ v for v in self.code_rows if v not in self.code_rows[2:4] ]
        self.assertEqual(ideal_code_rows, self.uncertain_code_references_model._row_data)
        ideal_data_rows = self.data_rows + self.code_rows[2:4]
        ideal_data_rows.sort()
        self.assertEqual(ideal_data_rows, self.uncertain_data_references_model._row_data)


if __name__ == "__main__":
    DISPLAY_LOGGING = False

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    if DISPLAY_LOGGING:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
    else:
        ch = logging.NullHandler()
    logger.addHandler(ch)

    if True:
        unittest.main()
    else:
        test_cases = [ v for v in globals().values() if type(v) is types.TypeType and issubclass(v, unittest.TestCase) ]
        for v in test_cases:
            suite = unittest.TestLoader().loadTestsFromTestCase(v)
            unittest.TextTestRunner(verbosity=2).run(suite)
