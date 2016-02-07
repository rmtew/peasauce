# This needs to lie outside the disassemblylib directory because of Python's arbitrary
# decision to limit relative importing to "packages".

import logging
import os
import struct
import unittest

from disassemblylib import archmips, archm68k, util


class BaseArchTestCase(unittest.TestCase):
    pass


class ArchmipsTestCase(BaseArchTestCase):
    def setUp(self):
        self.arch = archmips.ArchMIPS()
        self.arch.set_operand_type_table(archmips.operand_type_table)
        self.arch.set_instruction_table(archmips.instruction_table)

        self.test_data1 = "\x20\x01\x00\x0A"
        self.test_data1_entrypoint = 0x100

    def tearDown(self):
        pass

    def testDisassembly(self):
        # Check that the match gives the expected PC address.
        match, data_idx = self.arch.function_disassemble_one_line(self.test_data1, 0, self.test_data1_entrypoint)
        self.assertEquals(match.pc, self.test_data1_entrypoint + self.arch.constant_pc_offset)

        # Check that the match has the expected data words.
        bytes_per_instruction_word = int(self.arch.constant_word_size/8.0)
        data_word = struct.unpack(self.arch.variable_endian_type +"I", self.test_data1[0:bytes_per_instruction_word])[0]
        self.assertListEqual(match.data_words, [ data_word ])

        # Check that the instruction is identified correctly.
        self.assertEquals("ADDI", self.arch.function_get_instruction_string(match, match.vars))
        # Check that the right number of operands are present.
        self.assertEquals(len(match.opcodes), 3)

        self.arch.function_get_operand_string(match, match.opcodes[0], match.opcodes[0].vars)
        self.arch.function_get_operand_string(match, match.opcodes[1], match.opcodes[1].vars)
        self.arch.function_get_operand_string(match, match.opcodes[2], match.opcodes[2].vars)


class Archm68kTestCase(BaseArchTestCase):
    def setUp(self):
        self.arch = archm68k.ArchM68k()

    def tearDown(self):
        pass

    def testInstructionParsing(self):
        self.arch.set_operand_type_table(archm68k.operand_type_table)
        util.process_instruction_list(self.arch, archm68k.instruction_table)

    def testInstructions(self):
        self.arch.set_operand_type_table(archm68k.operand_type_table)
        self.arch.set_instruction_table(archm68k.instruction_table)

        # moveq #<v>, d0
        for op1value, binary_data in ((1, "\x70\x01"), (100, "\x70\x64"), (-100, "\x70\x9C"), (-1, "\x70\xFF")):
            match, next_data_idx = self.arch.function_disassemble_one_line(binary_data, 0, 0)
            self.assertEquals("MOVEQ", self.arch.function_get_instruction_string(match, match.vars))
            self.assertEquals(len(match.opcodes), 2)
            def lookup_symbol(address, absolute_info=None): return str(address)
            value = self.arch.function_get_operand_string(match, match.opcodes[0], match.opcodes[0].vars, lookup_symbol)
            self.assertEquals(value, "#%d" % op1value)
            register_name = self.arch.function_get_operand_string(match, match.opcodes[1], match.opcodes[1].vars, lookup_symbol)
            self.assertEquals(register_name, "D0")

        # movem.w d0-d3/a1/a6,-(a7)
        binary_data = "\x48\xA7\xF0\x42"
        match, next_data_idx = self.arch.function_disassemble_one_line(binary_data, 0, 0)
        self.assertEquals("MOVEM.W", self.arch.function_get_instruction_string(match, match.vars))
        self.assertEquals(len(match.opcodes), 2)
        operand1 = self.arch.function_get_operand_string(match, match.opcodes[0], match.opcodes[0].vars, lookup_symbol)
        self.assertEquals(operand1, "D0-D3/A1/A6")
        operand2 = self.arch.function_get_operand_string(match, match.opcodes[1], match.opcodes[1].vars, lookup_symbol)
        self.assertEquals(operand2, "-(A7)")

        # movem.w (a4)+, a0-a3/a5/d1-d4
        binary_data = "\x4C\x9C\x2F\x1E"
        match, next_data_idx = self.arch.function_disassemble_one_line(binary_data, 0, 0)
        self.assertEquals("MOVEM.W", self.arch.function_get_instruction_string(match, match.vars))
        self.assertEquals(len(match.opcodes), 2)
        operand1 = self.arch.function_get_operand_string(match, match.opcodes[0], match.opcodes[0].vars, lookup_symbol)
        self.assertEquals(operand1, "(A4)+")
        operand2 = self.arch.function_get_operand_string(match, match.opcodes[1], match.opcodes[1].vars, lookup_symbol)
        self.assertEquals(operand2, "D1-D4/A0-A3/A5")



