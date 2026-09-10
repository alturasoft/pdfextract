"""
Pruebas de validación y carga de configuración.
"""

from pathlib import Path
from pdfextract.core.config import AppConfig, load_config


def test_default_config():
    """Valida los valores por defecto del sistema."""
    config = AppConfig()
    assert config.processing.parallel is False
    assert config.engines.docling.enabled is True
    assert config.engines.paddleocr.enabled is True
    assert config.output.save_txt is True
    assert config.output.save_markdown is True
    assert config.output.save_json is True
    assert config.logging.level == "INFO"


def test_custom_yaml_loading(tmp_path: Path):
    """Valida la lectura y sobreescritura desde un archivo YAML personalizado."""
    yaml_file = tmp_path / "custom_config.yaml"
    yaml_content = """
processing:
  parallel: true
  max_workers: 4

engines:
  docling:
    enabled: true
    ocr_enabled: false
  paddleocr:
    enabled: false

output:
  output_dir: "./custom_output"
  save_txt: false
"""
    with open(yaml_file, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    cfg = load_config(yaml_file)
    assert cfg.processing.parallel is True
    assert cfg.processing.max_workers == 4
    assert cfg.engines.docling.ocr_enabled is False
    assert cfg.engines.paddleocr.enabled is False
    assert cfg.output.output_dir == "./custom_output"
    assert cfg.output.save_txt is False
