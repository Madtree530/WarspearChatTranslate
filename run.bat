@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist "%~dp0wptrans.py" (
  echo [错误] 请完整解压发布包，找不到 wptrans.py。
  pause
  exit /b 1
)
set "PYEXE=%~dp0.venv\Scripts\python.exe"
if exist "%PYEXE%" goto :check_deps

echo [首次启动] 创建 Python 3.12 环境...
where py >nul 2>&1
if errorlevel 1 goto :try_python
py -3.12 -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto :try_python
py -3.12 -m venv "%~dp0.venv"
if errorlevel 1 goto :venv_error
goto :install

:try_python
python -c "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 (
  echo [错误] 请安装 Python 3.12 64 位并勾选 Add python.exe to PATH。
  pause
  exit /b 1
)
python -m venv "%~dp0.venv"
if errorlevel 1 goto :venv_error
goto :install

:venv_error
echo [错误] 创建环境失败，请确认解压目录可写。
pause
exit /b 1

:check_deps
"%PYEXE%" -c "import mss,PIL,rapidocr_onnxruntime,numpy,cv2,onnxruntime,pyclipper,shapely" >nul 2>&1
if not errorlevel 1 goto :run

:install
"%PYEXE%" -m ensurepip --upgrade
if errorlevel 1 goto :install_error
"%PYEXE%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto :install_error
goto :run

:install_error
echo [错误] 安装依赖失败，请检查网络后重新运行 run.bat。
pause
exit /b 1

:run
"%PYEXE%" "%~dp0wptrans.py" %*
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo [退出码 %EC%]
  pause
  exit /b %EC%
)
if "%~1"=="" pause
exit /b 0
