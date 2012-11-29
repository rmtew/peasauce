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

----------------- RESEARCH NOTES -----------------

TODO: Detect F-Line instructions and understand what to do about them
From the X68000 TNT.x executable from the Tunnels and Trolls disk image.
                 FEDC BA9 876 543  210
0x6683A: 0xFF3C: 1111[111]100[111][100] cpSAVE 7, Imm
This is not a valid addressing mode, so would cause F-Line.

----------------- INSTRUCTION SIZES -----------------

  "+z"                          ADDI, ANDI, CMPI, EORI, ORI, SUBI reads one or two words depending on whether size is B, W or L.
  "z=00"                        ANDI to CCR, BCHG, BCLR, BSET, BTST, EORI to CCR, ORI to CCR reads an extra word for the lower byte.
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
import os
import sys
import struct
import logging


logger = logging.getLogger("disassembler-m68k")


def memoize(function):
    memo = {}
    def wrapper(*args):
        if args in memo:
            return memo[args]
        rv = function(*args)
        memo[args] = rv
        return rv
    return wrapper

def binary2number(s):
    v = 0
    while len(s):
        v <<= 1
        if s[0] == "1":
            v |= 1
        s = s[1:]
    return v
_b = binary2number

def number2binary(v):
    s = ""
    while v:
        s = [ "0", "1" ][v & 1] + s
        v >>= 1
    w = 4
    while w < len(s):
        w <<= 1
    return "%"+ "0"*(w-len(s)) + s

def signed_hex_string(v):
    sign_char = ""
    if v < 0:
        sign_char = "-"
        v = -v
    return sign_char + ("$%x" % v)


def get_direction_label(value):
    if value == 0: return "R"
    if value == 1: return "L"

def get_size_label(value):
    if value == 0: return "B"
    if value == 1: return "W"
    if value == 2: return "L"

def get_size_value(label):
    if label == "B": return 0
    if label == "W": return 1
    if label == "L": return 2

ConditionCodes = [
    [ "T" ],  # %0000
    [ "F" ],  # %0001
    [ "HI" ], # %0010
    [ "LS" ], # %0011
    [ "CC" ], # %0100
    [ "CS" ], # %0101
    [ "NE" ], # %0110
    [ "EQ" ], # %0111
    [ "VC" ], # %1000
    [ "VS" ], # %1001
    [ "PL" ], # %1010
    [ "MI" ], # %1011
    [ "GE" ], # %1100
    [ "LT" ], # %1101
    [ "GT" ], # %1110
    [ "LE" ], # %1111
]

def get_cc_label(value):
    return ConditionCodes[value][0]


SpecialRegisters = ("CCR", "SR")

EAMI_LABEL = 0
EAMI_FORMAT = 1
EAMI_MODE = 2
EAMI_REG = 3
EAMI_READS = 4

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

EffectiveAddressingModes = [
    # Syntax,        Formatting             Mode field       Register field       No. extension words
    [ "DR",         "Dn",                   _b("000"),          "Rn",                0,             "Data Register Direct Mode", ],
    [ "AR",         "An",                   _b("001"),          "Rn",                0,             "Address Register Direct Mode", ],
    [ "ARi",        "(An)",                 _b("010"),          "Rn",                0,             "Address Register Indirect Mode", ],
    [ "ARiPost",    "(An)+",                _b("011"),          "Rn",                0,             "Address Register Indirect Mode with Postincrement Mode", ],
    [ "PreARi",     "-(An)",                _b("100"),          "Rn",                0,             "Address Register Indirect Mode with Preincrement Mode", ],
    [ "ARid16",     "(D16,An)",             _b("101"),          "Rn",                "D16=+W",      "Address Register Indirect Mode with Displacement Mode", ],
    [ "ARiId8",     "(D8,An,Xn.z*S)",       _b("110"),          "Rn",                "EW",          "Address Register Indirect with Index (8-Bit Displacement) Mode", ],
    [ "ARiIdb",     "(bd,An,Xn.z*S)",       _b("110"),          "Rn",                "EW",          "Address Register Indirect with Index (Base Displacement) Mode", ],
    [ "MEMiPost",   "([bd,An],Xn.z*S,od)",  _b("110"),          "Rn",                "EW",          "Memory Indirect Postindexed Mode", ],
    [ "PreMEMi",    "([bd,An,Xn.z*S],od)",  _b("110"),          "Rn",                "EW",          "Memory Indirect Preindexed Mode", ],
    [ "PCid16",     "(D16,PC)",             _b("111"),       _b("010"),               "D16=+W",      "Program Counter Indirect with Displacement Mode", ],
    [ "PCiId8",     "(D8,PC,Xn.z*S)",       _b("111"),       _b("011"),               "EW",          "Program Counter Indirect with Index (8-Bit Displacement) Mode", ],
    [ "PCiIdb",     "(bd,PC,Xn.z*S)",       _b("111"),       _b("011"),               "EW",          "Program Counter Indirect with Index (Base Displacement) Mode", ],
    [ "PCiPost",    "([bd,PC],Xn.s*S,od)",  _b("111"),       _b("011"),               "EW",          "Program Counter Memory Indirect Postindexed Mode", ],
    [ "PrePCi",     "([bd,PC,Xn.s*S],od)",  _b("111"),       _b("011"),               "EW",          "Program Counter Memory Indirect Preindexed Mode", ],
    [ "AbsW",       "(xxx).W",              _b("111"),       _b("000"),               "xxx=+W",      "Absolute Short Addressing Mode", ],
    [ "AbsL",       "(xxx).L",              _b("111"),       _b("001"),               "xxx=+L",      "Absolute Long Addressing Mode", ],
    [ "Imm",        "#xxx",                 _b("111"),       _b("100"),               0,             "Immediate Data", ],
]


