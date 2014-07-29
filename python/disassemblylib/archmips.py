"""
    Peasauce - interactive disassembler
    Copyright (C) 2012, 2013, 2014 Richard Tew
    Licensed using the MIT license.
"""

"""
    api_func_names = [
        "is_final_instruction",
        "get_match_addresses",
        "get_instruction_string",
        "get_operand_string",
        "disassemble_one_line",
        "disassemble_as_data",
        "get_default_symbol_name",
    ]
"""

IF_MIPS32   = 1<<0
IF_MIPS32R2 = 1<<1
IF_MIPS64   = 1<<2


# FMT:
#   COP1: 0x10: 10000: .S: 
#   COP1: 0x11: 10001: .D: 
#   COP1: 0x14: 10100: .W:
#   COP1: 0x15: 10101: .L: 
#   COP1: 0x16: 10110: .PS: 

fp_cond_table = [
    [ "00000", "F", ],
    [ "00001", "UN", ],
    [ "00010", "EQ", ],
    [ "00011", "UEQ", ],
    [ "00100", "OLT", ],
    [ "00101", "ULT", ],
    [ "00110", "OLE", ],
    [ "00111", "ULE", ],
    [ "10000", "SF", ],
    [ "10001", "NGLE", ],
    [ "10010", "SEQ", ],
    [ "10011", "NGL", ],
    [ "10100", "LT", ],
    [ "10101", "NGE", ],
    [ "10110", "LE", ],
    [ "10111", "NGT", ],
]

argument_table = {
    "GPR": None, # TODO: Add some sort of table mapping GPR:(Rn=?) to r? or whatever
    "FPR": None, # TODO: Add some sort of table mapping FPR:(Rn=?) to f? or whatever
}

