# Guía de Empaquetado, Uso y Versionado de `pdfextract`

Esta guía explica cómo utilizar **`pdfextract`** como una librería reutilizable en otros proyectos Python, cómo estructurar llamadas en código y cómo publicar mejoras continuas mediante versionado semántico (SemVer).

---

## 1. Cómo instalar `pdfextract` en otro proyecto

Dependiendo de cómo esté organizado tu flujo de trabajo, tienes 3 opciones para consumir esta librería en cualquier otro proyecto de Python:

### Opción A: Modo Editable para Desarrollo Local (Recomendada mientras sigas programando mejoras)
Si tienes ambos proyectos en tu misma computadora y quieres que **cualquier mejora que hagas en `pdfextract` se refleje inmediatamente en el otro proyecto** sin tener que reinstalar:
```bash
cd /ruta/a/tu/otro_proyecto
pip install -e D:/OGOS/DESARROLLOS/pdfextract
```

### Opción B: Instalación directa desde Repositorio Git (Para despliegue o proyectos independientes)
Si el repositorio está subido a GitHub, GitLab o Bitbucket (privado o público):
```bash
# Instalar la versión estable más reciente
pip install git+https://github.com/tu-usuario/pdfextract.git

# O fijar una versión específica etiquetada
pip install git+https://github.com/tu-usuario/pdfextract.git@v1.0.0
```

En el archivo `requirements.txt` de tu otro proyecto, simplemente agregas:
```text
git+https://github.com/tu-usuario/pdfextract.git@v1.0.0
```

### Opción C: Generar un archivo Wheel binario (`.whl`)
Si deseas generar un paquete portable para compartir o instalar sin Git:
```bash
cd D:/OGOS/DESARROLLOS/pdfextract
py -3.14 -m pip install build
py -3.14 -m build
```
Esto creará una carpeta `dist/` con el archivo `pdfextract-1.0.0-py3-none-any.whl`. En el otro proyecto:
```bash
pip install dist/pdfextract-1.0.0-py3-none-any.whl
```

---

## 2. Cómo usar la librería en tu nuevo proyecto Python

### A. Extracción en 1 línea de código (API de Alto Nivel)
```python
from pdfextract import extract_pdf

# Extrae con ambos motores por defecto y guarda salidas estructuradas (TXT, MD, JSON)
resultado = extract_pdf("documentos/poliza_auto.pdf", output_dir="./salidas")

print("Estado general:", resultado.get("status"))
print("Resumen de tablas analizadas:", resultado.get("table_postprocessing_summary"))
```

### B. Extracción eligiendo un motor específico y configuración
```python
from pdfextract import extract_pdf

# Ejecutar únicamente Docling
resultado = extract_pdf(
    input_path="poliza.pdf",
    output_dir="./salida_docling",
    engine="docling", # o 'paddleocr'
)

# O pasar un archivo de configuración personalizado
resultado = extract_pdf(
    input_path="poliza.pdf",
    config="mi_config_personalizado.yaml"
)
```

### C. Procesamiento por lotes (Carpetas completas)
```python
from pdfextract import extract_batch

# Procesa todos los PDFs dentro de la carpeta
resultados = extract_batch(
    input_target="./documentos_polizas/",
    output_dir="./salida_batch",
    parallel=False
)

print(f"Total de documentos procesados: {len(resultados)}")
```

### D. Uso avanzado con el orquestador (`DocumentProcessor`)
```python
from pdfextract import DocumentProcessor, load_config

# Carga la configuración (busca en entorno local o usa los defaults internos)
config = load_config()
config.table_postprocessing.enabled = True

processor = DocumentProcessor(config=config)
res = processor.process(pdf_path=Path("poliza.pdf"))
```

---

## 3. Uso desde la Consola / Terminal

Al instalar la librería, se registra automáticamente el comando global `pdfextract`:
```bash
# Procesar un PDF individual
pdfextract -i ./poliza.pdf -o ./salidas --engine docling

# Procesar una carpeta completa
pdfextract -i ./carpeta_pdfs/ -o ./salidas

# Ver opciones y ayuda
pdfextract --help
```

---

## 4. Ciclo de Mejoras Continuas y Versionado (SemVer)

A medida que sigas trabajando en este proyecto agregando más reglas (`docling_rules.py`), nuevos clasificadores o mejoras de rendimiento, este es el flujo para que los otros proyectos se actualicen limpiamente:

### Paso 1: Actualizar la versión
Incrementa el número de versión en dos lugares:
1. En `pyproject.toml`:
   ```toml
   [project]
   version = "1.1.0"
   ```
2. En `pdfextract/__init__.py`:
   ```python
   __version__ = "1.1.0"
   ```

> **Regla SemVer:**
> - `1.0.1` (Patch): Corrección de errores menores o ajustes de regex que no alteran la API.
> - `1.1.0` (Minor): Nuevas funciones, reglas o mejoras compatibles hacia atrás.
> - `2.0.0` (Major): Cambios estructurales que requieran cambiar cómo se llama el código.

### Paso 2: Crear una etiqueta (Git Tag)
```bash
git add .
git commit -m "feat: nuevas reglas de extracción para pólizas complejas"
git tag v1.1.0
git push origin main --tags
```

### Paso 3: Actualizar en el otro proyecto
En cualquier proyecto donde la estés utilizando:
```bash
# Actualizar a la versión específica:
pip install --upgrade git+https://github.com/tu-usuario/pdfextract.git@v1.1.0

# O si tenías requirements.txt actualizado con v1.1.0:
pip install --upgrade -r requirements.txt
```

¡Listo! Con esto tu proyecto es formalmente una librería modular, extensible y fácilmente integrable en cualquier sistema Python.
