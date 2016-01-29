"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.
"""

import glob
import logging
import os
import sys

from . import constants


logger = logging.getLogger("tool-assembler-vasm")


def get_top_level_path():
    # path of the python script being run.
    #path = sys.path[0]
    ##if not len(path):
    path = os.getcwd()
    return path


class BaseAssembler(object):
    _cpu_id = constants.CPU_UNKNOWN
    _syntax_id = constants.ASM_SYNTAX_UNKNOWN
    _output_format_id = constants.OUTPUT_FORMAT_UNKNOWN

    _option_names = None
    _supported_cpus = None

    def set_cpu(self, cpu_id):
        self._cpu_id = cpu_id

    def set_syntax(self, syntax_id):
        self._syntax_id = syntax_id

    def set_output_format(self, output_format_id):
        _lookup_option_value(constants.OPTIONS_FILE_OUTPUT, output_format_id, check=True)
        self._output_format_id = output_format_id

    def _lookup_option_value(self, key_id, value_id, check=False):
        try:
            return self._option_names[key_id][value_id]
        except KeyError:
            if check:
                return None
            raise

LOCAL_BINARIES_NAME = "local_binaries"

class Assembler(BaseAssembler):
    _option_names = {
        constants.OPTIONS_STANDARD: {
            constants.OPTION_DISABLE_OPTIMISATIONS: "-no-opt",
        },
        constants.OPTIONS_CPU: {
            constants.CPU_MC60000: "-m68000",
            constants.CPU_MC60010: "-m68010",
            constants.CPU_MC60020: "-m68020",
            constants.CPU_MC60030: "-m68030",
            constants.CPU_MC60040: "-m68040",
            constants.CPU_MC60060: "-m68060",
        },
        constants.OPTIONS_FILE_OUTPUT: {
            constants.OUTPUT_FORMAT_BINARY: "-Fbin",
            constants.OUTPUT_FORMAT_ATARIST_TOS: "-Ftos",
            constants.OUTPUT_FORMAT_AMIGA_HUNK: "-Fhunk",
        },
    }

    """ These will be populated from the naming of located executables. """
    _supported_cpus = set([
    ])

    FILE_NAME_PREFIX = "vasm"
    FILE_NAME_SUFFIX = "_win32.exe"

    def __init__(self):
        if os.name != "nt":
            logger.warning("vasm only supported on Windows (pull requests accepted)")
            return

        # A top-level directory in the .
        path = get_top_level_path()
        local_binaries_path = os.path.join(path, LOCAL_BINARIES_NAME)
        if not os.path.exists(local_binaries_path):
            logger.warning("Top-level '%s' directory missing (place vasm binaries here)", LOCAL_BINARIES_NAME)
            return

        pattern_prefix = self.FILE_NAME_PREFIX
        # TODO: Handle suffixes for other platforms.
        pattern_suffix = self.FILE_NAME_SUFFIX
        match_pattern = os.path.join(local_binaries_path, pattern_prefix +"*"+ pattern_suffix)
        matches = glob.glob(match_pattern)
        if not len(matches):
            logger.warning("Unable to locate vasm executables (place vasm binaries in top-level '%s' directory", LOCAL_BINARIES_NAME)
            return

        for matched_file_path in matches:
            matched_dir_path, matched_file_name = os.path.split(matched_file_path)
            unique_substring = matched_file_name[len(pattern_prefix):-len(pattern_suffix)]
            cpu_name, syntax_name = unique_substring.split("_")
            syntax_id = None
            if syntax_name == "mot":
                syntax_id = constants.ASM_SYNTAX_MOTOROLA
            else:
                logger.warning("vasm executable '%s' has unknown syntax, skipping..", matched_file_path)
                continue

            if cpu_name == "m68k" and syntax_id is not None:
                self._supported_cpus.add((constants.CPU_MC60000, syntax_id))
                self._supported_cpus.add((constants.CPU_MC60010, syntax_id))
                self._supported_cpus.add((constants.CPU_MC60020, syntax_id))
                self._supported_cpus.add((constants.CPU_MC60030, syntax_id))
                self._supported_cpus.add((constants.CPU_MC60040, syntax_id))
                self._supported_cpus.add((constants.CPU_MC60060, syntax_id))

        logger.info("Detected %d supported cpu(s) for vasm assembler", len(self._supported_cpus))

    def compile_text(self, text):
        pass
