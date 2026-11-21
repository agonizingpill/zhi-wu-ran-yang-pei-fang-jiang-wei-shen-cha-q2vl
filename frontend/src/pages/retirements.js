import {store,refresh} from '../store.js';import {api,session} from '../api.js';import {heading,recipeOptions} from '../components/common.js';import {escape,decimal,notify,formData,localTime} from '../utils.js';
const BATCH_LABELS={proposed:'待主管确认',confirmed:'整批已确认',rejected:'整批已退回'};
function batchLabel(s){return BATCH_LABELS[s]||s;}
function itemLabel(s){return {proposed:'待确认',confirmed:'已腾退',rejected:'未腾退'}[s]||s;}
function evidence(a){return a?`PC1 ${decimal(a.explained_variance[0]*100)}% · PC2 ${decimal(a.explained_variance[1]*100)}% · 重构MSE ${decimal(a.reconstruction_mse,4)}`:'未计算';}
function candidateCard(b,it){
 const cand=store.swatches.find(s=>s.id===it.swatch_id),sub=store.swatches.find(s=>s.id===it.substitute_swatch_id);
 return `<article class="retire-item" data-item="${it.id}"><div class="code">腾退候选 / ${escape(it.lot)} ${it.state!=='proposed'?`<span class="status ${it.state==='confirmed'?'approved':'rejected'}">${itemLabel(it.state)}</span>`:''}</div>
  <div class="retire-pair"><div><h4>拟腾退 · ${escape(it.lot)}</h4><p class="hint">L ${decimal(cand?.l)} · a ${decimal(cand?.a)} · b ${decimal(cand?.b)}</p></div><div class="arrow">→</div><div><h4>留柜替代 · ${escape(it.substitute_lot)}</h4><p class="hint">L ${decimal(sub?.l)} · a ${decimal(sub?.a)} · b ${decimal(sub?.b)}<br>PCA 距离 ${decimal(it.pca_distance,3)} · 原光谱 RMS ${decimal(it.spectral_rms,4)}</p></div></div>
  <p class="hint">替代样处理后仍留在柜中，且未被其他块替代、未被复染引用；原光谱差距 ${decimal(it.spectral_rms,4)} ≤ 门限 ${decimal(b.max_spectral_rms,4)}。</p>
  ${it.reject_reason?`<div class="rule">未腾退原因：${escape(it.reject_reason)}</div>`:''}</article>`;
}
function keepRow(f){return `<tr><td>${escape(f.lot)}<br><span class="hint">留柜</span></td><td><span class="hint">${escape(f.reason)}</span></td></tr>`;}
function batchCard(b){
 const recipe=store.recipes.find(r=>r.id===b.recipe_id),active=b.state==='proposed';
 return `<article class="retire-batch trial" data-batch="${b.id}"><div class="code">腾退建议 / ${String(b.id).padStart(3,'0')} · ${escape(recipe?.code||b.recipe_id)} <span class="status ${b.state==='confirmed'?'approved':b.state==='rejected'?'rejected':'proposed'}">${batchLabel(b.state)}</span></div>
  <h3>${escape(recipe?.name||'')} · ${b.items.length} 张拟腾退</h3>
  <p class="hint">门限 ${decimal(b.max_spectral_rms,4)} · ${evidence(b.analysis)}<br>建立 ${escape(b.created_by)} · ${b.created_at?escape(localTime(b.created_at)):''}${b.reviewed_by?`<br>主管 ${escape(b.reviewed_by)} · ${b.reviewed_at?escape(localTime(b.reviewed_at)):''}`:''}</p>
  <div class="retire-items">${b.items.map(it=>candidateCard(b,it)).join('')}</div>
  <details class="retire-details"${active?'':''}><summary>留柜样与依据（${b.analysis?.findings?.length||0} 张）</summary><table><thead><tr><th>批号</th><th>留柜依据</th></tr></thead><tbody>${(b.analysis?.findings||[]).map(keepRow).join('')}</tbody></table></details>
  ${b.rejection_reason?`<div class="rule">退回原因：${escape(b.rejection_reason)}</div>`:''}
  <div class="actions">${active?`<button class="primary" data-confirm="${b.id}" ${session().role!=='admin'?'disabled':''}>主管确认整批腾退</button><button data-reject="${b.id}" ${session().role!=='admin'?'disabled':''}>整批退回</button>`:b.state==='rejected'?`<button data-reject="${b.id}" ${session().role!=='admin'?'disabled':''}>补充退回原因</button>`:`<span class="hint">已确认腾退，原始读数与确认凭据已留档。</span>`}</div>
  <form class="reject-form" data-key="${b.id}" hidden><label>退回原因<textarea name="reason" minlength="5" required placeholder="例如：替代样刚被复染试验引用"></textarea></label><button ${session().role!=='admin'?'disabled':''}>确认退回</button><button type="button" class="cancel-reject">取消</button></form>
 </article>`;
}
function previewPanel(p){
 return `<p class="hint">${p.count} 张同配方实测染样 · ${evidence(p)} · 门限 ${decimal(p.threshold,4)}</p>${p.candidates.length?`<table><thead><tr><th>拟腾退</th><th>替代样</th><th>原光谱RMS</th><th>PCA距离</th></tr></thead><tbody>${p.candidates.map(c=>`<tr><td>${escape(c.lot)}</td><td>${escape(c.substitute.lot)}</td><td>${decimal(c.substitute.spectral_rms,4)}</td><td>${decimal(c.substitute.pca_distance,3)}</td></tr>`).join('')}</tbody></table>`:'<div class="rule">当前门限下无合格腾退候选，全部留柜。</div>'}<details open><summary>留柜与不腾退理由（${p.findings.length}）</summary><table><tbody>${p.findings.map(keepRow).join('')}</tbody></table></details>`;
}
/** Suggestion form + existing batches. Shared by the swatch page and the cabinet page. */
export function cabinetMarkup(){const r=store.retirements||[];return `<form id="retire-form"><label>配方<select name="recipe_id">${recipeOptions(store.recipes)}</select></label><label>原光谱差距门限 / RMS<input name="max_spectral_rms" type="number" step=".001" min=".001" max="1" value=".005" required></label><button class="primary" ${session().role==='viewer'?'disabled':''}>光谱降维分析并生成建议</button><button type="button" id="preview">仅预览，不落库</button></form><div class="rule">36 波段先作 StandardScaler → 二维 PCA。建议只依据原光谱差距与留柜替代关系；PCA 距离仅作参考排序，不替代 ΔE 色差判定。确认时整批重核；并发复染选样以先落账为准。</div><h3>预览依据</h3><div id="retire-preview">${(store.retirePreview?previewPanel(store.retirePreview):'<p class="hint">点“仅预览”查看候选、替代样与留柜理由，不生成批次。</p>')}</div><h3>腾退建议与主管确认</h3><div class="retire-batches">${r.length?r.map(batchCard).join(''):'<div class="empty">尚无光谱降维腾退建议。先选择配方与门限生成整批建议，再由主管确认。</div>'}</div>`;}
export function render(){return heading('10','柜位有限，先证明替代样处理后仍在','对同配方实测染样做光谱降维比对，原光谱差距超限则留柜。每块拟腾退染样都须有处理完仍留柜的替代样；已替代别块或被复染引用的样布不腾退。主管确认时重核整批，一块不合条件即整批退回。')+`<div class="panel cabinet-panel">${cabinetMarkup()}</div>`;}
export function bind(rerender){bindCabinet(rerender);}
export function bindCabinet(rerender){
 const form=document.querySelector('#retire-form'),previewBtn=document.querySelector('#preview');
 if(form)form.onsubmit=async e=>{e.preventDefault();const d=formData(e.target);d.recipe_id=Number(d.recipe_id);d.max_spectral_rms=Number(d.max_spectral_rms);try{await api('/retirements','POST',d);await refresh();rerender();notify('腾退建议已生成，等待主管整批确认');}catch(err){notify(err.message);}};
 if(previewBtn)previewBtn.onclick=async()=>{const d=formData(form);try{store.retirePreview=await api('/retirements/preview?recipe_id='+Number(d.recipe_id)+'&max_spectral_rms='+Number(d.max_spectral_rms));rerender();notify('预览已更新，未生成批次');}catch(err){notify(err.message);}};
 document.querySelectorAll('[data-confirm]').forEach(b=>b.onclick=async()=>{try{await api('/retirements/'+b.dataset.confirm+'/confirm','POST');await refresh();rerender();notify('整批腾退已确认，替代样留柜，原始读数已留档');}catch(err){await refresh();rerender();notify(err.message);}});
 document.querySelectorAll('[data-reject]').forEach(b=>b.onclick=()=>{const rf=b.closest('.retire-batch').querySelector('.reject-form');rf.hidden=!rf.hidden;});
 document.querySelectorAll('.reject-form').forEach(f=>{
  f.onsubmit=async e=>{e.preventDefault();try{await api('/retirements/'+f.dataset.key+'/reject','POST',formData(f));await refresh();rerender();notify('整批已退回，退回原因已留存');}catch(err){notify(err.message);}};
  f.querySelector('.cancel-reject').onclick=()=>{f.hidden=true;};
 });
}
