import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

test('demo overview, all phases and scoped rankings', async ({ page }) => {
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'Every phase. A clearer picture.'})).toBeVisible();
  await expect(page.locator('.phase-card')).toHaveCount(6);
  await expect(page.locator('.stat-card').nth(1)).toContainText('18');
  await page.screenshot({ path:'test-results/overview-desktop.png', fullPage:true });
  await page.getByLabel('Delivery scenario').selectOption('existing_payload');
  await expect(page.locator('.stat-card').last()).toContainText('Existing payload');
  await page.locator('.phase-card').nth(3).click();
  await expect(page.locator('.phase-detail h2')).toHaveText('PCA & autoencoder');
  await expect(page.locator('.phase-table tbody tr')).not.toHaveCount(0);
  await page.getByRole('button',{name:'Results & rankings',exact:true}).click();
  await page.getByLabel('Fidelity requirement').selectOption('full_fidelity');
  await expect(page.locator('tbody tr')).toHaveCount(3);
  await expect(page.locator('tbody')).not.toContainText('Autoencoder');
  await page.getByLabel('Search configurations').fill('does-not-exist');
  await expect(page.getByRole('heading',{name:'No matching configurations'})).toBeVisible();
  expect(errors).toEqual([]);
});

test('configuration form, focus preservation and strict SSH fields', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('radio',{name:/Strict SSH/}).check();
  await expect(dialog.getByPlaceholder('user@host')).toBeVisible();
  await dialog.getByPlaceholder('user@host').fill('researcher@example.org');
  await page.waitForTimeout(3300);
  await expect(dialog.getByPlaceholder('user@host')).toBeFocused();
  await dialog.getByText('Connection and recovery settings',{exact:true}).click();
  await expect(dialog.getByLabel('SSH port',{exact:true})).toHaveValue('22');
  await expect(dialog.getByLabel('Maximum attempts per trial',{exact:true})).toHaveValue('3');
  await expect(dialog.getByText(/Phase 2: up to 10 transfer trials/)).toContainText('Phase 6: up to 10 trials');
  await expect(dialog.getByLabel(/^Transfer deadline \(seconds\)/)).toHaveValue('300');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
});

