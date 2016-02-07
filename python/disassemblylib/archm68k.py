"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.

----------------- RESEARCH NOTES -----------------

TODO: Detect F-Line instructions and understand what to do about them
From the X68000 TNT.x executable from the Tunnels and Trolls disk image.
                 FEDC BA9 876 543  210
0x6683A: 0xFF3C: 1111[111]100[111][100] cpSAVE 7, Imm
This is not a valid addressing mode, so would cause F-Line.

----------------- INSTRUCTION SIZES -----------------

  "=I+.z"                       ADDI, ANDI, CMPI, EORI, ORI, SUBI reads one or two words depending on whether size is B, W or L.
  "=I+.B"                       ANDI to CCR, BCHG, BCLR, BSET, BTST, EORI to CCR, ORI to CCR reads an extra word for the lower byte.
  "DISPLACEMENT:(xxx=v)"        BCC, BRA, BSR reads 0,1 or 2 extra words depending on its instruction word displacement value.
  "DISPLACEMENT:(xxx=I1.W)"     DBCC reads 1 extra word for 16-bit diplacement
  - unimplemented -             MOVEP reads 1 extra word for 16-bit diplacement
  - irrelevant -                JMP / JSR operand based ..... ignore
  "DISPLACEMENT:(xxx=I1.W)"     LINK.W reads 1 extra word
  "DISPLACEMENT:(xxx=I1.L)"     LINK.L reads 1 extra longword
  "RL:(xxx=I1.W)"               MOVEM

B:00, W:01, L:10 - ADDI, ADDQ, ADDX, ANDI, ASd, CLR, CMPI, CMPM, EORI, LSd, NEG, NEGx, NOT, ORI, ROd, ROXd, SUBI, SUBQ, SUBX, TST,
B:--, W:11, L:10 - CHK, MOVEA (handled case by case)
B:01, W:11, L:10 - MOVE (handled case by case)
B: -, W: 0, L: 1 - MOVEM (handled case by case)
???????????????? - DIVS, DIVU

