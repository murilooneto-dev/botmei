@echo off
:: Gera o pacote ZIP para distribuicao
cd /d "%~dp0.."

echo Gerando pacote de instalacao...

set "PACOTE=Bot-DAS-SIMEI-Tesserato"
if exist "%PACOTE%" rmdir /S /Q "%PACOTE%"
mkdir "%PACOTE%"

:: Arquivos obrigatorios
copy INSTALAR.bat          "%PACOTE%\"
copy app.py                "%PACOTE%\"
copy bot.py                "%PACOTE%\"
copy launcher.py           "%PACOTE%\"
copy requirements.txt      "%PACOTE%\"
copy .env                  "%PACOTE%\"
xcopy /E /I /Y templates   "%PACOTE%\templates"

:: Assinatura (se existir)
if exist assinatura.png copy assinatura.png "%PACOTE%\"

:: Compacta em ZIP via PowerShell
powershell -Command "Compress-Archive -Path '%PACOTE%\*' -DestinationPath '%PACOTE%.zip' -Force"
rmdir /S /Q "%PACOTE%"

echo.
echo Pacote criado: %PACOTE%.zip
echo Envie esse arquivo ZIP para qualquer maquina e extraia.
echo Em seguida, clique duas vezes em INSTALAR.bat
echo.
pause
