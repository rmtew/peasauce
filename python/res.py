# Resources

## Strings

class Strings(object):
    def __getitem__(self, idx):
        return getattr(self, idx, idx)

    TEXT_ANALYSING_FILE = "Analysing file"
    TEXT_DATA_TYPE_CHANGE = "Data type change"
    TEXT_CONVERTING_PROJECT_FILE = "Converting project to latest version"
    TEXT_DISASSEMBLY_PASS = "Disassembly pass"
    TEXT_LOADING_FILE = "Loading file"
    TEXT_LOADING_PROJECT = "Loading project"
    TEXT_LOADING = "Loading"
    TEXT_POSTPROCESSING = "Postprocessing"
    TEXT_PROCESSING = "Processing"
    TEXT_READING_PROJECT_DATA = "Reading project data"

strings = Strings()