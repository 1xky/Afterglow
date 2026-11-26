@echo off
setlocal
pushd "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" -B "afterglow.py" %*
) else (
    py -3 -B "afterglow.py" %*
)
set "afterglow_exit=%errorlevel%"
if not "%afterglow_exit%"=="0" pause
popd
exit /b %afterglow_exit%