"""

import cPickle
import logging
import os
import sys
import struct

from .util import *


logger = logging.getLogger("disassembler-m68k")


IF_000 = 1<<0
IF_010 = 1<<1
IF_020 = 1<<2
IF_030 = 1<<3
IF_040 = 1<<4
IF_060 = 1<<5
IF_PROCESSOR_MASK = (IF_000 | IF_010 | IF_020 | IF_030 | IF_040 | IF_060)

class ArchM68k(ArchInterface):
    constant_immediate_prefix = "#"
    constant_register_prefix = ""
    constant_binary_prefix = "%"
    constant_binary_suffix = ""
    constant_decimal_prefix = ""
    constant_decimal_suffix = ""
    constant_hexadecimal_prefix = "$"
    constant_hexadecimal_suffix = ""
    constant_comment_prefix = ";"

    constant_core_architecture_mask = IF_000
    constant_endian_types = ">"
    constant_word_size = 16
    constant_pc_offset = 2
    constant_operand_type_general_label = "EA"

    """
    constant_table_bits = [
        [ 8,  'B' ],
        [ 16, 'W' ],
        [ 32, 'L' ],
    ]
    """

    constant_table_condition_code_names = [
        "T",  # %0000
        "F",  # %0001
        "HI", # %0010
        "LS", # %0011
        "CC", # %0100
        "CS", # %0101
        "NE", # %0110
        "EQ", # %0111
        "VC", # %1000
        "VS", # %1001
        "PL", # %1010
        "MI", # %1011
        "GE", # %1100
        "LT", # %1101
        "GT", # %1110
        "LE", # %1111
    ]

    constant_table_size_names = [ "B", "W", "L" ]
    constant_table_direction_names = [ "R", "L" ]

    variable_endian_type = ">"

    def function_is_final_instruction(self, match, preceding_match=None):
        return match.specification.key in ("RTS", "RTR", "JMP", "BRA", "RTE")

    def function_get_match_addresses(self, match):
        # Is it an instruction that exits (RTS, RTR)?
        # Is it an instruction that conditionally branches (Bcc, Dbcc)?
        # Is it an instruction that branches and returns (JSR, BSR)?
        # Is it an instruction that jumps (BRA, JMP)?
        # Given a branch/jump address, have we seen it before?
        # Given a branch/jump address, should it be queued?
        # Given a branch/jump address, should it be done next?
        def _extract_address(match, opcode_idx):
            opcode = match.opcodes[opcode_idx]
            # Note that PC relative jumps are ignored, as the address may refer to leading offsets before referenced code.
            if opcode.key == "PCid16":
                return None # match.pc + self._signed_value(opcode.vars["D16"], 16), MAF_CERTAIN # JSR, JMP?
            elif opcode.key == "PCiId8":
                return None # match.pc + self._signed_value(opcode.vars["D8"], 16), MAF_CERTAIN # JSR, JMP?
            elif opcode.key in ("AbsL", "AbsW"): # JMP, JSR
                return opcode.vars["xxx"], MAF_ABSOLUTE_ADDRESS
            elif opcode.specification.key == DISPLACEMENT_OKEY: # JMP
                return match.pc + opcode.vars["xxx"], 0
            return None

        address = None
        flags = 0
        instruction_key = match.specification.key
        if instruction_key in ("RTS", "RTR"):
            pass
        elif instruction_key in ("JSR", "JMP"):
            result = _extract_address(match, 0)
            if result is not None:
                address, flags = result
        elif instruction_key in ("BSR", "BRA", "Bcc"): # DISPLACEMENT
            address = match.pc + match.opcodes[0].vars["xxx"]
        elif instruction_key == "DBcc":
            address = match.pc + match.opcodes[1].vars["xxx"]

        ret = {}
        if address is not None:
            ret[address] = (None, flags | MAF_CODE)
            return ret

        # Locate any general addressing modes which infer labels.
        # MAF_CERTAIN -> definitely should be mapped to labels.
        for i, opcode in enumerate(match.opcodes):
            if opcode.key == "PCid16":
                address = match.pc + self._signed_value(opcode.vars["D16"], 16)
                if address not in ret:
                    ret[address] = (i, MAF_CERTAIN)
            elif opcode.key == "PCiId8":
                address = match.pc + self._signed_value(opcode.vars["D8"], 16)
                if address not in ret:
                    ret[address] = (i, MAF_CERTAIN)
            elif opcode.key in ("AbsL", "AbsW"):
                address = opcode.vars["xxx"]
                if address not in ret:
                    ret[address] = (i, MAF_ABSOLUTE_ADDRESS)
            elif opcode.key == "Imm" and i == 0:
                # move.w #xxx, SR (no) / move.l #xxx, a0 (yes) / move.l #xxx, AR (yes)
                # Is the destination an address register?
                # Imm, AbsL; Imm, DR; Imm, AR
                address = opcode.vars["xxx"]
                bits = ret.get(address, (i, 0))
                bits = (bits[0], bits[1] | MAF_CONSTANT_VALUE)
                if True or match.specification.key != "MOVE.L":
                    if bits[1] & MAF_CODE != MAF_CODE:
                        bits = (bits[0], bits[1] | MAF_UNCERTAIN)
                ret[address] = bits
            elif opcode.key in ("PCiIdb", "PCiPost", "PrePCi"):
                logger.error("Unhandled opcode EA mode (680x0?): %s", opcode.key)

        return ret

    def function_get_instruction_string(self, instruction, vars):
        """ Get a printable representation of an instruction. """
        def _get_formatted_description(key, vars):
            description = key
            for var_name, var_value in vars.iteritems():
                description = description.replace(var_name, str(var_value))
            return description

        key = instruction.specification.key
        return _get_formatted_description(key, vars)

    def function_get_operand_string(self, instruction, operand, vars, lookup_symbol):
        """ Get a printable representation of an instruction operand. """
        def _get_formatted_ea_description(instruction, key, vars, lookup_symbol=None):
            pc = instruction.pc
            id = self.dict_operand_label_to_index[key]
            mode_format = self.table_operand_types[id][EAMI_FORMAT]
            reg_field = self.table_operand_types[id][EAMI_MATCH_FIELDS][EAMI_MATCH_REG]
            for k, v in vars.iteritems():
                if k == "D16" or k == "D8":
                    value = self._signed_value(vars[k], { "D8": 8, "D16": 16, }[k])
                    """ [ "PCid16",     "(D16,PC)",             "111",          "010",               "D16=+W",      "Program Counter Indirect with Displacement Mode", ],
                        [ "PCiId8",     "(D8,PC,Xn.z*S)",       "111",          "011",               "EW",          "Program Counter Indirect with Index (8-Bit Displacement) Mode", ],
                        [ "PCiIdb",     "(bd,PC,Xn.z*S)",       "111",          "011",               "EW",          "Program Counter Indirect with Index (Base Displacement) Mode", ],
                        [ "PCiPost",    "([bd,PC],Xn.s*S,od)",  "111",          "011",               "EW",          "Program Counter Memory Indirect Postindexed Mode", ],
                        [ "PrePCi",     "([bd,PC,Xn.s*S],od)",  "111",          "011",               "EW",          "Program Counter Memory Indirect Preindexed Mode", ], """
                    value_string = None
                    if key in ("PCid16", "PCiId8"):
                        value += pc
                        value_string = lookup_symbol(value)
                    if value_string is None:
                        value_string = signed_hex_string(self, value)
                    mode_format = mode_format.replace(k, value_string)
                elif k == "Rn":
                    Rn = vars["Rn"]
                    if reg_field == "Rn":
                        mode_format = mode_format.replace("Dn", "D"+str(Rn))
                        mode_format = mode_format.replace("An", "A"+str(Rn))
                    elif reg_field == Rn:
                        pass # TODO: Use to validate
                elif k == "xxx":
                    value = vars["xxx"]
                    is_absolute = key in ("Imm", "AbsL", "AbsW")
                    value_string = lookup_symbol(value, absolute_info=(pc-2, instruction.num_bytes))
                    if value_string is None:
                        value_string = "$%x" % value
                    mode_format = mode_format.replace("xxx",  value_string)
                else:
                    mode_format = mode_format.replace(k, str(v))
            return mode_format

        pc = instruction.pc
        key = operand.key
        if key is None:
            key = operand.specification.key
        if key == REGISTER_LIST_OKEY:
            # D0-D3/D7/A0-A2
            ranges = []
            for ri, mask in enumerate(operand.rl_bits):
                rsn = -1
                for rn in range(8):
                    if mask & (1 << rn):
                        # Note the start of a range.
                        if rsn == -1:
                            rsn = rn
                    elif rsn > -1:
                        ranges.append((ri, (rsn, rn-1)))
                        rsn = -1
                if rsn > -1:
                    ranges.append((ri, (rsn, rn)))
            s = ""
            for (i, (r0, rn)) in ranges:
                key = [ "DR", "AR" ][i]
                if len(s):
                    s += "/"
                s += _get_formatted_ea_description(instruction, key, {"Rn":r0})
                if r0 < rn:
                    s += "-"+ _get_formatted_ea_description(instruction, key, {"Rn":rn})
            return s
        elif key == DISPLACEMENT_OKEY:
            value = vars["xxx"]
            if instruction.specification.key[0:4] == "LINK":
                value_string = None
            else:
                value_string = lookup_symbol(instruction.pc + value)
            if value_string is None:
                value_string = signed_hex_string(self, value)
            return value_string
        elif key in SpecialRegisters:
            return key
        else:
            return _get_formatted_ea_description(instruction, key, vars, lookup_symbol=lookup_symbol)

    def function_disassemble_one_line(self, data, data_idx, data_abs_idx):
        return super(self.__class__, self).function_disassemble_one_line(data, data_idx, data_abs_idx)

    def function_disassemble_as_data(self, data, data_idx):
        # F-line instruction.
        if self._get_byte(data, data_idx)[0] & 0xF0 == 0xF0:
            return 2
        return 0

    def function_get_default_symbol_name(self, address, metadata):
        """
        'Resource'-style disassembly variable naming.
        See amiga-dev wiki page.  Link to be inserted here asap.
        """
        if metadata == "midinstruction":
            return "SYM%06X" % address
        elif metadata == "bounds":
            return "lbZ%06X" % address

        if metadata == "ascii":
            char = "A"
        elif metadata == "code":
            char = "C"
        elif metadata == "data08":
            char = "B"
        elif metadata == "data16":
            char = "W"
        elif metadata == "data32":
            char = "L"
        else:
            # Default to a character which means the unexpected case.
            char = "X"
            logger.error("Asked for label name at address %X with metadata %s", address, metadata)
        return "lb%s%06X" % (char, address)

    def create_duplicated_instruction_entries(self, entry, new_name, operands_string):
        """ This expands instructions with parameterised sizes into the individual sized variants. """
        new_entries = []
        for value, text in FmtTable:
            new_entry = entry[:]
            new_entry[II_MASK] = new_entry[II_MASK].replace("zz", _n2b(value, padded_length=2))
            new_entry[II_NAME] = new_name.replace(".z", "."+ text) + operands_string
            new_entries.append(new_entry)
        return new_entries

    def parse_instruction_syntax(self, instruction_syntax):
        bits = [ s.strip() for s in instruction_syntax.split(" ", 1) ]
        if len(bits) > 1:
            instruction_name, operand_syntax = bits
            operand_syntaxes = [ s.strip() for s in operand_syntax.split(",") ]
        else:
            instruction_name = instruction_syntax
            operand_syntaxes = []
        return instruction_name, operand_syntaxes

    def parse_operand_syntax(self, operand_syntax):
        return operand_syntax.split(":", 1)

    def get_bounds(self, s):
        if s in ("Dn", "An"):
            return ("n", (0, 7))
        elif s in ("D8", ".B"):
            return (s, (0, (1<<8)-1))
        elif s in ("D16", ".W"):
            return (s, (0, (1<<16)-1))

    def get_extra_words_for_size_char(self, size_char):
        # B (extracted from given word), W (extracted from given word), L (requires extra word)
        if size_char == "L":
            return 1
        return 0

    def _get_long(self, data, data_idx):
        return self._get_value(data, data_idx, 32, False)

    def _get_byte(self, data, data_idx):
        return self._get_value(data, data_idx, 8, False)

    def _get_data_by_size_char(self, data, idx, char):
        if char == "B":
            word, idx = self._get_word(data, idx)
            if word is None:
                return None, idx
            word &= 0xFF
            return word, idx
        elif char == "W":
            return self._get_word(data, idx)
        elif char == "L":
            return self._get_long(data, idx)

    def _decode_operand(self, data, data_idx, operand_idx, I, O):
        """
            data            The data stream.
            data_idx        The next read position in the data stream.
            operand_idx     The index of the current operand for the given instruction.
            I               Instruction match.
            O               Current operand for the given instruction.
        """
        def _data_word_lookup(data_words, text):
            """
            An instruction has N data words.  Something has defined it's value to be one of these, for a given size.
            e.g. A variable may refer to I1.W, which means the first data word.
            Note that extra/data words are effectively 1-indexed, as the 0 entry is for word read for the instruction.
            """
            size_idx = text.find(".")
            if size_idx > 0:
                size_char = text[size_idx+1]
                word_idx = int(text[1:size_idx])
                if size_char == "B":
                    if data_words[word_idx] & ~0xFF: return # Sanity check.
                    return data_words[word_idx] & 0xFF, 8
                elif size_char == "W":
                    return data_words[word_idx], 16
                elif size_char == "L":
                    return (data_words[word_idx] << 16) + data_words[word_idx+1], 32

        def _resolve_specific_ea_key(mode_bits, register_bits, operand_ea_mask):
            for i, line in enumerate(self.table_operand_types):
                if operand_ea_mask & (1 << i) and line[EAMI_MATCH_FIELDS][EAMI_MATCH_MODE] == mode_bits:
                    if line[EAMI_MATCH_FIELDS][EAMI_MATCH_REG] != "Rn" and line[EAMI_MATCH_FIELDS][EAMI_MATCH_REG] != register_bits:
                        continue
                    return line[EAMI_LABEL]

        if O.specification.key == REGISTER_LIST_OKEY:
            T2 = I.opcodes[1-operand_idx]
            word, size_char = _data_word_lookup(I.data_words, O.vars["xxx"])
            if word is None:
                logger.error("_decode_operand$%X: _data_word_lookup failure 1", I.pc)
                return None

            T2_key = T2.specification.key
            if T2_key == "EA":
                # Resolve which specific EA operand is in use.
                T2_key = self.dict_operand_index_to_label.get(T2.vars["mode"], None)
                if T2_key is None:
                    logger.debug("_decode_operand$%X: failed to resolve EA key mode:%%%s register:%%%s operand: %d instruction: %s ea_mask: %X",
                        I.pc, _n2b(T2.vars["mode"]), _n2b(T2.vars["register"]), operand_idx, I.specification.key, I.table_ea_masks[1-operand_idx])
                    return None

            if T2_key == "PreARi":
                mask = 0x8000
            else:
                mask = 0x0001

            dm = am = 0
            for i in range(16):
                if word & mask:
                    if i > 7: # a0-a7
                        am |= 1<<(i-8)
                    else: # d0-d7
                        dm |= 1<<i
                if mask == 0x0001:
                    word >>= 1
                else:
                    word <<= 1
            O.rl_bits = dm, am

            return data_idx
        elif O.specification.key == DISPLACEMENT_OKEY:
            value = O.vars["xxx"]
            if type(value) is str:
                value, bits = _data_word_lookup(I.data_words, value)
            else:
                bits = 8
                if value == 0:
                    bits = 16
                    value, data_idx = self._get_word(data, data_idx)
                elif value == 0xFF:
                    bits = 32
                    value, data_idx = self._get_long(data, data_idx)
            if value is None: # Disassembly failure
                logger.error("_decode_operand: Failed to obtain displacement offset")
                return None
            O.vars["xxx"] = self._signed_value(value, bits)
            return data_idx
        elif O.specification.key in SpecialRegisters:
            return data_idx

        # General EA possibility, or specific EA mode
        instruction_key = I.specification.key
        instruction_key4 = instruction_key[:4]
        operand_key = specific_key = O.specification.key

        if specific_key == "EA":
            specific_key = O.key = _resolve_specific_ea_key(O.vars["mode"], O.vars["register"], I.table_ea_masks[operand_idx])
            if specific_key is None:
                #logger.debug("_decode_operand$%X: %s unresolved EA key mode:%s register:%s", I.pc, I.specification.key, _n2b(O.vars["mode"]), _n2b(O.vars["register"]))
                return None
            O.vars["Rn"] = O.vars["register"]

        eam_line = self.table_operand_types[self.dict_operand_label_to_index[specific_key]]
        read_string = eam_line[EAMI_DATA_FIELDS][EAMI_DATA_READS]

        # Special case.
        if specific_key == "Imm":
            if operand_key == "EA": # The operand could be any of a range of EA depending on it's masked bits.
                size_char = O.vars.get("z", None)
                if size_char is None:
                    size_char = I.vars.get("z", None)
                    if size_char is None and instruction_key[-2:] in (".B", ".W", ".L"):
                        size_char = instruction_key[-1]
                        if size_char is None:
                            return None # Presumably an F-line instruction.

                value, data_idx = self._get_data_by_size_char(data, data_idx, size_char)
                if value is None: # Disassembly failure.
                    logger.debug("Failed to fetch EA/Imm data")
                    return None
                O.vars["xxx"] = value
            elif operand_key == "Imm" and "xxx" not in O.vars and "z" in O.vars:
                # This is a complete sized I+ reference, so convert it to an incomplete one for resolution below.
                z_value = O.vars["z"]
                O.vars["xxx"] = "I+.z"
                O.vars["z"] = z_value[3] # e.g. "B" from "I+.B"
            elif instruction_key4 in ("LSd.", "ASd.", "ROd.", "ROXd", "ADDQ", "SUBQ"):
                # These operations serve no purpose with 0, so the range is shifted from 0-7 to 1-8 by remapping 0.
                if O.vars["xxx"] == 0:
                    O.vars["xxx"] = 8

        if O.vars.get("xxx", None) == "I+.z":
            # An incomplete I+ reference that needs to be resolved with a 'z' lookup.
            value, data_idx = self._get_data_by_size_char(data, data_idx, O.vars["z"])
            if value is None: # Disassembly failure.
                logger.debug("Failed to fetch xxx/I+.z data")
                return None
            O.vars["xxx"] = value

        # Different EA modes may cause extra data to be read, to populate specified variables.
        if read_string:
            if read_string == "EW":
                ew1, data_idx = self._get_word(data, data_idx)
                if ew1 is None: # Disassembly failure.
                    logger.debug("Failed to extension word1")
                    return None

                register_type = get_masked_value_for_variable(ew1, EffectiveAddressingWordMask, "r")
                register_number = get_masked_value_for_variable(ew1, EffectiveAddressingWordMask, "R")
                index_size = get_masked_value_for_variable(ew1, EffectiveAddressingWordMask, "z")
                scale = get_masked_value_for_variable(ew1, EffectiveAddressingWordMask, "X")
                full_extension_word = get_masked_value_for_variable(ew1, EffectiveAddressingWordMask, "t")
                # Xn.z*S
                O.vars["Xn"] = ["D", "A"][register_type] + str(register_number)
                O.vars["z"] = ["W", "L"][index_size]
                O.vars["S"] = [1,2,4,8][scale]

                if full_extension_word:
                    ew2, data_idx = self._get_word(data, data_idx)
                    base_register_suppressed = get_masked_value_for_variable(ew1, EffectiveAddressingWordFullMask, "b")
                    index_suppressed = get_masked_value_for_variable(ew1, EffectiveAddressingWordFullMask, "i")
                    base_displacement_size = get_masked_value_for_variable(ew1, EffectiveAddressingWordFullMask, "B")
                    index_selection = get_masked_value_for_variable(ew1, EffectiveAddressingWordFullMask, "I")
                    # ...
                    base_displacement = 0
                    if base_displacement_size == 2: # %10
                        base_displacement, data_idx = self._get_word(data, data_idx)
                    elif base_displacement_size == 3: # %11
                        base_displacement, data_idx = self._get_long(data, data_idx)
                    if base_displacement is None: # Disassembly failure.
                        return None
                    # TODO: Finish implementation.
                    logger.debug("%X: Skipping full extension word for instruction '%s'", I.pc-2, I.specification.key)
                    return None
                    # raise RuntimeError("Full displacement incomplete", I.specification.key)
                else:
                    O.vars["D8"] = get_masked_value_for_variable(ew1, EffectiveAddressingWordBriefMask, "v")
            elif read_string.find("=I+.") != -1:
                # Inject an extra word (or long) value under the given key as an available variable.
                k, v = [ s.strip() for s in read_string.split("=") ]
                size_char = v[3]
                value, data_idx = self._get_data_by_size_char(data, data_idx, size_char)
                if value is None: # Disassembly failure.
                    logger.error("Failed to read extra size char")
                    return None
                O.vars[k] = value
            else:
                # Has to be "EW" or "I+.<W|L>"
                raise RuntimeError("Bad operand table EAMI_DATA_READS value.")
        return data_idx


def get_size_value(label):
    if label == "B": return 0
    if label == "W": return 1
    if label == "L": return 2

FmtTable = [
    [ _b2n("00"), "B" ],
    [ _b2n("01"), "W" ],
    [ _b2n("10"), "L" ],
]

REGISTER_LIST_OKEY = "RL"
DISPLACEMENT_OKEY = "DISPLACEMENT"

SpecialRegisters = ("CCR", "SR")
CustomOperandLabels = (REGISTER_LIST_OKEY, DISPLACEMENT_OKEY)

# r: index register type (0: Dn, 1: An)
# R: register number
# z: word/long index size (0: sign-extended word, 1: long word)
# X: scale (00: 1, 01: 2, 10: 4, 11: 8)
# t: extension word type (0: brief, 1: full)
EffectiveAddressingWordMask = "rRRRzXXt00000000"
# v: displacement
EffectiveAddressingWordBriefMask = "00000000vvvvvvvv"
# b: base register suppress (0: base register added, 1: base register suppressed)
# i: index suppress (0: evaluate and add index operand, 1: suppress index operand)
# B: base displacement size (00: reserved, 01: null displacement, 10: word displacement, 11: long word displacement)
# I: Index/indirect selection (
EffectiveAddressingWordFullMask =  "00000000biBB0III"

# Mode field:           m68k effective address matching.
EAMI_MATCH_MODE = 0
# Register field:       m68k effective address matching.
EAMI_MATCH_REG = 1

# No. extension words:  m68k effective address value used if matched.
EAMI_DATA_READS = 0

operand_type_table = [
    # Syntax,        Formatting                        Match fields                      Data fields     Description
    #                                          Mode field       Register field     No. extension words
    [ "DR",         "Dn",                   [ _b2n("000"),          "Rn",     ],    [ 0,          ],     "Data Register Direct Mode", ],
    [ "AR",         "An",                   [ _b2n("001"),          "Rn",     ],    [ 0,          ],     "Address Register Direct Mode", ],
    [ "ARi",        "(An)",                 [ _b2n("010"),          "Rn",     ],    [ 0,          ],     "Address Register Indirect Mode", ],
    [ "ARiPost",    "(An)+",                [ _b2n("011"),          "Rn",     ],    [ 0,          ],     "Address Register Indirect Mode with Postincrement Mode", ],
    [ "PreARi",     "-(An)",                [ _b2n("100"),          "Rn",     ],    [ 0,          ],     "Address Register Indirect Mode with Preincrement Mode", ],
    [ "ARid16",     "(D16,An)",             [ _b2n("101"),          "Rn",     ],    [ "D16=I+.W", ],     "Address Register Indirect Mode with Displacement Mode", ],
    [ "ARiId8",     "(D8,An,Xn.z*S)",       [ _b2n("110"),          "Rn",     ],    [ "EW",       ],     "Address Register Indirect with Index (8-Bit Displacement) Mode", ],
    [ "ARiIdb",     "(bd,An,Xn.z*S)",       [ _b2n("110"),          "Rn",     ],    [ "EW",       ],     "Address Register Indirect with Index (Base Displacement) Mode", ],
    [ "MEMiPost",   "([bd,An],Xn.z*S,od)",  [ _b2n("110"),          "Rn",     ],    [ "EW",       ],     "Memory Indirect Postindexed Mode", ],
    [ "PreMEMi",    "([bd,An,Xn.z*S],od)",  [ _b2n("110"),          "Rn",     ],    [ "EW",       ],     "Memory Indirect Preindexed Mode", ],
    [ "PCid16",     "(D16,PC)",             [ _b2n("111"),       _b2n("010"), ],    [ "D16=I+.W", ],     "Program Counter Indirect with Displacement Mode", ],
    [ "PCiId8",     "(D8,PC,Xn.z*S)",       [ _b2n("111"),       _b2n("011"), ],    [ "EW",       ],     "Program Counter Indirect with Index (8-Bit Displacement) Mode", ],
    [ "PCiIdb",     "(bd,PC,Xn.z*S)",       [ _b2n("111"),       _b2n("011"), ],    [ "EW",       ],     "Program Counter Indirect with Index (Base Displacement) Mode", ],
    [ "PCiPost",    "([bd,PC],Xn.s*S,od)",  [ _b2n("111"),       _b2n("011"), ],    [ "EW",       ],     "Program Counter Memory Indirect Postindexed Mode", ],
    [ "PrePCi",     "([bd,PC,Xn.s*S],od)",  [ _b2n("111"),       _b2n("011"), ],    [ "EW",       ],     "Program Counter Memory Indirect Preindexed Mode", ],
    [ "AbsW",       "(xxx).W",              [ _b2n("111"),       _b2n("000"), ],    [ "xxx=I+.W", ],     "Absolute Short Addressing Mode", ],
    [ "AbsL",       "(xxx).L",              [ _b2n("111"),       _b2n("001"), ],    [ "xxx=I+.L", ],     "Absolute Long Addressing Mode", ],
    [ "Imm",        "#xxx",                 [ _b2n("111"),       _b2n("100"), ],    [ 0,          ],     "Immediate Data", ],
]

def extend_operand_type_table():
    dummy_operand_line = [ None ] * len(operand_type_table[0])

    for label in SpecialRegisters:
        l = dummy_operand_line[:]
        l[EAMI_LABEL] = label
        l[EAMI_DESCRIPTION] = "Special Register "+ label
        operand_type_table.append(l)

    for label in CustomOperandLabels:
        l = dummy_operand_line[:]
        l[EAMI_LABEL] = label
        l[EAMI_DESCRIPTION] = "Special Operand Type "+ label
        operand_type_table.append(l)

extend_operand_type_table()

# z=I+.[BWL]                Force size to one byte, read as lower byte of following word.
# xxx=I+.z                  Read a value from the following words, with the size obtained from the 'z' size field.
# xxx=In.[WL]               Starting with the nth word after the instruction word, use the word or longword at that point.
# <varname1>=+-<varname2>   Convert the value from unsigned to signed.

instruction_table = [
    [ "1100DDD100000SSS", "ABCD DR:(Rn=S),DR:(Rn=D)",       IF_000, "Add Decimal With Extend (register)", ],
    [ "1100DDD100001SSS", "ABCD PreARi:(Rn=S),PreARi:(Rn=D)",      IF_000, "Add Decimal With Extend (memory)", ],
    [ "1101DDD0zzsssSSS", "ADD.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",             IF_000, "Add", ],
    [ "1101DDD1zzsssSSS", "ADD.z:(z=z) DR:(Rn=D), EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",             IF_000, "Add", ],
    [ "1101DDD011sssSSS", "ADDA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",                     IF_000, "Add Address", ],
    [ "1101DDD111sssSSS", "ADDA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",                     IF_000, "Add Address", ],
    [ "00000110zzsssSSS", "ADDI.z:(z=z) Imm:(z=z&xxx=I+.z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",                       IF_000, "Add Immediate", ],
    [ "0101vvv0zzsssSSS", "ADDQ.z:(z=z) Imm:(xxx=v), EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",                       IF_000, "Add Immediate", ],
    [ "1101DDD1zz000SSS", "ADDX.z:(z=z) DR:(Rn=S),DR:(Rn=D)",       IF_000, "Add Extended (register)", ],
    [ "1101DDD1zz001SSS", "ADDX.z:(z=z) PreARi:(Rn=S),PreARi:(Rn=D)",      IF_000, "Add Extended (memory)", ],
    [ "1100DDD0zzsssSSS", "AND.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",                        IF_000, "AND Logical (EA->DR)", ],
    [ "1100DDD1zzsssSSS", "AND.z:(z=z) DR:(Rn=D), EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",                        IF_000, "AND Logical (DR->EA)", ],
    [ "00000010zzsssSSS", "ANDI.z:(z=z) Imm:(z=z&xxx=I+.z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "AND Immediate", ],
    [ "0000001000111100", "ANDI Imm:(z=I+.B), CCR",      IF_000, "CCR AND Immediate", ],
    [ "1110vvvazz000DDD", "ASd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",       IF_000, "Arithmetic Shift (register rotate, source immediate)", ],
    [ "1110SSSazz100DDD", "ASd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",       IF_000, "Arithmetic Shift (register rotate, source register)", ],
    [ "1110000a11sssSSS", "ASd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Arithmetic Shift (memory rotate)", ],
    [ "0110ccccvvvvvvvv", "Bcc:(cc=c) DISPLACEMENT:(xxx=v)",       IF_000|IFX_BRANCH, "Branch Conditionally", ],
    [ "0000DDD101sssSSS", "BCHG DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Change (register bit number)", ],
    [ "0000100001sssSSS", "BCHG Imm:(z=I+.B), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Change (static bit number)", ],
    [ "0000DDD110sssSSS", "BCLR DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Clear (register bit number)", ],
    [ "0000100010sssSSS", "BCLR Imm:(z=I+.B), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Clear (static bit number)", ],
    [ "0100100001001vvv", "BKPT Imm:(xxx=v)",  IF_010|IF_020|IF_030|IF_040, "Breakpoint", ],
    [ "01100000vvvvvvvv", "BRA DISPLACEMENT:(xxx=v)",       IF_000|IFX_BRANCH, "Branch Always", ],
    [ "0000DDD111sssSSS", "BSET DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Set (register bit number)", ],
    [ "0000100011sssSSS", "BSET Imm:(z=I+.B), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Set (static bit number)", ],
    [ "01100001vvvvvvvv", "BSR DISPLACEMENT:(xxx=v)",       IF_000|IFX_BRANCH, "Branch to Subroutine", ],
    [ "0000DDD100sssSSS", "BTST DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}",      IF_000, "Test a Bit (register bit number)", ],
    [ "0000100000sssSSS", "BTST Imm:(z=I+.B), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",      IF_000, "Test a Bit (static bit number)", ],
    [ "0100DDD110sssSSS", "CHK.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",       IF_000, "Check Register Against Bounds", ],
    [ "0100DDD100sssSSS", "CHK.L EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",       IF_000, "Check Register Against Bounds", ],
    [ "01000010zzsssSSS", "CLR.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Clear an Operand", ],
    [ "1011DDD0zzsssSSS", "CMP.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",       IF_000, "Compare", ],
    [ "1011DDD011sssSSS", "CMPA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",      IF_000, "Compare Address", ],
    [ "1011DDD111sssSSS", "CMPA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",      IF_000, "Compare Address", ],
    [ "00001100zzsssSSS", "CMPI.z:(z=z) Imm:(z=z&xxx=I+.z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",      IF_000, "Compare Immediate", ],
    [ "1011DDD1zz001SSS", "CMPM.z:(z=z) ARiPost:(Rn=S), ARiPost:(Rn=D)",      IF_000, "Compare Memory", ],
    [ "0101cccc11001DDD", "DBcc:(cc=c) DR:(Rn=D), DISPLACEMENT:(xxx=I1.W)",      IF_000|IFX_BRANCH, "Test Condition, Decrement, and Branch", ],
    [ "1000DDD111sssSSS", "DIVS.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Signed Divide", ],
    [ "1000DDD011sssSSS", "DIVU.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Unsigned Divide", ],
    [ "1011DDDvvvsssSSS", "EOR DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Exclusive-OR Logical", ],
    [ "00001010zzsssSSS", "EORI.z:(z=z) Imm:(z=z&xxx=I+.z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Exclusive-OR Immediate", ],
    [ "0000101000111100", "EORI Imm:(z=I+.B), CCR",      IF_000, "Exclusive-OR Immediate to Condition Code", ],
    [ "1100SSS101000DDD", "EXG DR:(Rn=S), DR:(Rn=D)",       IF_000, "Exchange Registers (data)", ],
    [ "1100SSS101001DDD", "EXG AR:(Rn=S), AR:(Rn=D)",       IF_000, "Exchange Registers (address)", ],
    [ "1100SSS110001DDD", "EXG DR:(Rn=S), AR:(Rn=D)",       IF_000, "Exchange Registers (address and data)", ],
    [ "0100100010000DDD", "EXT.W DR:(Rn=D)",       IF_000, "Sign-Extend", ],
    [ "0100100011000DDD", "EXT.L DR:(Rn=D)",       IF_000, "Sign-Extend", ],
    [ "0100101011111100", "ILLEGAL",   IF_000, "Take Illegal Instruction Trap", ],
    [ "0100111011sssSSS", "JMP EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",       IF_000, "Jump", ],
    [ "0100111010sssSSS", "JSR EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",       IF_000, "Jump to Subroutine", ],
    [ "0100DDD111sssSSS", "LEA EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}, AR:(Rn=D)",       IF_000, "Load Effective Address", ],
    [ "101000000000vvvv", "LINEA Imm:(xxx=v)",      IF_000, "A-Line", ],
    [ "0100111001010SSS", "LINK.W AR:(Rn=S), DISPLACEMENT:(xxx=I1.W)",      IF_000, "Link and Allocate (word)", ],
    [ "0100100000001SSS", "LINK.L AR:(Rn=S), DISPLACEMENT:(xxx=I1.L)",      IF_000, "Link and Allocate (long)", ],
    [ "1110vvvazz001DDD", "LSd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",       IF_000, "Logical Shift (register shifts, source immediate)", ],
    [ "1110SSSazz101DDD", "LSd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",       IF_000, "Logical Shift (register shifts, source register)", ],
    [ "1110001a11sssSSS", "LSd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Logical Shift (register memory)", ],
    [ "0001DDDdddsssSSS", "MOVE.B EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, EA:(mode=d&register=D){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}", IF_000, "Move Data from Source to Destination", ],
    [ "0011DDDdddsssSSS", "MOVE.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, EA:(mode=d&register=D){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}", IF_000, "Move Data from Source to Destination", ],
    [ "0010DDDdddsssSSS", "MOVE.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, EA:(mode=d&register=D){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}", IF_000, "Move Data from Source to Destination", ],
    [ "0011DDD001sssSSS", "MOVEA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8},AR:(Rn=D)",     IF_000, "Move Address", ],
    [ "0010DDD001sssSSS", "MOVEA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8},AR:(Rn=D)",     IF_000, "Move Address", ],
    [ "0100001011sssSSS", "MOVE.W CCR, EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Move from the Condition Code Register", ],
    [ "0100010011sssSSS", "MOVE.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, CCR",      IF_000, "Move to Condition Code Register", ],
    [ "0100000011sssSSS", "MOVE.W SR, EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Move from the Status Register", ],
    [ "0100011011sssSSS", "MOVE.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, SR",      IF_000, "Move to the Status Register", ],
    ## 040 [ "1111011000100DDD", "MOVE16", IF_000, "Move 16-Byte Block (post increment)", ],
    [ "1111011000000DDD", "MOVE16 ARiPost:(Dn=D), AbsL",          IF_040, "Move 16-Byte Block (absolute)", ],
    [ "1111011000001DDD", "MOVE16 AbsL, ARiPost:(Dn=D)",          IF_040, "Move 16-Byte Block (absolute)", ],
    [ "1111011000010DDD", "MOVE16 ARi:(Dn=D), AbsL",              IF_040, "Move 16-Byte Block (absolute)", ],
    [ "1111011000011DDD", "MOVE16 AbsL, ARi:(Dn=D)",              IF_040, "Move 16-Byte Block (absolute)", ],
    [ "0100100010sssSSS", "MOVEM.W RL:(xxx=I1.W), EA:(mode=s&register=S){ARi|PreARi|ARid16|ARiId8|AbsW|AbsL}",     IF_000, "Move Multiple Registers", ],
    [ "0100100011sssSSS", "MOVEM.L RL:(xxx=I1.W), EA:(mode=s&register=S){ARi|PreARi|ARid16|ARiId8|AbsW|AbsL}",     IF_000, "Move Multiple Registers", ],
    [ "0100110010sssSSS", "MOVEM.W EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}, RL:(xxx=I1.W)",     IF_000, "Move Multiple Registers", ],
    [ "0100110011sssSSS", "MOVEM.L EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}, RL:(xxx=I1.W)",     IF_000, "Move Multiple Registers", ],
    [ "0000DDD100001SSS", "MOVEP.W ARid16:(Rn=S), DR:(Rn=D)",     IF_000, "Move Peripheral Data (memory to register)", ],
    [ "0000DDD101001SSS", "MOVEP.L ARid16:(Rn=S), DR:(Rn=D)",     IF_000, "Move Peripheral Data (memory to register)", ],
    [ "0000DDD110001SSS", "MOVEP.W DR:(Rn=D), ARid16:(Rn=S)",     IF_000, "Move Peripheral Data (register to memory)", ],
    [ "0000DDD111001SSS", "MOVEP.L DR:(Rn=D), ARid16:(Rn=S)",     IF_000, "Move Peripheral Data (register to memory)", ],
    [ "0111DDD0vvvvvvvv", "MOVEQ Imm:(v=v&xxx=v.s8), DR:(Rn=D)",          IF_000, "Move Quick", ],
    [ "1100DDD111sssSSS", "MULS.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Signed Multiply", ],
    [ "1100DDD011sssSSS", "MULU.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Unsigned Multiply", ],
    [ "0100100000sssSSS", "NBCD EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Negate Decimal With Extend (register)", ],
    [ "01000100zzsssSSS", "NEG.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Negate", ],
    [ "01000000zzsssSSS", "NEGX.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Negate with Extend", ],
    [ "0100111001110001", "NOP",       IF_000, "No Operation", ],
    [ "01000110zzsssSSS", "NOT.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Logical Complement", ],
    [ "1000DDD0zzsssSSS", "OR.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",        IF_000, "Inclusive-OR Logical (EA->DR)", ],
    [ "1000DDD1zzsssSSS", "OR.z:(z=z) DR:(Rn=D), EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",        IF_000, "Inclusive-OR Logical (DR->EA)", ],
    [ "00000000zzsssSSS", "ORI.z:(z=z) Imm:(z=z&xxx=I+.z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Inclusive-OR", ],
    [ "0000000000111100", "ORI.B Imm:(z=I+.B), CCR",              IF_000, "Inclusive-OR Immediate to Condition Codes", ],
    [ "0000000001111100", "ORI.W Imm:(z=I+.W), SR",               IF_000, "Inclusive-OR Immediate to Status Register", ],
    [ "0100100001sssSSS", "PEA EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",       IF_000, "Push Effective Address", ],
    [ "0100111001110000", "RESET",     IF_000, "Reset External Devices", ],
    [ "1110vvvazz011DDD", "ROd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",       IF_000, "Rotate without Extend (register rotate, source immediate)", ],
    [ "1110SSSazz111DDD", "ROd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",       IF_000, "Rotate without Extend (register rotate, source register)", ],
    [ "1110011a11sssSSS", "ROd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Rotate without Extend (memory rotate)", ],
    [ "1110vvvazz010DDD", "ROXd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",      IF_000, "Rotate with Extend (register rotate, source immediate)", ],
    [ "1110SSSazz110DDD", "ROXd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",      IF_000, "Rotate with Extend (register rotate, source register)", ],
    [ "1110010a11sssSSS", "ROXd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Rotate with Extend (memory rotate)", ],
    [ "0100111001110011", "RTE",       IF_000, "Return from Exception", ],
    [ "0100111001110111", "RTR",       IF_000, "Return and Restore Condition Codes", ],
    [ "0100111001110101", "RTS",       IF_020, "Return from Subroutine", ],
    [ "1000DDD100000SSS", "SBCD DR:(Rn=S),DR:(Rn=D)",       IF_000, "Add Decimal With Extend (register)", ],
    [ "1000DDD100001SSS", "SBCD PreARi:(Rn=S),PreARi:(Rn=D)",      IF_000, "Add Decimal With Extend (memory)", ],
    [ "0101cccc11sssSSS", "Scc:(cc=c) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Set According to Condition", ],
    [ "0100111001110010", "STOP Imm:(xxx=I1.W)",    IF_000, "Load Register Status and Stop", ],
    [ "1001DDD0zzsssSSS", "SUB.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8},DR:(Rn=D)",       IF_000, "Subtract", ],
    [ "1001DDD1zzsssSSS", "SUB.z:(z=z) DR:(Rn=D),EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Subtract", ],
    [ "1001DDD011sssSSS", "SUBA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",      IF_000, "Subtract Address (word)", ],
    [ "1001DDD111sssSSS", "SUBA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",      IF_000, "Subtract Address (long)", ],
    [ "00000100zzsssSSS", "SUBI.z:(z=z) Imm:(z=z&xxx=I+.z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Subtract Immediate", ],
    [ "0101vvv1zzsssSSS", "SUBQ.z:(z=z) Imm:(xxx=v), EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Subtract Quick", ],
    [ "1001DDD1zz000SSS", "SUBX.z:(z=z) DR:(Rn=S), DR:(Rn=D)",      IF_000, "Subtract with Extend (data registers)", ],
    [ "1001DDD1zz001SSS", "SUBX.z:(z=z) PreARi:(Rn=S), PreARi:(Rn=S)",      IF_000, "Subtract with Extend (PreARi)", ],
    [ "0100100001000SSS", "SWAP DR:(Rn=S)",      IF_000, "Swap Register Halves", ],
    [ "0100101011sssSSS", "TAS EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Test and Set an Operand", ],
    [ "010011100100vvvv", "TRAP Imm:(xxx=v)",      IF_000, "Trap", ],
    [ "0100111001110110", "TRAPV",     IF_000, "Trap on Overflow", ],
    [ "01001010zzsssSSS", "TST.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}",       IF_000, "Test an Operand", ],
    [ "0100111001011SSS", "UNLK AR:(Rn=S)",      IF_000, "Unlink", ],
    # 020, 030
    # These clash with f-line instructions.
    #[ "1111vvv101sssSSS", "cpRESTORE Imm:(xxx=v), EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}", IF_020|IF_030, "Coprocessor Restore Functions", ],
    #[ "1111vvv100sssSSS", "cpSAVE Imm:(xxx=v), EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL}", IF_020|IF_030, "Coprocessor Restore Functions", ],
    #1111___01z______ cpBcc
    #1111___001001SSS cpDBcc
    #1111___000sssSSS cpGEN
    #1111___001sssSSS cpScc
    #1111___001111xxx cpTRAPcc
]
