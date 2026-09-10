# Motor Comparativo de Extracción Documental de Pólizas de Seguros (Docling vs PaddleOCR-VL 1.6)

Sistema profesional, modular y extensible en Python diseñado para procesar, extraer y analizar con máxima fidelidad documentos de pólizas de seguros (condiciones particulares, generales, cuadros de coberturas, tablas de primas y deducibles) ejecutando en paralelo o de forma secuencial dos motores de Document Intelligence de última generación: **Docling** e **PaddleOCR-VL 1.6**.

---

## 1. Objetivo del Proyecto

El objetivo principal es permitir un **benchmark objetivo y riguroso** entre dos tecnologías líderes en procesamiento documental sobre las mismas pólizas de seguros, sin alterar los documentos originales y sin aplicar intervenciones o correcciones por Modelos de Lenguaje (LLM) en esta primera fase.

El sistema garantiza:
1. **Procesamiento Dual Puro**: Ambas tecnologías procesan el mismo archivo PDF de entrada manteniendo sus resultados completamente independientes.
2. **Máxima Fidelidad Estructural**: Énfasis en la extracción de tablas complejas de seguros (con celdas combinadas, `rowspan`, `colspan`, encabezados multinivel y tablas multipágina).
3. **Trazabilidad Espacial (RAG-Ready)**: Preservación de cajas delimitadoras (`bbox`), número de página y orden de lectura secuencial para auditoría visual y futura ingestión en bases de datos vectoriales.
4. **Soporte de Documentos Híbridos**: Detección página por página de páginas con texto digital nativo y páginas compuestas por imágenes escaneadas para evitar OCR innecesario.

---

## 2. Arquitectura del Sistema

El flujo arquitectónico sigue el principio de separación estricta entre el documento maestro canónico y las representaciones derivadas:

```text
                             PDF ORIGINAL
                                  │
                 ┌────────────────┴────────────────┐
                 │                                 │
                 ▼                                 ▼
         [ MOTOR 1: DOCLING ]            [ MOTOR 2: PADDLEOCR-VL 1.6 ]
                 │                                 │
                 ▼                                 ▼
      [ CANONICAL DOCUMENT MODEL ]       [ CANONICAL DOCUMENT MODEL ]
                 │                                 │
       ┌─────────┼─────────┐             ┌─────────┼─────────┐
       ▼         ▼         ▼             ▼         ▼         ▼
      TXT        MD       JSON          TXT        MD       JSON
```

### Principios de Diseño
- **Plugin Pattern (`BaseExtractionEngine`)**: Nuevos motores (ej. MinerU, Surya, Table Transformer) pueden incorporarse implementando una clase derivada sin modificar el resto de la aplicación.
- **Exportadores Desacoplados (`BaseExporter`)**: Los generadores de TXT, Markdown y JSON consumen el `DocumentModel` canónico, evitando cualquier acoplamiento con la API interna de los motores.
- **Tolerancia a Fallos y Aislamiento**: El fallo o excepción en un motor no interrumpe el procesamiento del otro; se genera un archivo `error.log` en su subdirectorio y se registra el incidente en `processing_metadata.json`.

---

## 3. Requisitos del Sistema

### Hardware Recomendado
- **CPU**: Mínimo 4 núcleos físicos (recomendado 8+ núcleos).
- **Memoria RAM**:
  - Mínimo: 8 GB.
  - Recomendado: 16 GB - 32 GB (para procesamiento de PDFs multipágina con tablas complejas).
- **GPU (Opcional pero recomendada para alto volumen)**:
  - NVIDIA GPU con soporte CUDA 11.8 o 12.x.
  - VRAM mínima: 6 GB - 8 GB (para inferencia de modelos Vision-Language como PaddleOCR-VL 0.9B).

### Software
- **Sistema Operativo**: Windows 10/11, Ubuntu 20.04/22.04/24.04 LTS o macOS (Apple Silicon).
- **Python**: Compatible con Python 3.10, 3.11 y 3.12 (utilizado en el entorno local: Python 3.12 / 3.14).

---

## 4. Instalación

### Opción A: Entorno Estándar / CPU

```bash
# 1. Clonar o posicionarse en el repositorio
cd pdfextract

# 2. Crear y activar un entorno virtual
python -m venv .venv

# En Windows (PowerShell):
.venv\Scripts\Activate.ps1
# En Linux / macOS:
source .venv/bin/activate

# 3. Instalar dependencias base
pip install --upgrade pip
pip install -r requirements.txt
```

### Opción B: Entorno con Aceleración GPU (CUDA)

```bash
# Instalar dependencias con soporte CUDA para PyTorch y PaddlePaddle
pip install -r requirements-gpu.txt
```

---

## 5. Configuración (`config.yaml`)

