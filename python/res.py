import logging

logger = logging.getLogger("res")

# Resources

## Strings

class BaseResource(object):
    def __getitem__(self, idx):
        return getattr(self, idx, idx)

class EnglishStrings(BaseResource):
    TEXT_GENERIC_LOADING = "Loading"
    TEXT_GENERIC_PROCESSING = "Processing"
    TEXT_LOAD_ANALYSING_FILE = "Analysing file"
    TEXT_LOAD_CONVERTING_PROJECT_FILE = "Converting project to latest version"
    TEXT_LOAD_DISASSEMBLY_PASS = "Disassembly pass"
    TEXT_LOAD_POSTPROCESSING = "Postprocessing"
    TEXT_LOAD_READING_PROJECT_DATA = "Reading project data"

    TITLE_DATA_TYPE_CHANGE = "Data type change"
    TITLE_LOADING_FILE = "Loading file"
    TITLE_LOADING_PROJECT = "Loading project"

strings = EnglishStrings()

import loaderlib

PLATFORM_KEY = 1
FILE_FORMAT_KEY = 2
PROCESSOR_KEY = 3
ENDIAN_KEY = 4

def get_string_by_id(lookup_key, lookup_value):
    lookup_result = None
    if lookup_key == PLATFORM_KEY:
        lookup_result = loaderlib.constants.platform_names.get(lookup_value, None)
    elif lookup_key == FILE_FORMAT_KEY:
        lookup_result = loaderlib.constants.file_format_names.get(lookup_value, None)
    elif lookup_key == PROCESSOR_KEY:
        lookup_result = loaderlib.constants.processor_names.get(lookup_value, None)
    elif lookup_key == ENDIAN_KEY:
        lookup_result = loaderlib.constants.endian_names.get(lookup_value, None)
    if lookup_result is None:
        logger.error("get_string_by_id: no match for %d/%d", lookup_key, lookup_value)
        lookup_result = "-ERROR-"
    return lookup_result
