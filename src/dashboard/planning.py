"""Thread and decision read model for both planning entry paths."""
import json
import uuid
from .evidence import text, link, json_detail, render_storage_status


def render_threads(connection, *, limit=20, interactive=False, csrf_token='', thread_id=None, thread_page=1, revision_page=1, message_page=1):
    from .workflow import _hidden, _review_preview
    from .flow import render_job_progress
    limit = max(1, min(int(limit), 100))
    thread_page = max(1, min(int(thread_page), 10000))
    revision_page = max(1, min(int(revision_page), 10000))
    message_page = max(1, min(int(message_page), 10000))
    production = False
    parts = ["<section class='workflow card' id='threads'><h2>Ideas &amp; threads</h2>",
             '<p>Detection goes directly to Determination with frozen source evidence. Human ideas go through Intake first. Each selected domain produces one ContentJob.</p>']
    parts.append(render_storage_status(connection))

    if interactive:
        parts.append("<form method='post' action='/commands'><h3>Submit an idea</h3>"
                     f"{_hidden('csrf_token', csrf_token)}{_hidden('command_kind', 'new_idea')}{_hidden('command_id', str(uuid.uuid4()))}"
                     "<label>What should the content help someone understand or do?<textarea name='body' maxlength='8000' required></textarea></label>"
                     '<p>Do not include credentials or private personal information.</p><button>Submit idea</button></form>')
    if thread_id:
        rows = connection.execute('SELECT * FROM content_threads WHERE thread_id=?', (thread_id,)).fetchall()
        parts.append(link('← All threads') + '<p>Thread detail · historical revisions and messages are paginated.</p>')
    else:
        rows = connection.execute('SELECT * FROM content_threads ORDER BY updated_at DESC,thread_id DESC LIMIT ? OFFSET ?', (limit+1, (thread_page-1)*limit)).fetchall()
        parts.append('<nav class="pagination">')
        if thread_page > 1:
            parts.append(link('← Newer threads', thread_page=thread_page-1))
        if len(rows)>limit:
            parts.append(link('Older threads →', thread_page=thread_page+1))
        parts.append('</nav>')
        rows = rows[:limit]
    if not rows:
        parts.append('<p>No threads found. Submit an idea above or wait for a selected Opportunity.</p>')
    for thread in rows:
        tid = thread['thread_id']
        revisions = connection.execute('SELECT * FROM brief_revisions WHERE thread_id=? ORDER BY revision_number DESC LIMIT ? OFFSET ?', (tid, 2 if thread_id else 1, revision_page-1 if thread_id else 0)).fetchall()
        topic = json.loads(revisions[0]['brief_json']).get('topic', 'Untitled') if revisions else 'Awaiting Intake'
        parts.append(f"<article class='card' id='thread-{tid}'><h3>{link('Thread #' + str(tid) + ': ' + topic, thread_id=tid)}</h3>"
                     f"<p>{text(thread['origin'])} · {text(thread['status'])} · updated {text(thread['updated_at'])} · row version {thread['row_version']}</p>")
        candidate = connection.execute('SELECT trend_candidate_id FROM trend_candidates WHERE selected_thread_id=? LIMIT 1', (tid,)).fetchone()
        if candidate:
            parts.append(link('← Opportunity / Cluster and source evidence', cluster_id=candidate[0]))
        messages = connection.execute('SELECT * FROM thread_messages WHERE thread_id=? ORDER BY sequence_number DESC LIMIT 51 OFFSET ?', (tid, (message_page-1)*50 if thread_id else 0)).fetchall()
        parts.append('<h4>Conversation</h4><ol class="conversation">')
        for message in reversed(messages[:50]):
            parts.append(f"<li id='message-{message['message_id']}' value='{message['sequence_number']}'><b>{text(message['author_kind'])}</b> <small>{text(message['created_at'])}</small><p>{text(message['body'])}</p></li>")
        parts.append('</ol>')
        if len(messages)>50:
            parts.append(link('Older messages →', thread_id=tid, message_page=message_page+1))
        if thread_id and message_page>1:
            parts.append(link('← Newer messages', thread_id=tid, message_page=message_page-1))
        requests = connection.execute('SELECT * FROM intake_requests WHERE thread_id=? ORDER BY intake_request_id DESC LIMIT 20', (tid,)).fetchall()
        for req in requests:
            parts.append(f"<p><b>Intake #{req['intake_request_id']}: {text(req['status'])}</b> {text(req['failure_detail'] or '')}</p>")
        if requests:
            parts.append(json_detail('Intake attempts, leases and retry times (latest 20)', [dict(r) for r in requests], diagnostic=True))
        if interactive and thread['status']=='open':
            parts.append("<form method='post' action='/commands'><h4>Reply or refine this idea</h4>"
                         f"{_hidden('csrf_token',csrf_token)}{_hidden('command_kind','continue_thread')}{_hidden('command_id',str(uuid.uuid4()))}"
                         f"{_hidden('thread_id',tid)}{_hidden('row_version',thread['row_version'])}"
                         "<textarea name='body' maxlength='8000' required aria-label='Reply or refinement'></textarea><button>Send reply</button></form>")
        if not revisions:
            parts.append('<p>No brief yet. A pending request needs the Intake poller; awaiting clarification needs your reply.</p>')
        for revision in revisions[:1]:
            rid = revision['revision_id']
            brief = json.loads(revision['brief_json'])
            parts.append(f"<h4>Brief revision {revision['revision_number']} · #{rid}</h4><dl class='brief'>")
            for key in ('editorial_goal','topic','coverage_kind','canonical_target','revision_scope','audience','desired_outcome','source_context'):
                parts.append(f"<dt>{text(key.replace('_',' '))}</dt><dd>{text(brief.get(key))}</dd>")
            parts.append('</dl>' + json_detail('Brief constraints and open questions', {key: brief.get(key) for key in ('constraints','open_questions')}))
            parts.append(json_detail('Frozen conversation / source evidence', revision['source_snapshot_json']))
            request = connection.execute('SELECT * FROM determination_requests WHERE revision_id=?', (rid,)).fetchone()
            if request is None:
                parts.append('<p>Missing Determination handoff.</p>')
                continue
            parts.append(f"<h4>Determination #{request['determination_request_id']}: {text(request['status'])}</h4><p>{text(request['failure_reason'] or '')}</p>")
            parts.append(json_detail('Frozen Determination input and capability catalog', request['input_snapshot_json']))
            parts.append(json_detail('Determination claim / lease / retry', {k:v for k,v in dict(request).items() if k!='input_snapshot_json'}, diagnostic=True))
            decision = connection.execute('SELECT * FROM determination_decisions WHERE determination_request_id=?', (request['determination_request_id'],)).fetchone()
            if decision:
                parts.append(f"<p class='notice'><b>{text(decision['outcome'])}</b> · {text(decision['opportunity_value'])}</p><p>{text(decision['rationale'])}</p>")
                parts.append(json_detail('Decision warnings', decision['warnings_json']))
                routes = connection.execute('SELECT * FROM determination_routes WHERE determination_decision_id=? ORDER BY pipeline_id', (decision['determination_decision_id'],)).fetchall()
                parts.append('<h4>Three domain routes</h4><div class="route-grid">')
                for route in routes:
                    parts.append(f"<section class='route {text(route['disposition'])}'><h3>{text(route['pipeline_id'])} · {text(route['disposition'])}</h3><p><b>Fit:</b> {text(route['fit'])}</p><p>{text(route['reason'])}</p>")
                    if route['angle_json']:
                        angle = json.loads(route['angle_json'])
                        parts.append('<dl>' + ''.join(f'<dt>{text(k.replace("_"," "))}</dt><dd>{text(v)}</dd>' for k,v in angle.items()) + '</dl>')
                    parts.append(json_detail('Output bindings and reasons', route['output_assessments_json']))
                    job = connection.execute('SELECT * FROM content_jobs WHERE determination_route_id=?', (route['determination_route_id'],)).fetchone()
                    if job:
                        jid=job['content_job_id']
                        generation = connection.execute('SELECT * FROM generation_runs WHERE content_job_id=? ORDER BY run_number DESC LIMIT 1', (jid,)).fetchone()
                        parts.append(f"<h4 id='job-{jid}'>ContentJob #{jid}</h4><p>Generation: {text(generation['status'] if generation else 'missing run')} · planning-only stops here.</p>")
                        parts.append(json_detail('Immutable job recipe',job['recipe_json']) + json_detail('Output plan',job['output_plan_json']))
                        if generation:
                            parts.append(json_detail('Latest generation attempt',dict(generation),diagnostic=True))
                        parts.append(render_job_progress(connection, jid))
                        reviews = connection.execute('SELECT v.review_request_id FROM review_requests v JOIN content_packages p ON p.content_package_id=v.content_package_id JOIN output_requests o ON o.output_request_id=p.output_request_id JOIN canonical_contents c ON c.canonical_content_id=o.canonical_content_id WHERE c.content_job_id=? ORDER BY v.review_request_id DESC LIMIT 20',(jid,)).fetchall()
                        for review in reviews:
                            parts.append(_review_preview(connection,review[0],interactive=interactive,csrf_token=csrf_token,production=production))
                    else:
                        parts.append('<p>No ContentJob for this route.</p>')
                    parts.append('</section>')
                parts.append('</div>')
        invocations = connection.execute("SELECT * FROM model_invocations WHERE (entity_type='intake_request' AND entity_id IN (SELECT intake_request_id FROM intake_requests WHERE thread_id=?)) OR (entity_type='determination_request' AND entity_id IN (SELECT determination_request_id FROM determination_requests WHERE revision_id IN (SELECT revision_id FROM brief_revisions WHERE thread_id=?))) ORDER BY model_invocation_id DESC LIMIT 30", (tid,tid)).fetchall()
        if invocations:
            parts.append('<h4>Gemini activity (latest 30)</h4><ul>')
            for inv in invocations:
                parts.append(f"<li>{text(inv['phase'])} · {text(inv['model_id'])} · {text(inv['outcome'])} · tokens {text(inv['total_tokens'])} · estimated USD {inv['estimated_cost_micro_usd']/1000000:.6f} · {text(inv['safe_error'] or '')}</li>")
            parts.append('</ul>')
        if thread_id and len(revisions)>1:
            parts.append(link('Older brief revision →', thread_id=tid, revision_page=revision_page+1))
        if thread_id and revision_page>1:
            parts.append(link('← Newer brief revision', thread_id=tid, revision_page=revision_page-1))
        parts.append('</article>')
    return ''.join(parts) + '</section>'
