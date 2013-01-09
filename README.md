# Peasauce Disassembler

## Support

You can email me at:

 richard.m.tew@gmail.com

If you wish to generally support or encourage the development of this tool, or sponsor the development of specific features, [Paypal donations](http://disinterest.org/donate.html) will be used for that purpose.  For those who are serious about sponsoring development of a specific feature it is best to discuss it with me at my email address first.

## Goal

The current primary goal is to handle disassembling Amiga m68000 executables. Support for the wider family of m680x0 instructions, or executables for other platforms that used these chips is within scope, in order to drive better code structure for later expansion to other architectures or platforms.

Using Resource to disassemble within an Amiga emulator is still a wonderful experience, however it has aged.  It is not possible to modify it, and it is also nowhere near as nice as being able to use a proper application in your own operating system.

## Features

Peasauce can currently do the following:

* Load and attempt to disassemble Amiga executable files.
* Load and attempt to disassemble Atari ST executable files.
* Load and attempt to disassemble X68000 executable files.
* Attempt to disassemble loaded M68000 code

Note that there are limitations, files which include unsupported assembly code or use special executable file features may among other things not get loaded, or disassembled fully.

![Editing a label](http://i.imgur.com/cUMLj.png "Editing a label")

![Self-modifying code](http://i.imgur.com/Fyefy.png "Self-modifying code")

## Licensing

All files that comprise this are released under the GPLv3 license.

Any source code contributions must be made by the sole author of those contributions, and be contributed with dual licensing under both the MIT and GPLv3 license.  At some point in the future, I may wish to use parts of this in commercial projects, or switch the license of the open source project as a whole to the more liberal MIT license.

## Installation

Currently Peasauce is prototyped in Python using wxPython to display it's user interface.  The only installation you need to do, is to ensure the following prerequisites are installed on your computer.

1. Download and install [Python 2.7](http://python.org/download/) for your platform.
2. Download and install [PySide for Python 2.7](http://www.pyside.org/) for your platform.

## Usage

With the prerequisites installed, and with the source code that accompanies this file on hand, you should be able to run Peasauce.  Note that you will need either Amiga, X68000 or Atari ST executable files to load into it.  You can obtain many Amiga programs from [aminet.net](http://aminet.net).  Some Amiga programs are archived using now obscure compression programs, but if you also download and install [7zip](www.7-zip.org) you should be able to extract files from within them.

Method 1 (any platform):
* Enter the "python" directory and run the "qtui.py" Python script.

Method 2 (Windows & DOS/Explorer):
* Run "run.bat".

Method 3 (Linux, MacOS X, Windows & MinGW .. etc):
* Edit "run.sh" to be able to find your Python 2.7 executable and run it.

You should be able to use the user interface to:
* Load and disassemble a new file (menu or Ctrl+O).
* Scroll through a loaded and disassembled file.
* Change the font used to a smaller or non-proportional one (menu).
* Edit label names (Enter).
* Change datatype of pieces of disassembled data (menu).
* Save and load ongoing disassembly work as a project file (menu).
* Export current complete disassembled source code (menu).
* Jump to an operand address (Ctrl+Right).
* Select from, and jump to addresses that refer to the currently selected label (Ctrl+Shift+Right).
* Return to the last address jumped from (Ctrl+Left).

Note that the ongoing work save file format is not final, and when it changes, older save files will not be loadable.  For this reason, you should not use this disassembler unless you can deal with that.

## Future Work

This is intended to be a summarised list of points that briefly note intended work, or possible future work.

### Short Term Tasks

#### Bugs

* Disassembly: Instruction "move.l $(4.w), a6" is interpreted as referring to offset 4 in executables.  This is a more general problem that creates a label for each absolute address.
* Metadata: If address lies outside known segment address ranges, only accept last block address + last block length as only valid address of that type.  Others not labeled. 
* Metadata: If a code is being processed, and it overruns its block, take the spilt part of the next block.  Ensure mid-match labels are dealt with.
* Metadata: Label placement should consider the case where a value happens to match a known address, like how Resource has #START+$50, where that might actually be $50 or whatever.
* UI: For binary file disassembly, changing some data blocks with uncertain references to code blocks will not remove the entries from the data reference list.
* UI: For loading projects, should show existing unused UI to prompt user to select the right file (if it is not encapsulated in the project).

#### Functionality

* UI: Ala Resource, change the numeric base of a value whether code operand or data.
* UI: Ala Resource, edit/override values.
* Disassembly: Enable customised display of upper case or lower case for instructions / operand bits.
* Disassembly: Display DBRA instead of DBF (is this right?).
* Disassembly: Customisable display of either A7 or SP.
* Disassembly: Jump table discovery / processing.
* Disassembly: Research assembler syntax for different platforms, to generalise custom output.
* Disassembly: Choose use of new or old style assembly syntax.
* File loading: For Amiga, choose use of "DATA, CHIP" or "DATA_C" in section headers.
* Metadata: File-backed storage space should optionally use aggregate instructions, e.g. "dcb.l 230,0"
* Metadata: Add leading comments that detail file type, processor, entry point offset.. maybe more.

#### Technical Debt

* Binary files: Separate platform and file loading.  Then binary files can be assigned a platform.
* Coding style: Look at ways to make the code more straightforward.
* Disassembly: Do a correct formatting check on the instruction table II_NAME column.
* Disassembly: Move the renaming symbol validation regular expression into the platform or architecture level.
* Metadata: "Imm"/absolute operand value label lookup should be improved.  Track offsets in instruction relocations are made?

### Medium Term Tasks

#### Functionality

* Debugging: Connect to WinUAE and select from and debug running processes.
* Debugging: Connect to WinUAE, browse files, and select a file to run and debug.
* Decompilation: Look into IRs.  LLVM?
* Disassembly: Handle more / differentiate between different M680x0 instructions.
* File loading: Use 'vamos' or Toni Wilen's WinUAE example to run amiga packer detection and unpacking.

### Long Term Tasks

#### Functionality

* Disassembly: Support ARM instructions.
* Disassembly: Support PowerPC instructions.
* Disassembly: Support x86 instructions.
* Disassembly: Support x86-64 instructions.
* File loading: Support Amiga library loading.
* File loading: Support Amiga object file loading.
* File loading: Support Mac OS X Mach-O executable loading.
* File loading: Support Macintosh m68k PEF loading.
* File loading: Support Windows PE loading.

#### Pie In The Sky

* Disassembly: Generate library signatures and use to jumpstart disassembly.
* UI: Collaborative work on the same file.
* UI: Upload symbols to a remote server and allow merging of work.
