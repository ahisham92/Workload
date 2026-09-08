"""Paste this into the web app's WSGI configuration file on PythonAnywhere.

Web tab -> your web app -> "WSGI configuration file" -> replace everything
with this, change the two names, Save, Reload.

If this checkout is already on the server, you do not have to edit anything by
hand:

    python -m workload_app.admin check --wsgi-only

prints the same file with the real paths already filled in.

Running a second web app beside an existing one on the same account is where
this goes wrong.  Both lines below must differ from the other app's:

  * ``CODE`` -- this checkout, not the other app's source directory.
  * ``WORKLOAD_DATA_DIR`` -- this app's accounts and workbooks, outside the
    code (a deploy replaces the code) and not shared with the other app.
"""

import os
import sys

# 1. Where this app's code is. Change <you> to your PythonAnywhere username.
CODE = '/home/<you>/Workload'

# 2. Where its accounts and workbooks live. OUTSIDE the code, and used by no
#    other web app on this account.
DATA = '/home/<you>/workload-data'

if CODE not in sys.path:
    sys.path.insert(0, CODE)

os.environ['WORKLOAD_DATA_DIR'] = DATA

from workload_app.wsgi import application        # noqa: E402,F401
