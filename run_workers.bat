@echo off
cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: run_workers.bat ^<input.csv or folder^> [num_workers]
    echo   num_workers defaults to 6
    exit /b 1
)

set "INPUT=%~1"
set "WORKERS=6"
if not "%~2"=="" set "WORKERS=%~2"

set /a LAST=%WORKERS%-1
for /L %%w in (0,1,%LAST%) do (
    start "enrich -w %%w" cmd /k python enrich_dealers.py "%INPUT%" -w %%w -W %WORKERS%
)

echo Started %WORKERS% workers for "%INPUT%"