El archivo [`config.yaml`](file:///d:/OGOS/DESARROLLOS/pdfextract/config.yaml) centraliza el comportamiento de la aplicación:

```yaml
processing:
  parallel: false             # true: ejecuta ambos motores simultáneamente; false: secuencial (seguro para VRAM)
  max_workers: 2              # Concurrencia de hilos
  timeout_seconds: 600        # Tiempo límite por documento

engines:
  docling:
    enabled: true
    ocr_enabled: true         # OCR adaptativo en páginas escaneadas
    ocr_engine: "auto"        # 'auto', 'rapidocr', 'easyocr', 'tesseract_cli'
    do_table_structure: true  # Reconstrucción profunda de tablas
    table_mode: "accurate"    # 'accurate' (recomendado para seguros) o 'fast'
    force_ocr: false

  paddleocr:
    enabled: true
    device: "auto"            # 'auto', 'cpu', 'cuda'
    model_name: "PaddlePaddle/PaddleOCR-VL-1.6"
    backend: "transformers"   # 'transformers' o 'paddleocr'
    use_layout: true
    use_table: true
    precision: "fp32"         # 'fp32', 'fp16', 'bf16'
    lang: "es"

output:
  output_dir: "./output"
  save_original: true         # Preserva el PDF original en original/
  save_txt: true
  save_markdown: true
  save_json: true
  include_raw_engine_data: true
  generate_rag_chunks: true

document_analysis:
  min_chars_native_page: 50   # Umbral de caracteres para clasificar página como nativa
  page_by_page_inspection: true
  merge_consecutive_multipage_tables: true

logging:
  level: "INFO"
  save_log_file: true
```

---

## 6. Uso de la Interfaz CLI

### Procesar un Archivo PDF Individual

```bash
python main.py --input ./input/poliza_automovil.pdf
```

### Procesar un Directorio Completo de Pólizas

```bash
python main.py --input ./input/ --output ./output/
```

### Forzar Modo Paralelo o Secuencial

```bash
# Modo paralelo (ambos motores al mismo tiempo):
python main.py --input ./input/poliza.pdf --parallel

# Modo secuencial (protección de recursos de GPU/CPU):
python main.py --input ./input/poliza.pdf --no-parallel
```

### Ejecutar un Solo Motor Específico

```bash
# Solo Docling:
python main.py --input ./input/poliza.pdf --engine docling

# Solo PaddleOCR-VL:
python main.py --input ./input/poliza.pdf --engine paddleocr
```

---

## 7. Estructura de Resultados

Para cada documento procesado (por ejemplo, `poliza_001.pdf`), el sistema genera una carpeta aislada con la siguiente jerarquía estricta:

```text
output/
└── poliza_001/
    │
    ├── original/
    │   └── poliza_001.pdf             # Copia exacta e inalterada del archivo fuente
    │
    ├── docling/
    │   ├── poliza_001.txt             # Texto plano ordenado con tablas ASCII
    │   ├── poliza_001.md              # Markdown GFM con tablas pipe y anclas de página
    │   └── poliza_001.json            # Estructura canónica completa con coordenadas bbox
    │
    ├── paddleocr/
    │   ├── poliza_001.txt             # Salida textual del motor PaddleOCR
    │   ├── poliza_001.md              # Markdown generado por PaddleOCR
    │   └── poliza_001.json            # JSON con layout, tablas y metadatos
    │
    └── processing_metadata.json       # Informe técnico consolidado de auditoría del proceso
```

---

## 8. Detalle de Archivos de Salida

### A. Archivo TXT (`.txt`)
- Incluye cabecera con metadatos del documento y fecha de extracción.
- Marcadores de página explícitos: `--- [PÁGINA X] ---`.
- Cuadros de texto ordenados por secuencia lógica de lectura.
- Tablas complejas representadas visualmente mediante caracteres ASCII alineados.

### B. Archivo Markdown (`.md`)
- Jerarquía documental completa (`#` Título, `##` Secciones, `###` Subsecciones).
- Tablas en formato GitHub Flavored Markdown (GFM):
  ```markdown
  | Cobertura | Suma Asegurada | Prima Anual |
  | --- | --- | --- |
  | Incendio y Rayo | USD 500.000 | USD 450 |
  ```
- Anclas de trazabilidad de página (`<!-- Página X -->`).

### C. Archivo JSON Estructurado (`.json`)
Es el formato de mayor fidelidad documental. Incluye:
- `document`: Nombre, ID, páginas totales, hash SHA-256 e integridad.
- `extraction`: Motor utilizado, versión, duración exacta en segundos y estado.
- `pages`: Dimensiones (`width`, `height`), clasificación (`is_scanned`, `has_native_text`).
- `texts`: Colección de bloques de texto con orden de lectura (`reading_order`) y coordenadas espaciales `bbox` (`x0`, `y0`, `x1`, `y1`, `page`, `coord_origin`).
- `tables`: Matriz de celdas con `row_span`, `col_span`, `is_header`, coordenadas individuales y detección de multipágina (`is_multipage`).
- `rag_chunks`: Segmentos semánticos preparados para ingestión vectorial con lista de `bboxes` asociados para resaltado visual posterior.
- `raw_engine_data`: Salida nativa completa del motor (ej. esquema de Docling o inferencia cruda de PaddleOCR) garantizando 0% de pérdida de información.

### D. Metadatos de Auditoría (`processing_metadata.json`)
Registra métricas técnicas comparativas:
- Huella del sistema (OS, arquitectura, CPU física/lógica, RAM total/disponible, estado GPU/VRAM).
- Versiones exactas instaladas de librerías (`docling`, `torch`, `transformers`, `paddleocr`).
- Comparativa por motor: estado (`success` o `error`), tiempo de ejecución, cantidad de páginas, tablas y rutas a los archivos generados.

---

## 9. Motor 1: Docling

- **Desarrollador**: IBM Research (Granite Document Intelligence).
- **Capacidades aprovechadas**:
  - Detección de layout y flujo de lectura basada en modelos de visión (Heron).
  - Reconstrucción profunda de tablas con `TableFormer` en modo `ACCURATE`.
  - Integración nativa de OCR (RapidOCR / EasyOCR / Tesseract) para páginas sin capa digital.
  - Generación interna de DoclingDocument enriquecido.

---

## 10. Motor 2: PaddleOCR-VL 1.6

- **Desarrollador**: PaddlePaddle (Baidu).
- **Capacidades aprovechadas**:
  - Modelo multimodal Vision-Language (0.9B parámetros) especializado en análisis de documentos y tablas complejas.
  - Renderizado de alta resolución con `pypdfium2` (150-200 DPI).
  - Reconocimiento de tablas HTML y Markdown preservando `rowspan` y `colspan`.
  - Pipeline de contingencia y respaldo que asegura la continuidad del procesamiento.

---

## 11. Ejecución en CPU vs GPU

| Característica | Entorno CPU | Entorno GPU (CUDA) |
|---|---|---|
| **Configuración recomendada** | `processing.parallel: false` | `processing.parallel: true` o `false` |
| **Docling** | Totalmente compatible | Compatible (utiliza PyTorch CUDA si está disponible) |
| **PaddleOCR-VL 1.6** | Compatible en precisión `fp32` | Acelerado en precisión `bfloat16` / `fp16` |
| **Consumo de VRAM** | 0 MB | ~4 GB a 8 GB |
| **Velocidad estimada** | 10s - 30s por página | 2s - 6s por página |

> **Recomendación para GPUs con < 8 GB de VRAM**: Mantener `parallel: false` en `config.yaml` para evitar saturación de memoria al ejecutar ambos motores sobre documentos pesados.

---

## 12. Tolerancia a Fallos y Manejo de Errores

Si durante la ejecución uno de los motores experimenta un error (por ejemplo, falta de conectividad para pesos, archivo corrupto o fallo de memoria):
1. El motor afectado captura la excepción y no detiene el pipeline principal.
2. Se genera el archivo `output/<doc>/<motor>/error.log` con el volcado del mensaje de error.
3. El otro motor continúa su procesamiento y genera sus archivos con normalidad.
4. El archivo `processing_metadata.json` documenta el estado de cada motor para el benchmark posterior.

---

## 13. Pruebas Automatizadas

El proyecto incluye una suite completa de pruebas unitarias y de integración construida con `pytest`:

```bash
# Ejecutar toda la suite de pruebas
python -m pytest -v

# Ejecutar con reporte de cobertura de código
python -m pytest --cov=app tests/
```

### Cobertura de las Pruebas
- `test_config.py`: Validación de tipos con Pydantic y carga de YAMLs personalizados.
- `test_file_utils.py`: Hashing SHA-256, normalización de IDs, copias seguras y clasificación de páginas PDF.
- `test_exporters.py`: Integridad de exportaciones TXT, Markdown GFM y JSON canónico con tablas y coordenadas.
- `test_processors.py`: Flujo de orquestación, preservación del PDF original, aislamiento de errores y procesamiento por lotes.

---

## 14. Limitaciones Conocidas

1. **Modelos VLM en Hugging Face**: Versiones recientes de `transformers` (v5.x) pueden presentar incompatibilidades menores de atributos con pesos de terceros (`PaddleOCRVLConfig`); el sistema cuenta con capturas defensivas para evitar bloqueos.
2. **Tablas manuscritas o sin contraste**: Documentos escaneados con muy baja resolución (menor a 100 DPI) o inclinaciones severas pueden requerir preprocesamiento de imagen previo.

---

## 15. Hoja de Ruta (Futuras Etapas)

- **Etapa 2**: Módulo de Benchmark automatizado para comparar similitud de texto (Levenshtein, BLEU), exactitud de celdas de tablas (IoU / F1-score) y métricas de consumo de hardware.
- **Etapa 3**: Normalización mediante esquema de póliza de negocio (extracción de asegurado, número de póliza, vigencia, primas netas, deducibles).
- **Etapa 4**: Integración RAG con base de datos vectorial (Qdrant / pgvector) aprovechando los `rag_chunks` y coordenadas espaciales ya generados en el JSON.
