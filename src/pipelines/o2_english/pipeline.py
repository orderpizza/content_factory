"""Fixed-format o2_english Instagram idiom carousel pipeline."""

import json

from common.models import ContentJob, ContentPackage
from pipelines.o2_english.content import GeminiIdiomContentGenerator, IdiomContentGenerator, validate_idiom_carousel
from pipelines.o2_english.templates import IDIOM_CAROUSEL_PROFILE, template_for_slide


class O2EnglishInstagramPipeline:
    pipeline_id = "o2_english_instagram"
    content_format = "instagram_idiom_carousel"

    def __init__(self, generator: IdiomContentGenerator | None = None):
        self.generator = generator or GeminiIdiomContentGenerator()

    def run(self, job: ContentJob) -> ContentPackage:
        if job.pipeline_id != self.pipeline_id:
            raise ValueError(f"Unsupported pipeline: {job.pipeline_id}")
        if job.target_platform != "instagram" or job.target_account != "o2_english":
            raise ValueError("o2 English pipeline requires the o2_english Instagram destination")
        if job.content_format != self.content_format or job.visual_profile_id != IDIOM_CAROUSEL_PROFILE:
            raise ValueError("Unsupported o2 English content format or visual profile")

        content = self.generator.generate(job)
        validate_idiom_carousel(content)
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
