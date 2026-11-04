@echo off
chcp 65001 >nul
title Siphon - testler
rem Siphon'un testlerini bu bilgisayarda, uygulamanin kendi Python'uyla
rem calistirir. Internet gerektirmez; sahte sunucular kurup calisir.
setlocal
set "HERE=%~dp0"
set "VPY=%HERE%.build\Scripts\python.exe"

if not exist "%VPY%" (
  echo.
  echo  [HATA] Once Siphon.bat'i bir kere calistirin.
  echo  Testler uygulamanin kendi Python ortamini kullaniyor.
  echo.
  pause & exit /b 1
)

echo.
echo  Test araclari kontrol ediliyor...
"%VPY%" -m pytest --version >nul 2>nul
if errorlevel 1 (
  "%VPY%" -m pip install -q pytest pytest-timeout || (
    echo  [HATA] Test araclari kurulamadi. & pause & exit /b 1)
)

echo  Testler calisiyor, bir dakika surebilir...
echo.
set "PYTHONPATH=%HERE%src;%PYTHONPATH%"
"%VPY%" -m pytest "%HERE%tests" -q --timeout=30 -p no:cacheprovider
set "RESULT=%ERRORLEVEL%"

echo.
if "%RESULT%"=="0" (
  echo  ==========================================
  echo    Hepsi gecti.
  echo  ==========================================
) else (
  echo  ==========================================
  echo    Bazi testler gecmedi. Yukaridaki
  echo    FAILED satirlarini paylasin.
  echo  ==========================================
)
echo.
pause
endlocal
