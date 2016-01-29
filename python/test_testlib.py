#

import copy
import logging
import os
import struct
import unittest

from disassemblylib import archm68k, util

import testlib.tool_assembler_vasm
import testlib.constants

#class BaseXXXTestCase(unittest.TestCase):
#    pass

def generate_unit_tests():
    arch = archm68k.ArchM68k()
    arch.set_operand_type_table(archm68k.operand_type_table)
    table_instructions = util.process_instruction_list(arch, archm68k.instruction_table)
    for i, t in enumerate(table_instructions):
        instruction_syntax, operand_syntaxes = arch.parse_instruction_syntax(t[util.II_NAME])
        instruction_flags = t[util.II_FLAGS]
        instruction_spec = util._make_specification(instruction_syntax)

        operand_specs = []
        for syntax in operand_syntaxes:
            operand_spec = copy.deepcopy(util._make_specification(syntax))
            operand_idx = arch.dict_operand_label_to_index.get(operand_spec.key, None)
            if operand_idx != None:
                v = arch.table_operand_types[operand_idx][util.EAMI_FORMAT]
                if v is not None:
                    # Need to resolve the operand string template.
                    if operand_spec.key == "Imm":
                        if "xxx" not in operand_spec.mask_char_vars:
                            z_value = operand_spec.mask_char_vars["z"]
                            operand_spec.mask_char_vars["xxx"] = z_value
                            del operand_spec.mask_char_vars["z"]
                        xxx_value = operand_spec.mask_char_vars["xxx"]
                        idx = xxx_value.find(".")
                        xxx_size_value = xxx_value[idx:]
                        operand_spec.mask_char_vars["xxx"] = arch.get_bounds(xxx_size_value)
                    elif operand_spec.key == "AR":
                        if "Rn" in operand_spec.mask_char_vars:
                            operand_spec.mask_char_vars["xxx"] = arch.get_bounds(v)
                        else:
                            raise RuntimeError("fixme")
                    else:
                        raise RuntimeError("unhandled operand spec=", operand_spec.key, v, "full=", syntax, "vars=", operand_spec.mask_char_vars)
                operand_specs.append((operand_spec, v))
            else:
                raise RuntimeError("cccc")

        def integrate_possible_values(possible_values, old_combinations, new_combinations):
            for combination in old_combinations:
                for value in possible_values:
                    combination_copy = combination[:]
                    combination_copy.append(value)
                    new_combinations.append(combination_copy)

        # Operand N will have N variations that need to be tested.
        # If there are M operands, then the total number of variations will be N[0]*N[1]*...*N[M-1]
        # So we start with the first operand's variations, then we extend with the seconds, and so on..
        operand_idx = 0
        combinations = [ [] ]
        while operand_idx < len(operand_specs):
            operand_spec, operand_format = operand_specs[operand_idx]
            combinations_temp = []

            if len(operand_spec.mask_char_vars):
                format_variations = [ operand_format ]
                for k, v in operand_spec.mask_char_vars.iteritems():
                    format_variations_temp = []
                    for format in format_variations:
                        if k in format:
                            if v is None:
                                raise RuntimeError("bad instruction, no bounds", operand_format, instruction_syntax, operand_syntaxes)
                            for bounding_value in v[1]:
                                format_variations_temp.append(format.replace(k, str(bounding_value)))
                        else:
                            raise RuntimeError("Key", k, "not in format", format)
                    format_variations = format_variations_temp
                # Each of the existing combinations will be combined with each of the values.
                integrate_possible_values(format_variations, combinations, combinations_temp)
            else:
                integrate_possible_values([ operand_spec.key ], combinations, combinations_temp)

            combinations = combinations_temp
            operand_idx += 1


        # Determine which CPU to tell the assembler to target.
        cpu_match_data = [
            (archm68k.IF_060, testlib.constants.CPU_MC60060),
            (archm68k.IF_040, testlib.constants.CPU_MC60040),
            (archm68k.IF_030, testlib.constants.CPU_MC60030),
            (archm68k.IF_020, testlib.constants.CPU_MC60020),
            (archm68k.IF_010, testlib.constants.CPU_MC60010),
            (archm68k.IF_000, testlib.constants.CPU_MC60000),
        ]
        cpu_id = None
        for mask, value in cpu_match_data:
            if instruction_flags & mask:
                cpu_id = value
                break
        else:
            raise RuntimeError("Failed to identify CPU from instruction flags")

        # Assemble each identified instruction variation and obtain the machine code for disassembler testing.
        asm = testlib.tool_assembler_vasm.Assembler()
        for combination in combinations:
            text = instruction_syntax +" "+ ",".join(combination)
            result = asm.compile_text("a: "+ text, cpu_id, testlib.constants.ASM_SYNTAX_MOTOROLA)
            if result is None:
                print "X", text
            else:
                print " ", text, [ hex(ord(c)) for c in result ]
        if i == 15:
            break

    # NOTE: This works.
    if False:
        asm = testlib.tool_assembler_vasm.Assembler()
        result = asm.compile_text("a: movem.w d0-d6/a0-a6,-(sp)", testlib.constants.CPU_MC60000, testlib.constants.ASM_SYNTAX_MOTOROLA)
        print [ hex(ord(c)) for c in result ]

        result = asm.compile_text("a: moveq #0,d0", testlib.constants.CPU_MC60000, testlib.constants.ASM_SYNTAX_MOTOROLA)
        print [ hex(ord(c)) for c in result ]


if __name__ == "__main__":
    DISPLAY_LOGGING = True

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if DISPLAY_LOGGING:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
    else:
        ch = logging.NullHandler()
    logger.addHandler(ch)

    generate_unit_tests()

    if False:
        unittest.main()
