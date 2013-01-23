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

