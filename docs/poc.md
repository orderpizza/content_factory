# Content Factory POC

## Objective

Prove that the system can automatically discover something interesting, decide
what content to create from it, execute a predefined content workflow, render a
visual asset, queue or publish the result, and preserve publication history.

The POC must demonstrate this flow:

```text
Trend Detection
  -> Trend Candidate
  -> Determination
  -> ContentJob
  -> One Content Pipeline
  -> Content Package
  -> Visual Rendering
  -> Post Queue
  -> Posting Agent
  -> Published Content
  -> Publication Record
```

## Scope

- One trend detection implementation.
- A small number of trend sources.
- One determination process.
- One real content pipeline: `poc_pipeline`.
- One deterministic visual template.
- One primary font/theme configuration.
- One posting platform initially.
- SQLite database.
- Mac Mini as the primary runtime.
- Gemini API for determination and content generation where useful.

## Success Criteria

The POC succeeds when the system can complete the loop with minimal or no manual
intervention:

1. A trend appears.
2. The system detects and stores it.
3. Gemini evaluates whether content should be created.
4. A `ContentJob` is stored.
5. The POC pipeline executes.
6. A `ContentPackage` is generated.
7. A visual asset is rendered.
8. The content is queued for posting.
9. The posting agent publishes or schedules it.
10. A publication record is stored.

The system must also be able to explain afterward:

- Which trend triggered the content.
- Which `ContentJob` was created.
- Which pipeline ran.
- What content was generated.
- When it was queued.
- When it was published.
- What external platform post ID was recorded, if any.

## Out Of Scope

- Multiple content pipelines.
- Sophisticated trend intelligence.
- Advanced trend prediction.
- Complex machine-learning trend models.
- Generic plugin architecture.
- Complex agent-to-agent architecture.
- Dynamic workflow generation.
- Kafka, RabbitMQ, Redis, Celery, or other distributed queues.
- Kubernetes.
- Cloud databases.
- Cloud workers.
- Large-scale vector databases.
- AI image generation for every asset.
- Visual template libraries.
- Multi-platform publishing.
- Multi-account publishing.
- Advanced posting optimization.
- Automatic model routing.
- Fine-tuning or custom model training.

## Development Order

1. Repository structure, configuration, and SQLite.
2. Trend collector/detector.
3. Trend to determination.
4. `ContentJob` persistence.
5. One POC pipeline.
6. Visual renderer.
7. Posting queue.
8. Posting agent.
9. End-to-end autonomous test.
10. Observe failures and improve.
