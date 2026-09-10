"""
Utilidades para gestión segura del sistema de archivos, hashing y creación de rutas.
"""

import hashlib
import re
import shutil
from pathlib import Path
from typing import Dict, List


def calculate_sha256(file_path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo para trazabilidad de integridad."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(65536), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def normalize_document_id(file_path: Path) -> str:
    """
    Genera un identificador limpio y seguro para carpetas y metadatos
    a partir del nombre del archivo.
    """
    stem = file_path.stem
    # Reemplazar caracteres no alfanuméricos por guiones bajos
    clean_name = re.sub(r"[^\w\-_]", "_", stem)
    return re.sub(r"_+", "_", clean_name).strip("_")


def find_pdf_files(input_path: Path) -> List[Path]:
    """
    Encuentra todos los archivos PDF en la ruta indicada (archivo individual o directorio).
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"La ruta de entrada no existe: {path}")

    if path.is_file():
        if path.suffix.lower() == ".pdf":
            return [path]
        else:
            raise ValueError(f"El archivo indicado no es un PDF: {path}")

    # Si es directorio, buscar recursivamente
    pdf_files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"]
    pdf_files.sort()
    return pdf_files


def prepare_document_output_dirs(base_output_dir: Path, document_id: str) -> Dict[str, Path]:
    """
    Crea la estructura de carpetas requerida para el documento:
    output/
    └── <document_id>/
        ├── original/
        ├── docling/
        └── paddleocr/
    """
    doc_root = base_output_dir / document_id
    dirs = {
        "root": doc_root,
        "original": doc_root / "original",
        "docling": doc_root / "docling",
        "paddleocr": doc_root / "paddleocr",
        "postprocessed": doc_root / "postprocessed",
    }

    for dir_path in dirs.values():
        dir_path.mkdir(parents=True, exist_ok=True)

    return dirs


def copy_original_pdf(source_path: Path, target_dir: Path) -> Path:
    """
    Copia el PDF original a la subcarpeta original/ manteniendo el archivo original intacto.
    """
    target_path = target_dir / source_path.name
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)
    return target_path