test('mobile navigation and responsive layout', async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  await expect(page.locator('.phase-card')).toHaveCount(6);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({ path:'test-results/overview-mobile.png', fullPage:true });
  await page.getByRole('button',{name:'Open navigation'}).click();
  await page.getByRole('button',{name:'Experiment history',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your experiment notebook.'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('imported reports and download', async ({ page }) => {
  await page.goto('/');
  const options=page.getByLabel('Current experiment').locator('option');
  await expect.poll(()=>options.count()).toBeGreaterThan(1);
  const imported=await options.evaluateAll(nodes=>nodes.find(n=>n.value!=='demo')?.value);
  await page.getByLabel('Current experiment').selectOption(imported);
  await expect(page.getByText('Synthetic demo',{exact:true})).not.toBeVisible();
  await page.getByRole('button',{name:'Results & rankings',exact:true}).click();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('link',{name:'02_decision_rankings.csv'}).click();
  const download=await downloadPromise;
  expect(download.suggestedFilename()).toBe('02_decision_rankings.csv');
});

test('launch a synthetic experiment through the UI and publish results', async ({ page }) => {
  // Six phases launch many Python workers; allow time on a loaded laptop.
  test.setTimeout(480000);
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'observatory-browser-'));
  const dataset=path.join(directory,'synthetic.csv');
  const rows=['patient_id,time,SepsisLabel,Age,ICULOS,HospAdmTime,HR,O2Sat,Temp,SBP,MAP,DBP,Resp,Lactate,Glucose'];
  for(let i=0;i<64;i++)rows.push([Math.floor(i/4),i%4,Math.floor(i/4)%2,30+Math.floor(i/4),i%4+1,-3,
    80+Math.sin(i)*8,96+Math.cos(i*.7),37+Math.sin(i*.3)*.3,120+Math.cos(i*.4)*10,
    80+Math.sin(i*.6)*6,65+Math.cos(i*.8)*5,18+Math.sin(i*.9)*2,1.5+Math.sin(i*.2)*.3,110+Math.cos(i*.5)*15].join(','));
  await fs.writeFile(dataset,rows.join('\n')+'\n');
  await page.goto('/');
  await expect(page.getByText('Local workspace connected')).toBeVisible();
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByLabel('Upload CSV',{exact:true}).setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:await fs.readFile(dataset)});
  await expect(dialog.getByPlaceholder('/path/to/clinical_dataset.csv')).toHaveValue(/\/uploads\//);
  await expect(dialog.getByRole('region',{name:'Dataset preview'})).toBeVisible();
  await dialog.getByLabel('Patient coverage criterion',{exact:true}).selectOption('0.8');
  await dialog.getByPlaceholder('2, 4, 8').fill('2');
  await dialog.getByLabel(/^Autoencoder iteration limit/).fill('10');
  await dialog.getByText(/^Packaging and transfer trials/).click();
  await dialog.getByLabel('Phase 2 packaging runs',{exact:true}).fill('1');
  await dialog.getByLabel('Phase 2 maximum transfer trials',{exact:true}).fill('2');
  await dialog.getByLabel('Phase 6 maximum transfer trials',{exact:true}).fill('2');
  await dialog.getByText(/^Model training and utility evaluation/).click();
  await dialog.getByLabel('AE loss improvement tolerance',{exact:true}).fill('0.001');
  await dialog.getByLabel('AE patience (epochs)',{exact:true}).fill('8');
  await dialog.getByLabel('Weight allocation',{exact:true}).selectOption('custom');
  const weightInputs=dialog.locator('.weight-editor input');
  for(const [i,value] of [30,20,15,10,10,5,10].entries())await weightInputs.nth(i).fill(String(value));
  await dialog.getByRole('button',{name:'Start experiment'}).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator('.experiment-meta .badge.running')).toBeVisible();
  await expect(page.locator('.experiment-meta .badge.complete')).toBeVisible({timeout:400000});
  await expect(page.locator('.phase-card.complete')).toHaveCount(6);
  await expect(page.locator('.stat-card').nth(1)).toContainText('10');
  const key=await page.getByLabel('Current experiment').inputValue();
  const result=await page.request.get(`/api/runs/${key}`).then(r=>r.json());
  expect(result.manifest.config.patient_coverage_min).toBe(.8);
  expect(result.manifest.config.topsis_weights).toEqual([.3,.2,.15,.1,.1,.05,.1]);
  expect(result.manifest.primary_weight_profile).toBe('custom');
  expect(result.manifest.config.packaging_runs).toBe(1);
  expect(result.manifest.config.phase2_transfer_trials).toBe(2);
  expect(result.manifest.config.transfer_trials).toBe(2);
  expect(result.manifest.config.ae_tol).toBe(.001);
  expect(result.manifest.config.ae_patience).toBe(8);
  await page.getByRole('button',{name:'Results & rankings',exact:true}).click();
  await expect(page.getByLabel('Weight profile',{exact:true})).toHaveValue('custom');
  await page.getByText('View custom weights · experiment selection',{exact:true}).click();
  await expect(page.locator('.weight-summary')).toContainText('30%');
  await expect(page.getByText('80% patient coverage',{exact:true})).toBeVisible();
  const reportPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Report',exact:true}).click();
  expect((await reportPromise).suggestedFilename()).toBe('FINAL_REPORT.md');
});

test('dataset viewer pages records and preserves text', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button',{name:'View dataset',exact:true}).click();
  const preview=page.getByRole('region',{name:'Dataset preview'});
  await expect(preview.getByText('Records 1–25',{exact:false})).toBeVisible();
  await preview.getByRole('button',{name:'Next',exact:true}).click();
  await expect(preview.getByText('Records 26–50',{exact:false})).toBeVisible();
  await preview.getByLabel('Find dataset columns').fill('HR');
  await expect(preview.getByRole('columnheader')).toHaveCount(2);
  await preview.getByRole('button',{name:'View record 26',exact:true}).click();
  await expect(preview.locator('.expanded-record')).toContainText('patient_id');
});

test('CSV upload previews leading zeros and lets users choose coverage', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByLabel('Upload CSV',{exact:true}).setInputFiles({name:'leading-zeros.csv',mimeType:'text/csv',buffer:Buffer.from('patient_id,HR\n001,80\n002,81\n')});
  const preview=dialog.getByRole('region',{name:'Dataset preview'});
  await expect(preview.getByRole('cell',{name:'001',exact:true})).toBeVisible();
  for(const value of ['0.75','0.8','0.9']){
    await dialog.getByLabel('Patient coverage criterion',{exact:true}).selectOption(value);
    await expect(dialog.getByLabel('Patient coverage criterion',{exact:true})).toHaveValue(value);
  }
  await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
});

