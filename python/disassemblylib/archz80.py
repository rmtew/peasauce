"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

import logging

from .util import *

logger = logging.getLogger("disassembler-z80")

# Flags to indicate which architecture variant the instruction belongs to.
IF_Z80     = 1<<0

class ArchZ80(ArchInterface):
    constant_immediate_prefix = ""
    constant_register_prefix = ""
    constant_binary_prefix = "%"
    constant_binary_suffix = ""
    constant_decimal_prefix = ""
    constant_decimal_suffix = ""
    constant_hexadecimal_prefix = ""
    constant_hexadecimal_suffix = "H"
    constant_comment_prefix = ";"

    constant_core_architecture_mask = IF_Z80
    constant_endian_types = ">"
    constant_word_size = 8
    constant_pc_offset = 1

# Reference: http://z80.info/decoding.htm

# TODO(rmtew): need to detect byte-wise nature and process as different from same sized opcode sets.
instruction_table = [
    # "xxyyyzzz"
    # "xxppqzzz"

    [ "00000000", "NOP", IF_Z80, "" ],
    [ "00001000", "EX AF,AF'", IF_Z80, "" ],
    [ "00010000", "DJNZ d:(d=I+.s8)", IF_Z80, "" ],
    [ "00011000", "JR d:(d=I+.s8)", IF_Z80, "" ],
    [ "00yyy000", "JR cc[v]:(v=y-4),d:(d=I+.s8)", IF_Z80, "" ], # EVALUATE y-4 to get table index

    [ "00pp0001", "LD rp[v]:(v=p),nn:(nn=I+.u16)", IF_Z80, "" ],
    [ "00pp1001", "ADD HL,rp[p]:(v=p)", IF_Z80, "" ],

    [ "00000010", "LD (BC),A", IF_Z80, "" ],
    [ "00010010", "LD (DE),A", IF_Z80, "" ],
    [ "00100010", "LD (nn):(nn=I+.u16),HL", IF_Z80, "" ],
    [ "00110010", "LD (nn):(nn=I+.u16),A", IF_Z80, "" ],
    [ "00001010", "LD A,(BC)", IF_Z80, "" ],
    [ "00011010", "LD A,(DE)", IF_Z80, "" ],
    [ "00101010", "LD (nn):(nn=I+.u16),(BC)", IF_Z80, "" ],
    [ "00111010", "LD (nn):(nn=I+.u16),A", IF_Z80, "" ],

    [ "00pp0011", "INC rp[v]:(v=p)", IF_Z80, "" ],
    [ "00pp1011", "DEC rp[v]:(v=p)", IF_Z80, "" ],

    [ "00yyy100", "INC r[v]:(v=y)", IF_Z80, "" ],
    [ "00yyy101", "DEC r[v]:(v=y)", IF_Z80, "" ],
    [ "00yyy110", "LD r[v]:(v=y),n:(n=I+.u8)", IF_Z80, "" ],

    [ "00000111", "RLCA", IF_Z80, "" ],
    [ "00001111", "RRCA", IF_Z80, "" ],
    [ "00010111", "RLA", IF_Z80, "" ],
    [ "00011111", "RRA", IF_Z80, "" ],
    [ "00100111", "DAA", IF_Z80, "" ],
    [ "00101111", "CPL", IF_Z80, "" ],
    [ "00110111", "SCF", IF_Z80, "" ],
    [ "00111111", "CCF", IF_Z80, "" ],

    [ "01yyyzzz", "LD r[v]:(v=y),r[v]:(v=z)", IF_Z80, "" ],
    [ "01110111", "HALT", IF_Z80, "" ],

    [ "10000zzz", "ADD A,r[v]:(v=z)", IF_Z80, "" ],
    [ "10001zzz", "ADC A,r[v]:(v=z)", IF_Z80, "" ],
    [ "10010zzz", "SUB r[v]:(v=z)", IF_Z80, "" ],
    [ "10011zzz", "SBC A,r[v]:(v=z)", IF_Z80, "" ],
    [ "10100zzz", "AND r[v]:(v=z)", IF_Z80, "" ],
    [ "10101zzz", "XOR r[v]:(v=z)", IF_Z80, "" ],
    [ "10110zzz", "OR r[v]:(v=z)", IF_Z80, "" ],
    [ "10111zzz", "CP r[v]:(v=z)", IF_Z80, "" ],

    [ "11yyy000", "RET cc[v]:(v=y)", IF_Z80, "" ],
    [ "11pp0001", "POP rp2[v]:(v=p)", IF_Z80, "" ],
    [ "11000001", "RET", IF_Z80, "" ],
    [ "11010001", "EXX", IF_Z80, "" ],
    [ "11100001", "JP HL", IF_Z80, "" ],
    [ "11110001", "LD SP,HL", IF_Z80, "" ],
    [ "11yyy010", "JP cc[v]:(v=y),nn:(nn=I+.u16)", IF_Z80, "" ],
    [ "11000011", "JP nn:(nn=I+.u16)", IF_Z80, "" ],
    # [ "11001011", "" ], # CB prefix (handled below)
    [ "11010011", "OUT (n):(n=I+.u8),A", IF_Z80, "" ],
    [ "11011011", "IN A,(n):(n=I+.u8)", IF_Z80, "" ],
    [ "11100011", "EX (SP),HL", IF_Z80, "" ],
    [ "11101011", "EX DE,HL", IF_Z80, "" ],
    [ "11110011", "DI", IF_Z80, "" ],
    [ "11111011", "EI", IF_Z80, "" ],
    [ "11yyy100", "CALL cc[y],(nn):(nn=I+.u16)", IF_Z80, "" ],
    [ "11pp0101", "PUSH rp2[v]:(v=p)", IF_Z80, "" ],
    [ "11001101", "CALL nn:(nn=I+.u16)", IF_Z80, "" ],
    # [ "11011101", "" ], # DD prefix (handled below)
    # [ "11101101", "" ], # ED prefix (handled below)
    # [ "11111101", "" ], # FD prefix (handled below)
    [ "11000110", "ADD A,n:(n=I+.u8)", IF_Z80, "" ],
    [ "11001110", "ADC A,n:(n=I+.u8)", IF_Z80, "" ],
    [ "11010110", "SUB n:(n=I+.u8)", IF_Z80, "" ],
    [ "11011110", "SBC A,n:(n=I+.u8)", IF_Z80, "" ],
    [ "11100110", "AND n:(n=I+.u8)", IF_Z80, "" ],
    [ "11101110", "XOR n:(n=I+.u8)", IF_Z80, "" ],
    [ "11110110", "OR n:(n=I+.u8)", IF_Z80, "" ],
    [ "11111110", "CP n:(n=I+.u8)", IF_Z80, "" ],
    [ "11yyy111", "RST n:(n=y*8)", IF_Z80, "" ], # EVALUATE n=y*8 to get constant

    # CB prefixed opcodes.
    [ _n2b(0xCB) +"00yyyzzz", "rot[v]:(v=y) r[v]:(v=z)", IF_Z80, "" ],
    [ _n2b(0xCB) +"01yyyzzz", "BIT y,r[v]:(v=z)", IF_Z80, "" ],
    [ _n2b(0xCB) +"10yyyzzz", "RES y,r[v]:(v=z)", IF_Z80, "" ],
    [ _n2b(0xCB) +"11yyyzzz", "SET y,r[v]:(v=z)", IF_Z80, "" ],

    # DD prefixed opcodes.
    [ _n2b(0xDD)+ "aaaaaaaa", "tbd", IF_Z80, "" ], # DD
    [ _n2b(0xDDDD), "ignore", IF_Z80, "" ], # DDDD
    [ _n2b(0xDDED), "ignore", IF_Z80, "" ], # DDED
    [ _n2b(0xDDFD), "ignore", IF_Z80, "" ], # DDFD

    # FD prefixed opcodes.
    [ _n2b(0xFD)+ "aaaaaaaa", "tbd", IF_Z80, "" ], # FD..
    [ _n2b(0xFDDD), "ignore", IF_Z80, "" ], # FDDD
    [ _n2b(0xFDED), "ignore", IF_Z80, "" ], # FDED
    [ _n2b(0xFDFD), "ignore", IF_Z80, "" ], # FDFD

    # ED prefixed opcodes.
    # [ "1110110100yyyzzz", "" ], # Invalid, equivalent to NONI followed by NOP
    [ "1110110101yyy000", "IN r[v]:(v=y),(C)", IF_Z80, "" ],
    [ "1110110101110000", "IN (C)", IF_Z80, "" ],
    [ "1110110101yyy001", "OUT (C),r[v]:(v=y)", IF_Z80, "" ],
    [ "1110110101110001", "OUT (C),0", IF_Z80, "" ],
    [ "1110110101pp0010", "SBC HL,rp[v]:(v=p)", IF_Z80, "" ],
    [ "1110110101pp1010", "ADC HL,rp[v]:(v=p)", IF_Z80, "" ],
    [ "1110110101pp0011", "LD (nn):(nn=I+.u16),rp[v]:(v=p)", IF_Z80, "" ],
    [ "1110110101pp1011", "LD rp[v]:(v=p),(nn):(nn=I+.u16)", IF_Z80, "" ],
    [ "1110110101000100", "NEG", IF_Z80, "" ],
    [ "1110110101yyy101", "RETN", IF_Z80, "" ],
    [ "1110110101001101", "RETI", IF_Z80, "" ],
    [ "1110110101yyy110", "IM im[v]:(v=y)", IF_Z80, "" ],
    [ "1110110101000111", "LD I,A", IF_Z80, "" ],
    [ "1110110101001111", "LD R,A", IF_Z80, "" ],
    [ "1110110101010111", "LD A,I", IF_Z80, "" ],
    [ "1110110101011111", "LD A,R", IF_Z80, "" ],
    [ "1110110101100111", "RRD", IF_Z80, "" ],
    [ "1110110101101111", "RLD", IF_Z80, "" ],
    [ "1110110101110111", "NOP", IF_Z80, "" ],
    [ "1110110101111111", "NOP", IF_Z80, "" ],
    # [ "1110110110yyyzzz", "bli[v1,v2]:(v1=y&v2=z)", IF_Z80, "" ], # WHERE z<3 AND y>=4 # ADDED BELOW
    # [ "1110110111yyyzzz", "" ], # Invalid, equivalent to NONI followed by NOP

    # DDCB / FDCB prefixed opcodes.
    [ _n2b(0xDDCB) +"dddddddd00yyyzzz", "LD r[v]:(v=z),rot[v]:(v=y) (IX+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xDDCB) +"dddddddd00yyy110", "rot[v]:(v=y) (IX+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xDDCB) +"dddddddd01yyyzzz", "BIT y,r[v]:(v=z)", IF_Z80, "" ],
    [ _n2b(0xDDCB) +"dddddddd10yyyzzz", "LD r[v]:(v=z),RES y:(y=y) (IX+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xDDCB) +"dddddddd10yyy110", "RES y:(y=y),(IX+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xDDCB) +"dddddddd11yyyzzz", "LD r[v]:(v=z),SET y:(y=y) (IX+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xDDCB) +"dddddddd11yyy110", "SET y:(y=y),(IX+d):(d=d.s8)", IF_Z80, "" ],

    [ _n2b(0xFDCB) +"dddddddd00yyyzzz", "LD r[v]:(v=z),rot[v]:(v=y) (IY+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xFDCB) +"dddddddd00yyy110", "rot[v]:(v=y) (IY+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xFDCB) +"dddddddd01yyyzzz", "BIT y,r[v]:(v=z)", IF_Z80, "" ],
    [ _n2b(0xFDCB) +"dddddddd10yyyzzz", "LD r[v]:(v=z),RES y:(y=y) (IY+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xFDCB) +"dddddddd10yyy110", "RES y:(y=y),(IY+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xFDCB) +"dddddddd11yyyzzz", "LD r[v]:(v=z),SET y:(y=y) (IY+d):(d=d.s8)", IF_Z80, "" ],
    [ _n2b(0xFDCB) +"dddddddd11yyy110", "SET y:(y=y),(IY+d):(d=d.s8)", IF_Z80, "" ],
]

def _extend_instruction_table():
    # This is a variation which has the same rule for a subset of y/z bit combinations.
    entry_template = [ None, None, IF_Z80, "" ]
    mask_template0 = "1110110110yyyzzz"
    for z in (0, 1, 2):
        mask_template = mask_template0.replace("zzz", _n2b(z, padded_length=3))
        for y in (4, 5, 6, 7):
            mask_template = mask_template.replace("yyy", _n2b(y, padded_length=3))

            entry = entry_template[:]
            entry[0] = mask_template
            entry[1] = "bli[v1,v2]:(v1=%d&v2=%d)" % (y, z)
            instruction_table.append(entry)

    # At this point, preprocess the custom markup.
    # 1. Expand table lookup variations.
    # 2. Expand constraint variations.
    tables_by_name = {
        "r": [ "B", "C", "D", "E", "H", "L", "(HL)", "A" ],
        "rp": [ "BC", "DE", "HL", "SP" ],
        "rp2": [ "BC", "DE", "HL", "AF" ],
        "cc": [ "NZ", "Z", "NC", "C", "PO", "PE", "P", "M" ],
        "alu": [ "ADD A,", "ADC A,", "SUB", "SBC A,", "AND", "XOR", "OR", "CP" ],
        "rot": [ "RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SLR" ],
        "im": [ "0", "0/1", "1", "2", "0", "0/1", "1", "2" ],
        "bli": {
            (4,0) : "LDI", (4,1) : "CPI", (4,2) : "INI", (4,3) : "OUTI",
            (5,0) : "LDD", (5,1) : "CPD", (5,2) : "IND", (5,3) : "OUTD",
            (6,0) : "LDIR", (6,1) : "CPIR", (6,2) : "INIR", (6,3) : "OTIR",
            (7,0) : "LDDR", (7,1) : "CPDR", (7,2) : "INDR", (7,3) : "OTDR",
        },
    }

    expanded_list = []
    for entry in instruction_table:
        mask_string = entry[II_MASK]
        rule = entry[II_NAME]

        pass

    # ...

_extend_instruction_table()