class UtilFunctionalityTestCase(unittest.TestCase):
    mask1_template_string = "L01MMMM001110TTT"
    mask1M_bit_string     = "0001111000000000"
    mask1T_bit_string     = "0000000000000111"
    mask1L_bit_string     = "1000000000000000"
    mask1L_shift = 15
    mask1M_shift = 9
    mask1T_shift = 0
    mask1M_base_mask_string = "1111"
    mask1T_base_mask_string = "111"
    mask1L_base_mask_string = "1"

    def test_get_mask_and_shift_from_mask_string(self):
        # When the mask character is not present.
        mask, shift = util.get_mask_and_shift_from_mask_string(self.mask1_template_string, "c")
        self.assertEqual(mask, 0)
        self.assertEqual(shift, 0)

        # When the mask character is leading.
        mask, shift = util.get_mask_and_shift_from_mask_string(self.mask1_template_string, "L")
        self.assertEqual(mask, util._b2n(self.mask1L_bit_string))
        self.assertEqual(shift, self.mask1L_shift)

        # When the mask character is mid-string.
        mask, shift = util.get_mask_and_shift_from_mask_string(self.mask1_template_string, "M")
        self.assertEqual(mask, util._b2n(self.mask1M_bit_string))
        self.assertEqual(shift, self.mask1M_shift)

        # When the mask character is trailing.
        mask, shift = util.get_mask_and_shift_from_mask_string(self.mask1_template_string, "T")
        self.assertEqual(mask, util._b2n(self.mask1T_bit_string))
        self.assertEqual(shift, self.mask1T_shift)

    def test_get_masked_value_for_variable(self):
        # When the mask character is not present.
        value = util.get_masked_value_for_variable(0x00000000, self.mask1_template_string, "c")
        self.assertEqual(value, 0)
        value = util.get_masked_value_for_variable(0xFFFFFFFF, self.mask1_template_string, "c")
        self.assertEqual(value, 0)

        # When the value fits in the masked area.
        mask_chars = ("L", "M", "T") # leading.. mid ..trailing.
        mask_char_strings = (self.mask1L_base_mask_string, self.mask1M_base_mask_string, self.mask1T_base_mask_string)
        for input_value in (0x00000000, 0xFFFFFFFF):
            for i, input_mask_char in enumerate(mask_chars):
                extracted_value = util.get_masked_value_for_variable(input_value, self.mask1_template_string, input_mask_char)
                if input_value == 0:
                    expected_value = 0
                else:
                    expected_value = util._b2n(mask_char_strings[i])
                self.assertEqual(extracted_value, expected_value)

    def test_set_masked_value_for_variable(self):
        test_data = [
            ("L", self.mask1L_bit_string, self.mask1L_base_mask_string),
            ("M", self.mask1M_bit_string, self.mask1M_base_mask_string),
            ("T", self.mask1T_bit_string, self.mask1T_base_mask_string),
        ]
        for mask_char, bit_string, base_mask_string in test_data:
            mask, shift = util.get_mask_and_shift_from_mask_string(self.mask1_template_string, mask_char)
            mask_value = util._b2n(base_mask_string)
            # Test setting those bits to a value they will always accept (1).
            resulting_value = util.set_masked_value_for_variable(0, self.mask1_template_string, mask_char, 1)
            self.assertTrue(resulting_value >> shift, 1)
            # Test setting a value that won't fit in the available bit range.
            self.assertRaises(ValueError, util.set_masked_value_for_variable, 0, self.mask1_template_string, mask_char, mask_value+1)

    test_cases_gmvfv = [ ("L", util._b2n("1")), ("M", util._b2n("101")), ("T", util._b2n("10")) ]

    def test_get_masked_values_for_variables_specific(self):
        # Whether specified variables are all extracted.
        #                  L01MMMM001110TTT
        value = util._b2n("1010101010101010")
        variable_chars = [ "L", "M", "T" ]
        char_vars = util.get_masked_values_for_variables(value, self.mask1_template_string, variable_chars)
        self.assertEqual(len(variable_chars), len(char_vars), "failed to find all expected variables")

        for var_char, var_value in self.test_cases_gmvfv:
            self.assertTrue(var_char in char_vars, "var '%s' not present" % var_char)
            self.assertEqual(char_vars[var_char], var_value, "%s != %s" % (char_vars[var_char], var_value))

    def test_get_masked_values_for_variables_all(self):
        # Whether all variables present are extracted.
        #                  L01MMMM001110TTT
        value = util._b2n("1010101010101010")
        char_vars = util.get_masked_values_for_variables(value, self.mask1_template_string)

        self.assertEqual(len(self.test_cases_gmvfv), len(char_vars), "failed to find all expected variables")
        for var_char, var_value in self.test_cases_gmvfv:
            self.assertTrue(var_char in char_vars, "var '%s' not present" % var_char)
            self.assertEqual(char_vars[var_char], var_value, "%s != %s" % (char_vars[var_char], var_value))

    def test_binary2number(self):
        self.assertTrue(util._b2n("1") == 1)
        self.assertTrue(util._b2n("10") == (1<<1))
        self.assertTrue(util._b2n("11") == (1<<1) + 1)
        self.assertTrue(util._b2n("11111111") == 0xFF)
        self.assertTrue(util._b2n("11110000") == 0xF0)
        self.assertTrue(util._b2n("00000000") == 0x00)

    def test_number2binary(self):
        self.assertTrue(util._n2b(1) == "1")
        self.assertTrue(util._n2b(7) == "111")
        self.assertTrue(util._n2b(255) == "11111111")
        self.assertTrue(util._n2b(254) == "11111110")
        self.assertTrue(util._n2b(256) == "100000000")

    def test_number2binary_padded(self):
        """ Padded out to multiples of 4 bits (octets). """
        self.assertTrue(util._n2b(1, dynamic_padding=True) == "0001")
        self.assertTrue(util._n2b(15, dynamic_padding=True) == "1111")
        self.assertTrue(util._n2b(16, dynamic_padding=True) == "00010000")
        self.assertTrue(util._n2b(255, dynamic_padding=True) == "11111111")

    def test_number2binary_padded_length(self):
        self.assertTrue(util._n2b(util._b2n("1"), padded_length=2) == "01")
        self.assertTrue(util._n2b(util._b2n("1"), padded_length=3) == "001")
        for text in ("111", "001", "00001111"):
            value = util._b2n(text)
            self.assertTrue(util._n2b(value, padded_length=len(text)) == text)


if __name__ == "__main__":
    DISPLAY_LOGGING = True

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    if DISPLAY_LOGGING:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
    else:
        ch = logging.NullHandler()
    logger.addHandler(ch)

    unittest.main()
