"""
Pruebas unitarias para el sistema de reglas de postprocesamiento de texto.
Verifica aislamiento por motor, reglas generales, reglas individuales y DocumentModel.
"""

import pytest
from pdfextract.core.config import TextRulesConfig
from pdfextract.core.models import (
    BoundingBox,
    Cell,
    DocumentMetadata,
    DocumentModel,
    Page,
    Table,
    TextElement,
)
from pdfextract.postprocess.rules import (
    BaseTextRule,
    CleanWhitespaceRule,
    DoclingHeaderCleanRule,
    DoclingMarkdownArtifactsRule,
    HeaderFooterRemovalRule,
    NormalizeTypographyRule,
    PaddleOCRDehyphenationRule,
    PaddleOCRSpeckleCleanupRule,
    RuleTarget,
    TextRulesPipeline,
    create_default_text_rules_pipeline,
)


def test_clean_whitespace_rule():
    rule = CleanWhitespaceRule()
    raw = "  Línea 1    con   muchos     espacios.   \n\n\n\nLínea   2.   "
    cleaned = rule.apply(raw)
    assert cleaned == "Línea 1 con muchos espacios.\n\nLínea 2."


def test_normalize_typography_rule():
    rule = NormalizeTypographyRule()
    raw = '“Póliza de Seguros” y «Coberturas» – Año 2024—2025'
    cleaned = rule.apply(raw)
    assert cleaned == '"Póliza de Seguros" y "Coberturas" - Año 2024-2025'


def test_docling_markdown_artifacts_rule():
    rule = DoclingMarkdownArtifactsRule()
    raw = "Texto con <!-- comentario oculto --><span>contenido</span><br>Segunda línea \\*con escape\\*"
    cleaned = rule.apply(raw)
    assert "<!-- comentario oculto -->" not in cleaned
    assert "<span>" not in cleaned
    assert "Segunda línea *con escape*" in cleaned


def test_docling_header_clean_rule():
    rule = DoclingHeaderCleanRule()
    raw = "### ### Coberturas Principales ###\n## Sección A"
    cleaned = rule.apply(raw)
    assert cleaned == "### Coberturas Principales\n## Sección A"


def test_paddleocr_dehyphenation_rule():
    rule = PaddleOCRDehyphenationRule()
    raw = "Las cober-\nturas del asegura-\n\ndo están cubiertas en el periodo 2023-2024."
    cleaned = rule.apply(raw)
    assert "coberturas" in cleaned
    assert "asegurado" in cleaned
    assert "2023-2024" in cleaned  # No debe alterar guiones numéricos


def test_paddleocr_speckle_cleanup_rule():
    rule = PaddleOCRSpeckleCleanupRule()
    raw = "Póliza Vigente\n.\n,\nSuma Asegurada: 100.000\n~\n..."
    cleaned = rule.apply(raw)
    lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
    assert "Póliza Vigente" in lines
    assert "Suma Asegurada: 100.000" in lines
    assert "." not in lines
    assert "," not in lines
    assert "~" not in lines
    assert "..." not in lines


def test_engine_rule_isolation():
    pipeline = create_default_text_rules_pipeline()

    docling_rules = pipeline.get_rules_for_engine("docling")
    paddle_rules = pipeline.get_rules_for_engine("paddleocr")
    general_rules = pipeline.get_rules_for_engine("general")

    # Ninguna regla de Docling debe estar en PaddleOCR
    docling_targets = {r.target for r in docling_rules}
    assert RuleTarget.DOCLING in docling_targets
    assert RuleTarget.PADDLEOCR not in docling_targets

    # Ninguna regla de PaddleOCR debe estar en Docling
    paddle_targets = {r.target for r in paddle_rules}
    assert RuleTarget.PADDLEOCR in paddle_targets
    assert RuleTarget.DOCLING not in paddle_targets

    # Las reglas generales deben estar presentes en ambos
    assert RuleTarget.GENERAL in docling_targets
    assert RuleTarget.GENERAL in paddle_targets
    assert all(r.target == RuleTarget.GENERAL for r in general_rules)


