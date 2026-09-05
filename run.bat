@echo off
setlocal enabledelayedexpansion
title Greenwich Moodle Crawler
cd /d "%~dp0"

echo ========================================================================
echo               GREENWICH MOODLE CRAWLER ^& DOWNLOADER
echo ========================================================================
echo.

rem 1. Kiem tra Python
set "PY_CMD="
where python >nul 2>&1
if %errorlevel% equ 0 set "PY_CMD=python"
if "%PY_CMD%"=="" (
    where py >nul 2>&1
    if %errorlevel% equ 0 set "PY_CMD=py"
)

if "%PY_CMD%"=="" (
    echo [X] LOI: Khong tim thay Python tren he thong!
    echo Vui long cai dat Python 3.10+ tai: https://www.python.org/
    echo LUU Y: Nho tich chon "Add python.exe to PATH" trong qua trinh cai dat.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('%PY_CMD% --version 2^>^&1') do set "PY_VER=%%v"
echo [*] Python: %PY_VER%

rem 2. Khoi tao file .env neu chua co
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [OK] Da tu dong khoi tao file .env tu .env.example
    )
)

rem 3. Kich hoat virtual environment neu co
if exist "venv\Scripts\activate.bat" (
    echo [*] Phat hien moi truong ao venv, dang kich hoat...
    call "venv\Scripts\activate.bat"
    set "PY_CMD=python"
)

rem 4. Kiem tra dependencies
if "%~1"=="--install" goto do_install
if "%~1"=="--update" goto do_install

%PY_CMD% -c "import requests, bottle, lxml, dotenv, tqdm, cryptography" >nul 2>&1
if errorlevel 1 goto do_install

echo [OK] Tat ca thu vien dependencies da san sang!
goto check_args

:do_install
echo.
echo [*] Dang cai dat/kiem tra cac thu vien tu requirements.txt...
echo [*] Vui long cho trong giay lat...
echo.
%PY_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [X] LOI: Cai dat thu vien that bai!
    echo Vui long kiem tra ket noi Internet hoac quyen ghi.
    echo.
    pause
    exit /b 1
)
echo.
echo [OK] Cai dat dependencies thanh cong!

if "%~1"=="--install" goto done_cmd
if "%~1"=="--update" goto done_cmd

:check_args
rem 5. Neu nguoi dung truyen tham so dong lenh (vd: run.bat --all, run.bat --list,...)
if not "%~1"=="" (
    echo.
    echo [*] Thuc thi: %PY_CMD% main.py %*
    echo.
    %PY_CMD% main.py %*
    goto end
)

rem 6. Menu khoi chay (Web GUI hoac CLI)
echo.
echo ========================================================================
echo   CHON CHE DO KHOI CHAY:
echo   [1] Web GUI (Khuyen dung - Tu dong mo Trinh duyet)
echo   [2] Dong Lenh CLI (Interactive Menu trong Console)
echo ========================================================================
echo Tu dong khoi chay [1] Web GUI sau 3 giay neu khong chon...
echo.

choice /c 12 /t 3 /d 1 /n /m "Nhap lua chon cua ban [1 hoac 2]: "
set "USER_CHOICE=!errorlevel!"

if "!USER_CHOICE!"=="2" goto run_cli
goto run_gui

:run_gui
echo.
echo ========================================================================
echo   DANG KHOI DONG WEB GUI (http://127.0.0.1:5000)...
echo   Trinh duyet se tu dong mo trong giay lat.
echo   Nhan to hop phim Ctrl+C de dong ung dung khi hoan tat.
echo ========================================================================
echo.
%PY_CMD% app.py
goto end

:run_cli
echo.
echo ========================================================================
echo   DANG KHOI DONG DONG LENH (CLI MENU)...
echo ========================================================================
echo.
%PY_CMD% main.py
goto end

:done_cmd
echo.
echo [*] Tac vu hoan tat.
exit /b 0

:end
if errorlevel 1 (
    echo.
    echo [!] Chuong trinh ket thuc voi ma loi: %errorlevel%
    pause
)
