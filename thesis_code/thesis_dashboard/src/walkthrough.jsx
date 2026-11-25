import React, {useState} from 'react';
import {ArrowLeft, ArrowRight} from 'lucide-react';
import study from './thesis_reference.json';
import './walkthrough.css';

const steps = [
  ['Profile', 'What is missing from an hourly record?', 'Objective 1 · Characterise the cohort'],
  ['Benchmark', 'How much can a change of format achieve?', 'Objective 2 · Establish the lossless baseline'],
  ['Select', 'Which measurements survive feature selection?', 'Objective 2 · Compare selection rules'],
  ['Reduce', 'How closely can a small code reconstruct a record?', 'Objective 2 · Compare representations'],
  ['Evaluate', 'Do reconstructed records keep their neighbours?', 'Objective 2 · Examine information preservation'],
  ['Deliver', 'When does the cost of fitting the model count?', 'Objective 3 · Verify transfer and receiver recovery'],
  ['Decide', 'Which package fits the receiver’s requirement?', 'Objective 4 · Recommend within a comparable group'],
];
const names = {original_source:'Source CSV', csv:'Rewritten CSV', csv_gzip:'CSV + gzip', parquet:'Parquet',
  csv_zstd:'CSV + Zstandard', pca:'PCA', autoencoder:'Autoencoder', gzip:'gzip', zstd:'Zstandard'};
const scenarios = {fresh_data:'Fresh data', existing_payload:'Existing payload'};
const requirements = {loss_tolerant:'Approximation allowed', selected_columns_exact:'Selected columns exact', full_fidelity:'Full source exact'};
const fmt = (v, digits=0) => v.toLocaleString('en-GB', {minimumFractionDigits:digits, maximumFractionDigits:digits});
const caption = key => key === 'original' ? 'Original source' : key.replace('FS_00_no_missingness_filter','No missingness filter')
  .replace(/^FS_(\d+)_/, '$1% · ').replace('clinical_review','protected').replace('missingness','missingness only');

