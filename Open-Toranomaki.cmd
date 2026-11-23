@echo off
setlocal
pushd "%~dp0" || exit /b 1

where uv.exe >nul 2>&1
if not errorlevel 1 (
    uv run toranomaki configure %*
) else if exist ".venv\Scripts\toranomaki.exe" (
    ".venv\Scripts\toranomaki.exe" configure %*
) else (
    echo uv or the Toranomaki virtual environment was not found.
    echo See README.md for setup instructions.
    pause
    popd
    exit /b 1
)

set "toranomaki_exit=%errorlevel%"
if not "%toranomaki_exit%"=="0" pause
popd
exit /b %toranomaki_exit%
