import React, { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Database, Eye, LoaderCircle, Upload } from 'lucide-react';

const display = value => value === null || value === undefined || value === '' ? '—' : typeof value === 'boolean' ? (value?'Yes':'No') : typeof value === 'object' ? JSON.stringify(value) : String(value);
const title = value => value.replaceAll('_',' ');
async function jsonRequest(url, options) {
  const response=await fetch(url,options);
  const body=await response.json();
  if(!response.ok){
    if(response.status===404&&['Report not found','Endpoint not found'].includes(body.error))
      throw new Error('The running dashboard server needs an update. Restart server.py, then refresh this page to use dataset previews and phase details.');
    throw new Error(body.error||'Unable to load this dataset or report');
  }
  return body;
}

export function RecordFields({record}) {
  return <dl className="record-fields">{Object.entries(record).map(([key,value])=><div key={key}><dt>{title(key)}</dt><dd>{display(value)}</dd></div>)}</dl>;
}

export function DatasetPreview({runId, path}) {
  const [offset,setOffset]=useState(0), [data,setData]=useState(null), [error,setError]=useState('');
  const [loading,setLoading]=useState(true), [columnSearch,setColumnSearch]=useState(''), [expanded,setExpanded]=useState(null);
  const [revision,setRevision]=useState(0);
  useEffect(()=>{setOffset(0);setExpanded(null);setColumnSearch('');},[runId,path]);
  useEffect(()=>{
    let active=true;setLoading(true);setError('');setData(null);setExpanded(null);
    const request=runId?jsonRequest(`/api/runs/${runId}/dataset?offset=${offset}&limit=25`):jsonRequest('/api/datasets/preview',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,offset,limit:25})});
    request.catch(async e=>{
      if(runId!=='demo')throw e;
      const demo=await jsonRequest('/demo-dataset.json');
      return {...demo,offset,rows:demo.rows.slice(offset,offset+25),has_more:offset+25<demo.rows.length};
    }).then(result=>{if(active)setData(result);}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[runId,path,offset,revision]);
  const visible=data?.columns.map((name,index)=>({name,index})).filter(c=>c.name.toLowerCase().includes(columnSearch.toLowerCase()))||[];
  return <section className="panel dataset-preview" aria-label="Dataset preview">
    <div className="panel-heading"><div><h2><Database size={17}/> Dataset preview</h2><p>{data?`${data.name} · ${data.column_count} columns · ${(data.bytes/1024).toFixed(1)} KB`:'Read-only view of the selected CSV'}</p></div><span className="soft-tag">{runId==='demo'?'Synthetic data':'Local CSV · read only'}</span></div>
    <div className="preview-notice">Values are shown as stored, including empty cells and leading zeros. Open a record to see every displayed column.</div>
    {loading&&<div className="loading"><LoaderCircle className="spin" size={20}/>Reading dataset…</div>}
    {error&&<div className="alert error" role="alert">{error}<button type="button" className="ghost" onClick={()=>setRevision(v=>v+1)}>Retry preview</button></div>}
    {data&&<>
      {data.matches_run_input===false&&<div className="alert error" role="alert">This CSV has changed since the experiment. This preview shows its current contents, not the original run input.</div>}
      {(data.row_width_mismatch||data.columns_truncated||data.cells_truncated)&&<div className="preview-notice">{data.row_width_mismatch?'Some rows have a different number of cells from the header. ':''}{data.columns_truncated?'Showing the first 200 columns. ':''}{data.cells_truncated?'Long cells are shortened to 1,000 characters.':''}</div>}
      <div className="table-toolbar"><label className="preview-search">Find columns<input aria-label="Find dataset columns" placeholder="e.g. HR, Lactate, patient_id" value={columnSearch} onChange={e=>setColumnSearch(e.target.value)}/></label><span className="soft-tag">{visible.length} visible columns</span></div>
      <div className="table-scroll dataset-scroll"><table><thead><tr><th>Record</th>{visible.map(c=><th key={c.index}>{c.name||`Column ${c.index+1}`}</th>)}</tr></thead><tbody>{data.rows.map((row,i)=><React.Fragment key={i}><tr><td><button className="record-button" aria-label={`View record ${offset+i+1}`} aria-expanded={expanded===i} onClick={()=>setExpanded(expanded===i?null:i)}>{expanded===i?<ChevronDown size={13}/>:<ChevronRight size={13}/>} {offset+i+1}</button></td>{visible.map(c=><td key={c.index}>{row[c.index]===undefined?<em className="missing-cell">not present</em>:row[c.index]===''?<em className="missing-cell">empty</em>:row[c.index]}</td>)}</tr>{expanded===i&&<tr className="expanded-record"><td colSpan={visible.length+1}><h3>Record {offset+i+1}</h3><dl className="record-fields">{data.columns.map((name,j)=><div key={j}><dt>{name||`Column ${j+1}`}</dt><dd>{display(row[j])}</dd></div>)}</dl></td></tr>}</React.Fragment>)}</tbody></table>{!data.rows.length&&<div className="empty"><h3>No data rows on this page</h3></div>}</div>
      <div className="table-footer pagination"><span>{data.rows.length?`Records ${offset+1}–${offset+data.rows.length}`:'No records'} · up to 25 per page</span><div><button type="button" className="ghost" disabled={offset===0||loading} onClick={()=>setOffset(Math.max(0,offset-25))}>Previous</button><button type="button" className="ghost" disabled={!data.has_more||loading} onClick={()=>setOffset(offset+25)}>Next</button></div></div>
    </>}
  </section>;
}

