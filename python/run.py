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
"""

DEBUG_ANNOTATE_DISASSEMBLY = True

import bisect
import logging
import os
import sys
import traceback

import wx

import archlib
from disasmlib import archm68k

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)


# CURRENT GLOBAL VARIABLES
reloc_addresses = None
branch_addresses = None
disassembly_listctrl = None
file_info = None
symbols_by_address = None
entrypoint_address = None

file_metadata_addresses = None
file_metadata_line0 = None
file_metadata_blocks = None
file_metadata_dirtyidx = None


class DisplayConfiguration(object):
    trailing_line_rts = True
    trailing_line_branch = True
    trailing_line_trap = True

display_configuration = DisplayConfiguration()

class SegmentBlock(object):
    """ The number of this segment in the file. """
    segment_id = None
    """ The offset of this block in its segment. """
    idx = None
    """ All segments appear as one contiguous address space.  This is the offset of this block in that space. """
    abs_idx = None
    """ The number of bytes data that this block contains. """
    length = None
    """ The data type of this block (DATA_TYPE_*) and more """
    flags = 0
    """ DATA_TYPE_CODE: Match metadata. """
    code_match = None
    """ Calculated number of lines. """
    line_count = 0

## Utility functions

def _count_bits(v):
    count = 0
    while v:
        count += 1
        v >>= 1
    return count

def _make_bitmask(bitcount):
    mask = 0
    while bitcount:
        bitcount -= 1
        mask |= 1<<bitcount
    return mask

## SegmentBlock flag helpers

def get_data_type(flags):
    return (flags >> DATA_TYPE_BIT0) & DATA_TYPE_BITMASK

def set_data_type(block, data_type):
    block.flags &= ~(DATA_TYPE_BITMASK << DATA_TYPE_BIT0)
    block.flags |= ((data_type & DATA_TYPE_BITMASK) << DATA_TYPE_BIT0)


DATA_TYPE_CODE      = 1
DATA_TYPE_ASCII     = 2
DATA_TYPE_BYTE      = 3
DATA_TYPE_WORD      = 4
DATA_TYPE_LONGWORD  = 5
DATA_TYPE_BIT0      = DATA_TYPE_CODE - 1
DATA_TYPE_BITCOUNT  = _count_bits(DATA_TYPE_LONGWORD)
DATA_TYPE_BITMASK   = _make_bitmask(DATA_TYPE_BITCOUNT)

""" If the block is not backed by file data. """
BLOCK_FLAG_ALLOC    = 1 << DATA_TYPE_BITCOUNT


def calculate_line_count(block):
    old_line_count = block.line_count
    block.line_count = 0
    if block.idx == 0 and file_info.has_section_headers():
        block.line_count += 1 # HUNK HEADER (SECTION ...)
    if get_data_type(block.flags) == DATA_TYPE_CODE:
        block.line_count += 1
        if display_configuration.trailing_line_rts and block.code_match.specification.key == "RTS":
            block.line_count += 1
        elif display_configuration.trailing_line_trap and block.code_match.specification.key == "TRAP":
            block.line_count += 1
        elif display_configuration.trailing_line_branch and block.code_match.specification.key in ("Bcc", "BRA", "DBcc", "JMP"):
            block.line_count += 1
    elif get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        # If there are excess bytes that do not fit into the given data type, append them in the smaller data types.
        if get_data_type(block.flags) == DATA_TYPE_LONGWORD:
            size_types = [ ("L", 4), ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_WORD:
            size_types = [ ("W", 2), ("B", 1) ]
        elif get_data_type(block.flags) == DATA_TYPE_BYTE:
            size_types = [ ("B", 1) ]

        size_counts = []
        excess_length = block.length
        for size_char, num_bytes in size_types:
            size_count = excess_length / num_bytes
            if size_count == 0:
                continue
            size_counts.append(size_count)
            excess_length -= size_count * num_bytes

        # Memory that is not mapped to file contents is placed into aggregate space declarations.
        if block.flags & BLOCK_FLAG_ALLOC:
            block.line_count += len(size_counts)
        else:
            block.line_count += sum(size_counts)
    else:
        block.line_count = 0
        return block.line_count - old_line_count

    # Last block in a segment gets a trailing line, if it is not the last segment.
    if block.idx + block.length == file_info.get_segment_length(block.segment_id) and block.segment_id < file_info.get_segment_count()-1:
        block.line_count += 1 # SEGMENT FOOTER (blank line)
    return block.line_count - old_line_count

LI_OFFSET = 0
LI_BYTES = 1
LI_LABEL = 2
LI_INSTRUCTION = 3
LI_OPERANDS = 4
if DEBUG_ANNOTATE_DISASSEMBLY:
    LI_ANNOTATIONS = 5


def get_file_line(line_idx, column_idx): # Zero-based
    block, block_idx = lookup_metadata_by_line_count(line_idx)
    block_line_count0 = file_metadata_line0[block_idx]
    block_line_countN = block_line_count0 + block.line_count
    
    # If the line is the first of the block, check if it is a segment header.
    leading_line_count = 0
    if block.idx == 0 and file_info.has_section_headers():
        if line_idx == block_line_count0:
            section_header = file_info.get_section_header(block.segment_id)
            i = section_header.find(" ")
            if column_idx == LI_INSTRUCTION:
                return section_header[0:i]
            elif column_idx == LI_OPERANDS:
                return section_header[i+1:]
            else:
                return ""
        leading_line_count += 1

    # If the line is the last line in a block, check if it a "between segments" trailing blank line.
    if line_idx == block_line_countN-1:
        if block.idx + block.length == file_info.get_segment_length(block.segment_id) and block.segment_id < file_info.get_segment_count()-1:
            return ""

    # Trailing blank lines after code (factor in leading lines).
    if get_data_type(block.flags) == DATA_TYPE_CODE:
        if line_idx > block_line_count0 + leading_line_count:
            return ""

    if get_data_type(block.flags) == DATA_TYPE_CODE:
        if column_idx == LI_OFFSET:
            return "%08X" % block.abs_idx
        elif column_idx == LI_BYTES:
            data = file_info.get_segment_data(block.segment_id)
            return "".join([ "%02X" % c for c in data[block.idx:block.idx+block.length] ])
        elif column_idx == LI_LABEL:
            label = lookup_address_label(block.abs_idx)
            if label is None:
                return ""
            return label
        elif column_idx == LI_INSTRUCTION:
            return archm68k.get_instruction_string(block.code_match, block.code_match.vars)
        elif column_idx == LI_OPERANDS:
            def make_operand_string(block, operand, operand_idx):
                operand_string = None
                if operand.specification.key == "DISPLACEMENT":
                    operand_string = lookup_address_label(block.code_match.pc + operand.vars["xxx"])
                elif operand.specification.key == "AbsL" or operand.key == "AbsL":
                    operand_string = lookup_address_label(operand.vars["xxx"])
                elif operand_idx == 0 and (operand.specification.key == "Imm" or operand.key == "Imm"):
                    if len(block.code_match.opcodes) > 1:
                        operand2 = block.code_match.opcodes[1]
                        if (operand2.specification.key == "AR" or operand.key == "AR"):
                            operand_string = lookup_address_label(operand.vars["xxx"])
                            if operand_string is not None:
                                operand_string = "#"+ operand_string
                if operand_string is None:
                    return archm68k.get_operand_string(block.code_match.pc, operand, operand.vars, lookup_symbol=lookup_address_label)
                return operand_string
            opcode_string = ""
            if len(block.code_match.opcodes) >= 1:
                opcode_string += make_operand_string(block, block.code_match.opcodes[0], 0)
            if len(block.code_match.opcodes) == 2:
                opcode_string += ", "+ make_operand_string(block, block.code_match.opcodes[1], 1)
            return opcode_string
        elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
            l = []
            for o in block.code_match.opcodes:
                key = o.specification.key
                if o.key is not None and key != o.key:
                    l.append(o.key)
                else:
                    l.append(key)
            return block.code_match.specification.key +" "+ ",".join(l)
    elif get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
        # If there are excess bytes that do not fit into the given data type, append them in the smaller data types.
        size_types = []
        if get_data_type(block.flags) == DATA_TYPE_LONGWORD:
            size_types.append((4, "L", archm68k._get_long))
        if get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD):
            size_types.append((2, "W", archm68k._get_word))
        if get_data_type(block.flags) in (DATA_TYPE_LONGWORD, DATA_TYPE_WORD, DATA_TYPE_BYTE):
            size_types.append((1, "B", archm68k._get_byte))

        unconsumed_byte_count = block.length
        size_line_countN = block_line_count0 + leading_line_count
        for num_bytes, size_char, read_func in size_types:
            size_line_count = unconsumed_byte_count / num_bytes
            if size_line_count == 0:
                continue
            data_idx0 = block.idx + (block.length - unconsumed_byte_count)
            unconsumed_byte_count -= size_line_count * num_bytes
            size_line_count0 = size_line_countN
            size_line_countN += size_line_count
            if line_idx < size_line_countN:
                data_idx = data_idx0 + (line_idx - size_line_count0) * num_bytes
                if column_idx == LI_OFFSET:
                    return "%08X" % (file_info.get_segment_address(block.segment_id) + data_idx)
                elif column_idx == LI_BYTES:
                    if block.flags & BLOCK_FLAG_ALLOC:
                        return ""
                    data = file_info.get_segment_data(block.segment_id)
                    return "".join([ "%02X" % c for c in data[data_idx:data_idx+num_bytes] ])
                elif column_idx == LI_LABEL:
                    label = lookup_address_label(file_info.get_segment_address(block.segment_id) + data_idx)
                    if label is None:
                        return ""
                    return label
                elif column_idx == LI_INSTRUCTION:
                    name = file_info.get_data_instruction_string(block.segment_id, (block.flags & BLOCK_FLAG_ALLOC) != BLOCK_FLAG_ALLOC)
                    return name +"."+ size_char
                elif column_idx == LI_OPERANDS:
                    if block.flags & BLOCK_FLAG_ALLOC:
                        return str(size_line_count)
                    data = file_info.get_segment_data(block.segment_id)
                    value = read_func(data, data_idx)[0]
                    label = None
                    if size_char == "L":
                        label = lookup_address_label(value, reloc_only=True)
                    if label is None:
                        label = ("$%0"+ str(num_bytes<<1) +"X") % value
                    return label
                elif DEBUG_ANNOTATE_DISASSEMBLY and column_idx == LI_ANNOTATIONS:
                    return "-"

    block_line_count0 = block_line_countN

    # Second to last line is a blank line.
    if line_idx == block_line_count0:
        return ""

    # Last line is an end instruction.
    if line_idx == block_line_count0+1:
        if column_idx == LI_INSTRUCTION:
            return "END"
        return ""

def lookup_address_label(address, reloc_only=False):
    format_string = "lbL%06X"
    if address in symbols_by_address:
        return symbols_by_address[address]
    if address in reloc_addresses:
        return format_string % address
    if not reloc_only:
        # Fake an entrypoint label.
        if address == entrypoint_address:
            return format_string % address
        if address in branch_addresses:
            return format_string % address

def insert_branch_address(address, src_abs_idx):
    if address not in reloc_addresses:
        branch_addresses.add(address)

def insert_symbol(address, name):
    symbols_by_address[address] = name

def insert_metadata_block(insert_idx, block):
    global file_metadata_dirtyidx, file_metadata_addresses, file_metadata_line0, file_metadata_blocks
    file_metadata_addresses.insert(insert_idx, block.abs_idx)
    file_metadata_line0.insert(insert_idx, None)
    file_metadata_blocks.insert(insert_idx, block)
    # Update how much of the sorted line number index needs to be recalculated.
    if file_metadata_dirtyidx is not None and insert_idx < file_metadata_dirtyidx:
        file_metadata_dirtyidx = insert_idx

def lookup_metadata_by_address(lookup_key):
    global file_metadata_addresses, file_metadata_blocks
    lookup_index = bisect.bisect_right(file_metadata_addresses, lookup_key)
    return file_metadata_blocks[lookup_index-1], lookup_index-1

def lookup_metadata_by_line_count(lookup_key):
    global file_metadata_dirtyidx, file_metadata_line0, file_metadata_blocks
    # If there's been a block insertion, update the cumulative line counts (if the key.
    if file_metadata_dirtyidx is not None:
        line_count_start = 0
        if file_metadata_dirtyidx > 0:
            line_count_start = file_metadata_line0[file_metadata_dirtyidx-1] + file_metadata_blocks[file_metadata_dirtyidx-1].line_count
        for i in range(file_metadata_dirtyidx, len(file_metadata_line0)):
            file_metadata_line0[i] = line_count_start
            line_count_start += file_metadata_blocks[i].line_count
        file_metadata_dirtyidx = None
    # This could be skipped if an update was done, and it also checked.
    lookup_index = bisect.bisect_right(file_metadata_line0, lookup_key)
    return file_metadata_blocks[lookup_index-1], lookup_index-1


def UI_display_file():
    global file_metadata_dirtyidx, file_metadata_line0, file_metadata_addresses, file_metadata_blocks
    global disassembly_listctrl, reloc_addresses, branch_addresses, symbols_by_address, entrypoint_address
    # Clear the disassembly display.
    disassembly_listctrl.SetItemCount(0)

    reloc_addresses = set()
    branch_addresses = set()
    symbols_by_address = {}

    # Two lists to help bisect do the searching, as it can't look into the blocks to get the sort value.
    file_metadata_blocks = []
    file_metadata_addresses = []
    file_metadata_line0 = []
    file_metadata_dirtyidx = 0

    entrypoint_segment_id, entrypoint_offset = file_info.get_entrypoint()
    entrypoint_address = file_info.get_segment_address(entrypoint_segment_id) + entrypoint_offset

    # Pass 1: Process the segments.
    line_count = 0
    for segment_id in range(len(file_info.segments)):
        address = file_info.get_segment_address(segment_id)
        data_length = file_info.get_segment_data_length(segment_id)
        segment_length = file_info.get_segment_length(segment_id)

        block = SegmentBlock()
        if file_info.get_segment_type(segment_id) == archlib.SEGMENT_TYPE_BSS:
            block.flags |= BLOCK_FLAG_ALLOC
        set_data_type(block, DATA_TYPE_LONGWORD)
        block.segment_id = segment_id

        block.idx = 0
        block.abs_idx = address
        block.length = data_length
        line_count += calculate_line_count(block)
        file_metadata_addresses.append(block.abs_idx)
        file_metadata_line0.append(None)
        file_metadata_blocks.append(block)

        if segment_length > data_length:
            block = SegmentBlock()
            block.flags |= BLOCK_FLAG_ALLOC
            set_data_type(block, DATA_TYPE_LONGWORD)
            block.segment_id = segment_id
            block.abs_idx = address + data_length
            block.idx = data_length
            block.length = segment_length - data_length
            line_count += calculate_line_count(block)
            file_metadata_addresses.append(block.abs_idx)
            file_metadata_line0.append(None)
            file_metadata_blocks.append(block)

    # Pass 2: Do a data caching pass.
    for segment_id in range(file_info.get_segment_count()):
        # Basically incorporate known addresses which were relocated.
        if file_info.get_segment_data_length(segment_id):
            file_info.get_segment_data(segment_id)
            reloc_addresses.update(file_info.relocated_addresses_by_segment_id[segment_id])

        # Incorporate known symbols.
        symbols = file_info.symbols_by_segment_id[segment_id]
        address = file_info.get_segment_address(segment_id)
        for symbol_offset, symbol_name, code_flag in symbols:
            symbol_address = address + symbol_offset
            insert_symbol(symbol_address, symbol_name)
            # TODO: This needs a fix mentioned at the top of the file.
            #if code_flag:
            #    insert_branch_address(symbol_address, None)

    # Pass 3: Do a disassembly pass.
    disassembly_offsets = []
    for address in branch_addresses:
        disassembly_offsets.append((address, None))
    if entrypoint_address not in branch_addresses:
        disassembly_offsets.insert(0, (entrypoint_address, None))

    disassembly_checklist = {}
    while len(disassembly_offsets):
        abs_idx, src_abs_idx = disassembly_offsets[0]
        del disassembly_offsets[0]

        # Identify the block it currently falls within.
        block, block_idx = lookup_metadata_by_address(abs_idx)
        if False:
            # bisect sorts based on value, and the list contains blocks..
            block_idx = bisect.bisect_left(file_metadata_addresses, abs_idx)
            if block_idx == len(file_metadata_addresses):
                li = len(file_metadata_addresses)-1
                lb = file_metadata_blocks[li]
                print "?? what was this for?", abs_idx, (lb.abs_idx, lb.abs_idx + lb.length)
            if file_metadata_addresses[block_idx] != abs_idx:
                block_idx -= 1
            block = file_metadata_blocks[block_idx]

        data = file_info.get_segment_data(block.segment_id)
        data_idx_start = (abs_idx + block.idx) - block.abs_idx
        try:
            if block.abs_idx & 1:
                raise Exception("misaligned disassembly attempt")
            match, data_idx_end = archm68k.disassemble_one_line(data, data_idx_start, abs_idx)
        except Exception:
            # The block should already be data.  Just exit and it should be handled correctly.
            print "Pass 2 exception", block.segment_id, "here", hex(abs_idx), "last", src_abs_idx and hex(src_abs_idx) or src_abs_idx
            traceback.print_exc()
            break

        if match is not None:
            excess_length = block.length
            leading_block = block

            if abs_idx - block.abs_idx > 0:
                # Truncate the current block.
                leading_block.length = abs_idx - leading_block.abs_idx
                line_count += calculate_line_count(leading_block)
                excess_length -= leading_block.length

                # Insert a new block at the current offset.
                block = SegmentBlock()
                block.flags = leading_block.flags
                block.segment_id = leading_block.segment_id
                block.idx = leading_block.idx + leading_block.length
                block.abs_idx = leading_block.abs_idx + leading_block.length
                insert_metadata_block(block_idx+1, block)

            # Insert the new code block.
            set_data_type(block, DATA_TYPE_CODE)
            block.code_match = match
            block.length = data_idx_end - data_idx_start
            line_count += calculate_line_count(block)
            disassembly_checklist[block.abs_idx] = None
            excess_length -= block.length

            # Extract any addresses which are referred to, for later use.
            if get_data_type(block.flags) == DATA_TYPE_CODE:
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

                if address is not None:
                    if address not in disassembly_checklist:
                        disassembly_offsets.insert(0, (address, abs_idx))
                    insert_branch_address(address, abs_idx)

                # Locate any general addressing modes which infer labels.
                for opcode in match.opcodes:
                    if opcode.key == "PCid16":
                        address = match.pc + archm68k._signed_value("W", opcode.vars["D16"])
                        insert_branch_address(address, abs_idx)
                    elif opcode.key == "PCiId8":
                        address = match.pc + archm68k._signed_value("W", opcode.vars["D8"])
                        insert_branch_address(address, abs_idx)
                    elif opcode.key in ("PCiIdb", "PCiPost", "PrePCi"):
                        print hex(abs_idx), opcode.key
                        raise RuntimeError("Not handled 680x0?") # TODO: Support later?

            # Ready any remaining block space for further disassembly.
            if excess_length:
                trailing_block = SegmentBlock()
                trailing_block.segment_id = block.segment_id
                trailing_block.flags = block.flags
                set_data_type(trailing_block, DATA_TYPE_LONGWORD)
                trailing_block.idx = block.idx + block.length
                trailing_block.abs_idx = block.abs_idx + block.length
                trailing_block.length = excess_length
                line_count += calculate_line_count(trailing_block)

                # Place the excess length block after the one just processed in the list of blocks that make up the address space.
                if leading_block != block:
                    insert_metadata_block(block_idx+2, trailing_block)
                else:
                    insert_metadata_block(block_idx+1, trailing_block)

                if instruction_key not in ("RTS", "RTR", "JMP", "BRA"):
                    if trailing_block.abs_idx not in disassembly_checklist:
                        disassembly_offsets.insert(0, (trailing_block.abs_idx, abs_idx))
        else:
            print "unable to disassemble at", hex(abs_idx), ", added by:", hex(src_abs_idx)

    line_count += 2 # blank line, then "end" instruction
    disassembly_listctrl.SetItemCount(line_count)
    

_ID_ = 101010
WXID_FRAME = _ID_+1
WXID_MENU_OPEN = wx.ID_OPEN
WXID_MENU_EXIT = wx.ID_EXIT
WXID_MENU_FONT = wx.ID_SAVE # _ID_+2  # Custom ids do not work

def UIConfirm(parent, title, msg):
    dlg = wx.MessageDialog(parent, msg, title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
    ret = dlg.ShowModal()
    dlg.Destroy()
    return ret == wx.YES

class UIDisassemblyListCtrl(wx.ListCtrl):
    def __init__(self, parent):
        wx.ListCtrl.__init__(self, parent, -1, style=wx.LC_REPORT|wx.LC_VIRTUAL|wx.LC_HRULES|wx.LC_VRULES)

        self.InsertColumn(LI_OFFSET, "Offset")
        self.SetColumnWidth(LI_OFFSET, 80)
        self.InsertColumn(LI_BYTES, "Bytes")
        self.SetColumnWidth(LI_BYTES, 100)    
        self.InsertColumn(LI_LABEL, "Label")
        self.SetColumnWidth(LI_LABEL, 110)
        self.InsertColumn(LI_INSTRUCTION, "Instruction")
        self.SetColumnWidth(LI_INSTRUCTION, 110)
        self.InsertColumn(LI_OPERANDS, "Operands")
        self.SetColumnWidth(LI_OPERANDS, 175)
        if DEBUG_ANNOTATE_DISASSEMBLY:
            self.InsertColumn(LI_ANNOTATIONS, "Annotations")
            self.SetColumnWidth(LI_ANNOTATIONS, 175)

        self.SetItemCount(0)

        self.attrs = []
        self.attrs.append(wx.ListItemAttr())
        attr = wx.ListItemAttr()
        colour1 = attr.GetTextColour()
        colour2 = attr.GetBackgroundColour()
        attr.SetTextColour(colour1)
        attr.SetBackgroundColour(colour1)
        self.attrs.append(attr)

        # font_size, font_name = 9, "Courier New"
        font_size, font_name = 8, "ProFontWindows" # 8 = 0074
        font_size, font_name = 11, "ProggyTinyTTSZ" # 10 = 0090.5, 11 = 0088
        font = wx.Font(font_size, 74, 90, 90, False, font_name)
        self.SetFont(font)

        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_item_activated)
        self.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)

    def on_item_selected(self, event):
        self.currentItem = event.m_itemIndex

    def on_item_activated(self, event):
        self.currentItem = event.m_itemIndex

    def getColumnText(self, index, col):
        item = self.GetItem(index, col)
        return item.GetText()

    def on_item_deselected(self, evt):
        pass

    def OnGetItemAttr(self, item):
        return self.attrs[item % 2]

    # Virtual API
    def OnGetItemText(self, item, col):
        return get_file_line(item, col)


class UIFrame(wx.Frame):
    def __init__(self, parent, ID, title, pos=wx.DefaultPosition, size=wx.DefaultSize, style=wx.DEFAULT_FRAME_STYLE):
        global disassembly_listctrl
        wx.Frame.__init__(self, parent, ID, title, pos, size, style)

        menu1 = wx.Menu()
        menu1.Append(WXID_MENU_OPEN, "&Open\tCtrl-O", "Open a load file")
        menu1.AppendSeparator()
        menu1.Append(WXID_MENU_EXIT, "E&xit", "Terminate the application")

        menu2 = wx.Menu()
        menu2.Append(WXID_MENU_FONT, "Choose font", "Choose a font")

        menuBar = wx.MenuBar()
        menuBar.Append(menu1, "&File")
        menuBar.Append(menu2, "&Settings")
        self.SetMenuBar(menuBar)

        disassembly_listctrl = UIDisassemblyListCtrl(self)
        self.current_font = self.GetFont()

        self.Bind(wx.EVT_MENU,   self.on_file_open_menu, id=WXID_MENU_OPEN)
        self.Bind(wx.EVT_MENU,   self.on_file_exit_menu, id=WXID_MENU_EXIT)
        self.Bind(wx.EVT_MENU,   self.on_settings_font_menu, id=WXID_MENU_FONT)

    def on_file_open_menu(self, event):
        dlg = wx.FileDialog(self, message="Choose a file", defaultDir=os.getcwd(),  defaultFile="", wildcard="All files (*.*)|*.*", style=wx.OPEN | wx.CHANGE_DIR)
        ret = dlg.ShowModal()
        if ret == wx.ID_OK:
            file_path = dlg.GetPath()
            self.set_file_path(file_path)

    def set_file_path(self, file_path):
        global file_info
        #x, y = os.path.split(file_path)
        # self.SetName("File: "+ y)

        file_info = archlib.load_file(file_path)
        if file_info is None:
            print "run.py is exiting"
            sys.exit(1)

        UI_display_file()
        #sys.exit(1)

    def on_file_exit_menu(self, event):
        if UIConfirm(self, "Viewing project", "Abandon current work?"):
            self.Close()
            print "closed"

    def on_settings_font_menu(self, event):
        data = wx.FontData()
        data.EnableEffects(True)
        data.SetInitialFont(self.current_font)

        dlg = wx.FontDialog(self, data)
        
        if dlg.ShowModal() == wx.ID_OK:
            data = dlg.GetFontData()
            font = data.GetChosenFont()
            print font.GetPointSize()
            print font.GetFamily()
            print font.GetStyle()
            print font.GetWeight()
            print font.GetFaceName()
            disassembly_listctrl.SetFont(font)
            print font.GetNativeFontInfoDesc()

class UIApp(wx.App):
    filePath = None

    def __init__(self, *args, **kwargs):
        if "file_path" in kwargs:
            self.file_path = kwargs.pop("file_path")
        wx.App.__init__(self, *args, **kwargs)

    def OnInit(self):
        frame = UIFrame(None, WXID_FRAME, "", size=(800, 600))
        frame.Show(True)
        self.SetTopWindow(frame)
        if self.file_path:
            frame.set_file_path(self.file_path)
        return True

def run(file_path):
    global app, disasm_list_widget

    app = UIApp(redirect=False, file_path=file_path)
    app.MainLoop()


if __name__ == "__main__":
    file_path = None
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    run(file_path)
