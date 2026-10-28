@echo off
chcp 65001 >nul
title Siphon - exe olustur
setlocal
set "HERE=%~dp0"
echo.
echo  ==========================================
echo    Siphon.exe olusturuluyor
echo  ==========================================
echo.
echo  Bu islem tek dosyalik bir Siphon.exe uretir.
echo  Bir kere yapilir; birkac dakika surer ve internet ister.
echo.

rem --- Python'u bul ------------------------------------------------------
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY (
  echo  [HATA] Python bulunamadi.
  echo  https://www.python.org/downloads/ adresinden Python kurun
  echo  ^(kurarken "Add python.exe to PATH" kutusunu isaretleyin^), sonra tekrar deneyin.
  echo.
  pause & exit /b 1
)
%PY% --version

rem --- Temiz bir derleme ortami -----------------------------------------
echo  Derleme ortami hazirlaniyor...
if not exist "%HERE%.build\Scripts\python.exe" (
  %PY% -m venv "%HERE%.build" || (echo [HATA] ortam kurulamadi & pause & exit /b 1)
)
set "VPY=%HERE%.build\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip >nul
echo  Eklentiler ve PyInstaller kuruluyor...
"%VPY%" -m pip install -r "%HERE%requirements.txt" pyinstaller==6.13.0 || (echo [HATA] kurulum basarisiz & pause & exit /b 1)

rem --- exe'yi uret ------------------------------------------------------
echo  Derleniyor...
pushd "%HERE%packaging\windows"
"%VPY%" -m PyInstaller --noconfirm --clean --distpath "%HERE%dist" --workpath "%HERE%.build\work" Siphon.spec
popd

if not exist "%HERE%dist\Siphon.exe" (
  echo.
  echo  [HATA] Siphon.exe olusturulamadi. Yukaridaki yaziyi paylasin.
  echo.
  pause & exit /b 1
)
echo.
echo  ==========================================
echo    Bitti.  dist\Siphon.exe hazir.
echo    O dosyaya cift tiklayarak calistirabilir,
echo    masaustune ya da istediginiz yere tasiyabilirsiniz.
echo  ==========================================
echo.
pause
endlocal