test('selecting a four-pair summary lists all four saved pairs', async ({ page }) => {
  const demo=JSON.parse(await fs.readFile(new URL('../public/demo.json',import.meta.url)));
  demo.overview.find(r=>r.metric==='highly_correlated_pairs').value=4;
  const pairs=[['Unit1','Unit2'],['time','ICULOS'],['Bilirubin_direct','Bilirubin_total'],['Hct','Hgb']];
  const group={id:'redundant',title:'Flagged correlation pairs',source:'redundant_pairs.csv',available:true,
    description:'Flagged pairs; Phase 1 does not remove columns.',columns:['column_a','column_b','pearson_r','pairwise_n'],
    rows:pairs.map(([column_a,column_b])=>({column_a,column_b,pearson_r:.96,pairwise_n:16}))};
  await page.route('**/api/runs/demo',route=>route.fulfill({json:demo}));
  await page.route('**/api/runs/demo/phases/phase1',route=>route.fulfill({json:{phase:'phase1',groups:[group]}}));
  await page.goto('/');
  await page.getByRole('button',{name:'Pipeline phases',exact:false}).click();
  await page.getByRole('button',{name:'Expand measurement highly_correlated_pairs',exact:true}).click();
  const detail=page.locator('.measurement-detail');
  for(const [a,b] of pairs){await expect(detail.getByRole('cell',{name:a,exact:true})).toBeVisible();await expect(detail.getByRole('cell',{name:b,exact:true})).toBeVisible();}
  await expect(detail.locator('.artifact-table tbody tr')).toHaveCount(4);
  await expect(page.getByLabel('Phase detail report')).toHaveValue('redundant');
});

