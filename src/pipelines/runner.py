"""Persisted ContentJob consumer for the single POC pipeline."""

import json

from common.models import ContentJob, utc_now
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

    def consume_next(self):
        jobs = self.database.pending_content_jobs(limit=1)
        if not jobs:
            return None
        row = jobs[0]
        if not self.database.claim_content_job(row["job_id"], utc_now()):
            return None
        job = self._job(row)
        try:
            pipeline = self.pipelines.get(job.pipeline_id)
            if pipeline is None:
                raise ValueError(f"No pipeline registered for {job.pipeline_id}")
            package = pipeline.run(job)
            package.content_id = self.database.save_content_package(package)
            self.database.finish_content_job(job.job_id, "completed", utc_now())
            return package
        except Exception:
            self.database.finish_content_job(job.job_id, "failed", utc_now())
            raise
