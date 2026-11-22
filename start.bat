@echo off
rem Uruchomienie bez uv: venv + pip + python -m src. Bez argumentow = "run" (input\ -> output\).
rem Wymaga Python 3.13+ (py launcher lub python w PATH) i pliku .env z kluczem API.
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    py -3.13 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo Brak Pythona 3.13+. Zainstaluj z https://www.python.org/downloads/
        exit /b 1
    )
)
echo [start] Instaluje zaleznosci (pierwsze uruchomienie moze potrwac kilka minut)...
.venv\Scripts\python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1
echo [start] Zaleznosci gotowe, uruchamiam przetwarzanie...
if "%~1"=="" (
    .venv\Scripts\python -m src run
) else (
    .venv\Scripts\python -m src %*
)