test('old server preview endpoint gives restart guidance, not a missing CSV claim', async ({ page }) => {
  await page.goto('/');
  const selector=page.getByLabel('Current experiment');
  await expect.poll(()=>selector.locator('option').count()).toBeGreaterThan(1);
  const key=await selector.locator('option').evaluateAll(nodes=>nodes.find(n=>n.value!=='demo').value);
  await page.route(`**/api/runs/${key}/dataset*`,route=>route.fulfill({status:404,json:{error:'Report not found'}}));
  await selector.selectOption(key);
  await page.getByRole('button',{name:'View dataset',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Restart server.py');
  await expect(page.getByRole('alert')).not.toContainText('moved');
});

test('SSH recovery states and resume keep the same experiment', async ({ page, request }) => {
  const demo=await (await request.get('/demo.json')).json();
  const id='job-123456abcdef';
  let status='failed', resumed=0;
  await page.route('**/api/runs', route=>route.fulfill({json:[{id,name:'Synthetic SSH recovery.csv',created:'2026-11-15T12:00:00Z',status,mode:'ssh'}]}));
  await page.route(`**/api/runs/${id}`, route=>route.fulfill({json:{...demo,id,demo:false,status,error:status==='failed'?'Connection reset by peer':null,report:'',network:{status:status==='failed'?'needs_attention':'connection_lost',operation:'Phase 6 synthetic trial',attempt:1,max_attempts:3,retry_in_seconds:2,error:'Connection reset by peer'}}}));
  await page.route(`**/api/runs/${id}/resume`, route=>{expect(route.request().method()).toBe('POST');resumed++;status='running';return route.fulfill({json:{id,status}});});
  await page.goto('/');
  await page.getByLabel('Current experiment').selectOption(id);
  await expect(page.getByText('Needs attention',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Resume this experiment'})).toBeEnabled();
  await page.getByRole('button',{name:'Resume this experiment'}).click();
  await expect(page.getByText('Connection lost — retrying',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Current experiment')).toHaveValue(id);
  await expect(page.getByRole('button',{name:'Stop run'})).toBeVisible();
  expect(resumed).toBe(1);
  await page.screenshot({path:'test-results/ssh-recovery.png',fullPage:true});
});

 test('TOPSIS equal defaults, custom totals and reset', async ({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog.getByLabel('Weight allocation',{exact:true})).toHaveValue('equal');
  const inputs=dialog.locator('.weight-editor input');
  await expect(inputs).toHaveCount(7);
  await expect(inputs.first()).toBeDisabled();
  await dialog.getByLabel('Weight allocation',{exact:true}).selectOption('custom');
  await inputs.first().fill('50');
  await expect(dialog.getByText('Weights must total 100%.',{exact:true})).toBeVisible();
  await expect(dialog.getByRole('button',{name:'Start experiment',exact:true})).toBeDisabled();
  for(const [i,value] of [1,19,20,20,20,20,0].entries())await inputs.nth(i).fill(String(value));
  await expect(dialog.getByText('Total: 100%',{exact:true})).toBeVisible();
  await expect(dialog.getByText('Weights must total 100%.',{exact:true})).toHaveCount(0);
  await inputs.last().fill('');
  await expect(dialog.getByText('Enter all seven weights.',{exact:true})).toBeVisible();
  await dialog.getByLabel('Weight allocation',{exact:true}).selectOption('equal');
  await expect(inputs.first()).toBeDisabled();
  await expect(dialog.getByText(/equal shares stored at full precision/)).toBeVisible();
 });

test('required labels, optional defaults and conditional SSH fields',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog.locator('.field-status.required')).toHaveCount(1);
  await expect(dialog.getByPlaceholder('/path/to/clinical_dataset.csv')).toHaveAttribute('required','');
  await expect(dialog.getByPlaceholder('2, 4, 8')).not.toHaveAttribute('required','');
  await dialog.getByText(/^Packaging and transfer trials/).click();
  await expect(dialog.getByLabel('Phase 2 packaging runs',{exact:true})).toHaveValue('3');
  await dialog.getByLabel('Phase 2 packaging runs',{exact:true}).fill('1');
  await expect(dialog.getByText(/Packaging: 1 fixed runs/)).toBeVisible();
  await dialog.getByRole('button',{name:'Reset optional settings',exact:true}).click();
  await expect(dialog.getByLabel('Phase 2 packaging runs',{exact:true})).toHaveValue('3');
  await dialog.getByRole('radio',{name:/Strict SSH/}).check();
  await expect(dialog.locator('.field-status.required')).toHaveCount(2);
  await expect(dialog.getByPlaceholder('user@host')).toHaveAttribute('required','');
  await dialog.getByText(/^Decision eligibility and sensitivity/).click();
  await expect(dialog.getByLabel('Maximum new clinical-screen violations (%)',{exact:true})).toHaveValue('');
  await page.screenshot({path:'test-results/experiment-options.png',fullPage:true});
});

 test('AE device and batch controls retain CPU defaults and reset',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByText(/^Model training and utility evaluation/).click();
  await expect(dialog.getByLabel('AE compute device',{exact:true})).toHaveValue('cpu');
  await expect(dialog.getByLabel('AE batch size (rows)',{exact:true})).toHaveValue('256');
  await dialog.getByLabel('AE compute device',{exact:true}).selectOption('gpu');
  await dialog.getByLabel('AE batch size (rows)',{exact:true}).fill('4096');
  await dialog.getByLabel('AE progress interval (epochs)',{exact:true}).fill('1');
  await page.screenshot({path:'test-results/ae-acceleration.png',fullPage:true});
  await dialog.getByRole('button',{name:'Reset optional settings',exact:true}).click();
  await expect(dialog.getByLabel('AE compute device',{exact:true})).toHaveValue('cpu');
  await expect(dialog.getByLabel('AE batch size (rows)',{exact:true})).toHaveValue('256');
 });

test('strict SSH offers SCP, rsync and a paired comparison',async({page})=>{
  const demo=JSON.parse(await fs.readFile(new URL('../public/demo.json',import.meta.url)));
  demo.manifest.transport_comparison=['rsync','scp'].map(transport=>({
    phase:'6',artifact:'synthetic.tar',transport,trials:1,mean_send_seconds:1,mean_wall_seconds:2,failed_attempts:0
  }));
  await page.route('**/api/runs/demo',route=>route.fulfill({json:demo}));
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('radio',{name:/Strict SSH/}).check();
  const choice=dialog.getByLabel('SSH file transfer');
  await expect(choice).toHaveValue('scp');
  await choice.selectOption('rsync');
  await choice.selectOption('both');
  await expect(choice).toHaveValue('both');
  await page.keyboard.press('Escape');
  await page.getByText('Verified SCP and rsync measurements',{exact:true}).click();
  const table=page.locator('details').filter({hasText:'Verified SCP and rsync measurements'});
  await expect(table.getByRole('cell',{name:'rsync',exact:true}).first()).toBeVisible();
  await expect(table.getByRole('cell',{name:'scp',exact:true}).first()).toBeVisible();
});

test('thesis preset and separate direct-file transport rankings', async ({page})=>{
  const demo=JSON.parse(await fs.readFile(new URL('../public/demo.json',import.meta.url)));
  demo.manifest.transport_studies={paired_rankings:['scp','rsync'].map(transport_method=>({
    format:'parquet',transport_method,rank:1,topsis_score:1,transfer_mean_seconds:16})),
    archives:[{artifact:'ae16',condition:'interrupted',scheduled:8,verified:8,matched_pairs:4,median_wall_difference_seconds:-10.46}]};
  await page.route('**/api/runs/demo',route=>route.fulfill({json:demo}));
  await page.goto('/');
  await page.getByRole('button',{name:'New experiment',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByRole('button',{name:'Use thesis experiment settings'}).click();
  await expect(dialog.getByLabel('SSH file transfer')).toHaveValue('both');
  await expect(dialog.getByRole('checkbox',{name:/Include paired baseline/})).toBeChecked();
  await expect(dialog.getByLabel('Receiver execution')).toHaveValue('remote');
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Results & rankings',exact:true}).click();
  const studies=page.locator('section').filter({has:page.getByRole('heading',{name:'Transport study results'})}).last();
  await expect(studies.getByRole('cell',{name:'rsync',exact:true})).toBeVisible();
  await studies.getByText('Prepared archives and interruptions',{exact:true}).click();
  await expect(studies.getByRole('cell',{name:'interrupted',exact:true})).toBeVisible();
});