def IndexEffectiveAddressingModes():
    idToLabel = {}
    labelToId = {}
    labelToMask = {}
    for i, t in enumerate(EffectiveAddressingModes):
        idToLabel[i] = t[EAMI_LABEL]
        labelToId[t[EAMI_LABEL]] = i
    return lambda k: idToLabel[k], lambda k: labelToId[k]
get_EAM_name, get_EAM_id = IndexEffectiveAddressingModes()

def get_EAM_row_by_name(EAMname):
    id = get_EAM_id(EAMname)
    return EffectiveAddressingModes[id]


class Specification(object):
    key = None
    mask_char_vars = None
    filter_keys = None
    ea_args = None

@memoize
def _make_specification(format):
    @memoize
    def get_substitution_vars(s):
        d = {}
        for candidate_string in s[1:-1].split("&"):
            k, v = [ t.strip() for t in candidate_string.split("=") ]
            d[k] = v
        return d

    # TYPE:CHAR
    # TYPE:CHAR(TYPE FILTER OPTION|...)
    # TYPE:VARLIST[FILTER_OPTION|...]
    spec = Specification()
    spec.mask_char_vars = {}

    idx_typeN = format.find(":")
    if idx_typeN == -1:
        spec.key = format
        return spec
    spec.key = format[:idx_typeN].strip()

    idx_charvarsN = len(format)
    idx_filter0 = format.find("{")
    if idx_filter0 != -1:
        idx_filterN = format.find("}", idx_filter0)
        spec.filter_keys = [ s.strip() for s in format[idx_filter0+1:idx_filterN].split("|") ]
        idx_charvarsN = idx_filter0-1

    idx_charvars0 = format.find("(", idx_typeN+1)
    if idx_charvars0 != -1:
        charvar_string = format[idx_charvars0:idx_charvarsN+1]
        spec.mask_char_vars = get_substitution_vars(charvar_string)
    
    return spec


II_MASK = 0
II_NAME = 1
II_FLAGS = 2
II_TEXT = 3
II_ANDMASK = 4
II_CMPMASK = 5
II_EXTRAWORDS = 6
II_SRCEAMASK = 7
II_DSTEAMASK = 8
II_LENGTH = 9

IF_000 = 1<<0
IF_010 = 1<<1
IF_020 = 1<<1
IF_030 = 1<<1
IF_040 = 1<<1
IF_060 = 1<<1

# z=00: Force size to one byte, read as lower byte of following word.
# xxx=+z: Read a value from the following words, with the size obtained from the 'z' size field.
# xxx=I<n>.[WL]: Starting with the nth word after the instruction word, use the word or longword at that point.

