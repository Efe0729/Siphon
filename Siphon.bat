@echo off
chcp 65001 >nul
rem Siphon'u kaynak koddan baslatir. Her guncellemede derlemeye gerek yok:
rem dosyalari degistirip bu dosyaya cift tiklamak yeterli.
rem Tek dosyalik bir exe icin Derle.bat'i calistirin.
setlocal
set "HERE=%~dp0"
if not exist "%HERE%.build\Scripts\pythonw.exe" goto kur
goto baslat

:kur
echo.
echo  Ilk calistirma: gerekli paketler kuruluyor, birkac dakika surer.
echo.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
  echo  [HATA] Python bulunamadi.
  echo  https://www.python.org/downloads/ adresinden Python kurun
  echo  ^(kurarken "Add python.exe to PATH" kutusunu isaretleyin^).
  echo.
  pause & exit /b 1
)
%PY% -m venv "%HERE%.build" || (echo  [HATA] ortam kurulamadi & pause & exit /b 1)
"%HERE%.build\Scripts\python.exe" -m pip install --upgrade pip >nul
"%HERE%.build\Scripts\python.exe" -m pip install -r "%HERE%requirements.txt" || (echo  [HATA] paketler kurulamadi & pause & exit /b 1)
echo  Hazir.

:baslat
set "PYTHONPATH=%HERE%src;%PYTHONPATH%"
start "" "%HERE%.build\Scripts\pythonw.exe" "%HERE%src\siphon\entrypoints\browse.py" %*
endlocal
