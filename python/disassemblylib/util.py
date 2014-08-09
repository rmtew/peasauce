import struct

#

# IDEA: Sizes should be specified for architectures in bits.  The size label should be an affectation.

# See the end of the file for the __all__ definition.

def memoize(function):
    memo = {}
    def wrapper(*args):
        if args in memo:
            return memo[args]
        rv = function(*args)
        memo[args] = rv
        return rv
    return wrapper

## Instruction table columns.
II_MASK = 0
II_NAME = 1
II_FLAGS = 2
II_TEXT = 3
II_ANDMASK = 4
II_CMPMASK = 5
II_EXTRAWORDS = 6
II_OPERANDMASKS = 7
II_LENGTH = 8

## Instruction table II_FLAGS general bits.
# Flags to indicate special attributes about the given instruction, these overlap the architecture specific flag set.
IFX_ENDSEQ    = 1<<30       # Indicates the end of a sequence of instructions.  
IFX_ENDSEQ_BD = 1<<31       # Indicates the end of a sequence of instructions.  Next instruction is still executed on the way (the branch delay slot).


## Operand type table columns.
# Syntax:
EAMI_LABEL = 0
# Formatting:           Where the arguments are injected to make the operand source code.
EAMI_FORMAT = 1
EAMI_MATCH_FIELDS = 2
EAMI_DATA_FIELDS = 3
# Description:          Text description.
EAMI_DESCRIPTION = 4


def make_operand_mask(mask_string):
    """
    Convert a binary mask string with variable characters and bits to an '&', and '==' mask. 
    This is used to be able to match an instruction word to the instruction table entry.
    """
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

class Specification(object):
    key = None
    mask_char_vars = None
    filter_keys = None
    ea_args = None


@memoize
def _make_specification(format):
    """
    Parse a token into a key, substitutions to be made into the key and filters on which operand variants are legal.
    """
    @memoize
    def get_substitution_vars(s):
        """
        Take a string of variable substitutions and convert it into the equivalent dictionary form.
        e.g. "a=b&c=d&e=f" -> { "a": "b", "c": "d", "e": "f" }
        """
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


def process_instruction_list(_A, _list):
    """
    An 'instruction list' is the hand editable representation of an architecture.
    This converts it into a tokenised form which can be used to disassemble an opcode stream.
    """
    
    # Pass 1: Each instruction entry with a ".z" size wildcard are expanded to specific entries.
    #         e.g. INSTR.z OP, OP -> INSTR.w OP, OP / INSTR.l OP, OP / ...
    _list_old = _list[:]
    _list = []
    while len(_list_old):
        entry = _list_old.pop()
        if " " in entry[II_NAME]:
            # <INSTR>(\.z)? <OPERAND>, ..
            entry_name, operands_string = entry[II_NAME].split(" ", 1)
            operands_string = " "+ operands_string.strip()
        else:
            # <INSTR>(\.z)?
            entry_name = entry[II_NAME]
            operands_string = ""

        # Size-based processing.
        specification = _make_specification(entry_name)
        if "z" in specification.mask_char_vars:
            mask_char_vars = specification.mask_char_vars.copy()
            del mask_char_vars["z"]

            # Append a new substitution mapping without the 'z' entry.
            new_name = specification.key
            var_list = mask_char_vars.items()
            if len(var_list):
                new_name += ":(" + "&".join(k+"="+v for (k, v) in var_list) +")"

            for size_entry in _A.create_duplicated_instruction_entries(entry, new_name, operands_string):
                _list.append(size_entry)
        else:
            _list.append(entry)

    # Pass 2: Sort all entries by known bits to reduce hitting matches with unknown bits first.
    #         Also inject calculated columns.
    d = {}
    for entry in _list:
        operand_mask = entry[II_MASK]

        # Ensure pre-calculated columns have space present and precalculate some useful information.
        entry.extend([ None ] * (II_LENGTH - len(entry)))

        # Matching and comparison masks.
        entry[II_ANDMASK], entry[II_CMPMASK] = make_operand_mask(operand_mask)
        entry[II_OPERANDMASKS] = [ None ] * _A.constant_operand_count_max

        # Take into account if the instruction needs extra words from the stream for it's definition.
        max_extra_words = 0
        line_bits = entry[II_NAME].split(" ", 1)
        if len(line_bits) > 1:
            operands_bits = line_bits[1].split(",")
            for operand_string in operands_bits:
                spec = _make_specification(operand_string)
                for var_name, value_name in spec.mask_char_vars.iteritems():
                    if value_name[0] == "I": # I<word_idx>.<size_char>
                        size_idx = value_name.find(".")
                        if size_idx > 0:
                            word_idx = int(value_name[1:size_idx])
                            extra_words = word_idx
                            size_char = value_name[size_idx+1]
                            extra_words += _A.get_extra_words_for_size_char(size_char)
                            if extra_words > max_extra_words:
                                max_extra_words = extra_words
        entry[II_EXTRAWORDS] = max_extra_words

        # Operand type mask generation.
        name_bits = entry[II_NAME].split(" ", 1)
        if len(name_bits) > 1:
            for i, operand_string in enumerate(name_bits[1].split(",")):
                mask = 0
                spec = _make_specification(operand_string)
                if spec.filter_keys is not None:
                    for ea_key in spec.filter_keys:
                        mask |= 1 << _A.dict_operand_label_to_index[ea_key]
                entry[II_OPERANDMASKS][i] = mask

        # Sort the masks.  These are ordered in terms of how many known bits there are, leaving variable masks lower in priority.
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
    
    # Pass 3: Validate instruction list.
    for entry in _list:
        name_bits = entry[II_NAME].split(" ", 1)
        if len(name_bits) > 1:
            for i, operand_string in enumerate(name_bits[1].split(",")):
                spec = _make_specification(operand_string)
                #print operand_string, spec.mask_char_vars
                #raise RuntimeError("ddd")
    
