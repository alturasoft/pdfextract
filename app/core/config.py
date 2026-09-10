"""
Gestión de configuración tipada para el sistema mediante Pydantic y PyYAML.
"""

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field


class ProcessingConfig(BaseModel):
    parallel: bool = Field(default=False, description="Ejecutar ambos motores en paralelo o secuencialmente")
    max_workers: int = Field(default=2, description="Concurrencia máxima de hilos")
    timeout_seconds: int = Field(default=600, description="Tiempo límite por documento")


class DoclingEngineConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar motor Docling")
    ocr_enabled: bool = Field(default=True, description="Habilitar OCR cuando sea requerido")
    ocr_engine: str = Field(default="auto", description="'auto', 'easyocr', 'tesseract_cli', 'rapidocr'")
    do_table_structure: bool = Field(default=True, description="Estructura profunda de tablas")
    table_mode: str = Field(default="accurate", description="'accurate' o 'fast'")
    force_ocr: bool = Field(default=False, description="Forzar OCR en todas las páginas")


class PaddleOCREngineConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar motor PaddleOCR-VL")
    device: str = Field(default="auto", description="'auto', 'cpu', 'cuda'")
    model_name: str = Field(default="PaddlePaddle/PaddleOCR-VL-1.6", description="Modelo a utilizar")
    backend: str = Field(default="transformers", description="'transformers' o 'paddleocr'")
    use_layout: bool = Field(default=True, description="Análisis de layout")
    use_table: bool = Field(default=True, description="Extracción de tablas")
    precision: str = Field(default="fp32", description="'fp32', 'fp16', 'bf16'")
    lang: str = Field(default="es", description="Idioma principal de reconocimiento")


class EnginesConfig(BaseModel):
    docling: DoclingEngineConfig = Field(default_factory=DoclingEngineConfig)
    paddleocr: PaddleOCREngineConfig = Field(default_factory=PaddleOCREngineConfig)


class OutputConfig(BaseModel):
    output_dir: str = Field(default="./output", description="Directorio de salida")
    save_original: bool = Field(default=True, description="Copiar PDF original a la subcarpeta original/")
    save_txt: bool = Field(default=True, description="Generar TXT")
    save_markdown: bool = Field(default=True, description="Generar Markdown")
    save_json: bool = Field(default=True, description="Generar JSON estructurado")
    include_raw_engine_data: bool = Field(default=True, description="Incluir salida nativa completa en JSON")
    generate_rag_chunks: bool = Field(default=True, description="Generar chunks para futuro RAG")


class DocumentAnalysisConfig(BaseModel):
    min_chars_native_page: int = Field(default=50, description="Mínimo de caracteres para página nativa")
    page_by_page_inspection: bool = Field(default=True, description="Inspección híbrida por página")
    merge_consecutive_multipage_tables: bool = Field(default=True, description="Fusionar tablas continuadas")


class TableValidatorConfig(BaseModel):
    high_threshold: float = Field(default=0.80, description="Umbral para considerar alta confianza")
    low_threshold: float = Field(default=0.50, description="Umbral bajo el cual se considera baja confianza")
    max_empty_cell_ratio: float = Field(default=0.60, description="Ratio máximo admisible de celdas vacías")
    max_overlap_iou: float = Field(default=0.20, description="IoU máximo tolerable entre celdas adyacentes")


class TableConsensusConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar motor de consenso entre Docling y PaddleOCR")
    min_table_overlap_iou: float = Field(default=0.40, description="IoU mínimo para emparejar dos tablas de la misma página")
    min_agreement_score: float = Field(default=0.70, description="Puntuación mínima de acuerdo para considerar consenso alto")
    weight_columns: float = Field(default=0.35, description="Ponderación para coincidencia de columnas")
    weight_rows: float = Field(default=0.25, description="Ponderación para coincidencia de filas")
    weight_geometry: float = Field(default=0.25, description="Ponderación para consistencia de bbox y distribución")
    weight_content: float = Field(default=0.15, description="Ponderación para coincidencia de texto")


class TableTransformerConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar Microsoft Table Transformer (TATR)")
    model_name: str = Field(default="microsoft/table-transformer-structure-recognition", description="Modelo TATR")
    device: str = Field(default="auto", description="'auto', 'cpu', 'cuda'")
    threshold: float = Field(default=0.60, description="Umbral de detección de elementos estructurales")


class TablePostprocessingConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar postprocesamiento y corrección selectiva de tablas")
    validator: TableValidatorConfig = Field(default_factory=TableValidatorConfig)
    consensus: TableConsensusConfig = Field(default_factory=TableConsensusConfig)
    table_transformer: TableTransformerConfig = Field(default_factory=TableTransformerConfig)
    save_audit_log: bool = Field(default=True, description="Guardar auditoría completa de decisiones y correcciones")


class EvaluationConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar sistema de métricas de evaluación")
    ground_truth_dir: str = Field(default="./ground_truth", description="Directorio de datos ground truth")


class TextRulesConfig(BaseModel):
    enabled: bool = Field(default=True, description="Habilitar pipeline de reglas de postprocesamiento de texto")
    general_enabled: bool = Field(default=True, description="Habilitar reglas generales")
    docling_enabled: bool = Field(default=True, description="Habilitar reglas específicas para Docling")
    paddleocr_enabled: bool = Field(default=True, description="Habilitar reglas específicas para PaddleOCR")


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO", description="Nivel de log")
    save_log_file: bool = Field(default=True, description="Guardar archivo de log")


class AppConfig(BaseModel):
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    engines: EnginesConfig = Field(default_factory=EnginesConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    document_analysis: DocumentAnalysisConfig = Field(default_factory=DocumentAnalysisConfig)
    table_postprocessing: TablePostprocessingConfig = Field(default_factory=TablePostprocessingConfig)
    text_rules: TextRulesConfig = Field(default_factory=TextRulesConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """
    Carga la configuración desde un archivo YAML o retorna valores por defecto.
    """
    if config_path is None:
        default_path = Path("config.yaml")
        if default_path.exists():
            config_path = default_path

    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}
            return AppConfig.model_validate(raw_data)

    return AppConfig()
