"""
Launcher do Bot DAS-SIMEI
Abre o servidor web e o navegador automaticamente.
"""
import os
import sys
import subprocess
import threading
import time
import webbrowser
from pathlib import Path

# Garante que o diretório de trabalho seja o da aplicação
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

os.chdir(BASE_DIR)

def abrir_navegador():
    time.sleep(2.5)
    webbrowser.open("http://localhost:5000")

threading.Thread(target=abrir_navegador, daemon=True).start()

# Adiciona o diretório ao path para importar app.py
sys.path.insert(0, str(BASE_DIR))

from app import app
app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
