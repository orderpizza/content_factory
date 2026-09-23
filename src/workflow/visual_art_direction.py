"""Archetype directions and the isolated accepted English prompt compatibility brief."""
EXPRESSION_BREAKDOWN_BRIEF = """Archetype: expression_breakdown_v1

Semantic sequence:
1. Hook
2. Meaning / definition
3. When to use it / use cases
4. Examples
5. Short conversation / dialogue
6. Takeaway / reminder
"""

EXPRESSION_ROLE_DIRECTIONS = (
    "Make the expression the dominant focal point with a bold, educational cover composition.",
    "Use a clear definition structure and one supporting visual metaphor or illustration.",
    "Make the situations highly scannable and organized with obvious visual grouping.",
    "Clearly separate the examples so each reads as a distinct practical use.",
    "Use a clear conversation layout with strong speaker separation.",
    "Make this a clean, memorable closing summary with an obvious recap hierarchy.",
)

# Frozen prompt wording for expression_breakdown_v1 only, never account identity.
EXPRESSION_BREAKDOWN_ACCEPTED_DESIGNER_BRIEF_V1 = """Act as a senior educational editorial designer and social-media art director.

Design one complete six-slide Instagram educational carousel as a single 3×2 storyboard
image. The six clearly separated panels represent individual 4:5 portrait Instagram slides,
arranged left-to-right, top-to-bottom. The complete storyboard must use a 5:4 aspect ratio.

The most important goal is instructional clarity; visual delight comes second. Each slide must
be immediately understandable at a glance, with one clear headline, one obvious reading order,
strong separation between title, explanation, examples, and supporting visuals, generous
breathing room, easy-to-read body text, and visual elements that reinforce the lesson rather
than compete with it.

Create a premium human-designed educational carousel: modern, polished, colorful, friendly,
editorial, and visually memorable. Use strong typography hierarchy, bold but controlled color,
clean cards or grouped content when useful, simple icons and illustrations that directly support
meaning, marker highlights, underlines, small decorative accents, or character illustrations
when useful, clear visual grouping, intentional whitespace, and varied slide compositions within
one overall design language.

Do not make it look like a poster collage, scrapbook, art print, dense infographic, PowerPoint
presentation, worksheet, or corporate dashboard. Avoid decorative elements overlapping text,
oversized illustrations dominating the lesson, excessive stickers, doodles, shapes, or accents,
text floating without clear grouping, cramped layouts, repeated identical compositions, visual
noise, washed-out pastel blobs, and thin line-art-only scenes. The learner should know where to
look first, second, and third on every slide.

The six slides must share visual language, compatible colors, typography character, illustration
style, and polish, but each must use the composition that best teaches its content. Keep every
panel visually self-contained and clearly separated from neighboring panels.
"""

AI_TECH_ROLE_DIRECTIONS = (
    "Use a strong headline and one clear visual idea; make the central change or topic immediately identifiable.",
    "Explain the actual feature, development or concept with structured cards or a simple annotated conceptual visual.",
    "Show a clear mechanism, flow, relationship or before/after structure; avoid unnecessary technical decoration.",
    "Show concrete use contexts; visually separate examples and do not imply fictional interfaces are real evidence.",
    "Give limitations / caveats equal visual prominence. Make constraints, availability, uncertainty and tradeoffs easy to read; avoid alarmist red-warning aesthetics unless the content warrants them.",
    "Use clean summary hierarchy, one memorable conclusion and minimal visual clutter.",
)

PSYCHOLOGY_ROLE_DIRECTIONS = (
    "Show a recognizable human situation or observed pattern without implying diagnosis.",
    "Explain the concept or interpretation clearly; distinguish an interpretation from the observation.",
    "Show a possible mechanism as explanatory and qualified, not absolute; keep uncertainty visible in the hierarchy.",
    "Show a relatable everyday scenario; distinguish hypothetical examples from factual evidence without inventing labels or text.",
    "Use practical-response cards for usable, non-clinical guidance; do not turn education into medical advice.",
    "Summarize the practical lesson while preserving qualification or alternative explanations; never erase earlier nuance.",
)
