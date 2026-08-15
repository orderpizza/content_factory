"""Render a read-only operational dashboard from SQLite state."""

from html import escape


def render_dashboard(database) -> str:
    candidates = database.connection.execute("SELECT * FROM trend_candidates ORDER BY score DESC LIMIT 20").fetchall()
    health = database.connection.execute("SELECT * FROM source_health ORDER BY checked_at DESC LIMIT 20").fetchall()
    candidate_rows = "".join(
        f"<tr><td>{escape(row['lifecycle_stage'])}</td><td>{escape(row['topic'])}</td><td>{row['score']:.2f}</td><td>{escape(row['supporting_sources'])}</td></tr>"
        for row in candidates
    ) or "<tr><td colspan='4'>No candidates yet</td></tr>"
    health_rows = "".join(
        f"<tr><td>{escape(row['source'])}</td><td>{escape(row['checked_at'])}</td><td>{'OK' if row['success'] else 'FAILED'}</td><td>{escape(row['error'] or '')}</td></tr>"
        for row in health
    ) or "<tr><td colspan='4'>No source runs yet</td></tr>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><title>Content Factory Scout</title>
<style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:40px auto;color:#1f2933}} table{{border-collapse:collapse;width:100%;margin:12px 0 32px}}th,td{{border-bottom:1px solid #ddd;text-align:left;padding:10px}} h1{{margin-bottom:32px}}</style>
</head><body><h1>Content Factory Scout</h1><h2>Ranked Candidates</h2><table><tr><th>Stage</th><th>Topic</th><th>Score</th><th>Sources</th></tr>{candidate_rows}</table>
<h2>Source Health</h2><table><tr><th>Source</th><th>Checked</th><th>Status</th><th>Error</th></tr>{health_rows}</table></body></html>"""
