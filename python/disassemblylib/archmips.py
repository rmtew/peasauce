"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013, 2014 Richard Tew
    Licensed using the MIT license.
"""

# TODO: Implement create_duplicated_instruction_entries(entry)
# - p322-323.  

import logging

from .util import *

logger = logging.getLogger("disassembler-mips")

# Abstraction ideas:
## There are instruction flags for different subarchitectures, but there's always a core architecture.
### IF_MIPS32R2/IF_MIPS64/... -> IF_MIPS32
### IF_010/IF_020/... -> IF_000
## All subarchitectures implicitly get the core architecture instructions.

IF_MIPS32     = 1<<0
IF_MIPS32R2   = 1<<1
IF_MIPS64     = 1<<2
IF_SMARTMIPS  = 1<<3
IF_EJTAG      = 1<<4

class ArchMIPS(ArchInterface):
    constant_immediate_prefix = ""
    constant_register_prefix = "$"
    constant_binary_prefix = "%"
    constant_binary_suffix = ""
    constant_decimal_prefix = ""
    constant_decimal_suffix = ""
    constant_hexadecimal_prefix = "0x"
    constant_hexadecimal_suffix = ""
    constant_comment_prefix = "#"

    constant_core_architecture_mask = IF_MIPS32
    constant_operand_count_max = 4
    
    def function_is_final_instruction(cls, *args, **kwargs):
        pass

    def function_get_match_addresses(cls, *args, **kwargs):
        pass

    def function_get_instruction_string(cls, *args, **kwargs):
        pass
       
    def function_get_operand_string(cls, *args, **kwargs):
        pass
       
    def function_disassemble_one_line(cls, *args, **kwargs):
        pass
        
    def function_disassemble_as_data(cls, *args, **kwargs):
        pass
        
    def function_get_default_symbol_name(cls, *args, **kwargs):
        pass

    def create_duplicated_instruction_entries(self, entry, new_name, operands_string):
        if entry[II_MASK].startswith("010001"): # COP1 instruction
            fmt_table = cop1_fmt_table
            match = "zzzzz" # bits 25..21
        elif entry[II_MASK].startswith("010011"): # COP1X instruction
            fmt_table = cop1x_fmt_table
            match = "zzz" # bits 0..2
        else:
            logger.error("create_duplicated_instruction_entries: invalid call")
            return []

        new_entries = []
        for value, text in fmt_table:
            new_entry = entry[:]
            new_entry[II_MASK] = new_entry[II_MASK].replace(match, _n2b(value, padded_length=len(match)))
            new_entry[II_NAME] = new_name.replace(".z", "."+ text) + operands_string
            new_entries.append(new_entry)
        return new_entries
        
    

# TODO: The m68k instruction list does some sort of ordering and ambiguity detection, can this be generalised?

def PLACEHOLDER_get_fpr_label(num):
    return "$f%d" % num

def PLACEHOLDER_get_gpr_label(num):
    return "$%d" % num

def PLACEHOLDER_get_gpr_name(num):
    return "$"+ {
        0: "zero", # static: Always contains the value 0.
        1: "at",
        2: "v0",
        3: "v1",
        4: "a0",
        5: "a1",
        6: "a2",
        7: "a3",
        8: "t0",
        9: "t1",
        10: "t2",
        11: "t3",
        12: "t4",
        13: "t5",
        14: "t6",
        15: "t7",
        16: "s0",
        17: "s1",
        18: "s2",
        19: "s3",
        20: "s4",
        21: "s5",
        22: "s6",
        23: "s7",
        24: "t8",
        25: "t9",
        26: "k0",
        27: "k1",
        28: "gp",
        29: "sp",
        30: "fp",
        31: "ra",
    }[num]


# FMT:
#   COP1: 0x10: 10000: .S: 
#   COP1: 0x11: 10001: .D: 
#   COP1: 0x14: 10100: .W:
#   COP1: 0x15: 10101: .L: 
#   COP1: 0x16: 10110: .PS: 

fp_cond_table = [
    [ _b2n("00000"), "F", ],
    [ _b2n("00001"), "UN", ],
    [ _b2n("00010"), "EQ", ],
    [ _b2n("00011"), "UEQ", ],
    [ _b2n("00100"), "OLT", ],
    [ _b2n("00101"), "ULT", ],
    [ _b2n("00110"), "OLE", ],
    [ _b2n("00111"), "ULE", ],
    [ _b2n("10000"), "SF", ],
    [ _b2n("10001"), "NGLE", ],
    [ _b2n("10010"), "SEQ", ],
    [ _b2n("10011"), "NGL", ],
    [ _b2n("10100"), "LT", ],
    [ _b2n("10101"), "NGE", ],
    [ _b2n("10110"), "LE", ],
    [ _b2n("10111"), "NGT", ],
]

cop1_fmt_table = [
    [ 0x10, "S"  ],
    [ 0x11, "D"  ],
    [ 0x14, "W"  ],
    [ 0x15, "L"  ],
    [ 0x16, "PS" ],
]

cop1x_fmt_table = [
    [ 0x0, "S" ],
    [ 0x1, "D" ],
    [ 0x4, "W" ],
    [ 0x5, "L" ],
    [ 0x6, "PS" ],
]

EAMI_MATCH_X = 0
EAMI_DATA_X = 0

# Q. How are raw formatted values displayed as for example, labels?  Or NGT instead of CC?
# A. See m68 and answer.
# Q. How are row formatted values displayed as specified variants, $gp instead of $28?  Or SP instead of A7?
# A. See m68 and answer.

operand_type_table = [
    # Syntax,        Formatting   Match fields  Data fields     Description
    [ "GPR",          "Rn",           [ ],    [           ],  "General purpose register", ],
    [ "FPR",          "fRn",          [ ],    [           ],  "Floating point register", ],
    [ "Imm",          "xxx",          [ ],    [           ],  "Numeric value", ],
    [ "PCRegion",     "xxx",          [ ],    [           ],  "Offset is combined with the high bits of the address of the current instruction", ],
    [ "PCRelative",   "xxx",          [ ],    [           ],  "Offset relative to the address of the next instruction", ],
    [ "GPRRelative",  "xxx(Rn)",      [ ],    [           ],  "Offset is combined with the register", ],
    [ "CC",           "xxx",          [ ],    [           ],  "Condition", ],
]

instruction_table = [
    [ "010001zzzzz00000sssssddddd000101", "ABS.z:(z=z)      FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Absolute Value" ],
    [ "000000ssssstttttddddd00000100000", "ADD              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", 0, "Add Word" ],
    [ "010001zzzzztttttsssssddddd000000", "ADD.z:(z=z)      FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Add" ],
    [ "001000ssssstttttvvvvvvvvvvvvvvvv", "ADD              GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", 0, "Add Immediate Word" ],
    [ "001000ssssstttttvvvvvvvvvvvvvvvv", "ADDIU            GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", 0, "Add Immediate Unsigned Word" ],
    [ "000000ssssstttttddddd00000100001", "ADDIU            GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", 0, "Add Unsigned Word" ],
    [ "010011rrrrrtttttsssssddddd000001", "ALNV.PS          FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t), rr", 0, "Floating Point Align Variable" ],
    [ "000000ssssstttttddddd00000100100", "AND              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", 0, "And" ],
    [ "001100ssssstttttvvvvvvvvvvvvvvvv", "ANDI             GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", 0, "And Immediate Word" ],
    [ "0001000000000000vvvvvvvvvvvvvvvv", "B                PCRelative:(xxx=v)", 0, "Unconditional Branch" ],
    [ "0000010000010001vvvvvvvvvvvvvvvv", "BAL              PCRelative:(xxx=v)", 0, "Branch And Link" ],
    [ "01000101000ccc00vvvvvvvvvvvvvvvv", "BC1F             cc, PCRelative:(xxx=v)", 0, "Branch on FP False" ],
    [ "01000101000ccc10vvvvvvvvvvvvvvvv", "BC1FL            cc, PCRelative:(xxx=v)", 0, "Branch on FP False Likely" ],
    [ "01000101000ccc01vvvvvvvvvvvvvvvv", "BC1T             cc, PCRelative:(xxx=v)", 0, "Branch on FP True" ],
    [ "01000101000ccc11vvvvvvvvvvvvvvvv", "BC1TL            cc, PCRelative:(xxx=v)", 0, "Branch on FP True Likely" ],
    [ "01001001000ccc00vvvvvvvvvvvvvvvv", "BC2F             cc, PCRelative:(xxx=v)", 0, "Branch on COP2 False" ],
    [ "01001001000ccc10vvvvvvvvvvvvvvvv", "BC2FL            cc, PCRelative:(xxx=v)", 0, "Branch on COP2 False Likely" ],
    [ "01001001000ccc01vvvvvvvvvvvvvvvv", "BC2T             cc, PCRelative:(xxx=v)", 0, "Branch on COP2 True" ],
    [ "01001001000ccc11vvvvvvvvvvvvvvvv", "BC2TL            cc, PCRelative:(xxx=v)", 0, "Branch on COP2 True Likely" ],
    [ "000100ssssstttttvvvvvvvvvvvvvvvv", "BEQ              GPR:(Rn=s), GPR:(Rn=t), PCRelative:(xxx=v)", 0, "Branch on Equal" ],
    [ "010100ssssstttttvvvvvvvvvvvvvvvv", "BEQL             GPR:(Rn=s), GPR:(Rn=t), PCRelative:(xxx=v)", 0, "Branch on Equal Likely" ],
    [ "000001sssss00001vvvvvvvvvvvvvvvv", "BGEZ             GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Greater Than or Equal to Zero" ],
    [ "000001sssss00011vvvvvvvvvvvvvvvv", "BGEZL            GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Greater Than or Equal to Zero Likely" ],
    [ "000001sssss10001vvvvvvvvvvvvvvvv", "BGEZAL           GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Greater Than or Equal to Zero and Link" ],
    [ "000001sssss10011vvvvvvvvvvvvvvvv", "BGEZALL          GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Greater Than or Equal to Zero and Link Likely" ],
    [ "000111sssss00000vvvvvvvvvvvvvvvv", "BGTZ             GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Greater Than Zero" ],
    [ "010111sssss00000vvvvvvvvvvvvvvvv", "BGTZL            GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Greater Than Zero Likely" ],
    [ "000110sssss00000vvvvvvvvvvvvvvvv", "BLEZ             GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Less Than or Equal to Zero" ],
    [ "010110sssss00000vvvvvvvvvvvvvvvv", "BLEZL            GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Less Than or Equal to Zero Likely" ],
    [ "000001sssss00000vvvvvvvvvvvvvvvv", "BLTZ             GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Less Than Zero" ],
    [ "000001sssss00010vvvvvvvvvvvvvvvv", "BLTZL            GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Less Than Zero Likely" ],
    [ "000001sssss10000vvvvvvvvvvvvvvvv", "BLTZAL           GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Less Than Zero and Link" ],
    [ "000001sssss10010vvvvvvvvvvvvvvvv", "BLTZALL          GPR:(Rn=s), PCRelative:(xxx=v)", 0, "Branch on Less Than Zero and Link Likely" ],
    [ "000101ssssstttttvvvvvvvvvvvvvvvv", "BNE              GPR:(Rn=s), GPR:(Rn=t), PCRelative:(xxx=v)", 0, "Branch on Not Equal" ],
    [ "010101ssssstttttvvvvvvvvvvvvvvvv", "BNEL             GPR:(Rn=s), GPR:(Rn=t), PCRelative:(xxx=v)", 0, "Branch on Not Equal Likely" ],
    [ "000000vvvvvvvvvvvvvvvvvvvv001101", "BREAK",              0, "Branch on Not Equal Likely" ],
    [ "010001zzzzztttttsssssccc0011ffff", "C.f.z:(z=z,f=f)  cc, FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Compare" ],
    [ "101111bbbbbooooovvvvvvvvvvvvvvvv", "CACHE            op, v+b", 0, "Perform Cache Operation" ],
    [ "010001zzzzz00000sssssddddd001010", "CEIL.L.z:(z=z)   FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Ceiling Convert to Long Fixed Point" ],
    [ "010001zzzzz00000sssssddddd001110", "CEIL.W.z:(z=z)   FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Ceiling Convert to Word Fixed Point" ],
    [ "01000100010tttttsssss00000000000", "CFC1             FPR:(Rn=t), FPR:(Rn=s)", 0, "Move Control Word From Floating Point" ],
    [ "01001000010tttttdddddddddddddddd", "CFC2             FPR:(Rn=t), FPR:(Rn=d)", 0, "Move Control Word From Coprocessor 2" ],
    [ "011100ssssstttttddddd00000100001", "CLO              FPR:(Rn=t), FPR:(Rn=s)", 0, "Count Leading Ones In Word" ],
    [ "011100ssssstttttddddd00000100000", "CLZ              FPR:(Rn=d), FPR:(Rn=s)", 0, "Count Leading Zeroes In Word" ],
    [ "0100101vvvvvvvvvvvvvvvvvvvvvvvvv", "COP2             Imm:(v=v)", 0, "Coprocessor Operation To Coprocessor 2" ],
    [ "01000100110tttttsssss00000000000", "CTC1             GPR:(Rn=t), FPR:(Rn=s)", 0, "Move Control Word To Floating Point" ],
    [ "01001000110tttttdddddddddddddddd", "CTC2             GPR:(Rn=t), GPR:(Rn=d)", 0, "Move Control Word To Coprocessor 2" ],
    [ "010001zzzzz00000sssssddddd100101", "CVT.D.z:(z=z)    FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert to Double Floating Point" ],
    [ "01000110000tttttsssssddddd100110", "CVT.PS.S         FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Convert Pair to Paired Single" ],
    [ "010001zzzzz00000sssssddddd100000", "CVT.S.z:(z=z)    FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert to Single Floating Point" ],
    [ "0100011011000000sssssddddd101000", "CVT.S.PL         FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert Pair Lower to Single Floating Point" ],
    [ "0100011011000000sssssddddd100000", "CVT.S.PU         FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert Pair Upper to Single Floating Point" ],
    [ "010001zzzzz00000sssssddddd100100", "CVT.W.z:(z=z)    FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert to Word Floating Point" ],
    [ "01000010000000000000000000011111", "DERET",              0, "Debug Exception Return" ],
    [ "01000001011ttttt0110000000000000", "DI               GPR:(Rn=t)", 0, "Disable Interrupts" ], # TODO "DI" / rt implicit
    [ "000000sssssttttt0000000000011010", "DIV              GPR:(Rn=s), GPR:(Rn=t)", 0, "Divide Word" ],
    [ "010001zzzzztttttsssssddddd000011", "DIV.z:(z=z)      FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Divide" ],
    [ "000000sssssttttt0000000000011011", "DIVU             GPR:(Rn=s), GPR:(Rn=t)", 0, "Divide Unsigned Word" ],
    [ "00000000000000000000000011000000", "EHB",                0, "Execution Hazard Barrier" ],
    [ "01000001011ttttt0110000000100000", "EI               GPR:(Rn=t)", 0, "Enable Interrupts" ],
    [ "01000010000000000000000000011000", "ERET",               0, "Exception Return" ],
    [ "011111ssssstttttmmmmmbbbbb011010", "EXT              GPR:(Rn=t), GPR:(Rn=s), pos:(v=m), size:(v=b)", 0, "Extract Bit Field" ],
    [ "010001zzzzz00000sssssddddd001011", "FLOOR.L.z:(z=z)  FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32R2|IF_MIPS64, "Floating Point Floor Convert to Long Fixed Point" ],
    [ "010001zzzzz00000sssssddddd001111", "FLOOR.W.z:(z=z)  FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Floor Convert to Word Fixed Point" ],
    [ "011111ssssstttttmmmmmbbbbb000100", "INS              GPR:(Rn=t), GPR:(Rn=s), pos:(v=m), size:(v=b)", IF_MIPS32R2, "Insert Bit Field" ],
    [ "000010vvvvvvvvvvvvvvvvvvvvvvvvvv", "J                PCRegion:(xxx=v)", IF_MIPS32, "Jump" ],
    [ "000011vvvvvvvvvvvvvvvvvvvvvvvvvv", "JAL              PCRegion:(xxx=v)", IF_MIPS32, "Jump And Link" ],
    [ "000000sssss00000dddddhhhhh001001", "JALR             GPR:(Rn=d), GPR:(Rn=s)", IF_MIPS32, "Jump And Link Register" ], # if rd==31, then rd is omitted and implied as that
    [ "000000sssss00000ddddd1hhhh001001", "JALR.HB          GPR:(Rn=d), GPR:(Rn=s)", IF_MIPS32R2, "Jump And Link Register With Hazard Barrier" ], # if rd==31, then rd is omitted and implied as that
    [ "000000sssss0000000000hhhhh001000", "JR               GPR:(Rn=s)", IF_MIPS32, "Jump Register" ],
    [ "000000sssss00000000001hhhh001000", "JR.HB            GPR:(Rn=s)", IF_MIPS32R2, "Jump Register With Hazard Barrier" ],
    [ "100000bbbbbtttttvvvvvvvvvvvvvvvv", "LB               GPR:(Rn=t), v+b", IF_MIPS32, "Load Byte" ], #TODO: v+b is more complicated
    [ "100100bbbbbtttttvvvvvvvvvvvvvvvv", "LBU              GPR:(Rn=t), v+b", IF_MIPS32, "Load Byte Unsigned" ], #TODO: v+b is more complicated
    [ "110101bbbbbtttttvvvvvvvvvvvvvvvv", "LDC1             FPR:(Rn=t), v+b", IF_MIPS32, "Load Double Word to Floating Point" ], #TODO: v+b is more complicated
    [ "110110bbbbbtttttvvvvvvvvvvvvvvvv", "LDC2             GPR:(Rn=t), v+b", IF_MIPS32, "Load Double Word to Coprocessor 2" ], #TODO: v+b is more complicated
    [ "010011bbbbbiiiii00000ddddd000001", "LDXC1            FPR:(Rn=d), i+b", IF_MIPS32R2|IF_MIPS64, "Load Double Word Indexed to Floating Point" ], #TODO: v+b is more complicated
    [ "100001bbbbbtttttvvvvvvvvvvvvvvvv", "LH               GPR:(Rn=t), v+b", IF_MIPS32, "Load Halfword" ], #TODO: v+b is more complicated
    [ "100101bbbbbtttttvvvvvvvvvvvvvvvv", "LHU              GPR:(Rn=t), v+b", IF_MIPS32, "Load Halfword Unsigned" ], #TODO: v+b is more complicated
    [ "110000bbbbbtttttvvvvvvvvvvvvvvvv", "LL               GPR:(Rn=t), v+b", IF_MIPS32, "Load Linked Word" ], #TODO: v+b is more complicated
    [ "00111100000tttttvvvvvvvvvvvvvvvv", "LUI              GPR:(Rn=t), v", IF_MIPS32, "Load Upper Immediate" ],
    [ "010011bbbbbiiiii00000ddddd000101", "LUXC1            FPR:(Rn=d), i+b", IF_MIPS32R2|IF_MIPS64, "Load Double Word Indexed Unaligned to Floating Point" ], #TODO: v+b is more complicated
    [ "100011bbbbbtttttvvvvvvvvvvvvvvvv", "LW               GPR:(Rn=t), v+b", IF_MIPS32, "Load Word" ], #TODO: v+b is more complicated
    [ "110001bbbbbtttttvvvvvvvvvvvvvvvv", "LWC1             FPR:(Rn=t), v+b", IF_MIPS32, "Load Word to Floating Point" ], #TODO: v+b is more complicated
    [ "110010bbbbbtttttvvvvvvvvvvvvvvvv", "LWC2             GPR:(Rn=t), v+b", IF_MIPS32, "Load Word to Coprocessor 2" ], #TODO: v+b is more complicated
    [ "100010bbbbbtttttvvvvvvvvvvvvvvvv", "LWL              GPR:(Rn=t), v+b", IF_MIPS32, "Load Word Left" ], #TODO: v+b is more complicated
    [ "100010bbbbbtttttvvvvvvvvvvvvvvvv", "LWR              GPR:(Rn=t), v+b", IF_MIPS32, "Load Word Right" ], #TODO: v+b is more complicated
    [ "010011bbbbbvvvvv00000ddddd000000", "LWXC1            FPR:(Rn=d), v+b", IF_MIPS32, "Load Word Indexed to Floating Point" ], #TODO: v+b is more complicated
    [ "011100sssssttttt0000000000000000", "MADD             GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply and Add Word to Hi,Lo" ],
    [ "010011rrrrrtttttsssssddddd100zzz", "MADD.z:(z=z)     FPR:(Rn=d), FPR:(Rn=r), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS32R2|IF_MIPS64, "Floating Point Multiply Add" ],
    [ "011100sssssttttt0000000000000001", "MADDU            GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply and Add Unsigned Word to Hi,Lo" ],
    [ "01000000000tttttddddd00000000vvv", "MFC0             GPR:(Rn=t), GPR:(Rn=d), sel:[v=v]", IF_MIPS32, "Move from Coprocessor 0" ],
    [ "01000100000tttttsssss00000000000", "MFC1             GPR:(Rn=t), FPR:(Rn=s), sel:[v=v]", IF_MIPS32, "Move Word from Floating Point" ],
    # [ "01001000000tttttvvvvvvvvvvvvvvvv", "MFC2      GPR:(Rn=t), GPR:(Rn=v), sel:[v=v]", IF_MIPS32, "Move Word from Coprocessor 2" ], # TODO: coprocessor custom sel/Rd from v.
    [ "01000100011tttttsssss00000000000", "MFHC1            GPR:(Rn=t), FPR:(Rn=s)", IF_MIPS32R2, "Move Word from High Half of Floating Point Register" ],
    # [ "01001000011tttttvvvvvvvvvvvvvvvv", "MFHC2     GPR:(Rn=t), FPR:(Rn=v), sel:[v=v]", IF_MIPS32R2, "Move Word from High Half of Coprocessor 2 Register" ], # TODO: coprocessor custom sel/Rd from v.
    [ "0000000000000000ddddd00000010000", "MFHI             GPR:(Rn=d)", IF_MIPS32, "Move from HI Register" ],
    [ "0000000000000000ddddd00000010010", "MFLO             GPR:(Rn=d)", IF_MIPS32, "Move from LO Register" ],
    [ "010001zzzzz00000sssssddddd000110", "MOV.z:(z=z)      FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Move" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "000000sssssvvv00ddddd00000000001", "MOVF             GPR:(Rn=d), GPR:(Rn=s), cc:[v=v]", IF_MIPS32, "Move Conditional on Floating Point False" ],
    [ "010001zzzzzvvv00sssssddddd010001", "MOVF.z:(z=z)     GPR:(Rn=d), GPR:(Rn=s), cc:[v=v]", IF_MIPS32, "Floating Point Move Conditional on Floating Point False" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "000000ssssstttttddddd00000001011", "MOVN             GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Move Conditional on Not Zero" ],
    [ "010001zzzzztttttsssssddddd010011", "MOVN.z:(z=z)     FPR:(Rn=d), FPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Floating Point Move Conditional on Not Zero" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "000000ssssszzz01ddddd00000000001", "MOVT             GPR:(Rn=d), GPR:(Rn=s), cc:[v=v]", IF_MIPS32, "Move Conditional on Floating Point True" ],
    [ "010001zzzzzvvv01sssssddddd010001", "MOVT.z:(z=z)     FPR:(Rn=d), FPR:(Rn=s), cc:[v=v]", IF_MIPS32, "Floating Point Move Conditional on Floating Point True" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "000000ssssstttttddddd00000001010", "MOVZ             GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Move Conditional on Zero" ],
    [ "010001zzzzztttttsssssddddd010010", "MOVZ.z:(z=z)     FPR:(Rn=d), FPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Floating Point Move Conditional on Zero" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "011100sssssttttt0000000000000100", "MSUB             GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply and Subtract Word to Hi,Lo" ],
    [ "010011rrrrrtttttsssssddddd101zzz", "MSUB.z:(z=z)     FPR:(Rn=d), FPR:(Rn=r), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS64, "Floating Point Multiply Subtract" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "011100sssssttttt0000000000000101", "MSUBU            GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply and Subtract Word to Hi,Lo" ],
    [ "01000000100tttttddddd00000000vvv", "MTC0             GPR:(Rn=t), GPR:(Rn=d), sel:[v=v]", IF_MIPS32, "Move to Coprocessor 0" ],
    [ "01000100100tttttsssss00000000000", "MTC1             GPR:(Rn=t), FPR:(Rn=s)", IF_MIPS32, "Move Word to Floating Point" ],
    # [ "01001000100tttttvvvvvvvvvvvvvvvv", "MTC2      GPR:(Rn=r), GPR:(Rn=d), sel:[v=v]", IF_MIPS32, "Move Word to Coprocessor 2" ], # TODO: coprocessor custom sel/Rd from v.
    [ "01000100111tttttsssss00000000000", "MTHC1            GPR:(Rn=t), FPR:(Rn=s)", IF_MIPS32R2, "Move Word to High Half of Floating Point Register" ],
    # [ "01001000111tttttvvvvvvvvvvvvvvvv", "MTHC2     GPR:(Rn=t), FPR:(Rn=s)", IF_MIPS32R2, "Move Word to High Half of Floating Point Register" ], # TODO: coprocessor custom sel/Rd from v.
    [ "000000sssss000000000000000010001", "MTHI             GPR:(Rn=s)", IF_MIPS32, "Move to HI Register" ],
    [ "000000sssss000000000000000010011", "MTLI             GPR:(Rn=s)", IF_MIPS32, "Move to LO Register" ],
    [ "011100ssssstttttddddd00000000010", "MUL              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply Word to GPR" ],
    [ "010001zzzzztttttsssssddddd000010", "MUL.z:(z=z)      FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS32, "Floating Point Multiply" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "000000sssssttttt0000000000011000", "MULT             GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply Word" ],
    [ "000000sssssttttt0000000000011001", "MULTU            GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Multiply Unsigned Word" ],
    [ "010001zzzzz00000sssssddddd000111", "NEG.z:(z=z)      FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Negate" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "010011rrrrrtttttsssssddddd110zzz", "NMADD.z:(z=z)    FPR:(Rn=d), FPR:(Rn=r), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS64, "Floating Point Negative Multiply Add" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "010011rrrrrtttttsssssddddd111zzz", "NMSUB.z:(z=z)    FPR:(Rn=d), FPR:(Rn=r), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS64, "Floating Point Negative Multiply Sub" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "00000000000000000000000000000000", "NOP",                IF_MIPS32, "No Operation" ], # TODO: Alias for SLL r0, r0, 0 (need to ensure no clash)
    [ "000000ssssstttttddddd00000100111", "NOR              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Not Or" ],
    [ "000000ssssstttttddddd00000100101", "OR               GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Or" ],
    [ "001101ssssstttttvvvvvvvvvvvvvvvv", "ORI              GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", IF_MIPS32, "Or Immediate" ],
    [ "01000110110tttttsssssddddd101100", "PLL.PS           FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS32R2|IF_MIPS64, "Pair Lower Lower" ],
    [ "01000110110tttttsssssddddd101101", "PLU.PS           FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS32R2|IF_MIPS64, "Pair Lower Upper" ],
    [ "110011bbbbbhhhhhvvvvvvvvvvvvvvvv", "PREF             h, b+v", IF_MIPS32, "Prefetch" ],
    [ "010011bbbbbvvvvvhhhhh00000001111", "PREFX            h, b+v", IF_MIPS32R2|IF_MIPS64, "Prefetch Indexed" ],
    [ "01000110110tttttsssssddddd101110", "PUL.PS           FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS32R2|IF_MIPS64, "Pair Upper Lower" ],
    [ "01000110110tttttsssssddddd101111", "PUU.PS           FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", IF_MIPS32R2|IF_MIPS64, "Pair Upper Upper" ],
    [ "01111100000tttttddddd00000111011", "RDHWR            GPR:(Rn=t), GPR:(Rn=d)", IF_MIPS32R2, "Read Hardware Register" ],
    [ "01000001010tttttddddd00000000000", "RDPGRR           GPR:(Rn=d), GPR:(Rn=t)", IF_MIPS32R2, "Read GPR from Previous Shadow Set" ],
    [ "010001zzzzz00000sssssddddd010101", "RECIP.z:(z=z)    GPR:(Rn=d), GPR:(Rn=t)", IF_MIPS32R2|IF_MIPS64, "Reciprocal Approximation" ],
    [ "00000000001tttttdddddvvvvv000010", "ROTR             GPR:(Rn=d), GPR:(Rn=t), Imm:(v=v)", IF_MIPS32R2|IF_SMARTMIPS, "Rotate Word Right" ],
    [ "000000ssssstttttddddd00001000110", "ROTRV            GPR:(Rn=d), GPR:(Rn=t), GPR:(Rn=s)", IF_MIPS32R2|IF_SMARTMIPS, "Rotate Word Right Variable" ],
    [ "010001zzzzz00000sssssddddd001000", "ROUND.L.z:(z=z)  FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32R2|IF_MIPS64, "Floating Point Round to Long Fixed Point" ],
    [ "010001zzzzz00000sssssddddd001100", "ROUND.W.z:(z=z)  FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Round to Word Fixed Point" ],
    [ "010001zzzzz00000sssssddddd010110", "RSQRT.z          FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32R2|IF_MIPS64, "Reciprocal Square Root Approximation" ],
    [ "101000bbbbbtttttvvvvvvvvvvvvvvvv", "SB               GPR:(Rn=t), v+b", IF_MIPS32, "Store Byte" ],
    [ "111000bbbbbtttttvvvvvvvvvvvvvvvv", "SC               GPR:(Rn=t), v+b", IF_MIPS32, "Store Conditional Word" ],
    [ "011100vvvvvvvvvvvvvvvvvvvv111111", "SDBBP            v", IF_EJTAG, "Software Debug Breakpoint" ],
    [ "111001bbbbbtttttvvvvvvvvvvvvvvvv", "SDC1             FPR:(Rn=t), v+b", IF_MIPS32, "Store Doubleword from Floating Point" ],
    [ "111110bbbbbtttttvvvvvvvvvvvvvvvv", "SDC2             GPR:(Rn=t), v+b", IF_MIPS32, "Store Doubleword from Coprocessor 2" ],
    [ "010011bbbbbvvvvvsssss00000001001", "SDXC1            FPR:(Rn=s), v+b", IF_MIPS32R2|IF_MIPS64, "Store Doubleword Indexed from Floating Point" ],
    [ "01111100000tttttddddd10000100000", "SEB              GPR:(Rn=d), GPR:(Rn=t)", IF_MIPS32R2, "Sign-Extend Byte" ],
    [ "01111100000tttttddddd11000100000", "SEH              GPR:(Rn=d), GPR:(Rn=t)", IF_MIPS32R2, "Sign-Extend Halfword" ],
    [ "101001bbbbbtttttvvvvvvvvvvvvvvvv", "SH               GPR:(Rn=t), v+b", IF_MIPS32, "Store Conditional Halfword" ],
    [ "00000000000tttttdddddvvvvv000000", "SLL              GPR:(Rn=d), GPR:(Rn=t), Imm:(v=v)", IF_MIPS32, "Shift Word Left Logical" ],
    [ "000000ssssstttttddddd00000000100", "SLLV             GPR:(Rn=d), GPR:(Rn=t), GPR:(Rn=s)", IF_MIPS32, "Shift Word Left Logical Variable" ],
    [ "000000ssssstttttddddd00000101010", "SLT              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Set on Less Than" ],
    [ "001010ssssstttttvvvvvvvvvvvvvvvv", "SLTI             GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", IF_MIPS32, "Set on Less Than Immediate" ],
    [ "001011ssssstttttvvvvvvvvvvvvvvvv", "SLTIU            GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", IF_MIPS32, "Set on Less Than Immediate Unsigned" ],
    [ "000000ssssstttttddddd00000101011", "SLTU             GPR:(Rn=t), GPR:(Rn=s), Imm:(v=v)", IF_MIPS32, "Set on Less Than Unsigned" ],
    [ "010001zzzzz00000sssssddddd000100", "SQRT.z:(z=z)     FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Square Root" ],
    [ "00000000000tttttdddddvvvvv000011", "SRA              GPR:(Rn=d), GPR:(Rn=t), Imm:(v=v)", IF_MIPS32, "Shift Word Right Arithmetic" ],
    [ "000000ssssstttttdddddvvvvv000111", "SRAV             GPR:(Rn=d), GPR:(Rn=t), GPR:(Rn=s)", IF_MIPS32, "Shift Word Right Arithmetic Variable" ],
    [ "00000000000tttttdddddvvvvv000010", "SRL              GPR:(Rn=d), GPR:(Rn=t), Imm:(v=v)", IF_MIPS32, "Shift Word Right Logical" ],
    [ "000000ssssstttttddddd00000000110", "SRLV             GPR:(Rn=d), GPR:(Rn=t), GPR:(Rn=s)", IF_MIPS32, "Shift Word Right Logical Variable" ],
    [ "00000000000000000000000001000000", "SSNOP",              IF_MIPS32, "Superscalar No Operation" ], # alias for SLL r0, r0, 1
    [ "000000ssssstttttddddd00000100010", "SUB              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Subtract Word" ],
    [ "010001zzzzztttttsssssddddd000001", "SUB.z:(z=z)      GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Floating Point Subtract" ], # TODO: .PS fmt/z is MIPS64/32R2 only
    [ "000000ssssstttttddddd00000100011", "SUBU             GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Subtract Unsigned Word" ],
    [ "010011bbbbbvvvvvsssss00000001101", "SUXC1            FPR:(Rn=s), v+b", IF_MIPS32R2|IF_MIPS64, "Store Doubleword Indexed Unaligned from Floating Point" ],
    [ "101011bbbbbtttttvvvvvvvvvvvvvvvv", "SW               GPR:(Rn=t), v+b", IF_MIPS32, "Store Word" ],
    [ "111001bbbbbtttttvvvvvvvvvvvvvvvv", "SWC1             FPR:(Rn=t), v+b", IF_MIPS32, "Store Word from Floating Point" ],
    [ "111010bbbbbtttttvvvvvvvvvvvvvvvv", "SWC2             GPR:(Rn=t), v+b", IF_MIPS32, "Store Word from Coprocessor 2" ],
    [ "101010bbbbbtttttvvvvvvvvvvvvvvvv", "SWL              GPR:(Rn=t), v+b", IF_MIPS32, "Store Word Left" ],
    [ "101110bbbbbtttttvvvvvvvvvvvvvvvv", "SWR              GPR:(Rn=t), v+b", IF_MIPS32, "Store Word Right" ],
    [ "010011bbbbbvvvvvsssss00000001000", "SWXC1            FPR:(Rn=s), v+b", IF_MIPS32R2|IF_MIPS64, "Store Word Indexed from Floating Point" ],
    [ "000000000000000000000vvvvv001111", "SYNC",               IF_MIPS32, "Synchronise Shared Memory" ],
    [ "000001bbbbb11111vvvvvvvvvvvvvvvv", "SYNCI            v+b", IF_MIPS32R2, "Synchronise Caches to Make Instruction Writes Effective" ],
    [ "000000vvvvvvvvvvvvvvvvvvvv001100", "SYSCALL          v", IF_MIPS32, "System Call" ],
    [ "000000ssssstttttvvvvvvvvvv110100", "TEQ              GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Trap If Equal" ],
    [ "000001sssss01100vvvvvvvvvvvvvvvv", "TEQI             GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Trap If Equal Immediate" ],
    [ "000000ssssstttttvvvvvvvvvv110000", "TGE              GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Trap If Greater or Equal" ],
    [ "000001sssss01000vvvvvvvvvvvvvvvv", "TGEI             GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Trap If Greater or Equal Immediate" ],
    [ "000001sssss01001vvvvvvvvvvvvvvvv", "TGEIU            GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Trap If Greater or Equal Immediate Unsigned" ],
    [ "000000ssssstttttvvvvvvvvvv110001", "TGEI             GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Trap If Greater or Equal Unsigned" ],
    [ "01000010000000000000000000001000", "TLBP",               IF_MIPS32, "Probe TLB for Matching Entry" ],
    [ "01000010000000000000000000000001", "TLBR",               IF_MIPS32, "Read Indexed TLB Entry" ],
    [ "01000010000000000000000000000010", "TLBWI",              IF_MIPS32, "Write Indexed TLB Entry" ],
    [ "01000010000000000000000000000110", "TLBWR",              IF_MIPS32, "Write Random TLB Entry" ],
    [ "000000ssssstttttvvvvvvvvvv110010", "TLT              GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Trap If Less Than" ],
    [ "000001sssss01010vvvvvvvvvvvvvvvv", "TLTI             GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Trap If Less Than Immediate" ],
    [ "000001sssss01011vvvvvvvvvvvvvvvv", "TLTIU            GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Trap If Less Than Immediate Unsigned" ],
    [ "000000ssssstttttvvvvvvvvvv110011", "TLTU             GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Trap If Less Than Unsigned" ],
    [ "000000ssssstttttvvvvvvvvvv110110", "TNE              GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Trap If Not Equal" ],
    [ "000001sssss01110vvvvvvvvvvvvvvvv", "TNEI             GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Trap If Not Equal Immediate" ],
    [ "010001zzzzz00000sssssddddd001001", "TRUNC.L.z:(z=z)  FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32R2|IF_MIPS64, "Floating Point Truncate to Long Fixed Point" ],
    [ "010001zzzzz00000sssssddddd001101", "TRUNC.W.z:(z=z)  FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Truncate to Word Fixed Point" ],
    [ "0100001vvvvvvvvvvvvvvvvvvv100000", "WAIT",               IF_MIPS32, "Enter Standby Mode" ],
    [ "01000001110tttttddddd00000000000", "WRPGPR           GPR:(Rn=d), GPR:(Rn=t)", IF_MIPS32R2, "Write to GPR in Previous Shadow Set" ],
    [ "01111100000tttttddddd00010100000", "WSBH             GPR:(Rn=d), GPR:(Rn=t)", IF_MIPS32R2, "Word Swap Bytes Within Halfwords" ],
    [ "000000ssssstttttddddd00000100110", "XOR              GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", IF_MIPS32, "Exclusive OR" ],
    [ "001110ssssstttttvvvvvvvvvvvvvvvv", "XORI             GPR:(Rn=t), GPR:(Rn=s), IMM:(v=v)", IF_MIPS32, "Exclusive OR Immediate" ],
]
 

def is_final_instruction(match):
    """ description """
    return False # match.specification.key in ("RTS", "RTR", "JMP", "BRA", "RTE")

def get_match_addresses(match):
    """ description """
    pass

def get_instruction_string(instruction, vars):
    """ description """
    pass

def get_operand_string(instruction, operand, vars, lookup_symbol=None):
    """ description """
    pass

def disassemble_one_line(data, data_idx, data_abs_idx):
    """ description """
    pass

def disassemble_as_data(data, data_idx):
    """ description """
    pass

def is_big_endian():
    """ description """
    return False

def get_default_symbol_name(address, metadata):
    """ description """
    raise NotImplementedError("")
