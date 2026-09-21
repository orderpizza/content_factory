"""Four bounded planning views over persisted lineage, not inferred title joins."""
import json
from urllib.parse import urlencode
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
                       stage='clusters', query='', source='', status='', raw_page=1,
                       cluster_page=1, opportunity_page=1, job_page=1,
                       cluster_sort='score_desc', page_count=1):
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
    filters={k:v for k,v in dict(view='detection',stage=stage,q=query,source=source,status=status,
                                raw_page=raw_page,cluster_page=cluster_page,opportunity_page=opportunity_page,
                                job_page=job_page,cluster_sort=cluster_sort).items() if v}
    labels=(('raw','Raw Feed Items',raw_count),('clusters','Clusters',cluster_count),
            ('opportunities','Opportunities',count),('jobs','ContentJobs',job_count))
    parts=["<nav class='stage-tabs' aria-label='Pipeline stages'>" + ''.join(
        f"<a class='{'active' if key == stage else ''}' href='/?{text(urlencode({**filters,'stage':key}))}'>{label}<b>{total}</b></a>"
        for key,label,total in labels) + "</nav>", "<section class='flow-stage active-stage'>"]
    def pager(current, key, total, page_size=50):
        pages=max(1,(total+page_size-1)//page_size)
        links=[]
        if current>1: links.append(link('← Previous', **{**filters,key:current-1}))
        links.append(f'<span>Page {current} of {pages}</span>')
        if current<pages: links.append(link('Next →', **{**filters,key:current+1}))
        return '<nav class="pagination">'+''.join(links)+'</nav>'
    if stage == 'raw':
        parts.append("<h2>Raw Feed Items</h2><table class='stage-table'><thead><tr><th>ID</th><th>Title</th><th>Source</th><th>Collected</th><th>Activity</th><th>Rank</th><th>Cluster(s)</th></tr></thead><tbody>")
        for item in observations:
            memberships=connection.execute('SELECT c.trend_candidate_id FROM candidate_observation_memberships m JOIN trend_candidates c ON c.trend_candidate_id=m.trend_candidate_id WHERE m.trend_observation_id=? GROUP BY c.trend_candidate_id ORDER BY MAX(m.topic_snapshot_id) DESC LIMIT 3',(item['trend_observation_id'],)).fetchall()
            clusters=' · '.join(link('#'+str(m['trend_candidate_id']),cluster_id=m['trend_candidate_id']) for m in memberships) or '—'
            parts.append(f"<tr id='raw-item-{item['trend_observation_id']}'><td>{link('#'+str(item['trend_observation_id']),raw_item_id=item['trend_observation_id'])}</td><td class='truncate'>{public_link(item['title'],item['canonical_url'])}</td><td>{text(item['provider_name'])}</td><td>{text(item['collected_at'])}</td><td>{item['activity']:.3f}</td><td>{text(item['rank'])}</td><td>{clusters}</td></tr>")
        if not observations: parts.append("<tr><td colspan='7' class='empty'>No Raw Feed Items match.</td></tr>")
        parts.append('</tbody></table>'+pager(raw_page,'raw_page',raw_count))
    elif stage == 'clusters':
        parts.append("<div class='stage-head'><h2>Clusters</h2><form method='get'><input type='hidden' name='stage' value='clusters'>" + ''.join(f"<input type='hidden' name='{text(k)}' value='{text(v)}'>" for k,v in filters.items() if k not in {'stage','cluster_sort','cluster_page'}) + "<label>Sort <select name='cluster_sort'><option value='score_desc'"+(' selected' if cluster_sort=='score_desc' else '')+">Score: High → Low</option><option value='recent'"+(' selected' if cluster_sort=='recent' else '')+">Newest / Recently evaluated</option></select></label><button>Apply</button></form></div><table class='stage-table'><thead><tr><th>ID</th><th>Subject</th><th>Score</th><th>Selection</th><th>Reason</th><th>Evaluated</th><th>Opportunity</th></tr></thead><tbody>")
        for cluster in clusters:
            opportunity=link('Open',thread_id=cluster['selected_thread_id']) if cluster['selected_thread_id'] else '—'
            parts.append(f"<tr id='cluster-row-{cluster['trend_candidate_id']}'><td>{link('#'+str(cluster['trend_candidate_id']),cluster_id=cluster['trend_candidate_id'])}</td><td class='truncate'>{text(cluster['canonical_subject'])}</td><td>{cluster['score']:.4f}</td><td>{text(cluster['eligibility_status'])}</td><td class='truncate'>{text(cluster['eligibility_reason'])}</td><td>{text(cluster['snapshot_at'])}</td><td>{opportunity}</td></tr>")
        if not clusters: parts.append("<tr><td colspan='7' class='empty'>No Clusters match.</td></tr>")
        parts.append('</tbody></table>'+pager(cluster_page,'cluster_page',cluster_count))
    elif stage == 'opportunities':
        parts.append("<h2>Opportunities</h2><table class='stage-table'><thead><tr><th>Cluster</th><th>Subject</th><th>Selected</th><th>Determination</th><th>Outcome</th></tr></thead><tbody>")
        for opportunity in opportunities:
            decision=connection.execute('SELECT outcome FROM determination_decisions WHERE determination_request_id=?',(opportunity['determination_request_id'],)).fetchone()
            parts.append(f"<tr id='opportunity-{opportunity['trend_candidate_id']}'><td>{link('#'+str(opportunity['trend_candidate_id']),cluster_id=opportunity['trend_candidate_id'])}</td><td class='truncate'>{link(opportunity['canonical_subject'],thread_id=opportunity['thread_id'])}</td><td>{text(opportunity['selected_at'])}</td><td>{text(opportunity['status'])}</td><td>{text(decision['outcome'] if decision else 'pending')}</td></tr>")
        if not opportunities: parts.append("<tr><td colspan='5' class='empty'>No Opportunities match.</td></tr>")
        parts.append('</tbody></table>'+pager(opportunity_page,'opportunity_page',count,20))
    else:
        parts.append("<h2>ContentJobs</h2><table class='stage-table'><thead><tr><th>Job</th><th>Pipeline</th><th>Origin</th><th>Angle / Target</th><th>Generation</th></tr></thead><tbody>")
        for job in jobs:
            angle=json.loads(job['angle_json'] or '{}'); origin=('Opportunity #'+str(job['seed_candidate_id'])) if job['origin']=='trend' else 'Human thread #'+str(job['thread_id'])
            parts.append(f"<tr id='contentjob-{job['content_job_id']}'><td>{link('#'+str(job['content_job_id']),job_id=job['content_job_id'])}</td><td>{text(job['pipeline_id'])}</td><td>{link(origin,thread_id=job['thread_id'])}</td><td class='truncate'>{text(angle.get('angle_kind',''))} · {text(angle.get('canonical_target',''))}</td><td>{text(job['generation_status'] or 'missing')}</td></tr>")
        if not jobs: parts.append("<tr><td colspan='5' class='empty'>No ContentJobs match.</td></tr>")
        parts.append('</tbody></table>'+pager(job_page,'job_page',job_count,20))
    return ''.join(parts)+'</section>'


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
