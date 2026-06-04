@echo off
echo ============================================
echo   Bot DAS-SIMEI — Interface Web
echo ============================================
echo.
echo Enderecos de acesso:
echo   Este PC:       http://localhost:5000
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set ip=%%a
    setlocal enabledelayedexpansion
    set ip=!ip: =!
    echo   Rede local:    http://!ip!:5000
    endlocal
)
echo.
echo Mantenha esta janela aberta enquanto usar o sistema.
echo ============================================
start http://localhost:5000
python app.py
pause
