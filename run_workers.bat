@echo off
cd /d "%~dp0"

if "%~1"=="" (
    echo Usage: run_workers.bat ^<input.csv/xlsx or folder^> [num_workers] [threads_per_worker] [vdp_sample_size] [mode] [staff_page_limit]
    echo   num_workers defaults to 6
    echo   threads_per_worker defaults to 2 for deep browser detection
    echo   vdp_sample_size defaults to 3
    echo   mode: deep ^(default^), standard, staff, or staff-refresh
    echo   staff_page_limit defaults to 8 and applies in staff modes
    echo.
    echo Examples:
    echo   run_workers.bat dealers.csv 6 2 3 deep
    echo   run_workers.bat dealers.csv 6 2 0 staff 8
    echo   run_workers.bat enriched_v8 6 2 0 staff-refresh 8
    exit /b 1
)

set "INPUT=%~1"
set "WORKERS=6"
if not "%~2"=="" set "WORKERS=%~2"
set "THREADS=2"
if not "%~3"=="" set "THREADS=%~3"
set "VDP_SAMPLE=3"
if not "%~4"=="" set "VDP_SAMPLE=%~4"
set "MODE=deep"
if not "%~5"=="" set "MODE=%~5"
set "STAFF_PAGE_LIMIT=8"
if not "%~6"=="" set "STAFF_PAGE_LIMIT=%~6"

set "MODE_ARGS="
set "MODE_LABEL="
if /I "%MODE%"=="deep" (
    set "MODE_ARGS=--deep-detection --vdp-sample-size %VDP_SAMPLE%"
    set "MODE_LABEL=deep-detection"
)
if /I "%MODE%"=="standard" (
    set "MODE_LABEL=standard enrichment"
)
if /I "%MODE%"=="staff" (
    set "MODE_ARGS=--staff-emails-only --staff-page-limit %STAFF_PAGE_LIMIT%"
    set "MODE_LABEL=staff-email-only"
)
if /I "%MODE%"=="staff-refresh" (
    set "MODE_ARGS=--staff-emails-only --staff-refresh-generic --staff-page-limit %STAFF_PAGE_LIMIT%"
    set "MODE_LABEL=staff-email refresh"
)
if not defined MODE_LABEL (
    echo Invalid mode "%MODE%". Choose deep, standard, staff, or staff-refresh.
    exit /b 1
)

set /a LAST=%WORKERS%-1
for /L %%w in (0,1,%LAST%) do (
    start "enrich -w %%w" cmd /k python enrich_dealers.py "%INPUT%" -w %%w -W %WORKERS% -t %THREADS% --fetch-mode auto %MODE_ARGS%
)

echo Started %WORKERS% %MODE_LABEL% workers for "%INPUT%" ^(threads/worker: %THREADS%^)
if /I "%MODE%"=="deep" echo VDP sample: %VDP_SAMPLE%
if /I "%MODE%"=="staff" echo Staff-page limit: %STAFF_PAGE_LIMIT%
if /I "%MODE%"=="staff-refresh" echo Staff-page limit: %STAFF_PAGE_LIMIT%
