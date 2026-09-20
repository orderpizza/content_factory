"""Four bounded planning views over persisted lineage, not inferred title joins."""
import json
from .evidence import text, link, public_link, json_detail


CLUSTER_STATES = {
    'observed': 'Scored; one or more Detection Selection gates not met.',
    'eligible': 'Evidence gates met; Selection has not committed a handoff.',
    'deferred_by_budget': 'Evidence gates met; waiting for Selection capacity.',
    'selected': 'Selected; inspect the persisted Opportunity handoff.',
}

# A selected label alone is insufficient: require the initial system brief and request.
OPPORTUNITY_FROM = """ FROM trend_candidates c
 JOIN content_threads t ON t.thread_id=c.selected_thread_id AND t.seed_candidate_id=c.trend_candidate_id AND t.origin='trend'
 JOIN brief_revisions b ON b.thread_id=t.thread_id AND b.revision_number=1 AND b.created_by='system'
 JOIN determination_requests d ON d.revision_id=b.revision_id
 WHERE c.selected_at IS NOT NULL """


def _pager(count, page, key, filters):
    pages=max(1,(count+19)//20)
    return ('<nav class="pagination">' +
            (link('← Newer', **{**filters,key:page-1}) if page>1 else '') +
            f'<span>Page {page} of {pages}</span>' +
            (link('Older →', **{**filters,key:page+1}) if page<pages else '') + '</nav>')


def render_progression(connection, observations, clusters, *, raw_count, cluster_count,
                       pagination, query='', source='', status='', page=1,
                       opportunity_page=1, job_page=1):
    pattern='%' + query.casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
    opportunity_where = " AND (?='' OR lower(c.canonical_subject) LIKE ? ESCAPE '\\') AND (?='' OR EXISTS (SELECT 1 FROM candidate_observation_memberships m JOIN trend_observations o ON o.trend_observation_id=m.trend_observation_id JOIN detection_source_instances s ON s.detection_source_instance_id=o.source_instance_id WHERE m.trend_candidate_id=c.trend_candidate_id AND s.stable_id=?))"
    args=(query,pattern,source,source)
    count=connection.execute('SELECT COUNT(*)'+OPPORTUNITY_FROM+opportunity_where,args).fetchone()[0]
    opportunity_page=max(1,min(int(opportunity_page),max(1,(count+19)//20)))
    opportunities=connection.execute('SELECT c.trend_candidate_id,c.canonical_subject,c.selected_at,t.thread_id,d.determination_request_id,d.status'+OPPORTUNITY_FROM+opportunity_where+' ORDER BY c.selected_at DESC,c.trend_candidate_id DESC LIMIT 20 OFFSET ?',(*args,(opportunity_page-1)*20)).fetchall()
    job_from=""" FROM content_jobs j JOIN brief_revisions b ON b.revision_id=j.brief_revision_id
       JOIN content_threads t ON t.thread_id=b.thread_id
       JOIN determination_routes r ON r.determination_route_id=j.determination_route_id
       LEFT JOIN generation_runs g ON g.generation_run_id=(SELECT generation_run_id FROM generation_runs WHERE content_job_id=j.content_job_id ORDER BY run_number DESC LIMIT 1)
       WHERE (?='' OR lower(j.pipeline_id || ' ' || b.brief_json || ' ' || r.angle_json) LIKE ? ESCAPE '\\')
       AND (?='' OR EXISTS (SELECT 1 FROM candidate_observation_memberships m JOIN trend_observations o ON o.trend_observation_id=m.trend_observation_id JOIN detection_source_instances s ON s.detection_source_instance_id=o.source_instance_id WHERE m.trend_candidate_id=t.seed_candidate_id AND s.stable_id=?)) """
    job_count=connection.execute('SELECT COUNT(*)'+job_from,args).fetchone()[0]
    job_page=max(1,min(int(job_page),max(1,(job_count+19)//20)))
    jobs=connection.execute('SELECT j.content_job_id,j.pipeline_id,j.brief_revision_id,r.angle_json,t.thread_id,t.origin,t.seed_candidate_id,g.status generation_status'+job_from+' ORDER BY j.content_job_id DESC LIMIT 20 OFFSET ?',(*args,(job_page-1)*20)).fetchall()
    filters={k:v for k,v in dict(view='detection',q=query,source=source,status=status,page=page,
                                opportunity_page=opportunity_page,job_page=job_page).items() if v}
    parts=["<p class='notice'>Raw Feed Items → Clusters → Opportunities → ContentJobs. Human ideas enter via Intake and join at Determination.</p>",
           "<p class='hint'>Search and Source apply across views; Cluster Selection state filters only Clusters. Raw items and Clusters use the active Detection release; Opportunities and ContentJobs retain all persisted handoffs.</p>",
           "<div class='flow-columns'>", "<section class='flow-stage' id='raw-items'><h2>Raw Feed Items</h2>",
           f'<p>{raw_count} observation(s). Repeated measurements are separate items, not new sources.</p>']
    for item in observations:
        oid=item['trend_observation_id']
        memberships=connection.execute('SELECT c.trend_candidate_id,c.canonical_subject FROM candidate_observation_memberships m JOIN trend_candidates c ON c.trend_candidate_id=m.trend_candidate_id WHERE m.trend_observation_id=? GROUP BY c.trend_candidate_id ORDER BY MAX(m.topic_snapshot_id) DESC LIMIT 3',(oid,)).fetchall()
        parts.append(f"<article class='flow-record' id='raw-item-{oid}'><h3>{link('Item #'+str(oid),raw_item_id=oid)}</h3><p>{public_link(item['title'],item['canonical_url'])}</p><p>{text(item['provider_name'])} · {text(item['collected_at'])}</p><p>Provider rank: {text(item['rank'])} · Source activity: {item['activity']:.3f}" + (' (HN provider vote score)' if item['source_kind']=='hacker_news_top_stories_v1' else '') + '</p>')
        parts.append('<p>Clusters: ' + (' · '.join(link('#'+str(m['trend_candidate_id']),cluster_id=m['trend_candidate_id']) for m in memberships) or 'no persisted scored membership') + '</p></article>')
    if not observations:
        parts.append('<p>No Raw Feed Items match.</p>')
    parts.append(pagination + "</section><section class='flow-stage' id='clusters'><h2>Clusters</h2>" + f'<p>{cluster_count} scored clusters. Status belongs to Detection Selection, not a source or item.</p>')
    for cluster in clusters:
        cid=cluster['trend_candidate_id']; state=cluster['eligibility_status']
        explanation=CLUSTER_STATES.get(state,'Stored schema state; no current Scout transition writes this value.')
        parts.append(f"<article class='flow-record' id='cluster-row-{cid}'><h3>{link('Cluster #'+str(cid),cluster_id=cid)}</h3><p>{text(cluster['canonical_subject'])}</p><p>Detection attention score: <b>{cluster['score']:.4f}</b></p><p><b>{text(state)}</b> — {text(explanation)}</p><p>{text(cluster['eligibility_reason'])}</p><p>Evaluated {text(cluster['snapshot_at'])}</p>")
        if cluster['selected_thread_id']:
            parts.append(link('Inspect Opportunity handoff',thread_id=cluster['selected_thread_id']))
        parts.append('</article>')
    if not clusters:
        parts.append('<p>No Clusters match.</p>')
    parts.append(pagination + "</section><section class='flow-stage' id='opportunities'><h2>Opportunities</h2>"+f'<p>{count} selected Clusters with persisted Determination handoffs. Selection does not guarantee a ContentJob.</p>')
    for opportunity in opportunities:
        cid=opportunity['trend_candidate_id']; tid=opportunity['thread_id']
        decision=connection.execute('SELECT outcome FROM determination_decisions WHERE determination_request_id=?',(opportunity['determination_request_id'],)).fetchone()
        parts.append(f"<article class='flow-record' id='opportunity-{cid}'><h3>{link('Opportunity #'+str(cid),thread_id=tid)}</h3><p>{text(opportunity['canonical_subject'])}</p><p>{link('Cluster #'+str(cid),cluster_id=cid)} · selected {text(opportunity['selected_at'])}</p><p>Initial Determination #{opportunity['determination_request_id']}: {text(opportunity['status'])} · {text(decision['outcome'] if decision else 'no decision yet')}</p>{link('Decisions, routes and jobs →',thread_id=tid)}</article>")
    if not opportunities:
        parts.append('<p>No Opportunities match. A high score alone does not create one.</p>')
    parts.append(_pager(count,opportunity_page,'opportunity_page',filters)+"</section><section class='flow-stage' id='contentjobs'><h2>ContentJobs</h2>"+f'<p>{job_count} jobs. Status is the latest GenerationRun, not publication status; planning-only leaves it pending.</p>')
    for job in jobs:
        jid=job['content_job_id']; angle=json.loads(job['angle_json'] or '{}')
        origin=('Opportunity #'+str(job['seed_candidate_id'])) if job['origin']=='trend' else 'Human thread #'+str(job['thread_id'])
        parts.append(f"<article class='flow-record' id='contentjob-{jid}'><h3>{link('ContentJob #'+str(jid),job_id=jid)}</h3><p><b>{text(job['pipeline_id'])}</b> · {text(job['generation_status'] or 'missing GenerationRun')}</p><p>{text(angle.get('thesis',''))}</p><p>Angle: {text(angle.get('angle_kind'))} · {text(angle.get('canonical_target'))}</p><p>From {link(origin,thread_id=job['thread_id'])} · brief #{job['brief_revision_id']}</p></article>")
    if not jobs:
        parts.append('<p>No ContentJobs match. A skipped or blocked route creates no job.</p>')
    parts.append(_pager(job_count,job_page,'job_page',filters)+'</section></div>')
    return ''.join(parts)


def render_raw_item(connection, item_id):
    row=connection.execute('SELECT o.*,s.provider_name,a.status collection_status FROM trend_observations o JOIN detection_source_instances s ON s.detection_source_instance_id=o.source_instance_id JOIN source_collection_attempts a ON a.source_collection_attempt_id=o.source_collection_attempt_id WHERE o.trend_observation_id=?',(item_id,)).fetchone()
    if row is None:
        return '<section class="card"><h2>Raw Feed Item not found</h2></section>'
    members=connection.execute('SELECT m.trend_candidate_id,m.topic_snapshot_id,m.contribution,s.created_at FROM candidate_observation_memberships m JOIN topic_snapshots s ON s.topic_snapshot_id=m.topic_snapshot_id WHERE m.trend_observation_id=? ORDER BY m.topic_snapshot_id DESC LIMIT 50',(item_id,)).fetchall()
    parts=[f"<section class='card' id='raw-item-detail'><h2>Raw Feed Item #{item_id}</h2><p>{public_link(row['title'],row['canonical_url'])}</p><p>Source / Feed: {text(row['provider_name'])} · Collection attempt #{row['source_collection_attempt_id']}: {text(row['collection_status'])}</p><h3>Cluster membership across evaluations (latest 50)</h3><ul>"]
    for m in members:
        parts.append(f"<li>{link('Cluster #'+str(m['trend_candidate_id']),cluster_id=m['trend_candidate_id'])} · snapshot #{m['topic_snapshot_id']} · {text(m['created_at'])} · scoring contribution {m['contribution']}</li>")
    if not members:
        parts.append('<li>No scored Cluster membership yet.</li>')
    return ''.join(parts)+'</ul>'+json_detail('Normalized item evidence',dict(row))+'</section>'


def render_job(connection, job_id):
    row=connection.execute('SELECT j.*,b.thread_id,t.origin,t.seed_candidate_id FROM content_jobs j JOIN brief_revisions b ON b.revision_id=j.brief_revision_id JOIN content_threads t ON t.thread_id=b.thread_id WHERE j.content_job_id=?',(job_id,)).fetchone()
    if row is None:
        return '<section class="card"><h2>ContentJob not found</h2></section>'
    run=connection.execute('SELECT * FROM generation_runs WHERE content_job_id=? ORDER BY run_number DESC LIMIT 1',(job_id,)).fetchone()
    origin=f"Opportunity #{row['seed_candidate_id']}" if row['origin']=='trend' else f"Human thread #{row['thread_id']}"
    return (f"<section class='card' id='job-detail'><h2>ContentJob #{job_id}</h2><p>{text(row['pipeline_id'])} · latest generation: {text(run['status'] if run else 'missing')}</p><p>From {link(origin,thread_id=row['thread_id'])} · immutable brief #{row['brief_revision_id']}</p>"+
            json_detail('Immutable job recipe',row['recipe_json'])+json_detail('Output plan',row['output_plan_json'])+'</section>')
