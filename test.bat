@echo off

IF "%1"=="g" goto handle_generate_tests
IF "%1"=="d" goto handle_disassemblylib_tests

REM Test the general code base.
set TESTDATA_PATH=%~dp0test-data
c:\python27\python.exe python\test.py %*

goto :EOF

:handle_disassemblylib_tests

c:\python27\python.exe python\test_disassemblylib.py
goto :EOF

:handle_generate_tests

REM Generate tests for architecture/cpu instructions.
c:\python27\python.exe python\test_testlib.py
goto :EOF
