"""The single predefined content pipeline used by the POC."""

from common.models import ContentJob, ContentPackage


class PocPipeline:
    pipeline_id = "poc_pipeline"

    def run(self, job: ContentJob) -> ContentPackage:
        if job.pipeline_id != self.pipeline_id:
            raise ValueError(f"Unsupported pipeline: {job.pipeline_id}")

        points = "\n".join(f"- {point}" for point in job.key_points)
        body = f"{job.angle}\n\n{points}" if points else job.angle
        return ContentPackage(
            job_id=job.job_id if job.job_id is not None else 0,
            pipeline_id=self.pipeline_id,
            title=job.topic.title(),
            body=body,
            caption=f"A concise explanation of {job.topic}.",
            visual_spec={"template_id": "poc_card", "title": job.topic.title(), "body": body, "format": "1080x1350"},
            sources=job.sources,
        )
