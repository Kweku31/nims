import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowDownToLine, ArrowRight, ArrowUpRight, BarChart3, Check, CheckCircle2,
  ChevronDown, ChevronRight, Clock3, Database, FileText, FlaskConical, GitBranch, HelpCircle,
  Layers3, LayoutDashboard, LoaderCircle, Menu, Play, Plus, Radio, Search, Settings2,
  ShieldCheck, SlidersHorizontal, Square, Terminal, X, XCircle, Zap } from 'lucide-react';
import './styles.css';
import {Walkthrough} from './walkthrough.jsx';
import {ExperimentOptions, optionalDefaults} from './experiment_options.jsx';
import { DatasetPreview, DatasetInputTools, usePhaseDetails, PhaseReportExplorer, RelatedRecord } from './inspection.jsx';

const PHASE_ICONS = [Database, ArrowUpRight, GitBranch, Layers3, Activity, ShieldCheck];
const NAV = [['overview', LayoutDashboard, 'Overview'], ['thesis', FileText, 'Thesis walkthrough'], ['dataset', Database, 'Dataset viewer'], ['phases', Layers3, 'Pipeline phases'],
  ['results', BarChart3, 'Results & rankings'], ['history', Clock3, 'Experiment history'], ['logs', Terminal, 'Live logs']];
const labels = { pca: 'PCA', autoencoder: 'Autoencoder', parquet: 'Parquet', gzip: 'CSV + gzip', zstd: 'CSV + zstd',
  original: 'Original dataset', simulated_ideal: 'Simulated network', ssh: 'Verified SSH', fresh_data: 'Fresh data',
  existing_payload: 'Existing payload', loss_tolerant: 'Loss-tolerant', full_fidelity: 'Full fidelity',
  selected_columns_exact: 'Selected columns · exact', equal: 'Equal weights', custom: 'Custom weights', balanced: 'Balanced', transfer_priority: 'Transfer priority',
  utility_priority: 'Utility priority', FS_95_clinical_review: 'Clinical review · 95%' };
const TOPSIS_CRITERIA = [
  ['total_transmitted_bytes','Total transmitted size','Lower is better'],
  ['effective_delivery_seconds','Delivery time','Lower is better'],
  ['R2_retained_variation_observed_STANDARDIZED','Reconstruction R²','Higher is better'],
  ['knn5_overlap_original_vs_reconstruction','Neighbourhood preservation','Higher is better'],
  ['clinical_predictor_retention_pct','Predictor columns retained','Higher is better'],
  ['original_observed_measurement_retention_pct','Observed measurements retained','Higher is better'],
  ['clinical_screen_new_violation_pct','New clinical-screen violations','Lower is better'],
];
const label = x => labels[x] || String(x || '—').replaceAll('_', ' ');
const fmt = (n, digits=2) => n == null || !Number.isFinite(Number(n)) ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
const seconds = n => n == null ? '—' : Number(n) >= 60 ? `${fmt(n/60, 1)} min` : `${fmt(n, 2)} s`;
const bytes = n => n == null ? '—' : n < 1024 ? `${fmt(n,0)} B` : n < 1048576 ? `${fmt(n/1024,1)} KB` : `${fmt(n/1048576,1)} MB`;
const candidate = r => `${label(r.method)}${r.k != null ? ` · k${r.k}` : ''}${r.codec && r.codec !== 'native' ? ` / ${r.codec}` : ''}`;
const date = s => s ? new Date(s).toLocaleString(undefined, { month:'short',day:'numeric',hour:'2-digit',minute:'2-digit' }) : 'Synthetic example';
async function api(path, options) {
  const response = await fetch('/api'+path, options);
  const json = await response.json();
  if (!response.ok) throw new Error(json.error || 'Unable to reach the local server');
  return json;
}
const post = (path, body) => api(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });

function Badge({ status, children }) {
  const Icon = ['complete','verified'].includes(status) ? CheckCircle2 : status === 'running' ? LoaderCircle : ['failed','cancelled','interrupted'].includes(status) ? XCircle : status === 'demo' ? FlaskConical : Clock3;
  return <span className={`badge ${status || 'pending'}`}><Icon size={12} className={status === 'running' ? 'spin' : ''}/>{children || label(status)}</span>;
}
function Empty({ title='No results yet', text='Results will appear as the pipeline completes.' }) {
  return <div className="empty"><Layers3 size={30}/><h3>{title}</h3><p>{text}</p></div>;
}
function Select({ title, value, values, onChange }) {
  return <label className="select-field"><span>{title}</span><div><select aria-label={title} value={value} onChange={e=>onChange(e.target.value)}>{values.map(v=><option key={v} value={v}>{label(v)}</option>)}</select><ChevronDown size={13}/></div></label>;
}

