import React from 'react';
import schema from './experiment_options.json';

export const optionalDefaults = () => Object.fromEntries(schema.flatMap(section=>section.fields.map(field=>[
  field.key,field.type.endsWith('-list')?field.default.join(', '):field.default??''
])));

export function ExperimentOptions({values,onChange,mode}) {
  const update=(key,value)=>onChange(old=>({...old,[key]:value}));
  return <section className="experiment-options" aria-label="Optional experiment settings">
    <h3>Optional settings</h3><p>Keep the displayed defaults or change the controls below. Clearing a numeric field restores its default; blank eligibility limits apply no extra restriction.</p>
    {schema.filter(section=>!section.when||section.when===mode).map(section=><details key={section.title}>
      <summary>{section.title}<span className="field-status">Optional</span></summary>
      <p>{section.description}</p><div className="form-grid">{section.fields.map(field=>{
        const value=values[field.key];const id=`option-${field.key}`;
        const props={id,'aria-label':field.label,'aria-describedby':`${id}-help`};
        let input;
        if(field.type==='choice')input=<select {...props} value={value} onChange={e=>update(field.key,e.target.value)}>{field.choices.map(([key,label])=><option value={key} key={key}>{label}</option>)}</select>;
        else if(field.type==='boolean')input=<input {...props} type="checkbox" checked={value} onChange={e=>update(field.key,e.target.checked)}/>;
        else if(field.type==='multi')input=<div>{field.choices.map(([key,label])=><label className="checkbox" key={key}><input type="checkbox" aria-label={label} checked={value.includes(key)} onChange={e=>update(field.key,e.target.checked?[...value,key]:value.filter(x=>x!==key))}/>{label}</label>)}</div>;
        else if(field.type.endsWith('-list'))input=<input {...props} value={value} onChange={e=>update(field.key,e.target.value)} placeholder={field.default.join(', ')}/>;
        else input=<input {...props} type="number" min={field.min} max={field.max} step={field.type==='integer'?'1':'any'} value={value} onChange={e=>update(field.key,e.target.value)} placeholder={field.default==null?'No override':String(field.default)}/>;
        const defaultText=field.default==null?'none':Array.isArray(field.default)?field.default.join(', '):typeof field.default==='boolean'?(field.default?'on':'off'):field.default;
        return <div className="form-field" key={field.key}><label htmlFor={field.type==='multi'?undefined:id}>{field.label}</label><small>Optional · default: {defaultText}</small>{input}<small id={`${id}-help`}>{field.help}</small></div>;
      })}</div>
    </details>)}
  </section>;
}
