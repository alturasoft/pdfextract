"""
Punto de entrada CLI local para desarrollo en pdfextract.
Ejecuta la CLI de la librería empaquetada pdfextract.main.

Ejemplos de uso:
  python main.py --input ./input/test_poliza.pdf
  python main.py --input ./input/ --output ./output/
  python main.py --input ./input/poliza.pdf --parallel
  python main.py --input ./input/poliza.pdf --engine docling
"""

import sys
from pdfextract.main import main

if __name__ == "__main__":
    sys.exit(main())
