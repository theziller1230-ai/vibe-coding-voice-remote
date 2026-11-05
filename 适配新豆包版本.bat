@echo off
rem =====================================================================
rem  适配新豆包版本（无需重新编译）
rem
rem  豆包升级后双击本文件，然后重启 VCVR 即可。
rem  原理：程序启动时会读取 doubao_profiles.json，把新版本的
rem        ImeService/rpc/tsf 哈希、三个 RVA 和两段签名字节合并进内置表。
rem =====================================================================
setlocal EnableDelayedExpansion

rem 仓库根目录 = 本脚本所在目录；Python 优先用 VCVR_PYTHON 覆盖，
rem 其次用 PATH 上的 python，最后退回仓库旁边的 build-venv。
set "REPO=%~dp0"
set "PY=%VCVR_PYTHON%"
if "%PY%"=="" set "PY=python"
if not exist "%PY%" if exist "%REPO%..\build-venv\Scripts\python.exe" set "PY=%REPO%..\build-venv\Scripts\python.exe"
set PROFILE=%LOCALAPPDATA%\RemoteMic\RC003\doubao_profiles.json

if not exist "%PY%" (
  echo [X] 找不到可用的 Python: %PY%
  echo     请安装 Python 3.12，或设置 VCVR_PYTHON 指向解释器。
  pause
  exit /b 1
)

echo.
echo === 当前豆包版本目录 ===
powershell -NoProfile -Command "(Get-ItemProperty 'HKLM:\SOFTWARE\DoubaoIme').VersionDir"

echo.
echo === 计算参数并写入 %PROFILE% ===
cd /d "%REPO%"
"%PY%" tools\adapt_doubao.py --json "%PROFILE%"
if errorlevel 1 (
  echo.
  echo [X] 适配失败
  pause
  exit /b 1
)

echo.
echo =====================================================================
echo  完成，不需要重新编译。
echo  请重启"无线麦 win版 1.0.103.exe"（以管理员身份），
echo  然后按遥控器语音键说话、再按一次验证。
echo =====================================================================
pause