def test_custom_rule_addition():
    class CustomDoclingRule(BaseTextRule):
        rule_id = "custom_docling_test"
        name = "Regla de prueba Docling"
        target = RuleTarget.DOCLING

        def apply(self, text: str) -> str:
            return text.replace("DOCLING_ORIGINAL", "DOCLING_MODIFICADO")

    pipeline = create_default_text_rules_pipeline()
    pipeline.register(CustomDoclingRule())

    # Aplicado a docling: debe modificar
    text_docling = pipeline.clean_text("Prueba DOCLING_ORIGINAL", engine_name="docling")
    assert text_docling == "Prueba DOCLING_MODIFICADO"

    # Aplicado a paddleocr: NO debe modificar
    text_paddle = pipeline.clean_text("Prueba DOCLING_ORIGINAL", engine_name="paddleocr")
    assert text_paddle == "Prueba DOCLING_ORIGINAL"


def test_clean_document_model():
    pipeline = create_default_text_rules_pipeline()

    doc = DocumentModel(
        metadata=DocumentMetadata(
            document_id="test_doc",
            filename="test.pdf",
            engine_name="paddleocr",
        ),
        pages=[
            Page(
                page_number=1,
                raw_text="Texto con cober-\nturas y “comillas”.",
                elements=[
                    TextElement(
                        element_id="elem_1",
                        page=1,
                        text="Asegura-\ndo  principal  ",
                    )
                ],
                tables=[
                    Table(
                        table_id="tbl_1",
                        page_start=1,
                        page_end=1,
                        num_rows=1,
                        num_cols=1,
                        headers=["Encabezado  –  Detalle"],
                        rows=[
                            [Cell(text="Valor con   espacios   ", row_index=0, col_index=0)]
                        ],
                    )
                ],
            )
        ],
    )

    cleaned_doc = pipeline.clean_document(doc, engine_name="paddleocr", in_place=False)

    # Verificar TextElement
    elem_text = cleaned_doc.pages[0].elements[0].text
    assert elem_text == "Asegurado principal"

    # Verificar Table Cell y Headers
    tbl = cleaned_doc.pages[0].tables[0]
    assert tbl.headers[0] == 'Encabezado - Detalle'
    assert tbl.rows[0][0].text == "Valor con espacios"

    # Verificar raw_text de la página
    page_raw = cleaned_doc.pages[0].raw_text
    assert "coberturas" in page_raw
    assert '"comillas"' in page_raw


def test_config_toggles():
    cfg = TextRulesConfig(
        enabled=True,
        general_enabled=True,
        docling_enabled=False,
        paddleocr_enabled=True,
    )
    pipeline = create_default_text_rules_pipeline(config=cfg)

    docling_rules = pipeline.get_rules_for_engine("docling")
    # Al estar deshabilitado docling_enabled, sólo deben quedar las generales
    assert all(r.target == RuleTarget.GENERAL for r in docling_rules)

    # Si se deshabilita por completo
    pipeline.enabled = False
    assert pipeline.clean_text("   espacios   ", engine_name="paddleocr") == "   espacios   "


def test_header_footer_removal_credinform_example():
    rule = HeaderFooterRemovalRule()

    raw_text = """# Póliza de Seguro de Automotores
Suma asegurada: 50.000 USD.
Coberturas: Daño propio, robo total y responsabilidad civil.

OFICINA PRINCIPAL
SUCURSAL 1
SANTA CRUZ
POTOSI
Calacoto Calle Julio Patiño Nro. 550 Esq. Calle 12
Calle Capitan Ravelo Nro. 2328
Telf: (03)3341335
Telf: (02)6223189
Central Piloto: (02)2775550
Telf: (02)2315566
COCHABAMBA
ORURO
CAMIRI
TRINIDAD
Fax: (591-02)2203917
Telf: (04)4250095
Telf: (02)5277544
Telf: (03)9522176
email: credinformsa@credinformsa.com SUCRE
TARIJA
YACUIBA
La Paz - Bolivia Telf: (04)6453312
Telf: (04)6642736
Telf: (04)6823799"""

    cleaned = rule.apply(raw_text)

    # El contenido de negocio debe mantenerse
    assert "Póliza de Seguro de Automotores" in cleaned
    assert "Suma asegurada: 50.000 USD." in cleaned
    assert "responsabilidad civil" in cleaned

    # El bloque de pie de página de contacto debe haber sido eliminado
    assert "OFICINA PRINCIPAL" not in cleaned
    assert "Central Piloto" not in cleaned
    assert "credinformsa@credinformsa.com" not in cleaned
    assert "Calle Capitan Ravelo" not in cleaned


