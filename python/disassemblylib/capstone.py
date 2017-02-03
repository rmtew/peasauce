"""
This module is intended to emulate Capstone, with the option of bringing in
Capstone to do the work, if desirable.
"""

# mypy-lang support
from typing import Iterator

from . import util as disassemblylib_util

CS_ARCH_ARM = 0
CS_ARCH_ARM64 = 1
CS_ARCH_MIPS = 2
CS_ARCH_X86 = 3
CS_ARCH_PPC = 4
CS_ARCH_SPARC = 5
CS_ARCH_SYSZ = 6
CS_ARCH_XCORE = 7
CS_ARCH_M68K = 8
CS_ARCH_MAX = 9
CS_ARCH_ALL = 0xFFFF

CS_MODE_LITTLE_ENDIAN = 0      # little-endian mode (default mode)
CS_MODE_ARM = 0                # ARM mode
CS_MODE_16 = (1 << 1)          # 16-bit mode (for X86)
CS_MODE_32 = (1 << 2)          # 32-bit mode (for X86)
CS_MODE_64 = (1 << 3)          # 64-bit mode (for X86, PPC)
CS_MODE_THUMB = (1 << 4)       # ARM's Thumb mode, including Thumb-2
CS_MODE_MCLASS = (1 << 5)      # ARM's Cortex-M series
CS_MODE_V8 = (1 << 6)          # ARMv8 A32 encodings for ARM
CS_MODE_MICRO = (1 << 4)       # MicroMips mode (MIPS architecture)
CS_MODE_MIPS3 = (1 << 5)       # Mips III ISA
CS_MODE_MIPS32R6 = (1 << 6)    # Mips32r6 ISA
CS_MODE_V9 = (1 << 4)          # Sparc V9 mode (for Sparc)
CS_MODE_QPX = (1 << 4)         # Quad Processing eXtensions mode (PPC)
CS_MODE_M68K_000 = (1 << 1)    # M68K 68000 mode
CS_MODE_M68K_010 = (1 << 2)    # M68K 68010 mode
CS_MODE_M68K_020 = (1 << 3)    # M68K 68020 mode
CS_MODE_M68K_030 = (1 << 4)    # M68K 68030 mode
CS_MODE_M68K_040 = (1 << 5)    # M68K 68040 mode
CS_MODE_M68K_060 = (1 << 6)    # M68K 68060 mode
CS_MODE_BIG_ENDIAN = (1 << 31) # big-endian mode
CS_MODE_MIPS32 = CS_MODE_32    # Mips32 ISA
CS_MODE_MIPS64 = CS_MODE_64    # Mips64 ISA

_cs_register_names = [
	"invalid",
	"d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7",
	"a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
	"fp0", "fp1", "fp2", "fp3", "fp4", "fp5", "fp6", "fp7",
	"pc",
	"sr", "ccr", "sfc", "dfc", "usp", "vbr", "cacr",
	"caar", "msp", "isp", "tc", "itt0", "itt1", "dtt0",
	"dtt1", "mmusr", "urp", "srp",
	"fpcr", "fpsr", "fpiar",
]

