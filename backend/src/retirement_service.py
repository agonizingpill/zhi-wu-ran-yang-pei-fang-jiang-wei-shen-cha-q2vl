import math
from datetime import datetime
from sqlalchemy import select
from fastapi import HTTPException
from .models import DyeRecipe,Swatch,Trial
from .production_models import DyeBatch
from .retirement_models import RetirementBatch,RetirementItem,SwatchRetirement
from .atlas import project,METHOD
from .recipe_service import log

DEFAULT_THRESHOLD=.005
SAMPLE_FIELDS=('lot','spectrum','l','a','b','recipe_id')

def spectral_rms(a,b):
    return math.sqrt(sum((float(x)-float(y))**2 for x,y in zip(a,b))/len(a))

def pca_distance(a,b):
    return math.hypot(a[0]-b[0],a[1]-b[1])

def reading(swatch):
    """Immutable snapshot of the original instrument reading, kept as evidence."""
    return {k:getattr(swatch,k) for k in SAMPLE_FIELDS}

def _referenced_swatch_ids(db):
    refs={}
    for trial in db.scalars(select(Trial).order_by(Trial.id)):
        for key,label in (('reference_swatch_id','目标样'),('candidate_swatch_id','候选样')):
            sid=getattr(trial,key)
            refs.setdefault(sid,[]).append(f'复染试验 #{trial.id}（{label}）')
    for batch in db.scalars(select(DyeBatch).order_by(DyeBatch.id)):
        lot=(batch.target_snapshot or {}).get('lot')
        if lot:
            swatch=db.scalar(select(Swatch).where(Swatch.lot==lot))
            if swatch:refs.setdefault(swatch.id,[]).append(f'生产缸 {batch.code} 目标色快照')
    return refs

def _retired_ids(db):
    return set(db.scalars(select(SwatchRetirement.swatch_id)))

def _reserved_ids(db,exclude_batch_id=None):
    """Swatches that must stay in the cabinet although they are not retired themselves.

    Returns (committed, pending): swatches already serving as a keeper for a confirmed
    retirement, and swatches claimed by another still-pending proposal (its candidates
    and substitutes). Both sets are never retired: a swatch that replaced another one
    stays; two live proposals must not plan around the same swatches. Re-checking a
    batch excludes that batch's own rows from the pending set.
    """
    committed=set(db.scalars(select(SwatchRetirement.substitute_swatch_id)))
    pending=set()
    rows=db.execute(select(RetirementItem.substitute_swatch_id,RetirementItem.swatch_id,RetirementItem.batch_id)
                     .join(RetirementBatch,RetirementBatch.id==RetirementItem.batch_id)
                     .where(RetirementBatch.state=='proposed')).all()
    for sub_id,candidate_id,batch_id in rows:
        if batch_id!=exclude_batch_id:pending.update((sub_id,candidate_id))
    return committed,pending

def select_candidates(pool,eligible,threshold,coords):
    """Pick the retire set so every retired swatch keeps a substitute in the cabinet.

    Greatest fixed point over the *eligible* swatches: a swatch stays a candidate only
    while it has at least one neighbour outside the candidate set, within the raw
    spectrum threshold. Pairs that could only substitute each other are therefore
    both kept, which guarantees every proposed retirement still has a surviving
    same-recipe sample after processing.

    `pool` must contain only swatches physically in the cabinet (retired swatches are
    gone, so they can never serve as a substitute). Swatches that are in the pool but
    not eligible (referenced by a trial / production target, or reserved by another
    live proposal) are never retired and may serve as keepers.
    """
    totals={s.id:sum(spectral_rms(s.spectrum,t.spectrum) for t in pool if t.id!=s.id) for s in eligible}
    order=sorted(eligible,key=lambda s:(totals[s.id],s.id))
    dist={(a.id,b.id):spectral_rms(a.spectrum,b.spectrum) for i,a in enumerate(pool) for b in pool[i+1:]}
    dist.update({(b,a):v for (a,b),v in list(dist.items())})
    candidates={s.id for s in eligible}
    changed=True
    while changed:
        changed=False
        for s in order:
            if s.id not in candidates:continue
            if not any(t.id not in candidates and dist[(s.id,t.id)]<=threshold for t in pool):
                candidates.discard(s.id);changed=True
    chosen={}
    for s in eligible:
        if s.id not in candidates:continue
        subs=[t for t in pool if t.id!=s.id and t.id not in candidates and dist[(s.id,t.id)]<=threshold]
        chosen[s.id]=min(subs,key=lambda t:(pca_distance(coords[s.id],coords[t.id]),dist[(s.id,t.id)],t.id))
    return candidates,chosen

