@echo off
rem Launcher wrapper for test-ddagrab-record.py.
rem Place next to test-ddagrab-record.py (same folder as bin\).
rem Tries the Windows py launcher, then the python command, so it starts
rem even when the .py extension isn't associated with Python.
rem
rem Kept ASCII-only on purpose: cmd.exe misreads non-ASCII (e.g. Japanese)
rem comments/text under some system locales, corrupting the script.
rem
rem Does not cd/pushd to %~dp0 on purpose: if this file lives on a UNC path
rem (e.g. \\wsl.localhost\...), cmd.exe cannot use a UNC path as its current
rem directory and falls back to C:\Windows instead. All python/py arguments
rem below use %~dp0-based absolute paths, so this works regardless of the
rem current directory.

setlocal

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py "%~dp0test-ddagrab-record.py" %*
    goto :end
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%~dp0test-ddagrab-record.py" %*
    goto :end
)

echo Python was not found.
echo Install it from https://www.python.org/downloads/windows/
echo Make sure to check "Add python.exe to PATH" during setup.
pause

:end
endlocal