function App() {
  const [page,setPage] = useState(()=>window.location.hash==='#thesis'?'thesis':'overview');
  const [runs,setRuns] = useState([]);
  const [selected,setSelected] = useState('demo');
  const [data,setData] = useState(null);
  const [settings,setSettings] = useState(null);
  const [connection,setConnection] = useState(false);
  const [error,setError] = useState('');
  const [modal,setModal] = useState(false);
  const [phase6Modal,setPhase6Modal] = useState(false);
  const [mobile,setMobile] = useState(false);
  const [phase,setPhase] = useState('phase1');
  const [logs,setLogs] = useState({ text:'Waiting for output…' });
  const [filters,setFilters] = useState({ dataset:'original', delivery_scenario:'fresh_data', network_mode:'simulated_ideal', transport_method:'scp', scenario:'loss_tolerant', weight_profile:'' });
  const [search,setSearch] = useState('');
  const [sort,setSort] = useState({ key:'rank', desc:false });
  const [stopConfirm,setStopConfirm] = useState(false);
  const [resuming,setResuming] = useState(false);
  const logEnd = useRef(null);
  const navigate = p => {setPage(p);setMobile(false);};
  useEffect(()=>{
    let active=true;
    async function refresh() {
      try {
        const [history,config] = await Promise.all([api('/runs'),api('/settings')]);
        if(active){setRuns(history);setSettings(config);setConnection(true);}
      } catch {if(active)setConnection(false);}
    }
    refresh(); const timer=setInterval(refresh,4000);
    return ()=>{active=false;clearInterval(timer);};
  },[]);
  useEffect(()=>{
    let active=true;setData(null);setError('');setFilters(v=>({...v,weight_profile:''}));
    async function refresh() {
      try {
        let next;
        try{next=await api(`/runs/${selected}`);}catch(e){if(selected!=='demo')throw e;next=await fetch('/demo.json').then(r=>r.json());}
        if(active){setData(next);setError('');}
      }catch(e){if(active)setError(e.message);}
    }
    refresh();const timer=setInterval(refresh,3000);
    return ()=>{active=false;clearInterval(timer);};
  },[selected]);
  useEffect(()=>{
    let active=true;
    if(page!=='logs')return;
    const refresh=()=>api(`/runs/${selected}/logs`).then(v=>active&&setLogs(v)).catch(e=>active&&setLogs({text:e.message}));
    refresh();const timer=setInterval(refresh,2000);return()=>{active=false;clearInterval(timer);};
  },[page,selected]);
  const ranks = (data?.rankings || []).map(r=>({...r,transport_method:r.transport_method || (r.network_mode==='ssh' ? (data?.manifest?.config?.ssh_transport==='rsync'?'rsync':'scp') : 'simulated')}));
  const options = Object.fromEntries(Object.keys(filters).map(key=>[key,[...new Set(ranks.map(r=>r[key]).filter(Boolean))]]));
  const primaryProfile = data?.manifest?.primary_weight_profile || 'equal';
  const effective = Object.fromEntries(Object.keys(filters).map(key=>[key,options[key].includes(filters[key])?filters[key]:(key==='weight_profile'&&options[key].includes(primaryProfile)?primaryProfile:options[key][0]||filters[key])]));
  const pool = ranks.filter(r=>Object.entries(effective).every(([key,value])=>r[key]===value));
  const ranked = pool.filter(r=>candidate(r).toLowerCase().includes(search.toLowerCase())).sort((a,b)=>(sort.desc?-1:1)*(Number(a[sort.key])-Number(b[sort.key])));
  const completed = data?.phases.filter(p=>p.status==='complete').length || 0;
  const totalTime = data?.phases.reduce((sum,p)=>sum+(p.seconds||0),0) || 0;
  const meta = data?.manifest || {};
  const packages = meta.phase6_packages_completed ?? 0;
  const top = [...pool].sort((a,b)=>a.rank-b.rank)[0];
  const isRunning = data?.status==='running';
  const change = (key,value)=>setFilters(v=>({...v,[key]:value}));
  const onStart = async config => { const job=await post('/runs',config);setSelected(job.id);setPage('overview');setRuns(await api('/runs'));setModal(false); };
  const stop = async()=>{try{await post(`/runs/${selected}/cancel`,{});setStopConfirm(false);setData(await api(`/runs/${selected}`));}catch(e){setError(e.message);}};
  const resume = async()=>{setResuming(true);setError('');try{const result=await post(`/runs/${selected}/resume`,{});if(result.id!==selected)throw new Error('Resume returned a different experiment ID; refusing to switch runs.');setData(await api(`/runs/${selected}`));setRuns(await api('/runs'));}catch(e){setError(e.message);}finally{setResuming(false);}};
  const canResume = selected.startsWith('job-') && ['failed','cancelled','interrupted'].includes(data?.status);
  const canReplayPhase6 = selected.startsWith('job-') && !isRunning &&
    data?.phases?.slice(0,5).every(p=>p.status==='complete');
  const replayPhase6 = async options => {
    const job = await post(`/runs/${selected}/rerun-phase6`, options);
    if (job.id!==selected) throw new Error('Phase 6 replay returned a different experiment ID');
    setPhase6Modal(false);setData(await api(`/runs/${selected}`));setRuns(await api('/runs'));
  };
  function downloadDemo() {
    const blob=new Blob([data.report],{type:'text/plain'}),url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download='synthetic-demo-report.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const download = ()=>data?.demo ? downloadDemo() : window.location.assign(`/api/runs/${selected}/files/FINAL_REPORT.md`);
  const comparisonFilters = <><div className="filters">
    <Select title="Feature set" value={effective.dataset} values={options.dataset} onChange={v=>change('dataset',v)}/>
    <Select title="Delivery scenario" value={effective.delivery_scenario} values={options.delivery_scenario} onChange={v=>change('delivery_scenario',v)}/>
    <Select title="Network evidence" value={effective.network_mode} values={options.network_mode} onChange={v=>change('network_mode',v)}/>
    <Select title="Transport" value={effective.transport_method} values={options.transport_method} onChange={v=>change('transport_method',v)}/>
    <Select title="Fidelity requirement" value={effective.scenario} values={options.scenario} onChange={v=>change('scenario',v)}/>
    <Select title="Weight profile" value={effective.weight_profile} values={options.weight_profile} onChange={v=>change('weight_profile',v)}/>
  </div>{meta.decision_weights?.[effective.weight_profile]&&<details className="weight-summary"><summary>View {label(effective.weight_profile).toLowerCase()} · {effective.weight_profile===primaryProfile?'experiment selection':'comparison profile'}</summary><ul>{TOPSIS_CRITERIA.map(([key,name],i)=><li key={key}>{name}: <strong>{fmt(meta.decision_weights[effective.weight_profile][i]*100,4)}%</strong></li>)}</ul><p>Criteria that are identical across candidates do not affect their order; remaining weights are renormalized.</p></details>}</>;
  return <div className="app-shell">
    {mobile&&<button className="sidebar-scrim" aria-label="Close navigation" onClick={()=>setMobile(false)}/>}
    <aside className={`sidebar ${mobile?'open':''}`}>
      <a className="brand" href="#" onClick={e=>{e.preventDefault();navigate('overview');}}><span className="brand-icon"><Radio size={22}/></span><span>observatory<span className="brand-sub">THESIS WORKSPACE</span></span></a>
      <div className="workspace"><span className="workspace-avatar">CT</span><div>Clinical transfer study<small>Research workspace <span>v7</span></small></div><ChevronDown size={14}/></div>
      <p className="nav-label">WORKSPACE</p>
      <nav>{NAV.map(([key,Icon,title])=><button key={key} onClick={()=>navigate(key)} className={page===key?'active':''}><Icon size={18}/>{title}{key==='phases'&&<span className="nav-count">6</span>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="local-note"><span className={`dot ${connection?'':'offline'}`}/><div>{connection?'Local workspace connected':'Demo preview'}<small>{connection?'Your data stays on this computer':'Connect the Python server to run'}</small></div></div><button className={page==='settings'?'active':''} onClick={()=>navigate('settings')}><Settings2 size={18}/>Workspace settings</button><button onClick={()=>navigate('guide')}><HelpCircle size={18}/>How it works<ArrowUpRight size={14}/></button><div className="user"><span>R</span><div>Researcher<small>Local session</small></div><span className="user-dot"/></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={()=>setMobile(true)}><Menu size={20}/></button>Workspace<ChevronRight size={14}/><strong>{NAV.find(x=>x[0]===page)?.[2]||label(page)}</strong></div><div className="topbar-right"><span className="local-pill"><span className="dot"/>Local environment</span><span className="topbar-avatar">R</span></div></header>
      <main>
        <div className="page-heading"><div><div className="eyebrow">CLINICAL DATA · SIX-PHASE PIPELINE</div><h1>{page==='thesis'?'From a clinical record to a transfer decision':page==='overview'?'Every phase. A clearer picture.':page==='dataset'?'Explore the source data.':page==='phases'?'Inside the pipeline.':page==='results'?'Evidence behind the decision.':page==='history'?'Your experiment notebook.':page==='logs'?'Follow the work, live.':page==='settings'?'A workspace on your terms.':'From source to verified delivery.'}</h1><p>{page==='thesis'?'Explore the six phases and the decision using the measurements reported in the thesis.':page==='overview'?'Track your experiment from the first data check to the final delivery.':page==='results'?'Compare like-for-like results, with integrity and uncertainty in view.':page==='history'?'Each completed run keeps its own timestamped result directory.':'One connected view of your clinical-data transfer research.'}</p></div><button className="primary" onClick={()=>setModal(true)}><Plus size={17}/>New experiment</button></div>
        {connection&&settings&&settings.api_version!==4&&<div className="alert error" role="alert">The page has been updated, but the running Python server is older. Restart your updated server.py and refresh to enable the latest experiment controls.</div>}
        {error&&page!=='thesis'&&<div className="alert error" role="alert"><XCircle size={18}/>{error}<button className="icon-button" onClick={()=>setError('')} aria-label="Dismiss error"><X size={16}/></button></div>}
        {['overview','dataset','phases','results','logs'].includes(page)&&<>
          <div className="experiment-bar"><div className="experiment-id"><span className="experiment-icon"><FlaskConical size={20}/></span><div><small>CURRENT EXPERIMENT</small><select aria-label="Current experiment" value={selected} onChange={e=>setSelected(e.target.value)}><option value="demo">Synthetic clinical cohort · Demo</option>{runs.map(r=><option key={r.id} value={r.id}>{r.name} · {date(r.created)} · {r.status}</option>)}{selected!=='demo'&&!runs.some(r=>r.id===selected)&&<option value={selected}>Starting experiment…</option>}</select></div></div><div className="experiment-meta">{data?.demo&&<Badge status="demo">Synthetic demo</Badge>}<Badge status={data?.status||'pending'}/><span className="divider"/>{data?.configuration?.patient_coverage_min!=null&&<span className="soft-tag">{fmt(data.configuration.patient_coverage_min*100,0)}% patient coverage</span>}<Clock3 size={14}/><span>{seconds(totalTime)}</span><button className="ghost" onClick={()=>navigate('dataset')}><Database size={14}/>View dataset</button>{isRunning?<button className="ghost danger" onClick={()=>setStopConfirm(true)}><Square size={13}/>Stop run</button>:<button className="ghost" disabled={!data?.report} onClick={download}><ArrowDownToLine size={15}/>Report</button>}</div></div>
          {canResume&&<div className="alert recovery-banner"><div><strong>{data.status==='failed'?'Needs attention':'Experiment interrupted'}</strong><p>{data.error||'This experiment stopped before completion.'}</p><small>After restoring the connection or correcting the reported problem, resume with the saved configuration. Verified completed phases and package checkpoints are reused in this same experiment; an interrupted phase may restart from its last completed checkpoint. Changed code, dataset or options require a separate experiment.</small></div><button className="primary" disabled={resuming||!connection||settings?.api_version!==4} onClick={resume}><Play size={15}/>{resuming?'Resuming…':'Resume this experiment'}</button></div>}
          {canReplayPhase6&&<div className="alert recovery-banner"><div><strong>Receiver-side remeasurement</strong><p>Phases 1–5 are complete. Run Phase 6 again over verified SSH, reconstruct on the server, and update the experiment's TOPSIS ranking.</p><small>Preserves the original run ID and earlier results snapshot. Requires the original dataset and verified Phase 1–5 artifacts; no simultaneous experiment worker.</small></div><button className="primary" disabled={!connection||settings?.api_version!==4||!settings?.transport_controls} onClick={()=>setPhase6Modal(true)}><ShieldCheck size={15}/>Re-run Phase 6 on Server</button></div>}
          {data?.network && isRunning && ['connecting','connection_lost','retrying','needs_attention'].includes(data.network.status)&&<div className="alert recovery-banner" role="status"><Radio size={19}/><div><strong>{({connecting:'Connecting to SSH',connection_lost:'Connection lost — retrying',retrying:'Retrying SSH delivery',needs_attention:'Needs attention'})[data.network.status]}</strong><p>{data.network.operation} · Attempt {data.network.attempt} of {data.network.max_attempts}</p>{data.network.error&&<small>{data.network.error}{data.network.retry_in_seconds?` · Next attempt after ${data.network.retry_in_seconds}s`:''}</small>}</div></div>}
          {data?.demo&&<div className="demo-banner"><FlaskConical size={15}/><span><strong>A real pipeline, synthetic data.</strong> Explore 64 generated rows from 16 synthetic patients. Network delivery is simulated.</span><button onClick={()=>setModal(true)}>Run your dataset<ArrowRight size={14}/></button></div>}
          {!data&&!error&&<div className="loading"><LoaderCircle className="spin"/>Loading experiment…</div>}
        </>}
        {page==='thesis'&&<Walkthrough runs={runs} onInspect={(id,step,delivery,requirement)=>{
          setSelected(id);
          if(step<6){setPhase('phase'+(step+1));navigate('phases');}
          else{setFilters({dataset:'original',delivery_scenario:delivery,network_mode:'ssh',transport_method:'scp',scenario:requirement,weight_profile:'equal'});navigate('results');}
        }}/>}
        {data&&page==='overview'&&<>
          <button className="text-button" onClick={()=>navigate('thesis')}>Present the recorded thesis results<ArrowRight size={15}/></button>
          <div className="stat-grid"><Stat title="Pipeline progress" value={`${completed}`} suffix="/ 6 phases" icon={Layers3} note={completed===6?'All phases completed':'Processing your experiment'} progress={completed/6}/><Stat title="Verified local packages" value={packages} suffix={`/ ${meta.phase6_packages_expected??'—'}`} icon={ShieldCheck} note={`${meta.remote_verified_packages??0} remotely verified · ${meta.simulated_packages??0} simulated`}/><Stat title="Leading configuration" value={top?label(top.method):'Awaiting results'} suffix={top?.k?`k = ${top.k}`:''} icon={BarChart3} note={top?`${label(effective.weight_profile)} · ${label(effective.scenario)}`:'Comparable candidates will appear here'}/><Stat title="Delivery time" value={top?fmt(top.effective_delivery_seconds):'—'} suffix="seconds" icon={Zap} note={`${label(effective.delivery_scenario)} · ${effective.network_mode==='ssh'?(meta.receiver_recovery_location?.includes('remote_ssh')?'SSH + server reconstruction':'SSH + local recovery'):'includes simulated network'}`}/></div>
          <div className="section-title"><div><h2>The experiment, step by step <span className="count">06</span></h2><p>Select a phase to inspect its outputs and measurements.</p></div><button className="text-button" onClick={()=>navigate('phases')}>Explore pipeline<ArrowRight size={15}/></button></div>
          <div className="phase-grid">{data.phases.map((p,i)=>{const Icon=PHASE_ICONS[i];return <button key={p.id} className={`phase-card ${p.status}`} onClick={()=>{setPhase(p.id);navigate('phases');}}><div className="phase-top"><span className="phase-number">0{i+1}</span>{p.status==='complete'?<CheckCircle2 size={16}/>:p.status==='running'?<LoaderCircle className="spin" size={16}/>:<Clock3 size={16}/>}</div><Icon size={22} className="phase-icon"/><h3>{p.title}</h3><div className="phase-bottom"><span>{label(p.status)}</span><span>{p.seconds?seconds(p.seconds):'—'}</span></div></button>;})}</div>
          <TransportStudies studies={meta.transport_studies}/>
          {meta.transport_comparison?.length>0&&<details className="panel"><summary>Verified SCP and rsync measurements</summary>
            <p>Mean wall time includes retries, checksum verification and publication. Transport rankings use the verified trials available for the selected experiment.</p>
            <div style={{overflowX:'auto'}}><table><thead><tr>{['Phase','Artifact','Transport','Trials','Mean send (s)','Mean wall (s)','Failed attempts'].map(h=><th key={h}>{h}</th>)}</tr></thead>
            <tbody>{meta.transport_comparison.map(row=><tr key={JSON.stringify([row.phase,row.artifact,row.transport])}><td>{row.phase}</td><td>{row.artifact}</td><td>{row.transport}</td><td>{row.trials}</td><td>{fmt(row.mean_send_seconds,3)}</td><td>{fmt(row.mean_wall_seconds,3)}</td><td>{row.failed_attempts}</td></tr>)}</tbody></table></div></details>}
          <div className="section-title comparison-title"><div><h2>Performance at a glance</h2><p>A fair comparison starts with the same conditions.</p></div><span className="soft-tag"><SlidersHorizontal size={13}/>Scoped comparison</span></div>
          {ranks.length>0&&comparisonFilters}
          <div className="chart-grid"><DeliveryChart rows={pool} mode={effective.network_mode}/><UtilityChart rows={pool}/></div>
          <div className="integrity-strip"><ShieldCheck size={22}/><div><strong>Evidence first. Recommendations second.</strong><p>Unverified SSH results never enter rankings. Simulated results are provisional; a TOPSIS score does not establish clinical acceptance.</p></div><button className="text-button" onClick={()=>navigate('results')}>Review evidence<ArrowRight size={15}/></button></div>
        </>}
        {data&&page==='dataset'&&<DatasetPreview runId={selected}/>}
        {data&&page==='phases'&&<PhaseView data={data} selected={phase} onSelect={setPhase}/>}
        {data&&page==='results'&&<>
          <TransportStudies studies={meta.transport_studies}/>
          <div className="section-title"><div><h2>Decision rankings</h2><p>Compare configurations for one feature set, transport, delivery scenario and fidelity requirement.</p></div><span className="soft-tag">{pool.length} comparable candidates</span></div>
          {ranks.length?comparisonFilters:<Empty title="No eligible ranking" text="Candidates need complete, valid criteria and the required integrity checks. Failed or unverified candidates are not assigned a score."/>}
          {ranks.length>0&&<div className="panel"><div className="table-toolbar"><div className="search"><Search size={16}/><input aria-label="Search configurations" placeholder="Find a configuration…" value={search} onChange={e=>setSearch(e.target.value)}/></div><Badge status={effective.network_mode==='ssh'?'verified':'demo'}>{effective.network_mode==='ssh'?'Verified SSH pool':'Provisional · simulated'}</Badge></div><div className="table-scroll"><table><thead><tr><th>Rank</th><th>Configuration</th>{[['topsis_score','TOPSIS score'],['total_transmitted_bytes','Total sent'],['effective_delivery_seconds','Delivery'],['R2_retained_variation_observed_STANDARDIZED','R²'],['clinical_predictor_retention_pct','Retention']].map(([key,title])=><th key={key}><button onClick={()=>setSort({key,desc:sort.key===key?!sort.desc:false})}>{title}<ChevronDown size={12}/></button></th>)}</tr></thead><tbody>{ranked.map(r=><tr key={r.package_id}><td><span className={r.rank===1?'rank first':'rank'}>{r.rank}</span></td><td><strong>{candidate(r)}</strong><small>{r.codec==='native'?'Native payload':`${r.codec} codec`}</small></td><td><div className="score-cell"><span>{fmt(r.topsis_score,4)}</span><i style={{width:`${r.topsis_score*60}px`}}/></div></td><td>{bytes(r.total_transmitted_bytes)}</td><td>{seconds(r.effective_delivery_seconds)}</td><td>{fmt(r.R2_retained_variation_observed_STANDARDIZED,3)}</td><td>{fmt(r.clinical_predictor_retention_pct,1)}%</td></tr>)}</tbody></table>{!ranked.length&&<Empty title="No matching configurations" text="Try another search or comparison scope."/>}</div><div className="table-footer">{ranked.length} of {pool.length} configurations · Lower delivery costs and stronger utility inform the weighted score.</div></div>}
          <div className="report-grid"><div className="panel report-notes"><h3>Reading these results</h3><p><strong>Fresh data</strong> includes fitting allocated by model reuse, initial encoding and payload compression. <strong>Existing payload</strong> starts from an already-created Phase 4 payload.</p><p>Receiver recovery location is recorded for each configuration (local or remote_ssh). R² can be negative. Range checks are exploratory clinical screens, not safety standards.</p><p>Tables display up to {fmt(data.table_limit||20000,0)} rows. Download the original reports for the complete evidence.</p></div><div className="panel downloads"><h3>Experiment files</h3>{data.files.length?data.files.map(file=><a key={file} href={`/api/runs/${selected}/files/${file}`}><FileText size={16}/><span>{file}</span><ArrowDownToLine size={15}/></a>):<p>Demo data is for exploration. Start an experiment to download its original reports.</p>}</div></div>
        </>}
        {page==='history'&&<div className="panel"><div className="panel-heading"><div><h2>Experiment history</h2><p>Original reports remain in their timestamped folders.</p></div><span className="soft-tag">{runs.length} experiments</span></div>{runs.length?<div className="history-list">{runs.map(r=><button key={r.id} onClick={()=>{setSelected(r.id);navigate('overview');}}><span className="history-icon"><FlaskConical size={19}/></span><div><strong>{r.name}</strong><small>{date(r.created)} · {r.snapshot||r.id}</small></div><Badge status={r.status}/><ChevronRight size={18}/></button>)}</div>:<Empty title="Your first experiment starts here" text="New runs and imported timestamped reports will appear here. The synthetic demo is available in the experiment selector."/>}<div className="history-action"><button className="primary" onClick={()=>setModal(true)}><Plus size={16}/>New experiment</button><button className="ghost" onClick={()=>{setSelected('demo');navigate('overview');}}>Explore synthetic demo<ArrowRight size={14}/></button></div></div>}
        {page==='logs'&&<div className="panel log-panel"><div className="panel-heading"><div><h2>Pipeline output</h2><p>Updates every two seconds. The full log stays on disk.</p></div><button className="ghost" onClick={()=>logEnd.current?.scrollIntoView({behavior:'smooth'})}>Jump to latest<ChevronDown size={14}/></button></div><pre className="console" aria-label="Pipeline log">{logs.truncated&&'[Showing the most recent 100 KB]\n'}{logs.text}<span ref={logEnd}/></pre></div>}
        {page==='settings'&&<div className="settings-grid"><div className="panel settings-panel"><Settings2 size={24}/><h2>Local connection</h2><p>The dashboard runs on your computer alongside the existing Python pipeline.</p><dl><dt>Server status</dt><dd>{connection?'Connected':'Disconnected — start python server.py'}</dd><dt>Pipeline directory</dt><dd>{settings?.pipeline||'Not connected'}</dd><dt>Python environment</dt><dd>{settings?.python||'Not connected'}</dd><dt>Imported output roots</dt><dd>{settings?.results_roots?.join('\n')||'None'}</dd><dt>Dependencies</dt><dd>{settings?.missing_dependencies?.length?`Missing: ${settings.missing_dependencies.join(', ')}`:connection?'All pipeline dependencies available':'Unknown'}</dd></dl></div><div className="panel settings-panel"><ShieldCheck size={24}/><h2>Research boundaries</h2><p>Simulated networking is the default. Strict SSH requires your explicit destination when creating an experiment and never falls back silently.</p><p>The Dataset viewer displays source CSV records locally when you open it. Phase comparisons use the original aggregate reports and checkpoint metadata.</p><p>Experiments and Phase 6 reruns stay under the same job ID. Earlier report snapshots are preserved.</p><p>Keep this local server on the loopback interface. It is not an authenticated multi-user service.</p></div></div>}
        {page==='guide'&&<div className="guide-grid">{['Start with your CSV','Follow every phase','Compare within a scope','Keep the evidence'].map((t,i)=><div className="panel guide-card" key={t}><span>0{i+1}</span><h2>{t}</h2><p>{['Upload or select a CSV on this computer, preview its records, choose the PCA/AE component counts and configure a simulated or strict SSH experiment.','The pipeline keeps its original algorithms. Progress comes from the actual checkpoint, with live logs for the detailed work.','Choose the same feature set, delivery scenario, network mode and fidelity requirement before comparing rankings.','Download the experiment reports and any paired-study tables. Each completed experiment has a timestamped snapshot, so later runs preserve earlier results.'][i]}</p></div>)}</div>}
        <footer><span><Radio size={13}/>Observatory · Research in view</span><span>Local data. Traceable results.</span></footer>
      </main>
    </div>
    {phase6Modal&&<Phase6ReplayModal initial={data?.configuration||{}} onClose={()=>setPhase6Modal(false)} onRun={replayPhase6}/>}
    {modal&&<NewExperiment settings={settings} connected={connection} onClose={()=>setModal(false)} onStart={onStart}/>}
    {stopConfirm&&<Modal title="Stop this experiment?" onClose={()=>setStopConfirm(false)}><p>The active pipeline and its child processes will stop. Completed checkpoint artifacts remain on disk.</p><div className="modal-actions"><button className="ghost" onClick={()=>setStopConfirm(false)}>Keep running</button><button className="primary danger-bg" onClick={stop}><Square size={14}/>Stop experiment</button></div></Modal>}
  </div>;
}

function Stat({title,value,suffix,icon:Icon,note,progress}) {return <div className="stat-card"><div className="stat-label">{title}<Icon size={17}/></div><div className="stat-value">{value}<span>{suffix}</span></div>{progress!=null&&<div className="progress-track"><i style={{width:`${progress*100}%`}}/></div>}<p>{progress===1&&<Check size={12}/>} {note}</p></div>;}

function DeliveryChart({rows,mode}) {
  const sorted=[...rows].sort((a,b)=>a.effective_delivery_seconds-b.effective_delivery_seconds);
  const max=Math.max(...sorted.map(r=>r.effective_delivery_seconds),.001);
  return <div className="panel delivery-chart"><div className="panel-heading"><div><h2>Delivery time by configuration</h2><p>Effective delivery · seconds · lower is better</p></div><Clock3 size={18}/></div>{sorted.length?<div className="bars">{sorted.map((r,i)=><div className="bar-row" key={r.package_id}><span>{candidate(r)}</span><div className="bar-track"><i className={i===0?'best':''} style={{width:`${Math.max(2,r.effective_delivery_seconds/max*100)}%`}}/></div><strong>{fmt(r.effective_delivery_seconds)}</strong></div>)}</div>:<Empty/>}<div className="chart-caption"><span className="legend-dot"/>{mode==='ssh'?'SSH transfer + receiver processing (see location in evidence)':'Measured local processing + idealized network transfer'}</div></div>;
}
function UtilityChart({rows}) {
  const low=Math.min(0,...rows.map(r=>r.R2_retained_variation_observed_STANDARDIZED));
  const maxBytes=Math.max(1,...rows.map(r=>r.total_transmitted_bytes));
  const y=v=>180-(v-low)/(1-low)*140;
  return <div className="panel utility-chart"><div className="panel-heading"><div><h2>Size meets utility</h2><p>Smaller payloads. Stronger reconstruction.</p></div><Activity size={18}/></div>{rows.length?<><svg viewBox="0 0 340 230" role="img" aria-label="Scatter plot of transmitted bytes versus reconstruction R squared">
    {[low,(1+low)/2,1].map(v=><g key={v}><line x1="42" x2="318" y1={y(v)} y2={y(v)} stroke="#e6eae5" strokeDasharray="4 4"/><text x="30" y={y(v)+4} textAnchor="end" fontSize="10" fill="#7b8782">{fmt(v,1)}</text></g>)}
    <text x="42" y="20" fontSize="10" fill="#6b7972">Reconstruction R² ↑</text>
    {rows.map(r=><circle key={r.package_id} cx={48+r.total_transmitted_bytes/maxBytes*255} cy={y(r.R2_retained_variation_observed_STANDARDIZED)} r="6" fill={r.method==='pca'?'#90a9ce':r.method==='autoencoder'?'#c6a36f':'#397966'} stroke="white" strokeWidth="2" opacity=".9"><title>{candidate(r)}: {bytes(r.total_transmitted_bytes)}, R² {fmt(r.R2_retained_variation_observed_STANDARDIZED,3)}</title></circle>)}
    <text x="46" y="203" fontSize="10" fill="#7b8782">0</text><text x="310" y="203" fontSize="10" fill="#7b8782" textAnchor="end">{bytes(maxBytes)}</text><text x="175" y="224" textAnchor="middle" fontSize="10" fill="#7b8782">Total transmitted size →</text>
    </svg><div className="chart-legend"><span><i style={{background:'#397966'}}/>Lossless</span><span><i style={{background:'#90a9ce'}}/>PCA</span><span><i style={{background:'#c6a36f'}}/>Autoencoder</span></div></>:<Empty/>}</div>;
}

function PhaseView({data,selected,onSelect}) {
  const current=data.phases.find(p=>p.id===selected)||data.phases[0];
  const n=Number(current.id.slice(-1));
  const details=usePhaseDetails(data.id,current.id,data.status);
  const [expanded,setExpanded]=useState(null);
  useEffect(()=>setExpanded(null),[data.id,current.id]);
  let rows=[],columns=[];
  if(n<=3){rows=data.overview.filter(r=>String(r.phase)===String(n));columns=['configuration','metric','value','unit'];}
  else if(n===4||n===5){rows=data.evidence.filter(r=>r.delivery_scenario==='fresh_data');columns=n===4?['dataset','method','k','codec','initial_encode_seconds','initial_payload_creation_seconds','model_fit_seconds']:['dataset','method','k','R2_retained_variation_observed_STANDARDIZED','knn5_overlap_original_vs_reconstruction','clinical_predictor_retention_pct','clinical_screen_new_violation_pct'];}
  else {rows=data.trials;columns=['dataset','method','k','codec','network_mode','transport_method','trial','successful_send_seconds','transfer_seconds','scp_seconds','attempts','recovery_overhead_seconds','delivery_wall_seconds','transfer_seconds_SIMULATED_IDEAL'];}
  const titles={R2_retained_variation_observed_STANDARDIZED:'Reconstruction R²',knn5_overlap_original_vs_reconstruction:'kNN overlap',clinical_predictor_retention_pct:'Predictor retention %',clinical_screen_new_violation_pct:'New violations %',initial_encode_seconds:'Encoding (s)',initial_payload_creation_seconds:'Payload creation (s)',model_fit_seconds:'Model fitting (s)',transfer_seconds_SIMULATED_IDEAL:'Simulated transfer (s)',scp_seconds:'SCP transfer (s)'};
  return <><div className="phase-tabs">{data.phases.map((p,i)=><button key={p.id} className={current.id===p.id?'active':''} onClick={()=>onSelect(p.id)}><span>0{i+1}</span>{p.title}</button>)}</div><div className="panel phase-detail"><div><div className="eyebrow">PHASE 0{n}</div><h2>{current.title}</h2><p>{current.description}</p></div><div className="phase-detail-stats"><Badge status={current.status}/><span>{seconds(current.seconds)} <small>elapsed</small></span><span>{current.completed}<small>completed stages</small></span></div></div><div className="panel"><div className="panel-heading"><div><h2>Phase measurements</h2><p>{n>=4?'Aggregate measurements for each tested configuration.':'Original phase outputs, kept in their recorded units.'}</p></div><span className="soft-tag">{rows.length} rows</span></div>{rows.length?<div className="table-scroll"><table className="phase-table"><thead><tr><th>Details</th>{columns.map(c=><th key={c}>{titles[c]||label(c)}</th>)}</tr></thead><tbody>{rows.slice(0,200).map((r,i)=><React.Fragment key={i}><tr><td><button className="record-button" aria-label={`Expand measurement ${r.metric||r.method||i+1}`} aria-expanded={expanded===i} onClick={()=>setExpanded(expanded===i?null:i)}>{expanded===i?<ChevronDown size={13}/>:<ChevronRight size={13}/>}View</button></td>{columns.map(c=><td key={c}>{typeof r[c]==='number'?fmt(r[c],4):label(r[c])}</td>)}</tr>{expanded===i&&<tr className="expanded-record"><td colSpan={columns.length+1}><RelatedRecord row={r} phase={current.id} details={details}/></td></tr>}</React.Fragment>)}</tbody></table></div>:<Empty text="This phase's aggregate results become available after the final reports are generated. Follow live logs while it runs."/>}</div><PhaseReportExplorer details={details}/>{current.stages.length>0&&<details className="panel stages-detail"><summary>Checkpoint stages <span>{current.stages.length}</span></summary>{current.stages.map(s=><div key={s.name}><code>{s.name}</code><Badge status={s.status}/><span>{seconds(s.seconds)}</span>{s.error&&<p role="alert">{s.error}</p>}</div>)}</details>}</>;
}

function Modal({title,onClose,children}) {
  const ref=useRef(null);
  const closeRef=useRef(onClose); closeRef.current=onClose;
  useEffect(()=>{const previous=document.activeElement;ref.current?.focus();const handler=e=>{if(e.key==='Escape')closeRef.current();if(e.key==='Tab'){const nodes=[...ref.current.querySelectorAll('button:not(:disabled),input,select,[tabindex="0"]')];if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1)?.focus();}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0]?.focus();}}};document.addEventListener('keydown',handler);return()=>{document.removeEventListener('keydown',handler);previous?.focus();};},[]);
  return <div className="modal-backdrop" onMouseDown={e=>e.target===e.currentTarget&&onClose()}><section className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref} tabIndex={-1}><div className="modal-heading"><div><div className="eyebrow">EXPERIMENT WORKSPACE</div><h2>{title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={20}/></button></div>{children}</section></div>;
}
function TransportStudies({studies}) {
  if (!studies || !Object.values(studies).some(rows=>rows?.length)) return null;
  return <section className="panel"><h2>Transport study results</h2>
    {[['paired_rankings','Four-block baseline TOPSIS'],['adaptive_rankings','Original baseline TOPSIS']].map(([key,title])=>studies[key]?.length>0&&<details key={key} open={key==='paired_rankings'}><summary>{title}</summary><p>Compressed formats ranked separately for each transport with equal weights for size reduction, mean preparation time and mean copy time.</p><table><thead><tr>{['Transport','Rank','Format','TOPSIS score','Mean copy (s)'].map(v=><th key={v}>{v}</th>)}</tr></thead><tbody>{studies[key].map(row=><tr key={row.transport_method+row.format}><td>{row.transport_method||'Historical'}</td><td>{row.rank}</td><td>{row.format}</td><td>{fmt(row.topsis_score,4)}</td><td>{fmt(row.transfer_mean_seconds)}</td></tr>)}</tbody></table></details>)}
    {[['baseline','Direct baseline files'],['archives','Prepared archives and interruptions']].map(([key,title])=>studies[key]?.length>0&&<details key={key}><summary>{title}</summary><p>Median difference in time to verified delivery within matched blocks. Negative values favour rsync.</p><table><thead><tr>{['Artifact','Condition','Verified / scheduled','Matched pairs','rsync − SCP (s)'].map(v=><th key={v}>{v}</th>)}</tr></thead><tbody>{studies[key].map(row=><tr key={row.artifact+row.condition}><td>{row.artifact}</td><td>{row.condition}</td><td>{row.verified} / {row.scheduled}</td><td>{row.matched_pairs}</td><td>{row.median_wall_difference_seconds==null?'—':fmt(row.median_wall_difference_seconds)}</td></tr>)}</tbody></table></details>)}
  </section>;
}

function TransportSelect({value,onChange}) {
  return <label className="form-field">SSH file transfer<select value={value} onChange={e=>onChange(e.target.value)}>
    <option value="scp">SCP</option><option value="rsync">rsync over SSH</option>
    <option value="both">Compare both on the same files</option></select></label>;
}
function Phase6ReplayModal({initial,onClose,onRun}) {
  const [transport,setTransport]=useState(initial.ssh_transport||'scp');
  const [remote,setRemote]=useState(initial.remote||'');
  const [remoteDir,setRemoteDir]=useState(initial.remote_dir||'/tmp/thesis_transfer/phase6');
  const [script,setScript]=useState(initial.remote_receiver_script||'');
  const [python,setPython]=useState(initial.remote_python||'python3');
  const [port,setPort]=useState(initial.ssh_port||22);
  const [timeout,setTimeoutSeconds]=useState(initial.remote_reconstruction_timeout||900);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function submit(e) {e.preventDefault();setBusy(true);setError('');
    try {await onRun({ssh_transport:transport,remote:remote.trim(),remote_dir:remoteDir.trim(),
      remote_receiver_script:script.trim(),remote_python:python.trim(),
      ssh_port:Number(port),remote_reconstruction_timeout:Number(timeout)});
    } catch(err) {setError(err.message);setBusy(false);}
  }
  return <Modal title="Re-run Phase 6 on university server" onClose={onClose}>
    <p className="modal-intro">Reuse the original Phases 1–5 checkpoints. All Phase 6 packages are re-transferred, reconstructed on the SSH server and ranked again with TOPSIS. Previous result snapshots remain available on disk.</p>
    <form onSubmit={submit}>
      <div className="form-grid">
        <TransportSelect value={transport} onChange={setTransport}/>
        <label className="form-field">SSH destination <input aria-label="Phase 6 SSH destination" required value={remote} onChange={e=>setRemote(e.target.value)} placeholder="user@university-host"/></label>
        <label className="form-field">SSH port <input aria-label="Phase 6 SSH port" required type="number" min="1" max="65535" value={port} onChange={e=>setPort(e.target.value)}/></label>
        <label className="form-field">Server receiver script <input aria-label="Phase 6 remote receiver script" required value={script} onChange={e=>setScript(e.target.value)} placeholder="/home/USER/thesis_receiver/receiver_reconstruct.py"/></label>
        <label className="form-field">Server Python executable <input aria-label="Phase 6 remote Python" required value={python} onChange={e=>setPython(e.target.value)} placeholder="/home/USER/thesis_receiver/.venv/bin/python"/></label>
        <label className="form-field">Remote package directory <input aria-label="Phase 6 remote directory" required value={remoteDir} onChange={e=>setRemoteDir(e.target.value)}/></label>
        <label className="form-field">Server reconstruction timeout (seconds) <input aria-label="Phase 6 reconstruction timeout" type="number" required min="1" max="86400" value={timeout} onChange={e=>setTimeoutSeconds(e.target.value)}/></label>
      </div>
      {error&&<div className="alert error" role="alert">{error}</div>}
      <div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{busy?'Starting Phase 6…':'Run Phase 6 + TOPSIS'}</button></div>
    </form>
  </Modal>;
}

function NewExperiment({settings,connected,onClose,onStart}) {
  const [dataset,setDataset]=useState(settings?.datasets?.[0]||'');
  const [k,setK]=useState('2, 4, 8');const [iterations,setIterations]=useState(500);
  const [coverage,setCoverage]=useState('0.75');const [features,setFeatures]=useState('clinical');const [mode,setMode]=useState('simulated');const [remote,setRemote]=useState('');const [codecs,setCodecs]=useState(false);
  const [sshPort,setSshPort]=useState(22);const [remoteDir,setRemoteDir]=useState('/tmp/thesis_transfer/phase6');const [attempts,setAttempts]=useState(3);const [deadline,setDeadline]=useState(300);
  const [transport,setTransport]=useState('scp');
  const [paired,setPaired]=useState(false);
  const [receiverExecution,setReceiverExecution]=useState('local');
  const [remoteReceiverScript,setRemoteReceiverScript]=useState('');
  const [remotePython,setRemotePython]=useState('python3');
  const [remoteReconstructionTimeout,setRemoteReconstructionTimeout]=useState(900);
  const [busy,setBusy]=useState(false);const [datasetBusy,setDatasetBusy]=useState(false);const [error,setError]=useState('');
  const [advanced,setAdvanced]=useState(optionalDefaults);
  const [weightMode,setWeightMode]=useState('equal');
  const [weights,setWeights]=useState(Array(7).fill('14.285714'));
  const numericWeights=weights.map(Number);
  const weightTotal=numericWeights.reduce((a,b)=>a+b,0);
  const weightsError=weightMode==='custom'?(weights.some(v=>v.trim()==='')?'Enter all seven weights.':numericWeights.some(v=>!Number.isFinite(v)||v<0||v>100)?'Each weight must be between 0% and 100%.':Math.abs(weightTotal-100)>0.00001?'Weights must total 100%.':''):'';
  const disabled=!connected||settings?.api_version!==4||!settings?.topsis_weight_controls||!settings?.experiment_options_controls||!settings?.ae_acceleration_controls||!settings?.transport_controls||settings?.missing_dependencies?.length>0;
  async function submit(e){e.preventDefault();if(weightsError){setError(weightsError);return;}setBusy(true);setError('');try{await onStart({dataset,paired_transport_studies:mode==='ssh'&&transport==='both'&&paired,ssh_transport:mode==='ssh'?transport:'scp',k:k.trim()?k.split(',').map(v=>Number(v.trim())):[2,4,8],ae_max_iter:iterations===''?500:Number(iterations),patient_coverage_min:Number(coverage),feature_sets:features==='all'?'all':'clinical',transfer_mode:mode,remote,ssh_port:sshPort===''?22:Number(sshPort),remote_dir:remoteDir.trim()||'/tmp/thesis_transfer/phase6',ssh_max_attempts:attempts===''?3:Number(attempts),ssh_transfer_timeout:deadline===''?300:Number(deadline),compare_npz_codecs:codecs,topsis_weights:weightMode==='equal'?Array(7).fill(1/7):numericWeights.map(v=>v/weightTotal),...advanced,receiver_execution:mode==='ssh'?receiverExecution:'local',remote_receiver_script:mode==='ssh'&&receiverExecution==='remote'?remoteReceiverScript.trim():null,remote_python:mode==='ssh'&&receiverExecution==='remote'?remotePython.trim():'python3',remote_reconstruction_timeout:Number(remoteReconstructionTimeout)});}catch(err){setError(err.message);setBusy(false);}}
  function applyThesisSettings(){
    setMode('ssh');setTransport('both');setPaired(true);setK('2, 4, 8, 16');setFeatures('all');
    setIterations(500);setCoverage('0.75');setCodecs(false);setWeightMode('equal');setAttempts(3);
    setReceiverExecution('remote');setAdvanced({...optionalDefaults(),packaging_runs:10,ae_backend:'gpu',ae_batch_size:4096});
  }
  return <Modal title="New experiment" onClose={onClose}><p className="modal-intro">Required fields are marked below. Optional fields have defaults; change only what your experiment needs.</p><form onSubmit={submit} onInvalid={e=>e.target.closest('details')?.setAttribute('open','')}>
    <button type="button" className="ghost" onClick={applyThesisSettings}>Use thesis experiment settings</button><p>Runs all feature sets, both transports and the paired interruption study. The thesis used GPU training and server reconstruction. Enter your receiver details below.</p>
    <label className="form-field">Dataset CSV <span className="field-status required">Required</span><input list="datasets" required placeholder="/path/to/clinical_dataset.csv" value={dataset} onChange={e=>setDataset(e.target.value)}/><datalist id="datasets">{settings?.datasets.map(d=><option key={d} value={d}/>)}</datalist><small>Choose a discovered file, enter a CSV path, or upload below.</small></label>
    <DatasetInputTools dataset={dataset} onDataset={setDataset} connected={connected} onBusy={setDatasetBusy}/>
    <div className="form-grid"><label className="form-field">PCA / AE components <span className="field-status">Optional · default 2, 4, 8</span><input value={k} onChange={e=>setK(e.target.value)} placeholder="2, 4, 8"/><small>Comma-separated component counts</small></label><label className="form-field">Autoencoder iteration limit <span className="field-status">Optional · default 500</span><input type="number" min="1" max="10000" value={iterations} onChange={e=>setIterations(e.target.value)}/><small>Higher limits may take longer</small></label></div>
    <label className="form-field">Feature sets <span className="field-status">Optional · clinical review</span><select aria-label="Feature sets" value={features} onChange={e=>setFeatures(e.target.value)}><option value="clinical">Original + clinical review at highest cutoff</option><option value="all">Original + all feature sets</option></select></label>
    <label className="form-field">Patient coverage criterion <span className="field-status">Optional · default 75%</span><select aria-label="Patient coverage criterion" value={coverage} onChange={e=>setCoverage(e.target.value)}><option value="0.75">75%</option><option value="0.8">80%</option><option value="0.9">90%</option></select><small>Phase 3 clinical-review safeguard: retain sparse features observed in at least this percentage of patients. This does not sample or remove patient rows.</small></label>
    <fieldset className="weight-editor"><legend>Final-decision TOPSIS weights</legend>
      <label className="form-field">Weight allocation <span className="field-status">Optional · equal by default</span><select aria-label="Weight allocation" value={weightMode} onChange={e=>setWeightMode(e.target.value)}><option value="equal">Equal weights (default)</option><option value="custom">Custom percentages</option></select></label>
      <p>Equal weights give each of the seven criteria exactly 1/7 (about 14.2857%). Custom percentages must total 100%; a zero weight excludes a criterion from the score.</p>
      <div className="form-grid">{TOPSIS_CRITERIA.map(([key,name,direction],i)=><label className="form-field" key={key}>{name}<input aria-label={`${name} weight (%)`} type="number" min="0" max="100" step="any" required disabled={weightMode==='equal'} value={weightMode==='equal'?'14.285714':weights[i]} onChange={e=>setWeights(old=>old.map((v,j)=>j===i?e.target.value:v))}/><small>% · {direction} · {weightMode==='custom'?'Required in custom mode':'Default equal share'}</small></label>)}</div>
      <p aria-live="polite">{weightMode==='equal'?'Total: 100% · equal shares stored at full precision':`Total: ${fmt(weightTotal,6)}%`}</p>
      {weightsError&&<p className="weight-error" role="alert">{weightsError}</p>}
      <small>These weights apply to the final seven-criterion decision. Phase 2’s separate baseline ranking uses three equally weighted criteria. The existing comparison profiles remain available in Results & rankings.</small>
    </fieldset>
    <fieldset className="network-choice"><legend>Network delivery <span className="field-status">Optional · simulated by default</span></legend><label className={mode==='simulated'?'chosen':''}><input type="radio" name="network" checked={mode==='simulated'} onChange={()=>setMode('simulated')}/><div><strong>Simulated</strong><small>Idealized network · no SSH connection</small></div><FlaskConical size={18}/></label><label className={mode==='ssh'?'chosen':''}><input type="radio" name="network" checked={mode==='ssh'} onChange={()=>setMode('ssh')}/><div><strong>Strict SSH</strong><small>Real transfer · fails if unreachable</small></div><ShieldCheck size={18}/></label></fieldset>
    {mode==='ssh'&&<><label className="form-field">SSH destination <span className="field-status required">Required for SSH</span><input required value={remote} onChange={e=>setRemote(e.target.value)} placeholder="user@host"/><small>Requires existing key authentication and a trusted host key. No simulated fallback.</small></label><details className="ssh-settings"><summary>Connection and recovery settings</summary><div className="form-grid"><label className="form-field">SSH port <span className="field-status">Optional · default 22</span><input aria-label="SSH port" type="number" min="1" max="65535" value={sshPort} onChange={e=>setSshPort(e.target.value)}/></label><label className="form-field">Maximum attempts per trial <span className="field-status">Optional · default 3</span><input aria-label="Maximum attempts per trial" type="number" min="1" max="10" value={attempts} onChange={e=>setAttempts(e.target.value)}/></label></div><label className="form-field">Remote directory <span className="field-status">Optional · /tmp/thesis_transfer/phase6</span><input aria-label="Remote directory" value={remoteDir} onChange={e=>setRemoteDir(e.target.value)}/></label><label className="form-field">Transfer deadline (seconds) <span className="field-status">Optional · default 300</span><input aria-label="Transfer deadline (seconds)" type="number" min="1" max="86400" value={deadline} onChange={e=>setDeadline(e.target.value)}/><small>Transient failures retry after increasing delays. Authentication and checksum errors need your attention. Interrupted trials restart from the beginning.</small></label></details></>}
    {mode==='ssh'&&<TransportSelect value={transport} onChange={setTransport}/>}
    {mode==='ssh'&&transport==='both'&&<label className="form-field"><span><input type="checkbox" checked={paired} onChange={e=>{setPaired(e.target.checked);if(e.target.checked){if(!k.split(',').some(v=>Number(v)===16))setK(k.trim()?k+', 16':'2, 4, 8, 16');if(Number(attempts)<2)setAttempts(3);}}}/> Include paired baseline and interruption studies</span><small>40 direct file transfers and 32 archive deliveries in four blocks. Includes a controlled interruption on AE-16. Requires 16 feasible components in the original data.</small></label>}
    {mode==='ssh'&&<fieldset className="receiver-choice"><legend>Phase 6 receiver reconstruction <span className="field-status">Where to decode the transferred package</span></legend>
      <label className="form-field">Reconstruction location <select aria-label="Receiver execution" value={receiverExecution} onChange={e=>setReceiverExecution(e.target.value)}><option value="local">Local verification on laptop (previous behavior)</option><option value="remote">University server (SSH execution)</option></select><small>Remote reconstructs after verified SCP, using the installed server-side decoder. Phase 5 research-utility reconstruction still runs locally.</small></label>
      {receiverExecution==='remote'&&<div className="form-grid">
        <label className="form-field">Server receiver script <span className="field-status required">Required</span><input aria-label="Remote receiver script" required value={remoteReceiverScript} onChange={e=>setRemoteReceiverScript(e.target.value)} placeholder="/home/USER/thesis_receiver/receiver_reconstruct.py"/><small>Absolute path to receiver_reconstruct.py on the university server.</small></label>
        <label className="form-field">Server Python executable <span className="field-status required">Required</span><input aria-label="Remote Python" required value={remotePython} onChange={e=>setRemotePython(e.target.value)} placeholder="/home/USER/thesis_receiver/.venv/bin/python"/><small>Use the server's Python virtual environment.</small></label>
        <label className="form-field">Receiver reconstruction timeout (seconds)<input aria-label="Remote reconstruction timeout" required type="number" min="1" max="86400" value={remoteReconstructionTimeout} onChange={e=>setRemoteReconstructionTimeout(e.target.value)}/></label>
      </div>}
    </fieldset>}
    <ExperimentOptions values={advanced} onChange={setAdvanced} mode={mode}/>
    <button type="button" className="ghost" onClick={()=>setAdvanced(optionalDefaults())}>Reset optional settings</button>
    <p className="modal-intro">Phase 2: up to {advanced.phase2_transfer_trials||10} transfer trials with a {advanced.phase2_repeat_threshold_seconds||10}-second first-transfer cutoff. Phase 6: up to {advanced.transfer_trials||10} trials with a {advanced.phase6_repeat_threshold_seconds||10}-second cutoff. Packaging: {advanced.packaging_runs||3} fixed runs. A retry repeats a failed trial attempt; it does not count as an additional completed trial.</p>
    <label className="checkbox"><input type="checkbox" checked={codecs} onChange={e=>setCodecs(e.target.checked)}/><span>Compare native, gzip and zstd NPZ codecs <span className="field-status">Optional · off by default</span></span></label><div className="form-note"><CheckCircle2 size={15}/>Selected delivery scenarios: {advanced.delivery_scenarios.map(v=>v==='fresh_data'?'fresh data':'existing payload').join(' and ')||'none — select at least one' }.</div>
    {disabled&&<div className="alert error">{connected&&(settings?.api_version!==4||!settings?.topsis_weight_controls||!settings?.experiment_options_controls||!settings?.ae_acceleration_controls||!settings?.transport_controls)?'Restart your updated server.py to use these experiment controls.':connected?`Missing Python dependencies: ${settings.missing_dependencies.join(', ')}. Start the server from the pipeline's environment.`:'Connect the local Python server to start an experiment. You can still explore the demo.'}</div>}
    {error&&<div className="alert error" role="alert">{error}</div>}
    <div className="modal-actions"><button type="button" className="ghost" onClick={onClose}>Cancel</button><button className="primary" disabled={disabled||busy||datasetBusy||Boolean(weightsError)}>{busy?<LoaderCircle size={16} className="spin"/>:<Play size={16}/>} {busy?'Starting…':'Start experiment'}</button></div>
  </form></Modal>;
}

createRoot(document.getElementById('root')).render(<App/>);
