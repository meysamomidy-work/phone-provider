@echo off
cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: run_workers.bat ^<input.csv/xlsx or folder^> [num_workers] [threads_per_worker] [vdp_sample_size]
    echo   num_workers defaults to 6
    echo   threads_per_worker defaults to 2 for deep browser detection
    echo   vdp_sample_size defaults to 3
    exit /b 1
)

set "INPUT=%~1"
set "WORKERS=6"
if not "%~2"=="" set "WORKERS=%~2"
set "THREADS=2"
if not "%~3"=="" set "THREADS=%~3"
set "VDP_SAMPLE=3"
if not "%~4"=="" set "VDP_SAMPLE=%~4"

set /a LAST=%WORKERS%-1
for /L %%w in (0,1,%LAST%) do (
    start "enrich -w %%w" cmd /k python enrich_dealers.py "%INPUT%" -w %%w -W %WORKERS% -t %THREADS% --fetch-mode auto --deep-detection --vdp-sample-size %VDP_SAMPLE%
)

echo Started %WORKERS% deep-detection workers for "%INPUT%" ^(threads/worker: %THREADS%, VDP sample: %VDP_SAMPLE%^)