function Table({title, columns, rows}) {
  return <div className="walk-table"><table><caption>{title}</caption><thead><tr>{columns.map(c=><th key={c} scope="col">{c}</th>)}</tr></thead>
    <tbody>{rows.map(([key,...values])=><tr key={key}><th scope="row">{key}</th>{values.map((v,i)=><td key={columns[i+1]}>{v}</td>)}</tr>)}</tbody></table></div>;
}
function Choice({title, options, value, change}) {
  return <label className="walk-choice">{title}<select value={value} onChange={e=>change(e.target.value)}>
    {Object.entries(options).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>;
}
function Insight({children}) { return <div className="walk-insight"><strong>Interpretation</strong><p>{children}</p></div>; }

export function Walkthrough({runs, onInspect}) {
  const archivedRun = runs.find(r=>r.snapshot===study.snapshot && (!r.run_id || r.run_id===study.run));
  const [step,setStep] = useState(0);
  const [k,setK] = useState('16');
  const [threshold,setThreshold] = useState('80');
  const [transport,setTransport] = useState('scp');
  const [delivery,setDelivery] = useState('fresh_data');
  const [requirement,setRequirement] = useState('loss_tolerant');
  const cohort = study.profile;
  const models = Object.entries(study.models[k]);
  const winners = study.winners.filter(r=>r.delivery_scenario===delivery && r.scenario===requirement)
    .sort((a,b)=>Number(b.dataset==='original')-Number(a.dataset==='original') || a.dataset.localeCompare(b.dataset));
  const wins = new Map();
  for (const row of winners) wins.set(row.method,(wins.get(row.method) || 0) + 1);
  const winnerSummary = [...wins.entries()].map(([method,count])=>names[method]+' ('+count+' of '+winners.length+')').join(', ');
  const widthChoice = <Choice title="Latent dimensions" options={{2:2,4:4,8:8,16:16}} value={k} change={setK}/>;
  const scenarioChoice = <Choice title="Payload at dispatch" options={scenarios} value={delivery} change={setDelivery}/>;
  return <section className="walk" aria-label="Recorded thesis walkthrough">
    <p className="walk-source"><strong>Recorded experiment</strong> PhysioNet 2019 Set A · Workstation to the KNUST server in Kumasi · Chapter 4</p>
    <nav className="walk-steps" aria-label="Walkthrough steps">{steps.map(([name],i)=>
      <button key={name} aria-current={step===i?'step':undefined} onClick={()=>setStep(i)}>{i<6?'Phase '+(i+1):'Decision'}<b>{name}</b></button>)}</nav>
    <article className="panel walk-panel" aria-live="polite">
      <header><p>{steps[step][2]}</p><h2>{steps[step][1]}</h2></header>
      {step===0&&<>
        <Table title="Prepared sepsis cohort" columns={['Profile','Result']} rows={[
          ['Patients','20,336'],['Hourly records',fmt(cohort.n_rows)],['Columns',fmt(cohort.n_columns)],
          ['Missing cells',fmt(cohort.overall_cell_missingness_pct,2)+'%'],['Highly correlated pairs (|r| ≥ 0.95)',cohort.highly_correlated_pairs]]}/>
        <Insight>Hourly missingness counts rows. Patient coverage counts people with at least one measurement. Lactate was missing from 96.57% of hourly rows, yet removing its column would discard every recorded lactate value.</Insight>
        <details><summary>Inspect the four correlated pairs</summary><Table title="Pearson correlation on jointly observed rows (Chapter 4)" columns={['Variables','r','Paired rows']} rows={[
          ['Unit1 / Unit2','−1.0000','404,050'],['time / ICULOS','0.9905','790,215'],['Bilirubin_direct / Bilirubin_total','0.9621','892'],['Hct / Hgb','0.9620','68,504']]}/>
          <p>The pairs prompted review. No variable was automatically removed on this evidence in the reported study.</p></details>
      </>}
      {step===1&&<>
        <Table title="Direct files · original adaptive SCP benchmark" columns={['Representation','Size (decimal MB)','Mean preparation (s)','Mean copy (s)']}
          rows={Object.entries(study.baseline).map(([key,r])=>[names[key],fmt(r.file_bytes/1e6,2),fmt(r.packaging_mean_seconds,2),fmt(r.transfer_mean_seconds,2)])}/>
        <Choice title="Paired baseline transport" options={{scp:'SCP',rsync:'rsync'}} value={transport} change={setTransport}/>
        <Table title={'Separate paired study · '+study.direct_trials+' verified transfers across both transports'} columns={['Compressed format','Equal-weight TOPSIS']}
          rows={Object.entries(study.baseline_scores[transport]).sort((a,b)=>b[1]-a[1]).map(([key,v])=>[names[key],fmt(v,3)])}/>
        <Insight>Parquet led on size reduction, preparation time and mean copy time. Each transport has its own ranking. The direct-file copy clock excludes the separately timed checksum check.</Insight>
      </>}
      {step===2&&<>
        <Choice title="Hourly missingness threshold" options={{80:'80%',90:'90%',95:'95%'}} value={threshold} change={setThreshold}/>
        <Table title="Selection from 40 candidate predictors" columns={['Selection rule','Predictors retained']} rows={[
          ['Missingness only',study.retained['FS_'+threshold+'_missingness']],['With protection rules',study.retained['FS_'+threshold+'_clinical_review']]]}/>
        <Insight>The review rule can rescue sparse fields through patient coverage (here {fmt(study.coverage*100)}%) or explicit protection, including Lactate. Exact recovery of a selected file preserves only the columns that survived selection.</Insight>
      </>}
      {step===3&&<>{widthChoice}
        <Table title="Original feature set · observed standardised variation" columns={['Model','Reconstruction R²']} rows={models.map(([key,r])=>[names[key],fmt(r.r2,3)])}/>
        <p className="walk-equation">Observed R² = 1 − (standardised squared reconstruction error / standardised variation about observed means)</p>
        <Insight>PCA projects onto orthogonal directions of greatest variance. The autoencoder learns a nonlinear encoder and decoder. R² measures the reduction in squared error against predicting each variable’s observed mean. It can be negative if reconstruction does worse.</Insight>
      </>}
      {step===4&&<>{widthChoice}
        <Table title="Original feature set · neighbourhood and range checks" columns={['Model','Mean 5-neighbour overlap','New range flags (cells)']}
          rows={models.map(([key,r])=>[names[key],fmt(r.overlap,3),fmt(r.flags)])}/>
        <Insight>An overlap of 0.8 means four of five neighbours are retained on average. The comparison uses one hourly record per sampled patient in a common scaled feature space. Range flags count originally in-range measurements reconstructed outside a screening bound. Neither measure establishes clinical validity.</Insight>
      </>}
      {step===5&&<>{scenarioChoice}
        <Table title={'Original feature set · two latent dimensions · '+scenarios[delivery]} columns={['Model','Effective delivery (s)']}
          rows={Object.entries(study.models[2]).map(([key,r])=>[names[key],fmt(r[delivery],2)])}/>
        <p className="walk-equation">Delivery = package + transmit + verify + unpack + recover</p>
        <Insight>{delivery==='fresh_data'?'Fresh data charges initial payload preparation, including model fitting allocated to this delivery (one use), encoding and initial file creation where applicable. The autoencoder fit took about 609 seconds at two dimensions on the study GPU. PCA ran on the CPU.':'An existing payload is an already encoded or compressed file ready to package. The sender still builds the delivery package, and the receiver still verifies, unpacks and recovers it.'}</Insight>
        <details><summary>Compare interruption recovery for SCP and rsync</summary><p>The separate archive experiment comprised {study.archive_trials} verified deliveries. Across {study.archive_pairs} matched interrupted AE-16 pairs, the median within-pair difference (rsync − SCP) was {fmt(study.archive_delta,2)} s. Rsync could reuse partial data. This clock stopped at verified publication, before unpacking or reconstruction.</p></details>
      </>}
      {step===6&&<>
        <div className="walk-controls">{scenarioChoice}<Choice title="Receiver fidelity" options={requirements} value={requirement} change={setRequirement}/></div>
        <Table title="First within each feature set · equal weights · verified SCP" columns={['Feature set','First-ranked format','TOPSIS closeness']}
          rows={winners.map(r=>[caption(r.dataset),names[r.method],fmt(r.score,3)])}/>
        <p><strong>First-ranked formats for this choice</strong> {winnerSummary}.</p>
        <p className="walk-equation">Closeness = distance to the worst ideal / (distance to the best ideal + distance to the worst ideal)</p>
        <Insight>TOPSIS balances two delivery costs (bytes and time), four benefits (R², neighbour overlap, predictor and measurement retention) and the cost of new range flags. Higher closeness is preferable within the same pool. Requiring the full source rules out feature deletion.</Insight>
        <p>{study.packages} recovered packages · {study.comparisons} package–scenario comparisons · {study.package_trials} verified SCP trials. The archive follow-up supports an interruption comparison on one route. It does not supply a full rsync package ranking.</p>
      </>}
      {archivedRun&&<button className="text-button" onClick={()=>onInspect(archivedRun.id,step,delivery,requirement)}>
        {step===6?'Inspect the recorded ranking table':'Inspect this phase in the recorded experiment'}<ArrowRight size={14}/></button>}
      <footer><button className="secondary" disabled={step===0} onClick={()=>setStep(step-1)}><ArrowLeft size={15}/>Previous</button>
        <span>{step+1} of {steps.length}</span><button className="primary" onClick={()=>setStep(step===6?0:step+1)}>{step===6?'Start again':'Next step'}<ArrowRight size={15}/></button></footer>
    </article>
    <details className="walk-provenance"><summary>Evidence and provenance</summary><p>Study population and correlation examples are from Chapter 4. The tables of benchmark and decision results were extracted from run <code>{study.run}</code>. Times describe this cohort, equipment and network route.</p>
      <p>Source CSV SHA-256 <code>{study.input_sha256}</code></p><ul>{Object.entries(study.sources).map(([file,sha])=><li key={file}>{file} <code>{sha}</code></li>)}</ul></details>
  </section>;
}