_cs_instruction_names = [
	"invalid",
	"abcd", "add", "adda", "addi", "addq", "addx", "and", "andi", "asl", "asr", "bhs", "blo", "bhi", "bls", "bcc", "bcs", "bne", "beq", "bvc",
	"bvs", "bpl", "bmi", "bge", "blt", "bgt", "ble", "bra", "bsr", "bchg", "bclr", "bset", "btst", "bfchg", "bfclr", "bfexts", "bfextu", "bfffo", "bfins",
	"bfset", "bftst", "bkpt", "callm", "cas", "cas2", "chk", "chk2", "clr", "cmp", "cmpa", "cmpi", "cmpm", "cmp2", "cinvl", "cinvp", "cinva", "cpushl", "cpushp",
	"cpusha", "dbt", "dbf", "dbhi", "dbls", "dbcc", "dbcs", "dbne", "dbeq", "dbvc", "dbvs", "dbpl", "dbmi", "dbge", "dblt", "dbgt", "dble", "dbra",
	"divs", "divsl", "divu", "divul", "eor", "eori", "exg", "ext", "extb", "fabs", "fsabs", "fdabs", "facos", "fadd", "fsadd", "fdadd", "fasin",
	"fatan", "fatanh", "fbf", "fbeq", "fbogt", "fboge", "fbolt", "fbole", "fbogl", "fbor", "fbun", "fbueq", "fbugt", "fbuge", "fbult", "fbule", "fbne", "fbt",
	"fbsf", "fbseq", "fbgt", "fbge", "fblt", "fble", "fbgl", "fbgle", "fbngle", "fbngl", "fbnle", "fbnlt", "fbnge", "fbngt", "fbsne", "fbst", "fcmp", "fcos",
	"fcosh", "fdbf", "fdbeq", "fdbogt", "fdboge", "fdbolt", "fdbole", "fdbogl", "fdbor", "fdbun", "fdbueq", "fdbugt", "fdbuge", "fdbult", "fdbule", "fdbne",
	"fdbt", "fdbsf", "fdbseq", "fdbgt", "fdbge", "fdblt", "fdble", "fdbgl", "fdbgle", "fdbngle", "fdbngl", "fdbnle", "fdbnlt", "fdbnge", "fdbngt", "fdbsne",
	"fdbst", "fdiv", "fsdiv", "fddiv", "fetox", "fetoxm1", "fgetexp", "fgetman", "fint", "fintrz", "flog10", "flog2", "flogn", "flognp1", "fmod", "fmove",
	"fsmove", "fdmove", "fmovecr", "fmovem", "fmul", "fsmul", "fdmul", "fneg", "fsneg", "fdneg", "fnop", "frem", "frestore", "fsave", "fscale", "fsgldiv",
	"fsglmul", "fsin", "fsincos", "fsinh", "fsqrt", "fssqrt", "fdsqrt", "fsf", "fseq", "fsogt", "fsoge", "fsolt", "fsole", "fsogl", "fsor", "fsun", "fsueq",
	"fsugt", "fsuge", "fsult", "fsule", "fsne", "fst", "fssf", "fsseq", "fsgt", "fsge", "fslt", "fsle", "fsgl", "fsgle", "fsngle",
	"fsngl", "fsnle", "fsnlt", "fsnge", "fsngt", "fssne", "fsst", "fsub", "fssub", "fdsub", "ftan", "ftanh", "ftentox", "ftrapf", "ftrapeq", "ftrapogt",
	"ftrapoge", "ftrapolt", "ftrapole", "ftrapogl", "ftrapor", "ftrapun", "ftrapueq", "ftrapugt", "ftrapuge", "ftrapult", "ftrapule", "ftrapne", "ftrapt",
	"ftrapsf", "ftrapseq", "ftrapgt", "ftrapge", "ftraplt", "ftraple", "ftrapgl", "ftrapgle", "ftrapngle", "ftrapngl", "ftrapnle", "ftrapnlt", "ftrapnge",
	"ftrapngt", "ftrapsne", "ftrapst", "ftst", "ftwotox", "halt", "illegal", "jmp", "jsr", "lea", "link", "lpstop", "lsl", "lsr", "move", "movea", "movec",
	"movem", "movep", "moveq", "moves", "move16", "muls", "mulu", "nbcd", "neg", "negx", "nop", "not", "or", "ori", "pack", "pea", "pflush", "pflusha",
	"pflushan", "pflushn", "ploadr", "ploadw", "plpar", "plpaw", "pmove", "pmovefd", "ptestr", "ptestw", "pulse", "rems", "remu", "reset", "rol", "ror",
	"roxl", "roxr", "rtd", "rte", "rtm", "rtr", "rts", "sbcd", "st", "sf", "shi", "sls", "scc", "shs", "scs", "slo", "sne", "seq", "svc", "svs", "spl", "smi",
	"sge", "slt", "sgt", "sle", "stop", "sub", "suba", "subi", "subq", "subx", "swap", "tas", "trap", "trapv", "trapt", "trapf", "traphi", "trapls",
	"trapcc", "traphs", "trapcs", "traplo", "trapne", "trapeq", "trapvc", "trapvs", "trappl", "trapmi", "trapge", "traplt", "trapgt", "traple", "tst", "unlk", "unpk",
]

M68K_GRP_JUMP = 1
M68K_GRP_RET = 3
M68K_GRP_IRET = 5

