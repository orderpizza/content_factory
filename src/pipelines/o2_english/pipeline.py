"""Fixed-format o2_english Instagram idiom carousel pipeline."""

import json

from common.models import ContentJob, ContentPackage
from pipelines.o2_english.content import (
    GeminiIdiomContentGenerator, GeminiIdiomMetadataGenerator, IdiomCarouselContent,
    IdiomContentGenerator, IdiomMetadataGenerator, validate_idiom_carousel, validate_metadata,
)
from pipelines.o2_english.templates import IDIOM_CAROUSEL_PROFILE, template_for_slide


class O2EnglishInstagramPipeline:
    pipeline_id = "o2_english_instagram"
    content_format = "instagram_idiom_carousel"

    def __init__(self, generator: IdiomContentGenerator | None = None,
                 metadata_generator: IdiomMetadataGenerator | None = None,
                 metadata_attempts: int = 2):
        if metadata_attempts < 1:
            raise ValueError("metadata_attempts must be at least one")
        self.generator = generator or GeminiIdiomContentGenerator()
        self.metadata_generator = metadata_generator or GeminiIdiomMetadataGenerator()
        self.metadata_attempts = metadata_attempts
        self.last_usage_events: list[tuple[str, object]] = []

    def run(self, job: ContentJob) -> ContentPackage:
        if job.pipeline_id != self.pipeline_id:
            raise ValueError(f"Unsupported pipeline: {job.pipeline_id}")
        if job.target_platform != "instagram" or job.target_account != "o2_english":
            raise ValueError("o2 English pipeline requires the o2_english Instagram destination")
        if job.content_format != self.content_format or job.visual_profile_id != IDIOM_CAROUSEL_PROFILE:
            raise ValueError("Unsupported o2 English content format or visual profile")

        self.last_usage_events = []
        draft = self.generator.generate(job)
        validate_idiom_carousel(draft)
        self._capture_usage("pipeline_content", self.generator)
        metadata = self._generate_metadata(draft, job)
        content = IdiomCarouselContent(
            draft.teaching_target, draft.slides, metadata.caption, metadata.tags, metadata.hashtags, metadata.model,
        )
        slides = [slide.to_dict() for slide in content.slides]
        resolved_templates = [template_for_slide(slide.slide_type).template_id for slide in content.slides]
        visual_spec = {
            "profile_id": IDIOM_CAROUSEL_PROFILE,
            "format": "1080x1920",
            "palette_id": "neutral_v1",
            "teaching_target": content.teaching_target,
            "slides": slides,
            "resolved_template_ids": resolved_templates,
        }
        return ContentPackage(
            job_id=job.job_id or 0,
            pipeline_id=self.pipeline_id,
            title=content.teaching_target,
            body=json.dumps({"slides": slides}, ensure_ascii=False),
            caption=content.caption,
            visual_spec=visual_spec,
            sources=job.sources,
            platform="instagram",
            account="o2_english",
            content_format=self.content_format,
            tags=list(content.tags),
            hashtags=list(content.hashtags),
            metadata_status="generated",
            metadata_model=content.model,
        )

    def _capture_usage(self, phase: str, generator: object) -> None:
        usage = getattr(generator, "last_usage", None)
        if usage is not None:
            self.last_usage_events.append((phase, usage))

    def _generate_metadata(self, draft, job: ContentJob):
        """Retry only metadata generation; validated slide content remains intact."""
        last_error: Exception | None = None
        for _ in range(self.metadata_attempts):
            try:
                metadata = self.metadata_generator.generate(draft, job)
                validate_metadata(metadata)
                self._capture_usage("pipeline_metadata", self.metadata_generator)
                return metadata
            except Exception as error:
                last_error = error
        assert last_error is not None
        raise last_error