def test_header_footer_pagination_removal():
    rule = HeaderFooterRemovalRule()
    raw = "Condiciones Particulares\nPágina 1 de 12\nTexto de cláusula primera.\nPág. 2"
    cleaned = rule.apply(raw)
    assert "Condiciones Particulares" in cleaned
    assert "Texto de cláusula primera." in cleaned
    assert "Página 1 de 12" not in cleaned
    assert "Pág. 2" not in cleaned


def test_header_footer_multipage_cross_repetition():
    from pdfextract.core.models import BoundingBox, DocumentMetadata, DocumentModel, Page, TextElement

    rule = HeaderFooterRemovalRule()

    # Documento de 3 páginas con encabezado repetitivo y pie repetitivo
    pages = []
    for p in range(1, 4):
        pages.append(
            Page(
                page_number=p,
                height=792.0,
                width=612.0,
                elements=[
                    # Encabezado en margen superior (y0=25 <= 0.15*792 = 118.8)
                    TextElement(
                        element_id=f"hdr_{p}",
                        page=p,
                        text="SEGUROS CREDINFORM - CONDICIONES GENERALES",
                        bbox=BoundingBox(x0=50, y0=25, x1=500, y1=45, page=p),
                        reading_order=0,
                    ),
                    # Contenido real del documento
                    TextElement(
                        element_id=f"body_{p}",
                        page=p,
                        text=f"Artículo {p}: Coberturas exclusivas de la sección {p}.",
                        bbox=BoundingBox(x0=50, y0=200, x1=500, y1=300, page=p),
                        reading_order=1,
                    ),
                    # Pie de página en margen inferior (y1=760 >= 0.82*792 = 649.4)
                    TextElement(
                        element_id=f"ftr_{p}",
                        page=p,
                        text=f"Página {p} de 3",
                        bbox=BoundingBox(x0=250, y0=745, x1=350, y1=760, page=p),
                        reading_order=2,
                    ),
                ],
            )
        )

    doc = DocumentModel(
        metadata=DocumentMetadata(document_id="multi_page_test", filename="test.pdf", engine_name="docling"),
        pages=pages,
    )

    cleaned_doc = rule.apply_to_document(doc)

    for page in cleaned_doc.pages:
        elem_texts = [e.text for e in page.elements]
        # El encabezado repetitivo debe haber desaparecido
        assert not any("SEGUROS CREDINFORM" in t for t in elem_texts)
        # La paginación debe haber desaparecido
        assert not any("Página" in t for t in elem_texts)
        # El cuerpo legítimo debe conservarse
        assert any("Artículo" in t for t in elem_texts)


def test_columnar_form_disentangle_rule():
    from pdfextract.postprocess.rules.form_rules import ColumnarFormDisentangleRule

    rule = ColumnarFormDisentangleRule()
    raw_input = (
        "Producto:\n"
        "Tipo de Póliza:\n"
        "Frecuencia de Pago:\n"
        "Contratante:\n"
        "Dirección:\n"
        "Vigencia:\n"
        "Forma de Pago\n"
        "Agente:\n"
        "3604 AUT SUDAMERICANA BS.\n"
        "Individual\n"
        "Anual\n"
        "MORALES NORO, DUNIA ESPERANZA - N0000000508320\n"
        "B. FABRIL 26 DE SEPTIEMBRE CALLE 1RO DE MAYO.\n"
        "Hasta el 10 de noviembre del 2026 12 M. Desde el 10 de noviembre del 2025 12 M.\n"
        "Financiado.\n"
        "J0000000000081\n"
        "SUDAMERICANA S.R.L. CORREDORES Y ASESORES DE SEGUROS - 124\n"
        "Póliza: 10229219\n"
    )

    result = rule.apply(raw_input)

    # Cada clave debe estar emparejada con su valor correspondiente
    assert "Producto: 3604 AUT SUDAMERICANA BS." in result
    assert "Tipo de Póliza: Individual" in result
    assert "Frecuencia de Pago: Anual" in result
    assert "Contratante: MORALES NORO, DUNIA ESPERANZA - N0000000508320" in result
    assert "Dirección: B. FABRIL 26 DE SEPTIEMBRE CALLE 1RO DE MAYO." in result
    assert "Vigencia: Desde el 10 de noviembre del 2025 12 M. Hasta el 10 de noviembre del 2026 12 M." in result
    assert "Forma de Pago: Financiado." in result
    assert "Agente: J0000000000081 SUDAMERICANA S.R.L. CORREDORES Y ASESORES DE SEGUROS - 124" in result
    assert "Póliza: 10229219" in result

