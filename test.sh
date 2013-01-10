#!/bin/bash
[ -f /c/python27/python.exe ] && export PYTHON=/c/python27/python.exe || export PYTHON=python
export TESTDATA_PATH="$( cd "$( dirname "$0")" && pwd)"/test-data
$PYTHON python/test.py $@