# TODO: Verification.
# - Check that all variable bits in the mask are used by the name column.
# - Check that operand types used in the name column exist.
# - Check that name column operand type variable names all exist in the operand type spec.    
 
    return _list


## Architecture interface.

def _unimplemented_function(*args, **kwargs): raise NotImplementedError("arch-function-undefined")


class ArchInterface(object):
    """ This object allows an interface to define functionality implementations, and default constants. """

    """ Constant: Prefix for immediate values. """
    constant_immediate_prefix = ""
    """ Constant: Prefix for register names. """
    constant_register_prefix = ""
    """ Constant: Prefix for binary values. """
    constant_binary_prefix = "arch-constant-undefined"
    """ Constant: Suffix for binary values. """
    constant_binary_suffix = "arch-constant-undefined"
    """ Constant: Prefix for decimal values. """
    constant_decimal_prefix = "arch-constant-undefined"
    """ Constant: Suffix for decimal values. """
    constant_decimal_suffix = "arch-constant-undefined"
    """ Constant: Prefix for hexadecimal values. """
    constant_hexadecimal_prefix = "arch-constant-undefined"
    """ Constant: Suffix for hexadecimal values. """
    constant_hexadecimal_suffix = "arch-constant-undefined"
    """ Constant: Character which indicates trailing text is comment. """
    constant_comment_prefix = "arch-constant-undefined"

    """ Constant: Core architecture bit mask. """
    constant_core_architecture_mask = 0
    """ Constant: Maximum number of operands per instruction. """
    constant_operand_count_max = 0
    """ Constant: The architecture supported endian types.  little endian '<' big endian '>'."""
    constant_endian_types = None
    """ Constant: How many bits an architectural word is comprised of. """
    constant_word_size = None
    """ Constant: How far from the start of the current instruction PC is offset while it is executing. """
    constant_pc_offset = 0

    """ Variable: The implicit (or user selected) endian type. """
    variable_endian_type = None

    # API: External use.
    """ Function: Identify if the given instruction alters the program counter. """
    function_is_final_instruction = _unimplemented_function
    """ Function: . """
    function_get_match_addresses = _unimplemented_function
    """ Function: . """
    function_get_instruction_string = _unimplemented_function
    """ Function: . """
    function_get_operand_string = _unimplemented_function
    """ Function: . """
    function_disassemble_one_line = _unimplemented_function
    """ Function: . """
    function_disassemble_as_data = _unimplemented_function
    """ Function: . """
    function_get_default_symbol_name = _unimplemented_function

    # API: Internal use.        
    def set_instruction_table(self, table_data):
        self.table_instructions = process_instruction_list(self, table_data)

    def set_operand_type_table(self, table_data):
        self.table_operand_types = table_data
    
        idToLabel = {}
        labelToId = {}
        labelToMask = {}
        for i, t in enumerate(table_data):
            idToLabel[i] = t[EAMI_LABEL]
            labelToId[t[EAMI_LABEL]] = i
            
        self.dict_operand_label_to_index = labelToId
        self.dict_operand_index_to_label = idToLabel

    def create_duplicated_instruction_entries(self, entry, new_name, operands_string):
        """ This expands instructions with parameterised sizes into the individual sized variants. """
        raise NotImplementedError("arch-function-undefined")

    def get_extra_words_for_size_char(self, size_char):
        raise NotImplementedError("arch-function-undefined")
        
    # ...
    
    def _get_word(self, data, data_idx):
        return self._get_value(data, data_idx, self.constant_word_size, False)

    def _get_value(self, data, data_idx, bits, signed):
        k = (bits, signed)
        d = {
            (64, False):   "Q",
            (64, True):    "q",
            (32, False):   "I",
            (32, True):    "i",
            (16, False):   "H",
            (16, True):    "h",
            (8,  False):   "B",
            (8,  True):    "b",
        }
        sfmt = self.variable_endian_type + d[k]
        size = struct.calcsize(sfmt)
        if data_idx + size <= len(data):
            return struct.unpack(sfmt, data[data_idx:data_idx+size])[0], data_idx+size
        return None, data_idx

    def _match_instructions(self, data, data_idx, data_abs_idx):
        """ Read one word from the stream, and return matching instructions by order of decreasing confidence. """
        @memoize
        def get_instruction_format_parts(instr_format):
            """ Split "INSTR OP1, OP2, ..." into [ "INSTR", "OP1, "OP2", ... ]. """
            opcode_sidx = instr_format.find(" ")
            if opcode_sidx == -1:
                return [ instr_format ]
            ret = [ instr_format[:opcode_sidx] ]
            opcode_string = instr_format[opcode_sidx+1:]
            opcode_bits = opcode_string.replace(" ", "").split(",")
            ret.extend(opcode_bits)
            return ret

        word1, data_idx = self._get_word(data, data_idx)
        if word1 is None: # Disassembly failure
            logger.error("Data out of bounds: data_offset=%d data_length=%d", data_idx, len(data))
            return [], data_idx

        matches = []
        for i, t in enumerate(self.table_instructions):
            mask_string = t[II_MASK]
            and_mask, cmp_mask = t[II_ANDMASK], t[II_CMPMASK]
            if (word1 & and_mask) == cmp_mask:
                instruction_parts = get_instruction_format_parts(t[II_NAME])

                M = Match()
                M.pc = data_abs_idx + self.constant_pc_offset
                M.data_words = [ word1 ]

                M.table_text = t[II_TEXT]
                M.table_mask = mask_string
                M.table_extra_words = t[II_EXTRAWORDS]
                M.table_ea_masks = t[II_OPERANDMASKS]
                M.table_iflags = t[II_FLAGS]

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