_cs_group_names = [
    None,
    "jump",
    None,
    "ret",
    None,
    "iret",
]

_cs_instruction_nameindexes_by_name = None

class capstone_Operand(object):
    pass

class capstone_Instruction(object):
    def __init__(self, peasauce_instruction):
        # type: (disassemblylib_util.Match) -> None
        self.peasauce_instruction = peasauce_instruction

        self.operands = [] # type: List[capstone_Operand]
        for peasauce_operand in peasauce_instruction.opcodes:
            # TODO(rmtew): Build capstone operands for each peasauce one.
            pass

    @property
    def id(self):
        # type: () -> int
        if _cs_instruction_nameindexes_by_name is None:
            _cs_instruction_nameindexes_by_name = {}
            for i, cs_instruction_name in enumerate(_cs_instruction_names):
                self._capstone_instruction_name_index_by_name[cs_instruction_name] = i
        # This will raise an exception if the instruction name is not in there.
        return _cs_instruction_nameindexes_by_name[self.insn_name]

    @property
    def address(self):
        # type: () -> int
        return self.peasauce_instruction.pc - 2 # TODO(rmtew): 2 is m68k offset

    @property
    def size(self):
        # type: () -> int
        return self.peasauce_instruction.num_bytes

    @property
    def bytes(self):
        # type: () -> str
        return self.peasauce_instruction.data

    @property
    def mnemonic(self):
        # type: () -> str
        # Returns the instruction name with . suffix (size).
        # However, it is possible for things to substitute mnemonics.
        return self.specification.key.lower()

    @property
    def op_str(self): # TODO
        # type: () -> str
        # The operands string.  Per-platform as specified by the given assembler.
        # TODO(rmtew): Generate the operands string.
        return ""

    @property
    def groups(self):
        # type: () -> List[int] 
        peasauce_flags = self.peasauce_instruction.table_flags
        group_ids = []
        if peasauce_flags & IFX_BRANCH == IFX_BRANCH:
            group_ids.append(M68K_GRP_JUMP)
        elif peasauce_flags & IFX_ENDSEQ == IFX_ENDSEQ:
            group_ids.append(M68K_GRP_RET)
        return group_ids

    @property
    def regs_read(self): # TODO
        # type: () -> List[int]
        return []

    @property
    def regs_read_count(self): # TODO
        # type: () -> int
        return 0

    @property
    def regs_write(self): # TODO
        # type: () -> List[int]
        return []

    @property
    def regs_read_count(self): # TODO
        # type: () -> int
        return 0

    def reg_name(self, reg_id, default=None):
        # type: (int, str) -> str
        return _cs_register_names[reg_id]

    @property
    def insn_name(self, default=None):
        # type: (str) -> str
        # Returns the instruction name.
        base_instruction_name = self.specification.key.lower()
        suffix_index = base_instruction_name.find(".")
        if suffix_index != -1:
            base_instruction_name = base_instruction_name[:suffix_index]
        return base_instruction_name

    def group_name(self, group_id, default=None):
        # type: (int, str) -> str
        name = _cs_group_names[group_id]
        if name is None:
            return default
        return name

    def group(self, group_id):
        # type: (int) -> bool
        return group_id in self.groups

    # reg_read
    # reg_write

    def op_count(self, op_type):
        # type: (int) -> int
        count = 0
        for operand in self.operands:
            if operand.type == op_type:
                count += 1
        return count

    def op_find(self, op_type, position):
        # type: (int) -> _capstone_Operand
        count = 0
        for operand in self.operands:
            if operand.type == op_type:
                count += 1
            if count == position:
                return operand

    def regs_access(self):
        # type: () -> Tuple[Tuple[int], Tuple[int]]
        return (self.regs_read, self.regs_write)


class Cs(object):
    detail = False

    def __init__(self, cs_arch, cs_mode):
        # type: (int, int) -> None
        self.cs_arch = cs_arch
        self.cs_mode = cs_mode

    def disasm(self, code, offset, count=1):
        # type: (str, int, int) -> Iterator[capstone_Instruction]
        """
        code: the data
        offset: address of first instruction word
        count: the number of instructions to disassemble
        """
        for i in range(count):
            pass
            # TODO(rmtew): disassemble a line.
            # offset = address of first instruction word
            # 

