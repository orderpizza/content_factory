"""Persisted ContentJob consumer for the single POC pipeline."""

import json

from common.models import ContentJob, ContentPackage, utc_now
from common.gemini import estimated_cost_usd
from database.sqlite import Database


class PipelineRunner:
    def __init__(self, database: Database, pipeline):
        self.database = database
        if isinstance(pipeline, dict):
            self.pipelines = pipeline
        else:
            self.pipelines = {pipeline.pipeline_id: pipeline}

    @staticmethod
    def _job(row) -> ContentJob:
        return ContentJob(
            trend_id=row["trend_id"],
            determination_handoff_id=row["determination_handoff_id"],
            candidate_id=row["candidate_id"],
            pipeline_id=row["pipeline_id"],
            target_platform=row["target_platform"],
            target_account=row["target_account"],
            content_format=row["content_format"],
            visual_profile_id=row["visual_profile_id"],
            topic=row["topic"],
            angle=row["angle"],
            audience=row["audience"],
            objective=row["objective"],
            key_points=json.loads(row["key_points"]),
            sources=json.loads(row["sources"]),
            priority=row["priority"],
            status=row["status"],
            job_id=row["job_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _package(row) -> ContentPackage:
        return ContentPackage(
            job_id=row["job_id"], pipeline_id=row["pipeline_id"], title=row["title"], body=row["body"],
            caption=row["caption"], visual_spec=json.loads(row["visual_spec"]), assets=json.loads(row["assets"]),
            sources=json.loads(row["sources"]), content_id=row["content_id"], created_at=row["created_at"],
            platform=row["platform"], account=row["account"], content_format=row["content_format"],
            tags=json.loads(row["tags"]), hashtags=json.loads(row["hashtags"]), status=row["status"],
            metadata_status=row["metadata_status"], metadata_model=row["metadata_model"],
        )

    def consume_next(self):
        jobs = self.database.pending_content_jobs(limit=1)
        if not jobs:
            return None
        row = jobs[0]
        if not self.database.claim_content_job(row["job_id"], utc_now()):
            return None
        job = self._job(row)
        pipeline = self.pipelines.get(job.pipeline_id)
        if pipeline is None:
            self.database.finish_content_job(job.job_id, "failed", utc_now())
            raise ValueError(f"No pipeline registered for {job.pipeline_id}")
        existing = self.database.connection.execute(
            "SELECT content_id FROM content_packages WHERE job_id = ?", (job.job_id,)
        ).fetchone()
        if existing:
            self.database.finish_content_job(job.job_id, "completed", utc_now())
            existing_row = self.database.connection.execute(
                "SELECT * FROM content_packages WHERE content_id = ?", (existing["content_id"],)
            ).fetchone()
            return self._package(existing_row)
        try:
            package = pipeline.run(job)
            package.content_id = self.database.save_content_package(package)
            self.database.finish_content_job(job.job_id, "completed", utc_now())
            return package
        except Exception:
            self.database.finish_content_job(job.job_id, "failed", utc_now())
            raise
        finally:
            for phase, usage in getattr(pipeline, "last_usage_events", []):
                self.database.record_api_usage(
                    phase, job.job_id, usage.model, usage.input_tokens, usage.output_tokens,
                    usage.total_tokens, estimated_cost_usd(usage), utc_now(),
                )