def binary2number(s):
    """ Convert a string of 1 and 0 to the equivalent integer value. """
    v = 0
    while len(s):
        v <<= 1
        if s[0] == "1":
            v |= 1
        s = s[1:]
    return v
""" Shorter alias for binary2number. """
_b2n = binary2number

def number2binary(v, dynamic_padding=False, padded_length=None):
    """ Convert an integer value to the equivalent string of 1 and 0 characters. """
    s = ""
    while v:
        s = [ "0", "1" ][v & 1] + s
        v >>= 1
    if dynamic_padding:
        w = 4
        while w < len(s):
            w <<= 1
    else:
        w = len(s) if padded_length is None else padded_length
    return "0"*(w-len(s)) + s
""" Shorter alias for number2binary. """
_n2b = number2binary

def signed_hex_string(_arch, v):
    """ For a given integer value, return the architecture specific hexadecimal representation. """
    sign_char = ""
    if v < 0:
        sign_char = "-"
        v = -v
    return sign_char + _arch.constant_hexadecimal_prefix + ("%x" % v) + _arch.constant_hexadecimal_suffix

# ----------------------------------------------------------------------------

@memoize
def _extract_mask_bits(mask_string, s):
    """
    A mask string is composed of instruction bits and data.  The bits for a given
    piece of data, are indicated by the same variable character repeated.
    
    e.g. mask_string = "010101010fffffvvvvvggggg01010"
    
    This function takes the mask string, and a character 's', and returns the
    bit mask and shift amount to produce the value for that character variable.
    
    e.g. s = "f"
         instruction_word = 0xF0F0
         -> instruction_word = %1111 1111 0000 0000 1111 1111 0000 0000
         -> mask             = %0000 0000 0000 1111 1000 0000 0000 0000
         -> shift            = 15
         f = (instruction_word & mask) >> shift
         f = %0000 0000 0000 0000 1000 0000 0000 0000 >> 15
         f = 1
    """
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
    """ Extract the value of the mask char in the data word. """
    mask, shift = _extract_mask_bits(mask_string, mask_char)
    return (data_word & mask) >> shift
    
def _get_var_values(chars, data_word1, mask_string):
    var_values = {}
    if chars:
        for mask_char in chars:
            if mask_char in mask_string:
                var_values[mask_char] = _extract_masked_value(data_word1, mask_string, mask_char)
    return var_values
    
# ----------------------------------------------------------------------------
    
def generate_all():
    """
    Return the names of the objects in this file which are imported by the wildcard.
    This is done in this function, so as not to introduce entries into the global dictionary.
    """
    l = [ "ArchInterface", "_b2n", "_n2b", "_make_specification", "_extract_masked_value", "_get_var_values", "make_operand_mask", "memoize", "process_instruction_list", "signed_hex_string" ]
    for k in globals().keys():
        if k.startswith("II_") or k.startswith("EAMI") or k.startswith("IFX_"):
            l.append(k)
    return l

# The wildcard import specification.
__all__ = generate_all()
