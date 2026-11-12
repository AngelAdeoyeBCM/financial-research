"""Docling PDF conversion with a choice of pipeline: the standard layout/table/OCR stack or the VLM pipeline."""

from pathlib import Path
from typing import Literal

from docling.datamodel import vlm_model_specs
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, VlmPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.pipeline.vlm_pipeline import VlmPipeline
from docling_core.types.doc import DoclingDocument

PipelineMode = Literal["standard", "vlm"]


class DoclingParser:
    """Converts PDFs to a ``DoclingDocument`` with the standard pipeline or the VLM pipeline.

    The standard pipeline runs separate layout, table and OCR models. The VLM pipeline sends page images to one
    vision-language model (granite-docling-258M), replacing layout detection and OCR.
    """

    def __init__(
        self,
        *,
        mode: PipelineMode = "standard",
        enrich_formula: bool = False,
        enrich_code: bool = False,
        enrich_picture_classes: bool = False,
    ) -> None:
        """Build the converter.

        Args:
            mode: ``"standard"`` or ``"vlm"``.
            enrich_formula: Recognise formulas (standard pipeline only).
            enrich_code: Recognise code blocks (standard pipeline only).
            enrich_picture_classes: Classify figures (standard pipeline only).

        Raises:
            ValueError: If an enrichment flag is set with the VLM pipeline, which does not run those models.
        """
        if mode == "vlm" and (enrich_formula or enrich_code or enrich_picture_classes):
            raise ValueError("enrichment flags apply to the standard pipeline only")
        self.mode = mode
        self._converter = DocumentConverter(
            format_options={
                InputFormat.PDF: self._pdf_format_option(enrich_formula, enrich_code, enrich_picture_classes)
            }
        )

    def convert(self, path: Path) -> DoclingDocument:
        """Convert one PDF."""
        return self._converter.convert(path).document

    def to_markdown(self, path: Path) -> str:
        """Convert one PDF and export it as Markdown."""
        return self.convert(path).export_to_markdown()

    def _pdf_format_option(
        self, enrich_formula: bool, enrich_code: bool, enrich_picture_classes: bool
    ) -> PdfFormatOption:
        if self.mode == "vlm":
            options = VlmPipelineOptions(vlm_options=vlm_model_specs.GRANITEDOCLING_TRANSFORMERS)
            return PdfFormatOption(pipeline_cls=VlmPipeline, pipeline_options=options)
        options = PdfPipelineOptions(
            do_formula_enrichment=enrich_formula,
            do_code_enrichment=enrich_code,
            do_picture_classification=enrich_picture_classes,
        )
        return PdfFormatOption(pipeline_options=options)