export function DatasetInputTools({dataset,onDataset,connected,onBusy}) {
  const [previewPath,setPreviewPath]=useState(null),[uploading,setUploading]=useState(false),[error,setError]=useState('');
  async function upload(file) {
    if(!file)return;
    setError('');
    if(!file.name.toLowerCase().endsWith('.csv')){setError('Please choose a CSV file.');return;}
    if(file.size>100*1024*1024){setError('Upload limit is 100 MB. Use the local CSV path for larger files.');return;}
    setUploading(true);onBusy?.(true);
    try{
      const result=await jsonRequest('/api/datasets/upload',{method:'POST',headers:{'Content-Type':'text/csv','X-Filename':encodeURIComponent(file.name)},body:file});
      onDataset(result.path);setPreviewPath(result.path);
    }catch(e){setError(e.message);}finally{setUploading(false);onBusy?.(false);}
  }
  return <div className="dataset-input-tools"><div className="dataset-input-actions">
    <label className={`upload-button ghost ${!connected||uploading?'disabled':''}`}><Upload size={15}/>{uploading?'Uploading…':'Upload CSV'}<input aria-label="Upload CSV" type="file" accept=".csv,text/csv" disabled={!connected||uploading} onChange={e=>{upload(e.target.files[0]);e.target.value='';}}/></label>
    <button type="button" className="ghost" disabled={!connected||!dataset||uploading} onClick={()=>setPreviewPath(dataset)}><Eye size={15}/>Preview CSV</button>
  </div><p className="input-help">Uploads stay in this dashboard’s local data folder. Maximum upload: 100 MB.</p>
  {error&&<div className="alert error" role="alert">{error}</div>}
  {previewPath===dataset&&<details className="input-preview" open><summary>Selected dataset preview</summary><DatasetPreview path={previewPath}/></details>}
  </div>;
}

export function usePhaseDetails(runId,phase,status) {
  const [value,setValue]=useState({groups:[]}),[error,setError]=useState(''),[loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;setValue({groups:[]});setError('');setLoading(true);
    async function refresh(){
      try{
        let result;
        try{result=await jsonRequest(`/api/runs/${runId}/phases/${phase}`);}catch(e){if(runId!=='demo')throw e;result=(await jsonRequest('/demo-phases.json'))[phase]||{groups:[]};}
        if(active){setValue(result);setError('');}
      }catch(e){if(active)setError(e.message);}finally{if(active)setLoading(false);}
    }
    refresh();const timer=status==='running'?setInterval(refresh,5000):null;
    return()=>{active=false;if(timer)clearInterval(timer);};
  },[runId,phase,status]);
  return {...value,error,loading};
}

