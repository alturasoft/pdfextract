"""
Módulo de compatibilidad hacia atrás.
Redirige llamadas a la librería 'pdfextract'.
"""

import sys
import pdfextract
from pdfextract import *  # noqa: F401, F403
from pdfextract import __version__

# Asegurar retrocompatibilidad para subpaquetes
sys.modules.setdefault("app", sys.modules[__name__])
