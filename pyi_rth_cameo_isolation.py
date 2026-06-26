# PyInstaller runtime hook: isolate the bundled Python runtime from any
# system Python installation on the end-user machine.
#
# The new Python Install Manager for Windows (python.org / Microsoft Store)
# installs runtimes under %LOCALAPPDATA%\Python\pythoncore-X.Y-64 and can
# leave PYTHONPATH, PYTHONHOME, or registry-derived paths pointing at a
# different Python version.  If a PyInstaller one-file executable picks up
# that system stdlib while its extension modules are linked to the bundled
# Python DLL, imports like `socket` fail with:
#   "Module use of python312.dll conflicts with this version of Python."
# This hook clears those environment variables and resets sys.path to the
# bundle before the main script starts importing.

import os
import sys
import site

# Environment variables that can redirect a Python interpreter to a
# different installation or stdlib.  Remove them so the bundled runtime
# stays isolated.
_VARS_TO_CLEAR = (
    'PYTHONPATH',
    'PYTHONHOME',
    'PYTHONSTARTUP',
    'PYTHONNOUSERSITE',
    'PYTHONUSERBASE',
    'PYTHONUTF8',
    'PYTHONCOERCECLOCALE',
    'PYTHONMALLOC',
    'PYTHONFAULTHANDLER',
    'PYTHONHASHSEED',
    'PYTHONVERBOSE',
    'PYTHONDEBUG',
    'PYTHONINSPECT',
    'PYTHONUNBUFFERED',
    'PYTHONOPTIMIZE',
    'PYTHONDONTWRITEBYTECODE',
    'PYTHONPYCACHEPREFIX',
    'PYTHONDEVMODE',
    'PYTHONASYNCIODEBUG',
    'PYTHONTRACEMALLOC',
    'PYTHONPROFILEIMPORT',
    'PYTHONBREAKPOINT',
    'PYTHONTHREADDEBUG',
    'PYTHONDUMPREFS',
    'PYTHONSAFEPATH',
    'PYTHONPLATLIBDIR',
    'PYTHONWARNDEFAULTENCODING',
    'PYTHONLEGACYWINDOWSFSENCODING',
    'PYTHONLEGACYWINDOWSSTDIO',
    'PYTHONIOENCODING',
    'PYTHONEXECUTABLE',
    'PYTHONFRAMEWORK',
    'PYTHONMULTIPHASEINIT',
    'PYTHONPERFSUPPORT',
    'PY_PYTHON',
    'PY_PYTHON3',
    'PY_PYTHON2',
    'PY_LAUNCHER',
    'PY_LAUNCHER_DEBUG',
    'PY_PYTHON_DIR',
    'PY_VENV_LAUNCHER',
)

for var in _VARS_TO_CLEAR:
    os.environ.pop(var, None)

# Disable user-site packages so a per-user site-packages directory cannot
# shadow or conflict with the bundled libraries.
site.ENABLE_USER_SITE = False

# Reset sys.path to the PyInstaller bundle only.  Anything outside the
# temporary extraction directory (sys._MEIPASS) is treated as external
# Python pollution and removed.
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    meipass = sys._MEIPASS
    new_path = []
    for p in sys.path:
        if p == '' or p == meipass or p.startswith(meipass + os.sep):
            if p not in new_path:
                new_path.append(p)
    if meipass not in new_path:
        new_path.insert(0, meipass)
    sys.path = new_path