instruction_table = [
    [ "010001zzzzz00000sssssddddd000101", "ABS.z     FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Absolute Value" ],
    [ "000000ssssstttttddddd00000100000", "ADD       GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", 0, "Add Word" ],
    [ "010001zzzzztttttsssssddddd000000", "ADD.z     FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Add" ],
    [ "001000ssssstttttvvvvvvvvvvvvvvvv", "ADD       GPR:(Rn=t), GPR:(Rn=s), v", 0, "Add Immediate Word" ],
    [ "001000ssssstttttvvvvvvvvvvvvvvvv", "ADDIU     GPR:(Rn=t), GPR:(Rn=s), v", 0, "Add Immediate Unsigned Word" ],
    [ "000000ssssstttttddddd00000100001", "ADDIU     GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", 0, "Add Unsigned Word" ],
    [ "010011rrrrrtttttsssssddddd000001", "ALNV.PS   FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t), rr", 0, "Floating Point Align Variable" ],
    [ "000000ssssstttttddddd00000100100", "AND       GPR:(Rn=d), GPR:(Rn=s), GPR:(Rn=t)", 0, "And" ],
    [ "001100ssssstttttvvvvvvvvvvvvvvvv", "ANDI      GPR:(Rn=t), GPR:(Rn=s), v", 0, "And Immediate Word" ],
    [ "0001000000000000vvvvvvvvvvvvvvvv", "B         v", 0, "Unconditional Branch" ],
    [ "0000010000010001vvvvvvvvvvvvvvvv", "BAL       v", 0, "Branch And Link" ],
    [ "01000101000ccc00vvvvvvvvvvvvvvvv", "BC1F      cc, v", 0, "Branch on FP False" ],
    [ "01000101000ccc10vvvvvvvvvvvvvvvv", "BC1FL     cc, v", 0, "Branch on FP False Likely" ],
    [ "01000101000ccc01vvvvvvvvvvvvvvvv", "BC1T      cc, v", 0, "Branch on FP True" ],
    [ "01000101000ccc11vvvvvvvvvvvvvvvv", "BC1TL     cc, v", 0, "Branch on FP True Likely" ],
    [ "01001001000ccc00vvvvvvvvvvvvvvvv", "BC2F      cc, v", 0, "Branch on COP2 False" ],
    [ "01001001000ccc10vvvvvvvvvvvvvvvv", "BC2FL     cc, v", 0, "Branch on COP2 False Likely" ],
    [ "01001001000ccc01vvvvvvvvvvvvvvvv", "BC2T      cc, v", 0, "Branch on COP2 True" ],
    [ "01001001000ccc11vvvvvvvvvvvvvvvv", "BC2TL     cc, v", 0, "Branch on COP2 True Likely" ],
    [ "000100ssssstttttvvvvvvvvvvvvvvvv", "BEQ       GPR:(Rn=s), GPR:(Rn=t), v", 0, "Branch on Equal" ],
    [ "010100ssssstttttvvvvvvvvvvvvvvvv", "BEQL      GPR:(Rn=s), GPR:(Rn=t), v", 0, "Branch on Equal Likely" ],
    [ "000001sssss00001vvvvvvvvvvvvvvvv", "BGEZ      GPR:(Rn=s), v", 0, "Branch on Greater Than or Equal to Zero" ],
    [ "000001sssss00011vvvvvvvvvvvvvvvv", "BGEZL     GPR:(Rn=s), v", 0, "Branch on Greater Than or Equal to Zero Likely" ],
    [ "000001sssss10001vvvvvvvvvvvvvvvv", "BGEZAL    GPR:(Rn=s), v", 0, "Branch on Greater Than or Equal to Zero and Link" ],
    [ "000001sssss10011vvvvvvvvvvvvvvvv", "BGEZALL   GPR:(Rn=s), v", 0, "Branch on Greater Than or Equal to Zero and Link Likely" ],
    [ "000111sssss00000vvvvvvvvvvvvvvvv", "BGTZ      GPR:(Rn=s), v", 0, "Branch on Greater Than Zero" ],
    [ "010111sssss00000vvvvvvvvvvvvvvvv", "BGTZL     GPR:(Rn=s), v", 0, "Branch on Greater Than Zero Likely" ],
    [ "000110sssss00000vvvvvvvvvvvvvvvv", "BLEZ      GPR:(Rn=s), v", 0, "Branch on Less Than or Equal to Zero" ],
    [ "010110sssss00000vvvvvvvvvvvvvvvv", "BLEZL     GPR:(Rn=s), v", 0, "Branch on Less Than or Equal to Zero Likely" ],
    [ "000001sssss00000vvvvvvvvvvvvvvvv", "BLTZ      GPR:(Rn=s), v", 0, "Branch on Less Than Zero" ],
    [ "000001sssss00010vvvvvvvvvvvvvvvv", "BLTZL     GPR:(Rn=s), v", 0, "Branch on Less Than Zero Likely" ],
    [ "000001sssss10000vvvvvvvvvvvvvvvv", "BLTZAL    GPR:(Rn=s), v", 0, "Branch on Less Than Zero and Link" ],
    [ "000001sssss10010vvvvvvvvvvvvvvvv", "BLTZALL   GPR:(Rn=s), v", 0, "Branch on Less Than Zero and Link Likely" ],
    [ "000101ssssstttttvvvvvvvvvvvvvvvv", "BNE       GPR:(Rn=s), GPR:(Rn=t), v", 0, "Branch on Not Equal" ],
    [ "010101ssssstttttvvvvvvvvvvvvvvvv", "BNEL      GPR:(Rn=s), GPR:(Rn=t), v", 0, "Branch on Not Equal Likely" ],
    [ "000000vvvvvvvvvvvvvvvvvvvv001101", "BREAK",      0, "Branch on Not Equal Likely" ],
    [ "010001ffffftttttsssssccc0011zzzz", "C.z.f     cc, FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Compare" ],
    [ "101111bbbbbooooovvvvvvvvvvvvvvvv", "CACHE     op, v+b", 0, "Perform Cache Operation" ],
    [ "010001zzzzz00000sssssddddd001010", "CEIL.L.z  FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Ceiling Convert to Long Fixed Point" ],
    [ "010001zzzzz00000sssssddddd001110", "CEIL.W.z  FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Ceiling Convert to Word Fixed Point" ],
    [ "01000100010tttttsssss00000000000", "CFC1      FPR:(Rn=t), FPR:(Rn=s)", 0, "Move Control Word From Floating Point" ],
    [ "01001000010tttttdddddddddddddddd", "CFC2      FPR:(Rn=t), FPR:(Rn=d)", 0, "Move Control Word From Coprocessor 2" ],
    [ "011100ssssstttttddddd00000100001", "CLO       FPR:(Rn=t), FPR:(Rn=s)", 0, "Count Leading Ones In Word" ],
    [ "011100ssssstttttddddd00000100000", "CLZ       FPR:(Rn=d), FPR:(Rn=s)", 0, "Count Leading Zeroes In Word" ],
    [ "0100101vvvvvvvvvvvvvvvvvvvvvvvvv", "COP2      v", 0, "Coprocessor Operation To Coprocessor 2" ],
    [ "01000100110tttttsssss00000000000", "CTC1      GPR:(Rn=t), FPR:(Rn=s)", 0, "Move Control Word To Floating Point" ],
    [ "01001000110tttttdddddddddddddddd", "CTC2      GPR:(Rn=t), GPR:(Rn=d)", 0, "Move Control Word To Coprocessor 2" ],
    [ "010001zzzzz00000sssssddddd100101", "CVT.D.z   FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert to Double Floating Point" ],
    [ "01000110000tttttsssssddddd100110", "CVT.PS.S  FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Convert Pair to Paired Single" ],
    [ "010001zzzzz00000sssssddddd100000", "CVT.S.z   FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert to Single Floating Point" ],
    [ "0100011011000000sssssddddd101000", "CVT.S.PL  FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert Pair Lower to Single Floating Point" ],
    [ "0100011011000000sssssddddd100000", "CVT.S.PU  FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert Pair Upper to Single Floating Point" ],
    [ "010001zzzzz00000sssssddddd100100", "CVT.W.z   FPR:(Rn=d), FPR:(Rn=s)", 0, "Floating Point Convert to Word Floating Point" ],
    [ "01000010000000000000000000011111", "DERET",      0, "Debug Exception Return" ],
    [ "01000001011ttttt0110000000000000", "DI        GPR:(Rn=t)", 0, "Disable Interrupts" ], # TODO "DI" / rt implicit
    [ "000000sssssttttt0000000000011010", "DIV       GPR:(Rn=s), GPR:(Rn=t)", 0, "Divide Word" ],
    [ "010001zzzzztttttsssssddddd000011", "DIV.z     FPR:(Rn=d), FPR:(Rn=s), FPR:(Rn=t)", 0, "Floating Point Divide" ],
    [ "000000sssssttttt0000000000011011", "DIVU      GPR:(Rn=s), GPR:(Rn=t)", 0, "Divide Unsigned Word" ],
    [ "00000000000000000000000011000000", "EHB",        0, "Execution Hazard Barrier" ],
    [ "01000001011ttttt0110000000100000", "EI        GPR:(Rn=t)", 0, "Enable Interrupts" ],
    [ "01000010000000000000000000011000", "ERET",       0, "Exception Return" ],
    [ "011111ssssstttttmmmmmbbbbb011010", "EXT       GPR:(Rn=t), GPR:(Rn=s), pos:(v=m), size:(v=b)", 0, "Extract Bit Field" ],
    [ "010001zzzzz00000sssssddddd001011", "FLOOR.L.z FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32R2|IF_MIPS64, "Floating Point Floor Convert to Long Fixed Point" ],
    [ "010001zzzzz00000sssssddddd001111", "FLOOR.W.z FPR:(Rn=d), FPR:(Rn=s)", IF_MIPS32, "Floating Point Floor Convert to Word Fixed Point" ],
    [ "011111ssssstttttmmmmmbbbbb000100", "INS       GPR:(Rn=t), GPR:(Rn=s), pos:(v=m), size:(v=b)", IF_MIPS32R2, "Insert Bit Field" ],
    [ "000010vvvvvvvvvvvvvvvvvvvvvvvvvv", "J         v", IF_MIPS32, "Jump" ],
    [ "000011vvvvvvvvvvvvvvvvvvvvvvvvvv", "JAL       v", IF_MIPS32, "Jump And Link" ],
    [ "000000sssss00000dddddhhhhh001001", "JALR      GPR:(Rn=d), GPR:(Rn=s)", IF_MIPS32, "Jump And Link Register" ], # if rd==31, then rd is omitted and implied as that
    [ "000000sssss00000ddddd1hhhh001001", "JALR.HB   GPR:(Rn=d), GPR:(Rn=s)", IF_MIPS32R2, "Jump And Link Register With Hazard Barrier" ], # if rd==31, then rd is omitted and implied as that
    [ "000000sssss0000000000hhhhh001000", "JR        GPR:(Rn=s)", IF_MIPS32, "Jump Register" ],
    [ "000000sssss00000000001hhhh001000", "JR.HB     GPR:(Rn=s)", IF_MIPS32R2, "Jump Register With Hazard Barrier" ],
    [ "100000bbbbbtttttvvvvvvvvvvvvvvvv", "LB        GPR:(Rn=t), v+b", IF_MIPS32, "Load Byte" ], #TODO: v+b is more complicated
    [ "100100bbbbbtttttvvvvvvvvvvvvvvvv", "LBU       GPR:(Rn=t), v+b", IF_MIPS32, "Load Byte Unsigned" ], #TODO: v+b is more complicated
    [ "110101bbbbbtttttvvvvvvvvvvvvvvvv", "LDC1      FPR:(Rn=t), v+b", IF_MIPS32, "Load Double Word to Floating Point" ], #TODO: v+b is more complicated
    [ "110110bbbbbtttttvvvvvvvvvvvvvvvv", "LDC2      GPR:(Rn=t), v+b", IF_MIPS32, "Load Double Word to Coprocessor 2" ], #TODO: v+b is more complicated
    [ "010011bbbbbiiiii00000ddddd000001", "LDXC1     FPR:(Rn=d), i+b", IF_MIPS32R2|IF_MIPS64, "Load Double Word Indexed to Floating Point" ], #TODO: v+b is more complicated
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