def analyse(db,recipe_id,threshold,exclude_batch_id=None):
    recipe=db.get(DyeRecipe,recipe_id)
    if not recipe:raise HTTPException(404,'配方不存在')
    swatches=db.scalars(select(Swatch).where(Swatch.recipe_id==recipe_id,Swatch.measured==True).order_by(Swatch.id)).all()
    if len(swatches)<3:raise HTTPException(409,'同配方实测染样不足三张，无法做光谱降维比对')
    projection=project([s.spectrum for s in swatches])
    coords=dict(zip([s.id for s in swatches],projection['coordinates']))
    retired=_retired_ids(db);committed,pending=_reserved_ids(db,exclude_batch_id);refs=_referenced_swatch_ids(db)
    blocked={};eligible=[]
    for s in swatches:
        if s.id in retired:blocked[s.id]='已经腾退，留柜替代样不可再腾退'
        elif s.id in committed:blocked[s.id]='已作为其他已确认腾退的留柜替代样，必须留柜'
        elif s.id in pending:blocked[s.id]='已被其他待确认腾退建议占用（候选或替代样）'
        elif refs.get(s.id):blocked[s.id]='、'.join(refs[s.id])
        else:eligible.append(s)
    candidate_ids,chosen=select_candidates([s for s in swatches if s.id not in retired],eligible,threshold,coords)
    findings=[];candidates=[]
    totals={s.id:sum(spectral_rms(s.spectrum,t.spectrum) for t in swatches if t.id!=s.id) for s in swatches}
    order=sorted(swatches,key=lambda s:(totals[s.id],s.id))
    for s in order:
        if s.id in candidate_ids:
            t=chosen[s.id]
            candidates.append({'swatch_id':s.id,'lot':s.lot,'state':'candidate','reading':reading(s),
                               'substitute':{'swatch_id':t.id,'lot':t.lot,'reading':reading(t),
                                             'pca_distance':round(pca_distance(coords[s.id],coords[t.id]),6),
                                             'spectral_rms':round(spectral_rms(s.spectrum,t.spectrum),6)}})
        else:
            reason=blocked.get(s.id)
            if not reason:
                near=min((spectral_rms(s.spectrum,t.spectrum) for t in swatches if t.id not in retired and t.id!=s.id),default=None)
                if near is None:
                    reason='同配方没有其他在柜实测染样可作为替代样，留柜'
                elif near>threshold:
                    reason=f'最近同配方样原光谱差距 {near:.4f} 超过门限 {threshold:.4f}，留柜'
                else:
                    reason=f'作为留柜代表样：邻近样处理后仍需保留一张同配方样本，原光谱差距 {near:.4f} 在门限内'
            findings.append({'swatch_id':s.id,'lot':s.lot,'state':'keep','reason':reason,'reading':reading(s)})
    return recipe,swatches,{'method':METHOD,'count':len(swatches),'threshold':threshold,
            'explained_variance':projection['explained_variance'],'reconstruction_mse':projection['reconstruction_mse'],
            'candidates':candidates,'findings':findings}

def propose(db,p,user):
    # Lock the recipe so two concurrent proposals cannot both pass the "one live batch"
    # check and then plan around the same swatches.
    db.scalar(select(DyeRecipe).where(DyeRecipe.id==p.recipe_id).with_for_update())
    live=db.scalar(select(RetirementBatch).where(RetirementBatch.recipe_id==p.recipe_id,RetirementBatch.state=='proposed'))
    if live:raise HTTPException(409,f'该配方已有待主管确认的腾退建议 #{live.id}，请先确认或整批退回')
    recipe,_,analysis=analyse(db,p.recipe_id,p.max_spectral_rms)
    if not analysis['candidates']:raise HTTPException(409,'没有同时满足替代与留柜条件的腾退候选，未生成建议')
    batch=RetirementBatch(recipe_id=recipe.id,state='proposed',max_spectral_rms=p.max_spectral_rms,method=analysis['method'],
                          analysis=analysis,created_by=user.email)
    db.add(batch);db.flush()
    for c in analysis['candidates']:
        db.add(RetirementItem(batch_id=batch.id,swatch_id=c['swatch_id'],substitute_swatch_id=c['substitute']['swatch_id'],
                              pca_distance=c['substitute']['pca_distance'],spectral_rms=c['substitute']['spectral_rms'],state='proposed'))
    log(db,user,f'生成腾退建议 配方{recipe.code} 候选{len(analysis["candidates"])}张 门限{p.max_spectral_rms}')
    db.commit();db.refresh(batch);return batch

