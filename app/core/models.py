"""
Modelos canónicos de datos para el Motor Comparativo de Extracción Documental.
Diseñados con Pydantic para garantizar tipado estricto, serialización JSON limpia
y retención íntegra de coordenadas espaciales y estructura de tablas de seguros.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """
    Representa las coordenadas espaciales rectangulares de un elemento en el PDF.
    Sistema estándar de coordenadas: [x0, y0, x1, y1] (izq, sup, der, inf).
    """
    x0: float = Field(..., description="Coordenada izquierda (left)")
    y0: float = Field(..., description="Coordenada superior (top)")
    x1: float = Field(..., description="Coordenada derecha (right)")
    y1: float = Field(..., description="Coordenada inferior (bottom)")
    page: int = Field(..., description="Número de página (1-indexada)")
    coord_origin: str = Field(default="TOP_LEFT", description="Origen de coordenadas: TOP_LEFT o BOTTOM_LEFT")

    def to_list(self) -> List[float]:
        return [self.x0, self.y0, self.x1, self.y1]


class Cell(BaseModel):
    """
    Representa una celda individual dentro de una tabla de póliza.
    Conserva fusiones de celdas (rowspan, colspan) y posición espacial.
    """
    text: str = Field(default="", description="Texto contenido en la celda")
    row_index: int = Field(..., description="Índice de fila (0-indexado)")
    col_index: int = Field(..., description="Índice de columna (0-indexado)")
    row_span: int = Field(default=1, description="Cantidad de filas combinadas (rowspan)")
    col_span: int = Field(default=1, description="Cantidad de columnas combinadas (colspan)")
    is_header: bool = Field(default=False, description="Indica si la celda es parte del encabezado")
    bbox: Optional[BoundingBox] = Field(default=None, description="Coordenadas espaciales de la celda")
    confidence: Optional[float] = Field(default=None, description="Nivel de confianza del OCR/modelo (0.0 a 1.0)")


class Table(BaseModel):
    """
    Representa una tabla detectada y reconstruida estructuralmente.
    Soporta tablas complejas de coberturas, deducibles, primas y tablas multipágina.
    """
    table_id: str = Field(..., description="Identificador único de la tabla")
    page_start: int = Field(..., description="Página inicial donde comienza la tabla")
    page_end: int = Field(..., description="Página final donde termina la tabla")
    num_rows: int = Field(..., description="Cantidad total de filas")
    num_cols: int = Field(..., description="Cantidad total de columnas")
    headers: List[str] = Field(default_factory=list, description="Lista de nombres de columnas detectadas")
    rows: List[List[Cell]] = Field(default_factory=list, description="Matriz bidimensional de celdas")
    bbox: Optional[BoundingBox] = Field(default=None, description="Coordenadas globales de la tabla")
    caption: Optional[str] = Field(default=None, description="Título o descripción de la tabla")
    is_multipage: bool = Field(default=False, description="Indica si la tabla continúa a lo largo de varias páginas")


class TextElement(BaseModel):
    """
    Elemento textual individual con orden de lectura y clasificación estructural.
    """
    element_id: str = Field(..., description="Identificador único del bloque")
    type: str = Field(
        default="paragraph",
        description="Tipo de elemento: 'title', 'section_header', 'paragraph', 'list_item', 'footnote', 'header', 'footer'"
    )
    text: str = Field(..., description="Texto reconocido")
    bbox: Optional[BoundingBox] = Field(default=None, description="Coordenadas espaciales del bloque")
    page: int = Field(..., description="Número de página (1-indexada)")
    reading_order: int = Field(default=0, description="Secuencia en el orden de lectura del documento")
    confidence: Optional[float] = Field(default=None, description="Confianza del reconocimiento")


class Page(BaseModel):
    """
    Representa una página física del documento PDF y su caracterización (nativa, escaneada, híbrida).
    """
    page_number: int = Field(..., description="Número de página (1-indexada)")
    width: float = Field(default=0.0, description="Ancho de página en puntos")
    height: float = Field(default=0.0, description="Alto de página en puntos")
    is_scanned: bool = Field(default=False, description="Indica si la página fue procesada como imagen escaneada")
    has_native_text: bool = Field(default=True, description="Indica si contenía texto digital nativo incrustado")
    elements: List[TextElement] = Field(default_factory=list, description="Bloques textuales de la página")
    tables: List[Table] = Field(default_factory=list, description="Tablas presentes en la página")
    raw_text: Optional[str] = Field(default="", description="Texto plano consolidado de la página")


class RAGChunk(BaseModel):
    """
    Bloque semántico preparado para futura ingestión RAG con trazabilidad a página y coordenadas.
    """
    chunk_id: str = Field(..., description="Identificador único del chunk")
    document_id: str = Field(..., description="Identificador del documento fuente")
    section: str = Field(default="General", description="Sección documental a la que pertenece")
    page_start: int = Field(..., description="Página de inicio")
    page_end: int = Field(..., description="Página de fin")
    chunk_type: str = Field(default="text", description="'text' o 'table'")
    text: str = Field(..., description="Contenido textual para embedding")
    bboxes: List[BoundingBox] = Field(default_factory=list, description="Coordenadas para resaltado visual posterior")
    token_estimate: Optional[int] = Field(default=None, description="Estimación aproximada de tokens")


class DocumentMetadata(BaseModel):
    """
    Metadatos de trazabilidad, auditoría y ejecución de extracción.
    """
    document_id: str = Field(..., description="ID normalizado del documento (ej. 'poliza_001')")
    filename: str = Field(..., description="Nombre del archivo original (ej. 'poliza_001.pdf')")
    file_size_bytes: int = Field(default=0, description="Tamaño del archivo en bytes")
    file_hash_sha256: str = Field(default="", description="Hash SHA-256 para verificación de integridad")
    total_pages: int = Field(default=0, description="Número total de páginas del PDF")
    engine_name: str = Field(..., description="Motor que generó el modelo: 'docling' o 'paddleocr'")
    engine_version: str = Field(default="unknown", description="Versión exacta del motor/librería")
    processing_time_seconds: float = Field(default=0.0, description="Tiempo de procesamiento en segundos")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Fecha y hora UTC de extracción"
    )
    status: str = Field(default="success", description="'success' o 'error'")
    error_message: Optional[str] = Field(default=None, description="Detalle del error si falló")


class DocumentModel(BaseModel):
    """
    Modelo Maestro del Documento (Document Model).
    Representación canónica de máxima riqueza estructural, independiente del motor utilizado.
    """
    metadata: DocumentMetadata
    pages: List[Page] = Field(default_factory=list, description="Colección de páginas")
    sections: List[Dict[str, Any]] = Field(default_factory=list, description="Estructura jerárquica de secciones")
    texts: List[TextElement] = Field(default_factory=list, description="Lista plana de todos los elementos textuales")
    tables: List[Table] = Field(default_factory=list, description="Lista consolidada de tablas del documento")
    rag_chunks: List[RAGChunk] = Field(default_factory=list, description="Chunks preparados para el sistema RAG")
    raw_engine_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Salida cruda original del motor para preservar 100% de la información sin pérdidas"
    )
