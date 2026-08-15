# Content Factory — Vision

## 1. Long-Term Goal

Build a local-first, AI-native content factory that can continuously discover
interesting topics, determine content opportunities, produce content through
specialized pipelines, and automatically publish and manage that content.

The system should eventually support multiple independent content businesses
and content formats while sharing the same underlying intelligence,
orchestration, visual, and publishing infrastructure.

---

## 2. Core Concept

The fundamental loop is:

Trend
→ Content Opportunity
→ Pipeline
→ Content
→ Visual
→ Publication

The system should separate the question:

> "What should we create?"

from:

> "How should we create it?"

The intelligence layer determines the former.

A predefined content pipeline determines the latter.

---

## 3. Long-Term Architecture

The eventual system is conceptually composed of:

### Trend Intelligence

Continuously monitors external signals and identifies emerging,
persistent, or otherwise valuable trends.

### Determination

Interprets detected trends and determines:

- whether the trend is worth pursuing
- what content opportunity exists
- which pipeline should be used
- what angle should be taken
- who the target audience is

### Content Pipelines

Specialized, predefined workflows for producing particular types of content.

Examples may eventually include:

- English education
- AI news
- Finance
- Stock analysis
- Business
- Book summaries
- Psychology
- Wealth/entrepreneurship

### Visual System

Provides standardized, reusable visual rendering.

Not every piece of content requires AI image generation.
Simple content should be rendered deterministically using templates,
typography, CSS, and other reusable visual components.

### Posting Agent

Separates content creation from distribution.

It manages:

- publication scheduling
- duplicate prevention
- posting frequency
- publication history
- platform/account state
- publishing failures

---

## 4. Local-First Philosophy

The Mac Mini is intended to be the primary runtime for the system.

Cloud services should be used selectively where they provide meaningful
value, rather than moving the entire system into the cloud.

During the initial development phase, available GCP credits are intended
primarily for Vertex AI Gemini API calls.

The architecture should therefore favor:

- local computation
- local storage
- local scheduling
- local rendering
- lightweight external APIs
- selective LLM API usage

---

## 5. AI-Native Direction

The long-term system should become increasingly AI-native.

However, AI should not be used simply because it is available.

Deterministic operations should remain deterministic when they are cheaper,
faster, and more reliable.

Examples:

- trend statistics
- scheduling
- duplicate detection
- database operations
- template rendering
- image composition

LLMs should be used where reasoning, interpretation, generation, or
semantic understanding provides meaningful value.

For the current POC, trend detection is intentionally LLM-free. A local Scout
collects and measures external signals continuously. The downstream
determination layer may use Gemini after the detection output has been observed
and tuned.

The business goal is monetized content. Detection measures attention and
evidence; determination later evaluates content opportunity, audience, angle,
pipeline, and possible monetization paths. A popular topic is not automatically
a valuable business opportunity.

---

## 6. Scalability of the Concept

The system should eventually be able to support many content pipelines
without rebuilding the core infrastructure for each new content business.

A new pipeline should primarily define:

> what this pipeline produces and how it produces it.

The shared infrastructure should handle:

- trend intelligence
- content opportunity determination
- job management
- visual rendering infrastructure
- publishing
- publication history

---

## 7. POC vs. Long-Term Vision

The current repository is a Proof of Concept.

The POC intentionally implements only a small subset of the long-term vision.

The POC exists to validate the fundamental loop before investing in
generalization and scale.

Do not interpret the long-term architecture as a requirement to implement
all of it now.
