@echo off
setlocal enabledelayedexpansion
title Instalador - Bot DAS-SIMEI / Tesserato Contabilidade
color 0B

echo.
echo  =====================================================
echo    Bot DAS-SIMEI - Tesserato Contabilidade
echo    Instalador automatico
echo  =====================================================
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\Tesserato\BotDAS"
set "SCRIPT_DIR=%~dp0"

:: ── ETAPA 1: Verificar/Instalar Python ───────────────────────────────────
echo  [1/6] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo  Python nao encontrado. Instalando automaticamente...
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    python --version >nul 2>&1
    if errorlevel 1 (
        echo  Baixando Python 3.12 direto do python.org...
        powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '%TEMP%\python_setup.exe'"
        "%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
        del "%TEMP%\python_setup.exe" 2>nul
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    )
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v

:: ── ETAPA 2: Criar pasta e copiar arquivos ────────────────────────────────
echo.
echo  [2/6] Copiando arquivos...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
xcopy /E /I /Y "%SCRIPT_DIR%templates"  "%INSTALL_DIR%\templates" >nul
copy /Y "%SCRIPT_DIR%app.py"            "%INSTALL_DIR%\" >nul
copy /Y "%SCRIPT_DIR%bot.py"            "%INSTALL_DIR%\" >nul
copy /Y "%SCRIPT_DIR%launcher.py"       "%INSTALL_DIR%\" >nul
copy /Y "%SCRIPT_DIR%requirements.txt"  "%INSTALL_DIR%\" >nul
if exist "%SCRIPT_DIR%.env"          copy /Y "%SCRIPT_DIR%.env"          "%INSTALL_DIR%\" >nul
if exist "%SCRIPT_DIR%assinatura.png" copy /Y "%SCRIPT_DIR%assinatura.png" "%INSTALL_DIR%\" >nul
if not exist "%INSTALL_DIR%\.env" (
    echo EMAIL_REMETENTE=>  "%INSTALL_DIR%\.env"
    echo EMAIL_SENHA_APP=>> "%INSTALL_DIR%\.env"
    echo EMAIL_DESTINATARIO=>> "%INSTALL_DIR%\.env"
)
if not exist "%INSTALL_DIR%\DAS" mkdir "%INSTALL_DIR%\DAS"
echo  [OK] Arquivos em: %INSTALL_DIR%

:: ── ETAPA 3: Ambiente virtual ─────────────────────────────────────────────
echo.
echo  [3/6] Criando ambiente virtual Python...
if not exist "%INSTALL_DIR%\venv" python -m venv "%INSTALL_DIR%\venv" >nul 2>&1
echo  [OK] Ambiente virtual pronto.

:: ── ETAPA 4: Dependencias ─────────────────────────────────────────────────
echo.
echo  [4/6] Instalando dependencias (aguarde)...
"%INSTALL_DIR%\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%INSTALL_DIR%\venv\Scripts\pip.exe" install flask playwright python-dotenv playwright-stealth openpyxl --quiet
if errorlevel 1 (
    echo  ERRO ao instalar dependencias. Verifique a conexao com a internet.
    pause & exit /b 1
)
echo  [OK] Dependencias instaladas.

:: ── ETAPA 5: Browser Firefox ─────────────────────────────────────────────
echo.
echo  [5/6] Instalando Firefox para automacao (pode demorar)...
"%INSTALL_DIR%\venv\Scripts\python.exe" -m playwright install firefox
echo  [OK] Firefox instalado.

:: ── ETAPA 6: Atalhos ─────────────────────────────────────────────────────
echo.
echo  [6/6] Criando atalhos...

:: Launcher BAT
(
echo @echo off
echo title Bot DAS-SIMEI - Tesserato Contabilidade
echo cd /d "%INSTALL_DIR%"
echo start "" "http://localhost:5000"
echo "%INSTALL_DIR%\venv\Scripts\python.exe" "%INSTALL_DIR%\launcher.py"
echo pause
) > "%INSTALL_DIR%\Iniciar.bat"

:: Atalho Area de Trabalho
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%USERPROFILE%\Desktop\Bot DAS-SIMEI.lnk'); ^
   $s.TargetPath = '%INSTALL_DIR%\Iniciar.bat'; ^
   $s.WorkingDirectory = '%INSTALL_DIR%'; ^
   $s.WindowStyle = 1; ^
   $s.Description = 'Bot DAS-SIMEI Tesserato Contabilidade'; ^
   $s.Save()" >nul 2>&1

:: Atalho Menu Iniciar
set "SMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Tesserato"
if not exist "%SMENU%" mkdir "%SMENU%"
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%SMENU%\Bot DAS-SIMEI.lnk'); ^
   $s.TargetPath = '%INSTALL_DIR%\Iniciar.bat'; ^
   $s.WorkingDirectory = '%INSTALL_DIR%'; ^
   $s.WindowStyle = 1; ^
   $s.Save()" >nul 2>&1

:: Desinstalador
(
echo @echo off
echo echo Desinstalando Bot DAS-SIMEI...
echo rmdir /S /Q "%INSTALL_DIR%"
echo del /Q "%USERPROFILE%\Desktop\Bot DAS-SIMEI.lnk" 2^>nul
echo rmdir /S /Q "%SMENU%" 2^>nul
echo echo Concluido.
echo pause
) > "%INSTALL_DIR%\Desinstalar.bat"

:: Liberar firewall
netsh advfirewall firewall add rule name="Bot DAS-SIMEI porta 5000" dir=in action=allow protocol=TCP localport=5000 >nul 2>&1

echo  [OK] Atalhos criados.

:: ── FINALIZADO ────────────────────────────────────────────────────────────
echo.
echo  =====================================================
echo    Instalacao concluida com sucesso!
echo  =====================================================
echo.
echo   Atalhos criados:
echo     - Area de Trabalho: "Bot DAS-SIMEI"
echo     - Menu Iniciar ^> Tesserato ^> Bot DAS-SIMEI
echo.
echo   Acesso na rede local:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set ip=%%a
    set ip=!ip: =!
    echo     http://!ip!:5000
)
echo  =====================================================
echo.
set /p ABRIR= Iniciar o sistema agora? (S/N):
if /i "!ABRIR!"=="S" start "" "%INSTALL_DIR%\Iniciar.bat"

endlocal
pause