def preview(db,recipe_id,threshold):
    _,_,analysis=analyse(db,recipe_id,threshold)
    return analysis

def _live_failures(db,batch):
    _,_,fresh=analyse(db,batch.recipe_id,batch.max_spectral_rms,exclude_batch_id=batch.id)
    live={c['swatch_id']:c for c in fresh['candidates']}
    failures=[]
    for item in db.scalars(select(RetirementItem).where(RetirementItem.batch_id==batch.id).order_by(RetirementItem.id)):
        swatch=db.get(Swatch,item.swatch_id)
        candidate=live.get(item.swatch_id)
        if not candidate:
            reason=next((f['reason'] for f in fresh['findings'] if f['swatch_id']==item.swatch_id),'现状已不再满足留柜/替代条件')
            failures.append((swatch.lot,f'{swatch.lot}：{reason}'))
        elif candidate['substitute']['swatch_id']!=item.substitute_swatch_id:
            failures.append((swatch.lot,f'{swatch.lot}：替代样现状已变化，需重新生成建议'))
        elif abs(candidate['substitute']['spectral_rms']-item.spectral_rms)>1e-6:
            failures.append((swatch.lot,f'{swatch.lot}：原始光谱读数已变化'))
        elif is_retired(db,item.substitute_swatch_id) and not db.scalar(
                select(SwatchRetirement.id).where(SwatchRetirement.batch_id==batch.id,
                                                   SwatchRetirement.swatch_id==item.substitute_swatch_id)):
            failures.append((swatch.lot,f'{swatch.lot}：替代样已被其他批次腾退，须重新生成建议'))
    return failures

def confirm(db,key,user):
    # populate_existing: after waiting on the row lock, re-read the committed state so a
    # concurrent confirmation that just landed is seen here and returns idempotently.
    batch=db.scalar(select(RetirementBatch).where(RetirementBatch.id==key).with_for_update()
                    .execution_options(populate_existing=True))
    if not batch:raise HTTPException(404,'腾退批次不存在')
    # Retry after an interrupted confirmation: already committed, never retire twice.
    if batch.state=='confirmed':return batch
    if batch.state not in ('proposed',):raise HTTPException(409,'该批次已被退回，请重新生成建议')
    # Lock order recipe → swatches (by id), the same order used by re-dye trial
    # selection, so the two actions serialise: whichever lands first wins.
    db.scalar(select(DyeRecipe).where(DyeRecipe.id==batch.recipe_id).with_for_update())
    db.scalars(select(Swatch).where(Swatch.recipe_id==batch.recipe_id,Swatch.measured==True)
               .order_by(Swatch.id).with_for_update()).all()
    failures=_live_failures(db,batch)
    if failures:
        reason='整批退回：'+'；'.join(text for _,text in failures)
        batch.state='rejected';batch.rejection_reason=reason
        failed={lot:text for lot,text in failures}
        for item in db.scalars(select(RetirementItem).where(RetirementItem.batch_id==batch.id)):
            swatch=db.get(Swatch,item.swatch_id)
            item.state='rejected';item.reject_reason=failed.get(swatch.lot,'整批退回，未满足留柜条件')
        log(db,user,f'腾退批次 {key} 整批退回：{reason}');db.commit();raise HTTPException(409,reason)
    now=datetime.utcnow()
    for item in db.scalars(select(RetirementItem).where(RetirementItem.batch_id==batch.id)):
        if db.scalar(select(SwatchRetirement.id).where(SwatchRetirement.swatch_id==item.swatch_id)):
            db.rollback();raise HTTPException(409,'存在并发腾退，整批未执行，请重新生成建议')
        candidate=db.get(Swatch,item.swatch_id);substitute=db.get(Swatch,item.substitute_swatch_id)
        db.add(SwatchRetirement(batch_id=batch.id,swatch_id=item.swatch_id,substitute_swatch_id=item.substitute_swatch_id,
                                pca_distance=item.pca_distance,spectral_rms=item.spectral_rms,threshold=batch.max_spectral_rms,
                                evidence={'threshold':batch.max_spectral_rms,'method':batch.method,
                                          'explained_variance':batch.analysis.get('explained_variance'),
                                          'reconstruction_mse':batch.analysis.get('reconstruction_mse'),
                                          'candidate':reading(candidate),'substitute':reading(substitute),
                                          'confirmed_via':'主管整批确认'},
                                confirmed_by=user.email,confirmed_at=now))
        item.state='confirmed'
    batch.state='confirmed';batch.reviewed_by=user.email;batch.reviewed_at=now
    log(db,user,f'主管确认整批腾退 配方{batch.recipe_id} {len(batch.analysis["candidates"])}张，替代样留柜')
    db.commit();db.refresh(batch);return batch

