"""
    Peasauce - interactive disassembler
    Copyright (C) 2012-2016 Richard Tew
    Licensed using the MIT license.

    This file is intended to allow compilation of assembler instructions and
    from the compiled binary, the ability to isolate the machine code those
    instructions produce.

    The targeted assembler is vasm, whose home page is located here:

        http://sun.hasenbraten.de/vasm/index.php

    As the author uses Windows it is the only platform currently supported.
    Anyone wanting to add support for their own platform will need to do the
    following steps:

        1. Compile vasm for a combination of cpu and syntax.

           On Windows with Visual Studio 2015 installed, this is done with the
           following steps:

           a) Download and extract the vasm source code from the link above.
           b) Open a developer command prompt for Visual Studio.
           c) In the command window, enter the vasm source code directory.
           d) Type a variant of 'nmake -f Makefile.Win32 CPU=m68k SYNTAX=mot'.
           e) Observe 'vasm<cpu>_<syntax>_win32.exe' now exists, where <cpu>
              and <syntax> are whatever you specified to 'nmake'.

        2. At this point you will have an executable.  As illustrated in the
           previous step, on Windows for the m68k cpu and Motorola syntax,
           this will be named 'vasmm68k_mot_win32.exe'.  This module currently
           only knows to look in a particular directory for files with a name
           matching 'vasm*_win32.exe'.

           To add support for your platform:

           a) Modify FILE_NAME_PREFIX and FILE_NAME_SUFFIX so that only vasm
              executables matching your file name will be found.
           b) Add some code to look for commands in your path matching the
              resulting pattern - maybe call some shell command to do this.
           c) Process the results the same way Windows does.

        3. Commit the code to your github fork of the project and do a pull
           request to the author.

"""

import glob
import logging
import os
import subprocess
import sys
import StringIO
import tempfile

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

    def compile_text(self, text, cpu_id, syntax_id):
        """ Take assembly language instructions and return the corresponding machine code. """
        assembler_path = self._supported_cpus.get((cpu_id, syntax_id), None)
        if assembler_path is None:
            cpu_name = constants.get_cpu_name_by_id(cpu_id)
            syntax_name = constants.get_syntax_name_by_id(syntax_id)
            logger.error("cpu %s and syntax %s not unsupported", cpu_name, syntax_name)
            return

        # Work out the output file path.
        output_path = tempfile.gettempdir()
        output_file_name = self._option_names[constants.OPTIONS_STANDARD][constants.OPTION_DEFAULT_FILE_NAME]
        output_file_path = os.path.join(output_path, output_file_name)

        # Create a temporary file for the text to be assembled.
        input_file_path = tempfile.mktemp()
        input_file = open(input_file_path, "w")
        input_file.write(text)
        input_file.close()

        LOG_STDOUT = True
        LOG_STDERR = True

        stdout = tempfile.NamedTemporaryFile()
        stderr = tempfile.NamedTemporaryFile()

        current_path = os.getcwd()
        try:
            input_file_path = input_file.name

            os.chdir(output_path)
            if os.path.exists(output_file_path):
                os.remove(output_file_path)

            call_args = [ assembler_path, input_file_path ]

            option_list = [
                (constants.OPTIONS_STANDARD, constants.OPTION_DISABLE_OPTIMISATIONS),
                (constants.OPTIONS_FILE_OUTPUT, constants.OUTPUT_FORMAT_BINARY),
                (constants.OPTIONS_CPU, cpu_id),
            ]
            for k1, k2 in option_list:
                flag_string = self._lookup_option_value(k1, k2, check=True)
                if flag_string is not None:
                    call_args.append(flag_string)

            logger.debug("command line arguments: %s", " ".join(call_args[2:]))
            result = subprocess.call(call_args, stdout=stdout, stderr=stderr)

            if LOG_STDOUT:
                stdout.flush()
                stdout.seek(0, os.SEEK_SET)
                stdout_text = stdout.read()

            if result == 0:
                ret = open(output_file_path, "rb").read()
                logger.debug("success: binary file of size %d bytes", len(ret))
                return ret
            else:
                if LOG_STDERR:
                    stderr.flush()
                    stderr.seek(0, os.SEEK_SET)
                    stderr_text = stderr.read()

                    logger.error("assembler failure: standard error contents follow")
                    lines = [ line for line in stderr_text.split(os.linesep) if len(line) ]
                    for line in lines:
                        logger.error("assembler failure: %s", line)
                else:
                    logger.error("assembler returned failure result")
        finally:
            stdout.close()
            stderr.close()
            os.remove(input_file_path)
            os.chdir(current_path)


LOCAL_BINARIES_NAME = "local_binaries"

class Assembler(BaseAssembler):
    _option_names = {
        constants.OPTIONS_STANDARD: {
            constants.OPTION_DISABLE_OPTIMISATIONS: "-no-opt",
            constants.OPTION_DEFAULT_FILE_NAME: "a.out",
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
    _supported_cpus = {
    }

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
                self._supported_cpus[(constants.CPU_MC60000, syntax_id)] = matched_file_path
                self._supported_cpus[(constants.CPU_MC60010, syntax_id)] = matched_file_path
                self._supported_cpus[(constants.CPU_MC60020, syntax_id)] = matched_file_path
                self._supported_cpus[(constants.CPU_MC60030, syntax_id)] = matched_file_path
                self._supported_cpus[(constants.CPU_MC60040, syntax_id)] = matched_file_path
                self._supported_cpus[(constants.CPU_MC60060, syntax_id)] = matched_file_path

        logger.debug("Detected %d supported cpu(s) for vasm assembler", len(self._supported_cpus))
