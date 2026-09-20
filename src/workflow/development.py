"""Explicit, non-deliverable development catalog configuration."""
from pathlib import Path
from .store import WORKFLOW_PIPELINES


def configure_development_catalog(store):
    for pipeline in WORKFLOW_PIPELINES:
        store.register_capability(pipeline, enabled=True, generation_ready=True, outputs=[
            {"platform": platform, "account": f"fixture_{pipeline}",
             "content_format": content_format, "ready": True,
             "safe_reason": "development planning only; no delivery authorization"}
            for platform, content_format in (("instagram", "instagram_static_carousel_v2"), ("x", "x_static_post_v1"))
        ])


def prepare_development_database(path, *, include_youtube=False):
    from database.current import initialize_database
    from detection.configuration import load_manifest
    from detection.store import DetectionStore
    from .store import WorkflowStore
    from .maintenance import StorageMonitor
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create prevents an accidental reset, including an empty file.
    with path.open("xb"):
        pass
    initialize_database(path)
    root = Path(__file__).resolve().parents[2]
    manifest = load_manifest(root / "config/releases/detection.json")
    manifest["release_name"] = "development-detection-youtube" if include_youtube else "development-detection"
    for source in manifest["components"]["detection"]["sources"]:
        if source["source_kind"] == "youtube_most_popular_v1":
            source["enabled"] = include_youtube
    with DetectionStore(path) as store:
        store.apply_manifest(manifest)
    with WorkflowStore(path) as store:
        configure_development_catalog(store)
        StorageMonitor(store, root / "data/artifacts", root / "data/backups").run_once()
    return path