def reject(db,key,p,user):
    batch=db.scalar(select(RetirementBatch).where(RetirementBatch.id==key).with_for_update()
                    .execution_options(populate_existing=True))
    if not batch:raise HTTPException(404,'腾退批次不存在')
    if batch.state=='confirmed':raise HTTPException(409,'该批次已确认腾退，不能整批退回')
    if batch.state=='rejected':
        batch.rejection_reason=p.reason;log(db,user,f'补充腾退退回原因 {key}：{p.reason}');db.commit();db.refresh(batch);return batch
    if batch.state!='proposed':raise HTTPException(409,'只有待确认批次可以退回')
    batch.state='rejected';batch.rejection_reason=p.reason
    for item in db.scalars(select(RetirementItem).where(RetirementItem.batch_id==batch.id)):
        item.state='rejected';item.reject_reason=p.reason
    log(db,user,f'主管退回腾退批次 {key}：{p.reason}');db.commit();db.refresh(batch);return batch

def batch_list(db):
    return [_detail(db,batch) for batch in db.scalars(select(RetirementBatch).order_by(RetirementBatch.id.desc()))]

def _detail(db,batch):
    items=[]
    for item in db.scalars(select(RetirementItem).where(RetirementItem.batch_id==batch.id).order_by(RetirementItem.id)):
        candidate=db.get(Swatch,item.swatch_id);substitute=db.get(Swatch,item.substitute_swatch_id)
        items.append({'id':item.id,'swatch_id':item.swatch_id,'lot':candidate.lot if candidate else '',
                      'recipe_id':candidate.recipe_id if candidate else None,
                      'substitute_swatch_id':item.substitute_swatch_id,'substitute_lot':substitute.lot if substitute else '',
                      'pca_distance':item.pca_distance,'spectral_rms':item.spectral_rms,
                      'state':item.state,'reject_reason':item.reject_reason})
    return {'id':batch.id,'recipe_id':batch.recipe_id,'state':batch.state,'max_spectral_rms':batch.max_spectral_rms,
            'method':batch.method,'analysis':batch.analysis,'created_by':batch.created_by,'created_at':batch.created_at,
            'reviewed_by':batch.reviewed_by,'reviewed_at':batch.reviewed_at,'rejection_reason':batch.rejection_reason,
            'items':items}

def history(db,recipe_id=None):
    stmt=select(SwatchRetirement).order_by(SwatchRetirement.id.desc())
    if recipe_id:stmt=stmt.join(Swatch,Swatch.id==SwatchRetirement.swatch_id).where(Swatch.recipe_id==recipe_id)
    out=[]
    for item in db.scalars(stmt):
        candidate=db.get(Swatch,item.swatch_id);substitute=db.get(Swatch,item.substitute_swatch_id)
        out.append({'id':item.id,'batch_id':item.batch_id,'swatch_id':item.swatch_id,'lot':candidate.lot,
                    'substitute_swatch_id':item.substitute_swatch_id,'substitute_lot':substitute.lot,
                    'pca_distance':item.pca_distance,'spectral_rms':item.spectral_rms,'threshold':item.threshold,
                    'evidence':item.evidence,'confirmed_by':item.confirmed_by,'confirmed_at':item.confirmed_at})
    return out

def is_retired(db,swatch_id):
    return db.scalar(select(SwatchRetirement.id).where(SwatchRetirement.swatch_id==swatch_id)) is not None
