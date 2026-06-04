@echo off
echo Instalando dependencias...
pip install -r requirements.txt
echo Instalando browsers...
playwright install firefox
playwright install chromium
echo.
echo Instalacao concluida!
echo Para iniciar o sistema, clique duas vezes em: rodar_web.bat
pause
