"""The Bluesky text-card pipeline used by the POC."""

from common.models import ContentJob, ContentPackage
from pipelines.poc.metadata import GeminiMetadataGenerator, MetadataGenerator


class PocPipeline:
    pipeline_id = "poc_pipeline"

    def __init__(self, metadata_generator: MetadataGenerator | None = None):
        self.metadata_generator = metadata_generator or GeminiMetadataGenerator()

    def run(self, job: ContentJob) -> ContentPackage:
        if job.pipeline_id != self.pipeline_id:
            raise ValueError(f"Unsupported pipeline: {job.pipeline_id}")

        points = "\n".join(f"- {point}" for point in job.key_points)
        body = f"{job.angle}\n\n{points}" if points else job.angle
        metadata = self.metadata_generator.generate(
            topic=job.topic,
            body=body,
            audience=job.audience,
            objective=job.objective,
        )
        self._validate_metadata(metadata.caption, metadata.tags, metadata.hashtags)
        return ContentPackage(
            job_id=job.job_id if job.job_id is not None else 0,
            pipeline_id=self.pipeline_id,
            title=job.topic.title(),
            body=body,
            caption=metadata.caption,
            visual_spec={"template_id": "poc_card", "title": job.topic.title(), "body": body, "format": "1080x1350"},
            sources=job.sources,
            platform=job.target_platform,
            account=job.target_account,
            content_format=job.content_format,
            tags=metadata.tags,
            hashtags=metadata.hashtags,
            metadata_status="generated",
            metadata_model=metadata.model,
        )

    @staticmethod
    def _validate_metadata(caption: str, tags: list[str], hashtags: list[str]) -> None:
        if not caption.strip():
            raise ValueError("Generated caption must not be empty")
        if len(tags) != len(set(tags)):
            raise ValueError("Generated tags must be unique")
        if len(hashtags) > 8:
            raise ValueError("The Bluesky POC supports at most eight hashtags")
        if len(hashtags) != len(set(hashtags)):
            raise ValueError("Generated hashtags must be unique")
        if any(not tag.startswith("#") or any(character.isspace() for character in tag) for tag in hashtags):
            raise ValueError("Generated hashtags must use # syntax and contain no whitespace")
