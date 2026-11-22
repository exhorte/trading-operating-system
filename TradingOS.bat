@echo off
rem ---------------------------------------------------------------------------
rem  Trading OS - point d'entree. Double-clic, ou : TradingOS.bat [Mode] [options]
rem  Modes : Full (defaut) | Infrastructure | MT5 | Status | Stop | Doctor
rem  Options : -DryRun -IncludeDatabase (Stop) -Apply -Json -PythonPath <python.exe>
rem
rem  Ce fichier ne fait que lancer scripts\TradingOS.Launcher.ps1 (ADR 0039).
rem  Il ne change aucune politique d'execution : -ExecutionPolicy Bypass ne vaut
rem  que pour ce processus.
rem
rem  Pause finale : seulement SANS argument (c'est le double-clic), pour que la
rem  fenetre ne se ferme pas sur le resultat. Avec un argument, jamais : un .bat
rem  lance depuis PowerShell, Python ou un planificateur tourne aussi sous
rem  "cmd /c". Variable TRADINGOS_NOPAUSE=1 : jamais de pause.
rem ---------------------------------------------------------------------------
setlocal
set "TRADINGOS_SHELL=powershell.exe"
where pwsh.exe >nul 2>&1
if not errorlevel 1 set "TRADINGOS_SHELL=pwsh.exe"
"%TRADINGOS_SHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\TradingOS.Launcher.ps1" %*
set "TRADINGOS_EXIT=%ERRORLEVEL%"
if defined TRADINGOS_NOPAUSE goto done
if not "%~1"=="" goto done
echo.
pause
:done
exit /b %TRADINGOS_EXIT%