export function ArtifactTable({group,compact=false}) {
  const [expanded,setExpanded]=useState(null),[query,setQuery]=useState('');
  useEffect(()=>{setExpanded(null);setQuery('');},[group?.id]);
  if(!group)return <p className="preview-notice">The supporting report is not available for this record.</p>;
  if(!group.available)return <p className="preview-notice">{group.source} is missing. No details can be inferred from the summary count alone.</p>;
  const filtered=group.rows.filter(r=>!query||Object.values(r).some(v=>display(v).toLowerCase().includes(query.toLowerCase())));
  return <div className="artifact-table">
    <div className="artifact-description"><strong>{group.title}</strong><p>{group.description}</p><small>Source: {group.source} · {group.rows.length}{group.truncated?'+':''} records</small></div>
    {!compact&&<label className="preview-search artifact-search">Filter report records<input aria-label="Filter phase details" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search a column name, format or decision…"/></label>}
    {filtered.length?<div className="table-scroll artifact-scroll"><table><thead><tr><th>Details</th>{group.columns.map(c=><th key={c}>{title(c)}</th>)}</tr></thead><tbody>{filtered.slice(0,200).map((r,i)=><React.Fragment key={i}><tr><td><button type="button" className="record-button" aria-label={`Expand detail record ${i+1}`} aria-expanded={expanded===i} onClick={()=>setExpanded(expanded===i?null:i)}>{expanded===i?<ChevronDown size={13}/>:<ChevronRight size={13}/>}View</button></td>{group.columns.map(c=><td key={c}>{display(r[c])}</td>)}</tr>{expanded===i&&<tr className="expanded-record"><td colSpan={group.columns.length+1}><RecordFields record={r}/></td></tr>}</React.Fragment>)}</tbody></table></div>:<p className="preview-notice">{query?'No records match your filter.':'The saved report contains no records.'}</p>}
    {(filtered.length>200||group.truncated)&&<p className="preview-notice">Showing up to 200 records from the first 1,000 report rows. Filter these records or inspect the original artifact for the complete report.</p>}
  </div>;
}

export function PhaseReportExplorer({details}) {
  const [selected,setSelected]=useState('');
  const group=details.groups.find(g=>g.id===selected)||details.groups[0];
  return <details className="panel report-explorer" open><summary><span>More phase information</span><span className="soft-tag">{details.groups.length} reports</span></summary>
    {details.loading?<div className="loading"><LoaderCircle size={18} className="spin"/>Loading phase artifacts…</div>:details.error?<p className="alert error" role="alert">{details.error}</p>:details.groups.length?<>
      <label className="form-field">Detail report<select aria-label="Phase detail report" value={group.id} onChange={e=>setSelected(e.target.value)}>{details.groups.map(g=><option key={g.id} value={g.id}>{g.title}{g.available?'':' (missing)'}</option>)}</select></label>
      <ArtifactTable group={group}/>
    </>:<p className="preview-notice">Detailed reports are not available yet. Completed phases expose their artifacts here when their output folders are available.</p>}
  </details>;
}

export function RelatedRecord({row,phase,details}) {
  let group;
  if(phase==='phase1') {
    const id={highly_correlated_pairs:'redundant',duplicate_groups:'duplicates',n_columns:'columns',overall_cell_missingness_pct:'columns',numeric_identifiers_excluded:'numeric'}[row.metric];
    group=details.groups.find(g=>g.id===(id||'summary'));
  }else if(phase==='phase2'){
    const source=details.groups.find(g=>g.id==='baseline');
    if(source)group={...source,rows:source.rows.filter(r=>r.format===row.configuration)};
  }else if(phase==='phase3')group=details.groups.find(g=>g.id==='selection-'+row.configuration);
  else if(phase==='phase4'){
    const source=details.groups.find(g=>g.id===row.dataset+'-features');
    if(source)group={...source,rows:source.rows.filter(r=>r.method===row.method&&Number(r.k)===Number(row.k))};
  }
  return <div className="measurement-detail"><h3>Selected measurement</h3><RecordFields record={row}/>{details.loading?<p>Loading supporting report…</p>:group?<ArtifactTable group={group} compact/>:<p className="preview-notice">All fields recorded for this measurement are shown above. Use “More phase information” for additional artifacts.</p>}</div>;
}