def _process_instruction_info():
    """ Order operands by their static bits, ensures most likely matches come first. """
    # See if we've done this before, and if so, load it.
    mtime = int(os.stat(__file__).st_mtime)
    dir_path = os.path.dirname(__file__)
    file_name = os.path.basename(__file__)
    cache_file_path = os.path.join(dir_path, file_name) +".pikl"

    _list = None
    # This is not working.
    if False and os.path.exists(cache_file_path):
        with open(cache_file_path, "rb") as f:
            _list_mtime = cPickle.load(f)
            if mtime > _list_mtime:
                _list = cPickle.load(f)

    if _list is None:
        _list = [
            [ "1100DDD100000SSS", "ABCD DR:(Rn=S),DR:(Rn=D)",       IF_000, "Add Decimal With Extend (register)", ],
            [ "1100DDD100001SSS", "ABCD PreARi:(Rn=S),PreARi:(Rn=D)",      IF_000, "Add Decimal With Extend (memory)", ],
            [ "1101DDD0zzsssSSS", "ADD.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",             IF_000, "Add", ],
            [ "1101DDD1zzsssSSS", "ADD.z:(z=z) DR:(Rn=D), EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",             IF_000, "Add", ],
            [ "1101DDD011sssSSS", "ADDA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",                     IF_000, "Add Address", ],
            [ "1101DDD111sssSSS", "ADDA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",                     IF_000, "Add Address", ],
            [ "00000110zzsssSSS", "ADDI.z:(z=z) Imm:(z=z&xxx=+z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",                       IF_000, "Add Immediate", ],
            [ "0101vvv0zzsssSSS", "ADDQ.z:(z=z) Imm:(xxx=v), EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",                       IF_000, "Add Immediate", ],
            [ "1101DDD1zz000SSS", "ADDX.z:(z=z) DR:(Rn=S),DR:(Rn=D)",       IF_000, "Add Extended (register)", ],
            [ "1101DDD1zz001SSS", "ADDX.z:(z=z) PreARi:(Rn=S),PreARi:(Rn=D)",      IF_000, "Add Extended (memory)", ],
            [ "1100DDD0zzsssSSS", "AND.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",                        IF_000, "AND Logical (EA->DR)", ],
            [ "1100DDD1zzsssSSS", "AND.z:(z=z) DR:(Rn=D), EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",                        IF_000, "AND Logical (DR->EA)", ],
            [ "00000010zzsssSSS", "ANDI.z:(z=z) Imm:(z=z&xxx=+z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "AND Immediate", ],
            [ "0000001000111100", "ANDI Imm:(z=00), CCR",      IF_000, "CCR AND Immediate", ],
            [ "1110vvvazz000DDD", "ASd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",       IF_000, "Arithmetic Shift (register rotate, source immediate)", ],
            [ "1110SSSazz100DDD", "ASd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",       IF_000, "Arithmetic Shift (register rotate, source register)", ],
            [ "1110000a11sssSSS", "ASd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Arithmetic Shift (memory rotate)", ],
            [ "0110ccccvvvvvvvv", "Bcc:(cc=c) DISPLACEMENT:(xxx=v)",       IF_000, "Branch Conditionally", ],
            [ "0000DDD101sssSSS", "BCHG DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Change (register bit number)", ],
            [ "0000100001sssSSS", "BCHG Imm:(z=00), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Change (static bit number)", ],
            [ "0000DDD110sssSSS", "BCLR DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Clear (register bit number)", ],
            [ "0000100010sssSSS", "BCLR Imm:(z=00), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Clear (static bit number)", ],
            [ "0100100001001vvv", "BKPT Imm:(xxx=v)",  IF_010|IF_020|IF_030|IF_040, "Breakpoint", ],
            [ "01100000vvvvvvvv", "BRA DISPLACEMENT:(xxx=v)",       IF_000, "Branch Always", ],
            [ "0000DDD111sssSSS", "BSET DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Set (register bit number)", ],
            [ "0000100011sssSSS", "BSET Imm:(z=00), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Test a Bit and Set (static bit number)", ],
            [ "01100001vvvvvvvv", "BSR DISPLACEMENT:(xxx=v)",       IF_000, "Branch to Subroutine", ],
            [ "0000DDD100sssSSS", "BTST DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}",      IF_000, "Test a Bit (register bit number)", ],
            [ "0000100000sssSSS", "BTST Imm:(z=00), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",      IF_000, "Test a Bit (static bit number)", ],
            [ "0100DDD110sssSSS", "CHK.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",       IF_000, "Check Register Against Bounds", ],
            [ "0100DDD100sssSSS", "CHK.L EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",       IF_000, "Check Register Against Bounds", ],
            [ "01000010zzsssSSS", "CLR.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Clear an Operand", ],
            [ "1011DDD0zzsssSSS", "CMP.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",       IF_000, "Compare", ],
            [ "1011DDD011sssSSS", "CMPA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Compare Address", ],
            [ "1011DDD111sssSSS", "CMPA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Compare Address", ],
            [ "00001100zzsssSSS", "CMPI.z:(z=z) Imm:(z=z&xxx=+z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",      IF_000, "Compare Immediate", ],
            [ "1011DDD1zz001SSS", "CMPM.z:(z=z) AriPost:(Rn=S), AriPost:(Rn=D)",      IF_000, "Compare Memory", ],
            [ "0101cccc11001DDD", "DBcc:(cc=c) DR:(Rn=D), DISPLACEMENT:(xxx=I1.W)",      IF_000, "Test Condition, Decrement, and Branch", ],
            [ "1000DDD111sssSSS", "DIVS.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Signed Divide", ],
            [ "1000DDD011sssSSS", "DIVU.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Unsigned Divide", ],
            [ "1011DDDvvvsssSSS", "EOR DR:(Rn=D), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Exclusive-OR Logical", ],
            [ "00001010zzsssSSS", "EORI.z:(z=z) Imm:(z=z&xxx=+z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Exclusive-OR Immediate", ],
            [ "0000101000111100", "EORI Imm:(z=00), CCR",      IF_000, "Exclusive-OR Immediate to Condition Code", ],
            [ "1100SSS101000DDD", "EXG DR:(Rn=S), DR:(Rn=D)",       IF_000, "Exchange Registers (data)", ],
            [ "1100SSS101001DDD", "EXG AR:(Rn=S), AR:(Rn=D)",       IF_000, "Exchange Registers (address)", ],
            [ "1100SSS110001DDD", "EXG DR:(Rn=S), AR:(Rn=D)",       IF_000, "Exchange Registers (address and data)", ],
            [ "0100100010000DDD", "EXT.W DR:(Rn=D)",       IF_000, "Sign-Extend", ],
            [ "0100100011000DDD", "EXT.L DR:(Rn=D)",       IF_000, "Sign-Extend", ],
            [ "0100101011111100", "ILLEGAL",   IF_000, "Take Illegal Instruction Trap", ],
            [ "0100111011sssSSS", "JMP EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",       IF_000, "Jump", ],
            [ "0100111010sssSSS", "JSR EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",       IF_000, "Jump to Subroutine", ],
            [ "0100DDD111sssSSS", "LEA EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}, AR:(Rn=D)",       IF_000, "Load Effective Address", ],
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
            [ "0100001011sssSSS", "MOVE CCR, EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Move from the Condition Code Register", ],
            [ "0100010011sssSSS", "MOVE EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, CCR",      IF_000, "Move to Condition Code Register", ],
            [ "0100000011sssSSS", "MOVE SR, EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Move from the Status Register", ],
            ## 040 [ "1111011000100DDD", "MOVE16", IF_000, "Move 16-Byte Block (post increment)", ],
            [ "1111011000000DDD", "MOVE16 ARiPost:(Dn=D), AbsL", IF_040, "Move 16-Byte Block (absolute)", ],
            [ "1111011000001DDD", "MOVE16 AbsL, ARiPost:(Dn=D)", IF_040, "Move 16-Byte Block (absolute)", ],
            [ "1111011000010DDD", "MOVE16 ARi:(Dn=D), AbsL", IF_040, "Move 16-Byte Block (absolute)", ],
            [ "1111011000011DDD", "MOVE16 AbsL, ARi:(Dn=D)", IF_040, "Move 16-Byte Block (absolute)", ],
            [ "0100100010sssSSS", "MOVEM.W RL:(xxx=I1.W), EA:(mode=s&register=S){ARi|PreARi|ARid16|ARiId8|AbsW|AbsL}",     IF_000, "Move Multiple Registers", ],
            [ "0100100011sssSSS", "MOVEM.L RL:(xxx=I1.W), EA:(mode=s&register=S){ARi|PreARi|ARid16|ARiId8|AbsW|AbsL}",     IF_000, "Move Multiple Registers", ],
            [ "0100110010sssSSS", "MOVEM.W EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}, RL:(xxx=I1.W)",     IF_000, "Move Multiple Registers", ],
            [ "0100110011sssSSS", "MOVEM.L EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}, RL:(xxx=I1.W)",     IF_000, "Move Multiple Registers", ],
            [ "0000DDD100001SSS", "MOVEP.W ARid16:(Rn=S), DR:(Rn=D)",     IF_000, "Move Periphial Data (memory to register)", ],
            [ "0000DDD101001SSS", "MOVEP.L ARid16:(Rn=S), DR:(Rn=D)",     IF_000, "Move Periphial Data (memory to register)", ],
            [ "0000DDD110001SSS", "MOVEP.W DR:(Rn=S), ARid16:(Rn=D)",     IF_000, "Move Periphial Data (register to memory)", ],
            [ "0000DDD111001SSS", "MOVEP.L DR:(Rn=S), ARid16:(Rn=D)",     IF_000, "Move Periphial Data (register to memory)", ],
            [ "0111DDD0vvvvvvvv", "MOVEQ Imm:(xxx=v),DR:(Rn=D)",     IF_000, "Move Quick", ],
            [ "1100DDD111sssSSS", "MULS.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Signed Multiply", ],
            [ "1100DDD011sssSSS", "MULU.W EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",      IF_000, "Unsigned Multiply", ],
            [ "0100100000sssSSS", "NBCD EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Negate Decimal With Extend (register)", ],
            [ "01000100zzsssSSS", "NEG.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Negate", ],
            [ "01000000zzsssSSS", "NEGX.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Negate with Extend", ],
            [ "0100111001110001", "NOP",       IF_000, "No Operation", ],
            [ "01000110zzsssSSS", "NOT.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Logical Complement", ],
            [ "1000DDD0zzsssSSS", "OR.z:(z=z) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, DR:(Rn=D)",        IF_000, "Inclusive-OR Logical (EA->DR)", ],
            [ "1000DDD1zzsssSSS", "OR.z:(z=z) DR:(Rn=D), EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",        IF_000, "Inclusive-OR Logical (DR->EA)", ],
            [ "00000000zzsssSSS", "ORI.z:(z=z) Imm:(z=z&xxx=+z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Inclusive-OR", ],
            [ "0000000000111100", "ORI Imm:(z=00), CCR",       IF_000, "Inclusive-OR Immediate to Condition Codes", ],
            [ "0100100001sssSSS", "PEA EA:(mode=s&register=S){ARi|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}",       IF_000, "Push Effective Address", ],
            [ "1110vvvazz011DDD", "ROd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",       IF_000, "Rotate without Extend (register rotate, source immediate)", ],
            [ "1110SSSazz111DDD", "ROd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",       IF_000, "Rotate without Extend (register rotate, source register)", ],
            [ "1110011a11sssSSS", "ROd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Rotate without Extend (memory rotate)", ],
            [ "1110vvvazz010DDD", "ROXd.z:(z=z&d=a) Imm:(xxx=v), DR:(Rn=D)",      IF_000, "Rotate with Extend (register rotate, source immediate)", ],
            [ "1110SSSazz110DDD", "ROXd.z:(z=z&d=a) DR:(Rn=S), DR:(Rn=D)",      IF_000, "Rotate with Extend (register rotate, source register)", ],
            [ "1110010a11sssSSS", "ROXd.W:(d=a) EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Rotate with Extend (memory rotate)", ],
            [ "0100111001110111", "RTR",       IF_000, "Return and Restore Condition Codes", ],
            [ "0100111001110101", "RTS",       IF_020, "Return from Subroutine", ],
            [ "1000DDD100000SSS", "SBCD DR:(Rn=S),DR:(Rn=D)",       IF_000, "Add Decimal With Extend (register)", ],
            [ "1000DDD100001SSS", "SBCD PreARi:(Rn=S),PreARi:(Rn=D)",      IF_000, "Add Decimal With Extend (memory)", ],
            [ "0101cccc11sssSSS", "Scc:(cc=c) EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Set According to Condition", ],
            [ "1001DDD0zzsssSSS", "SUB.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8},DR:(Rn=D)",       IF_000, "Subtract", ],
            [ "1001DDD1zzsssSSS", "SUB.z:(z=z) DR:(Rn=D),EA:(mode=s&register=S){ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Subtract", ],
            [ "1001DDD011sssSSS", "SUBA.W EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",      IF_000, "Subtract Address (word)", ],
            [ "1001DDD111sssSSS", "SUBA.L EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}, AR:(Rn=D)",      IF_000, "Subtract Address (long)", ],
            [ "00000100zzsssSSS", "SUBI.z:(z=z) Imm:(z=z&xxx=+z), EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Subtract Immediate", ],
            [ "0101vvv1zzsssSSS", "SUBQ.z:(z=z) Imm:(xxx=v), EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",      IF_000, "Subtract Quick", ],
            [ "1001DDD1zz000SSS", "SUBX.z:(z=z) DR:(Rn=S), DR:(Rn=D)",      IF_000, "Subtract with Extend (data registers)", ],
            [ "1001DDD1zz001SSS", "SUBX.z:(z=z) PreARi:(Rn=S), PreARi:(Rn=S)",      IF_000, "Subtract with Extend (PreARi)", ],
            [ "0100100001000SSS", "SWAP DR:(Rn=S)",      IF_000, "Swap Register Halves", ],
            [ "0100101011sssSSS", "TAS EA:(mode=s&register=S){DR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL}",       IF_000, "Test and Set an Operand", ],
            [ "010011100100vvvv", "TRAP Imm:(xxx=v)",      IF_000, "Trap", ],
            [ "0100111001110110", "TRAPV",     IF_000, "Trap on Overflow", ],
            [ "01001010zzsssSSS", "TST.z:(z=z) EA:(mode=s&register=S){DR|AR|ARi|ARiPost|PreARi|ARid16|ARiId8|AbsW|AbsL|Imm|PCid16|PCiId8}",       IF_000, "Test an Operand", ],
            [ "0100111001011SSS", "UNLK AR:(Rn=S)",      IF_000, "Unlink", ],
            #1111___01z______ cpBcc
            #1111___001001SSS cpDBcc
            #1111___000sssSSS cpGEN
            #1111___001sssSSS cpScc
            #1111___001111xxx cpTRAPcc
            # 020, 030
            [ "1111vvv101sssSSS", "cpRESTORE Imm:(xxx=v), EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL|PCid16|PCiId8}", IF_020|IF_030, "Coprocessor Restore Functions", ],
            [ "1111vvv100sssSSS", "cpSAVE Imm:(xxx=v), EA:(mode=s&register=S){ARi|ARiPost|ARid16|ARiId8|AbsW|AbsL}", IF_020|IF_030, "Coprocessor Restore Functions", ],
        ]

        # Pass 1: Replace any instruction entry with a ".z" with specific .B, .W, .L entries.
        _list_old = _list
        _list = []
        while len(_list_old):
            entry = _list_old.pop()
            if " " in entry[II_NAME]:
                # INSTR.z OP, OP
                entry_name, operands_string = entry[II_NAME].split(" ", 1)
                entry_name_suffix = " "+ operands_string
            else:
                # INSTR.z
                entry_name = entry[II_NAME]
                entry_name_suffix = operands_string = ""

            # Size-based processing.
            specification = _make_specification(entry_name)
            if "z" in specification.mask_char_vars:
                mask_char_vars = specification.mask_char_vars.copy()
                new_name = specification.key
                # Append a new substitution mapping without the 'z' entry.
                del mask_char_vars["z"]
                var_list = mask_char_vars.items()
                if len(var_list):
                    new_name += ":(" + "&".join(k+"="+v for (k, v) in var_list) +")"

                # At this point, the instruction list should only have '.z' for those that use these bits for sizes:
                # B:00, W:01, L:10
                long_entry = entry[:]
                long_entry[II_MASK] = long_entry[II_MASK].replace("zz", "10")
                long_entry[II_NAME] = new_name.replace(".z", ".L") + entry_name_suffix
                _list.append(long_entry)

                word_entry = entry[:]
                word_entry[II_MASK] = word_entry[II_MASK].replace("zz", "01")
                word_entry[II_NAME] = new_name.replace(".z", ".W") + entry_name_suffix
                _list.append(word_entry)

                byte_entry = entry[:]
                byte_entry[II_MASK] = byte_entry[II_MASK].replace("zz", "00")
                byte_entry[II_NAME] = new_name.replace(".z", ".B") + entry_name_suffix
                _list.append(byte_entry)
            else:
                _list.append(entry)

        # Pass 2: Sort all entries by known bits to reduce hitting matches with unknown bits first.
        #         Also inject calculated columns.
        def make_operand_mask(mask_string):
            and_mask = cmp_mask = 0
            for c in mask_string:
                and_mask <<= 1
                cmp_mask <<= 1
                if c == '0':
                    and_mask |= 1
                elif c == '1':
                    and_mask |= 1
                    cmp_mask |= 1
            return and_mask, cmp_mask

        d = {}
        for entry in _list:
            operand_mask = entry[II_MASK]

            # Ensure pre-calculated columns have space present and precalculate some useful information.
            entry.extend([ None ] * (II_LENGTH - len(entry)))

            # Matching and comparison masks.
            and_mask, cmp_mask = make_operand_mask(operand_mask)
            entry[II_ANDMASK] = and_mask
            entry[II_CMPMASK] = cmp_mask

            # Extra word needs.
            max_extra_words = 0
            line_bits = entry[II_NAME].split(" ", 1)
            if len(line_bits) > 1:
                operands_bits = line_bits[1].split(",")
                for operand_string in operands_bits:
                    spec = _make_specification(operand_string)
                    for var_name, value_name in spec.mask_char_vars.iteritems():
                        if value_name[0] == "I":
                            size_idx = value_name.find(".")
                            if size_idx > 0:
                                word_idx = int(value_name[1:size_idx])
                                extra_words = word_idx
                                size_char = value_name[size_idx+1]
                                # B (extracted from given word), W (extracted from given word), L (requires extra word)
                                if size_char == "L":
                                    extra_words += 1
                                if extra_words > max_extra_words:
                                    max_extra_words = extra_words
            entry[II_EXTRAWORDS] = max_extra_words

            # EA mask generation.
            name_bits = entry[II_NAME].split(" ", 1)
            if len(name_bits) > 1:
                for i, operand_string in enumerate(name_bits[1].split(",")):
                    mask = 0
                    spec = _make_specification(operand_string)
                    if spec.filter_keys is not None:
                        for ea_key in spec.filter_keys:
                            mask |= 1 << get_EAM_id(ea_key)
                    if i == 0:
                        entry[II_SRCEAMASK] = mask
                    elif i == 1:
                        entry[II_DSTEAMASK] = mask

            # Sort..
            sort_key = ""
            sort_idx = 0
            for i, c in enumerate(operand_mask):
                if c == '0' or c == '1':
                    sort_key += c
                else:
                    if sort_idx == 0: sort_idx = len(operand_mask) - i
                    sort_key += '_'
            if (sort_idx, sort_key) in d:
                print "Duplicate (first):", d[(sort_idx, sort_key)]
                print "Duplicate (second):", entry
                raise RuntimeError("duplicate mask", sort_idx, sort_key)
            d[(sort_idx, sort_key)] = entry
        ls = d.keys()
        ls.sort()
        _list = [ d[k] for k in ls ]

        if False:
            # Cache the final ordered and extended instruction list.
            with open(cache_file_path, "wb") as f:
                cPickle.dump(mtime, f)
                cPickle.dump(_list, f)

    return _list

InstructionInfo = _process_instruction_info()
del _process_instruction_info


# Not 68000 instructions
#[ "BFCHG",     "1110101011abcdef", 0, "Test Bit Field and Change", ],
#[ "BFCLR",     "1110110011abcdef", 0, "Test Bit Field and Clear", ],
#[ "BFEXTS",    "1110101111abcdef", 0, "Extract Bit Field Signed", ],
#[ "BFEXTU",    "1110100111abcdef", 0, "Extract Bit Field Unsigned", ],
#[ "BFFFO",     "1110100111abcdef", 0, "Find First One in Bit Field", ],
#[ "BFINS",     "1110111111abcdef", 0, "Insert Bit Field", ],
#[ "BFSET",     "1110111011abcdef", 0, "Test Bit Field and Set", ],
#[ "BFTST",     "1110100011abcdef", 0, "Test Bit Field", ],

def _get_data_by_size_char(data, idx, char):
    if char == "B":
        word, idx = _get_word(data, idx)
        if word is None:
            return None, idx
        word &= 0xFF
        return word, idx
    elif char == "W":
        return _get_word(data, idx)
    elif char == "L":
        return _get_long(data, idx)

def _get_byte(data, idx):
    if idx + 1 <= len(data):
        return data[idx], idx + 1
    return None, idx

def _get_word(data, idx):
    if idx + 2 <= len(data):
        return (data[idx] << 8) +  data[idx+1], idx + 2
    return None, idx

def _get_long(data, idx):
    if idx + 4 <= len(data):
        return (data[idx] << 24) +  (data[idx+1] << 16) +  (data[idx+2] << 8) +  data[idx+3], idx + 4
    return None, idx

class Match(object):
    table_mask = None
    table_text = None
    table_extra_words = None
    format = None
    specification = None
    description = None
    data_words = None
    opcodes = None
    vars = None
    num_bytes = None

class MatchOpcode(object):
    key = None # Overrides the one in the spec
    format = None
    specification = None
    description = None
    vars = None
    rl_bits = None

def _resolve_specific_ea_key(mode_bits, register_bits, operand_ea_mask):
    for i, line in enumerate(EffectiveAddressingModes):
        if operand_ea_mask & (1 << i) and line[EAMI_MODE] == mode_bits:
            if line[EAMI_REG] != "Rn" and line[EAMI_REG] != register_bits:
                continue
            return line[EAMI_LABEL]

def _signed_value(size_char, value):
    unpack_char, pack_char = { "B": ('b', 'B'), "W": ('h', 'H'), "L": ('i', 'I') }[size_char]
    return struct.unpack(">"+ unpack_char, struct.pack(">"+ pack_char, value))[0]

def _get_formatted_ea_description(instruction, key, vars, lookup_symbol=None):
    pc = instruction.pc
    id = get_EAM_id(key)
    mode_format = EffectiveAddressingModes[id][EAMI_FORMAT]
    reg_field = EffectiveAddressingModes[id][EAMI_REG]
    for k, v in vars.iteritems():
        if k == "D16" or k == "D8":
            value = _signed_value({ "D8": "B", "D16": "W", }[k], vars[k])
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
                value_string = signed_hex_string(value)
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
            is_absolute = key == "Imm"
            value_string = lookup_symbol(value, absolute_info=(pc-2, instruction.num_bytes))
            if value_string is None:
                value_string = "$%x" % value
            mode_format = mode_format.replace("xxx",  value_string)
        else:
            mode_format = mode_format.replace(k, str(v))
    return mode_format

@memoize
def _extract_mask_bits(mask_string, s):
    mask = 0
    for i in range(len(mask_string)):
        mask <<= 1
        if mask_string[i] == s:
            mask |= 1
    shift = 0
    if mask:
        mask_copy = mask
        while mask_copy & 1 == 0:
            mask_copy >>= 1
            shift += 1
    return mask, shift

def _extract_masked_value(data_word, mask_string, mask_char):
    mask, shift = _extract_mask_bits(mask_string, mask_char)
    return (data_word & mask) >> shift

def _get_formatted_description(key, vars):
    description = key
    for var_name, var_value in vars.iteritems():
        description = description.replace(var_name, str(var_value))
    return description

def _data_word_lookup(data_words, text):
    size_idx = text.find(".")
    if size_idx > 0:
        size_char = text[size_idx+1]
        word_idx = int(text[1:size_idx])
        if size_char == "B":
            if data_words[word_idx] & ~0xFF: return # Sanity check.
            return data_words[word_idx] & 0xFF, size_char
        elif size_char == "W":
            return data_words[word_idx], size_char
        elif size_char == "L":
            return (data_words[word_idx] << 16) + data_words[word_idx+1], size_char

def _decode_operand(data, data_idx, operand_idx, M, T):
    if T.specification.key == "RL":
        T2 = M.opcodes[1-operand_idx]
        word, size_char = _data_word_lookup(M.data_words, T.vars["xxx"])
        if word is None:
            logger.error("_decode_operand$%X: _data_word_lookup failure 1", M.pc)
            return None
        T2_key = T2.specification.key
        if T2_key == "EA":
            T2_key = _resolve_specific_ea_key(T2.vars["mode"], T2.vars["register"], M.table_ea_masks[1-operand_idx])
            if T2_key is None:
                logger.debug("_decode_operand$%X: failed to resolve EA key mode:%s register:%s operand: %d instruction: %s ea_mask: %X", M.pc, number2binary(T2.vars["mode"]), number2binary(T2.vars["register"]), operand_idx, M.specification.key, M.table_ea_masks[1-operand_idx])
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
        T.rl_bits = dm, am
        return data_idx
    elif T.specification.key == "DISPLACEMENT":
        value = T.vars["xxx"]
        if type(value) is str:
            value, size_char = _data_word_lookup(M.data_words, value)
        else:
            size_char = "B"
            if value == 0:
                size_char = "W"
                value, data_idx = _get_word(data, data_idx)
            elif value == 0xFF:
                size_char = "L"
                value, data_idx = _get_long(data, data_idx)
        if value is None: # Disassembly failure
            logger.error("_decode_operand: Failed to obtain displacement offset")
            return None
        T.vars["xxx"] = _signed_value(size_char, value)
        return data_idx
    elif T.specification.key in SpecialRegisters:
        return data_idx

    # General EA possibility, or specific EA mode
    instruction_key = M.specification.key
    instruction_key4 = instruction_key[:4]
    operand_key = specific_key = T.specification.key

    if specific_key == "EA":
        specific_key = T.key = _resolve_specific_ea_key(T.vars["mode"], T.vars["register"], M.table_ea_masks[operand_idx])
        if specific_key is None:
            #logger.debug("_decode_operand$%X: %s unresolved EA key mode:%s register:%s", M.pc, M.specification.key, number2binary(T.vars["mode"]), number2binary(T.vars["register"]))
            return None
        T.vars["Rn"] = T.vars["register"]

    eam_line = get_EAM_row_by_name(specific_key)
    read_string = eam_line[EAMI_READS]

    # Special case.
    if specific_key == "Imm":
        if operand_key == "EA":
            if "z" in T.vars:
                size_char = T.vars["z"]
            elif "z" in M.vars:
                size_char = M.vars["z"]
            elif instruction_key[-2] == "." and instruction_key[-1] in ("B", "W", "L"):
                size_char = instruction_key[-1]
            else:
                # Presumably an F-line instruction.
                return None

            #try:
            value, data_idx = _get_data_by_size_char(data, data_idx, size_char)
            #except Exception:
            #    print M.specification.key, T.vars, "-- this should reach the core code and emit the dc.w instead for the instruction word"
            #    raise
            if value is None: # Disassembly failure.
                logger.debug("Failed to fetch EA/Imm data")
                return None
            T.vars["xxx"] = value
        elif operand_key == "Imm" and "z" in T.vars and "xxx" not in T.vars:
            value, data_idx = _get_data_by_size_char(data, data_idx, T.vars["z"])
            T.vars["xxx"] = value
        elif instruction_key4 in ("LSd.", "ASd.", "ROd.", "ROXd", "ADDQ", "SUBQ"):
           if T.vars["xxx"] == 0:
                T.vars["xxx"] = 8

    if "xxx" in T.vars:
        if T.vars["xxx"] == "+z":
            value, data_idx = _get_data_by_size_char(data, data_idx, T.vars["z"])
            if value is None: # Disassembly failure.
                logger.debug("Failed to fetch xxx/+z data")
                return None
            T.vars["xxx"] = value

    # Populate EA mode specific variables.
    if read_string == "EW":
        ew1, data_idx = _get_word(data, data_idx)
        if ew1 is None: # Disassembly failure.
            logger.debug("Failed to extension word1")
            return None

        register_type = _extract_masked_value(ew1, EffectiveAddressingWordMask, "r")
        register_number = _extract_masked_value(ew1, EffectiveAddressingWordMask, "R")
        index_size = _extract_masked_value(ew1, EffectiveAddressingWordMask, "z")
        scale = _extract_masked_value(ew1, EffectiveAddressingWordMask, "X")
        full_extension_word = _extract_masked_value(ew1, EffectiveAddressingWordMask, "t")
        # Xn.z*S                
        T.vars["Xn"] = ["D", "A"][register_type] + str(register_number)
        T.vars["z"] = ["W", "L"][index_size]
        T.vars["S"] = [1,2,4,8][scale]

        if full_extension_word:
            ew2, data_idx = _get_word(data, data_idx)
            base_register_suppressed = _extract_masked_value(ew1, EffectiveAddressingWordFullMask, "b")
            index_suppressed = _extract_masked_value(ew1, EffectiveAddressingWordFullMask, "i")
            base_displacement_size = _extract_masked_value(ew1, EffectiveAddressingWordFullMask, "B")
            index_selection = _extract_masked_value(ew1, EffectiveAddressingWordFullMask, "I")
            # ...
            base_displacement = 0
            if base_displacement_size == 2: # %10
                base_displacement, data_idx = _get_word(data, data_idx)
            elif base_displacement_size == 3: # %11
                base_displacement, data_idx = _get_long(data, data_idx)
            if base_displacement is None: # Disassembly failure.
                return None
            # TODO: Finish implementation.
            logger.debug("Skipping full extension word for instruction '%s'", M.specification.key)
            return None
            # raise RuntimeError("Full displacement incomplete", M.specification.key)
        else:
            T.vars["D8"] = _extract_masked_value(ew1, EffectiveAddressingWordBriefMask, "v")
    elif read_string:
        k, v = [ s.strip() for s in read_string.split("=") ]
        size_char = v[1]
        value, data_idx = _get_data_by_size_char(data, data_idx, size_char)
        if value is None: # Disassembly failure.
            logger.error("Failed to read extra size char")
            return None
        T.vars[k] = value
    return data_idx

def _match_instructions(data, data_idx, data_abs_idx):
    """ Read one word from the stream, and return matching instructions by order of decreasing confidence. """
    @memoize
    def get_instruction_format_parts(instr_format):
        opcode_sidx = instr_format.find(" ")
        if opcode_sidx == -1:
            return [ instr_format ]
        ret = [ instr_format[:opcode_sidx] ]
        opcode_string = instr_format[opcode_sidx+1:]
        opcode_bits = opcode_string.replace(" ", "").split(",")
        ret.extend(opcode_bits)
        return ret

    word1, data_idx = _get_word(data, data_idx)
    if word1 is None: # Disassembly failure
        return [], data_idx

    matches = []
    for t in InstructionInfo:
        mask_string = t[II_MASK]
        and_mask, cmp_mask = t[II_ANDMASK], t[II_CMPMASK]
        if (word1 & and_mask) == cmp_mask:
            instruction_parts = get_instruction_format_parts(t[II_NAME])

            M = Match()
            M.pc = data_abs_idx + 2
            M.data_words = [ word1 ]

            M.table_text = t[II_TEXT]
            M.table_mask = mask_string
            M.table_extra_words = t[II_EXTRAWORDS]
            M.table_ea_masks = (t[II_SRCEAMASK], t[II_DSTEAMASK])

            M.format = instruction_parts[0]
            M.specification = _make_specification(M.format)
            M.opcodes = []
            for i, opcode_format in enumerate(instruction_parts[1:]):
                T = MatchOpcode()
                T.format = opcode_format
                T.specification = _make_specification(T.format)
                M.opcodes.append(T)
            matches.append(M)

    return matches, data_idx

def _disassemble_vars_pass(I):
    def _get_var_values(chars, data_word1, mask_string):
        var_values = {}
        if chars:
            for mask_char in chars:
                if mask_char in mask_string:
                    var_values[mask_char] = _extract_masked_value(data_word1, mask_string, mask_char)
        return var_values

    def copy_values(mask_char_vars, char_vars):
        d = {}
        for var_name, char_string in mask_char_vars.iteritems():
            if char_string[0] in ("+", "I"): # Pending read, propagate for resolution when decoding this opcode 
                var_value = char_string
            else:
                var_value = char_vars[char_string]
                if var_name == "cc":
                    var_value = get_cc_label(var_value)
                elif var_name == "z":
                    var_value = get_size_label(var_value)
                elif var_name == "d":
                    var_value = get_direction_label(var_value)
            d[var_name] = var_value
        return d

    chars = I.specification.mask_char_vars.values()
    for O in I.opcodes:
        for mask_char in O.specification.mask_char_vars.itervalues():
            if mask_char not in chars:
                chars.append(mask_char)
    char_vars = _get_var_values(chars, I.data_words[0], I.table_mask)
    # In case anything wants to copy it, and it is explicitly specified.
    if I.specification.key[-2] == "." and I.specification.key[-1] in ("B", "W", "L"):
        char_vars["z"] = get_size_value(I.specification.key[-1])
    I.vars = copy_values(I.specification.mask_char_vars, char_vars) 
    for O in I.opcodes:
        O.vars = copy_values(O.specification.mask_char_vars, char_vars) 

# External API

# TODO: Will want to specify printable configuration
# - constant value type
# - constant value numeric base

def disassemble_one_line(data, data_idx, data_abs_idx):
    """ Tokenise one disassembled instruction with its operands. """
    idx0 = data_idx
    matches, data_idx = _match_instructions(data, data_idx, data_abs_idx)
    if not len(matches):
        return None, idx0

    M = matches[0]
    # An instruction may have multiple words to it, before operand data..  e.g. MOVEM
    for i in range(M.table_extra_words):
        data_word, data_idx = _get_word(data, data_idx)
        M.data_words.append(data_word)

    _disassemble_vars_pass(M)
    for operand_idx, O in enumerate(M.opcodes):
        data_idx = _decode_operand(data, data_idx, operand_idx, M, O)
        if data_idx is None: # Disassembly failure.
            return None, idx0
    M.num_bytes = data_idx - idx0
    return M, data_idx

def disassemble_as_data(data, data_idx):
    # F-line instruction.
    if _get_byte(data, data_idx)[0] & 0xF0 == 0xF0:
        return 2
    return 0

def get_instruction_string(instruction, vars):
    """ Get a printable representation of an instruction. """
    key = instruction.specification.key
    return _get_formatted_description(key, vars)

def get_operand_string(instruction, operand, vars, lookup_symbol=None):
    """ Get a printable representation of an instruction operand. """
    pc = instruction.pc
    key = operand.key
    if key is None:
        key = operand.specification.key
    if key == "RL":
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
    elif key == "DISPLACEMENT":
        value = vars["xxx"]
        if instruction.specification.key[0:4] == "LINK":
            value_string = None
        else:
            value_string = lookup_symbol(instruction.pc + value)
        if value_string is None:
            value_string = signed_hex_string(value)
        return value_string
    elif key in SpecialRegisters:
        return key
    else:
        return _get_formatted_ea_description(instruction, key, vars, lookup_symbol=lookup_symbol)

MAF_CODE = 1
MAF_ABSOLUTE = 2

def get_match_addresses(match, extra=True):
    # Is it an instruction that exits (RTS, RTR)?
    # Is it an instruction that conditionally branches (Bcc, Dbcc)?
    # Is it an instruction that branches and returns (JSR, BSR)?
    # Is it an instruction that jumps (BRA, JMP)?
    # Given a branch/jump address, have we seen it before?
    # Given a branch/jump address, should it be queued?
    # Given a branch/jump address, should it be done next?
    address = None
    instruction_key = match.specification.key[:3]
    if instruction_key in ("RTS", "RTR"):
        pass
    elif instruction_key in ("JMP", "BRA"):
        if match.opcodes[0].key == "AbsL":
            address = match.opcodes[0].vars["xxx"]
        elif match.opcodes[0].specification.key == "DISPLACEMENT":
            address = match.pc + match.opcodes[0].vars["xxx"]
    elif instruction_key == "JSR":
        if match.opcodes[0].key == "AbsL":
            address = match.opcodes[0].vars["xxx"]
    elif instruction_key == "BSR":
        address = match.pc + match.opcodes[0].vars["xxx"]
    elif instruction_key in ("Bcc", "DBc"):
        opcode_idx = 0 if instruction_key == "Bcc" else 1
        address = match.pc + match.opcodes[opcode_idx].vars["xxx"]

    ret = {}
    if address is not None:
        ret[address] = MAF_CODE

    # Locate any general addressing modes which infer labels.
    for opcode in match.opcodes:
        if opcode.key == "PCid16":
            address = match.pc + _signed_value("W", opcode.vars["D16"])
            if address not in ret:
                ret[address] = 0
        elif opcode.key == "PCiId8":
            address = match.pc + _signed_value("W", opcode.vars["D8"])
            if address not in ret:
                ret[address] = 0
        elif extra and opcode.key == "AbsL":
            address = opcode.vars["xxx"]
            if address not in ret:
                ret[address] = 0
        elif extra and opcode.key == "Imm":
            address = opcode.vars["xxx"]
            ret[address] = ret.get(address, 0) | MAF_ABSOLUTE
        elif opcode.key in ("PCiIdb", "PCiPost", "PrePCi"):
            logger.error("Unhandled opcode EA modde (680x0?): %s", opcode.key)

    return ret

def is_final_instruction(match):
    instruction_key = match.specification.key[:3]
    return instruction_key in ("RTS", "RTR", "JMP", "BRA")

def is_big_endian():
    return True

