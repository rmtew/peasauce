"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

import logging

logger = logging.getLogger("disassemblylib")


def get_processor_ids():
    import loaderlib
    return [
        loaderlib.constants.PROCESSOR_M680x0,
        loaderlib.constants.PROCESSOR_MIPS,
        loaderlib.constants.PROCESSOR_65c816,
    ]

def get_processor(processor_id):
    import loaderlib
    if processor_id == loaderlib.constants.PROCESSOR_65c816:
        from arch65c816 import Arch65c816 as ArchClass
        from arch65c816 import instruction_table
        from arch65c816 import operand_type_table
    elif processor_id == loaderlib.constants.PROCESSOR_M680x0:
        from archm68k import ArchM68k as ArchClass
        from archm68k import instruction_table
        from archm68k import operand_type_table
    elif processor_id == loaderlib.constants.PROCESSOR_MIPS:
        from archmips import ArchMIPS as ArchClass
        from archmips import instruction_table
        from archmips import operand_type_table
    elif processor_id == loaderlib.constants.PROCESSOR_Z80:
        from archmips import ArchZ80 as ArchClass
        from archmips import instruction_table
        from archmips import operand_type_table
    else:
        logger.error("get_processor: %s unknown", processor_id)

    arch = ArchClass()
    arch.set_operand_type_table(operand_type_table)
    arch.set_instruction_table(instruction_table)
    return arch
