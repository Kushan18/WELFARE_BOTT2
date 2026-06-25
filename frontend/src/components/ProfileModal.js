import React, { useState } from 'react';
import axios from 'axios';
import './ProfileModal.css';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const STATES = ['Andhra Pradesh','Arunachal Pradesh','Assam','Bihar','Chhattisgarh','Goa','Gujarat','Haryana','Himachal Pradesh','Jharkhand','Karnataka','Kerala','Madhya Pradesh','Maharashtra','Manipur','Meghalaya','Mizoram','Nagaland','Odisha','Punjab','Rajasthan','Sikkim','Tamil Nadu','Telangana','Tripura','Uttar Pradesh','Uttarakhand','West Bengal','Delhi','Jammu & Kashmir','Ladakh'];
const OCCUPATIONS = ['Student','Farmer','Daily Wage Worker','Self Employed','Government Employee','Private Employee','Unemployed','Homemaker','Retired','Other'];
const INCOMES = ['Below Rs.1 Lakh','Rs.1-2.5 Lakh','Rs.2.5-5 Lakh','Rs.5-10 Lakh','Above Rs.10 Lakh'];
const LANGS = ['English','Hindi','Telugu','Tamil','Kannada'];
const CASTES = ['General','OBC','SC','ST','EWS'];

export default function ProfileModal({ sessionId, prefillName, onClose }) {
  const [form, setForm] = useState({ name: prefillName||'', language_preference:'English', state:'', occupation:'', caste_category:'', gender:'', age:'', income_bracket:'', aadhaar:'' });
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const set = (k, v) => setForm(p => ({...p, [k]: v}));

  const handleSubmit = async (e) => {
    e.preventDefault(); setError('');
    const req = ['name','state','occupation','caste_category','gender','age','income_bracket'];
    for (const f of req) { if (!form[f].toString().trim()) { setError('Please fill in: ' + f.replace('_',' ')); return; } }
    if (isNaN(+form.age) || +form.age < 1 || +form.age > 120) { setError('Enter a valid age (1-120).'); return; }
    setLoading(true);
    try {
      const res = await axios.post(API + '/submit-profile', { session_id: sessionId, ...form });
      setResult(res.data.schemes || []);
    } catch { setError('Failed to submit. Check your connection.'); }
    finally { setLoading(false); }
  };

  const Chip = ({ field, val }) => (
    <button type='button' className={form[field] === val ? 'sel-chip selected' : 'sel-chip'} onClick={() => set(field, val)}>{val}</button>
  );

  if (result) return (
    <div className='modal-overlay' onClick={e => e.target === e.currentTarget && onClose()}>
      <div className='modal-box'>
        <div className='modal-header'>
          <div><div className='modal-title'>Found {result.length} scheme{result.length !== 1 ? 's' : ''} for you!</div><div className='modal-subtitle'>Government schemes you qualify for</div></div>
          <button className='modal-close' onClick={onClose}>x</button>
        </div>
        <div className='scheme-results'>
          {result.length === 0 && <div style={{color:'var(--text-secondary)',padding:'20px 0'}}>No matching schemes found right now.</div>}
          {result.map((s, i) => (
            <div className='scheme-card' key={i}>
              <div className='scheme-name'>{s.name || s.title}</div>
              {s.description && <div className='scheme-desc'>{s.description}</div>}
              {s.benefit && <div className='scheme-benefit'>Benefit: {s.benefit}</div>}
              {s.apply_link && <a href={s.apply_link} target='_blank' rel='noopener noreferrer' className='scheme-link'>Apply Now</a>}
            </div>
          ))}
          <div className='form-footer'><button className='btn-primary' onClick={onClose}>Done</button></div>
        </div>
      </div>
    </div>
  );

  return (
    <div className='modal-overlay' onClick={e => e.target === e.currentTarget && onClose()}>
      <div className='modal-box'>
        <div className='modal-header'>
          <div><div className='modal-title'>Find Your Schemes</div><div className='modal-subtitle'>Fill in your details to see matching schemes</div></div>
          <button className='modal-close' onClick={onClose}>x</button>
        </div>
        <form className='modal-form' onSubmit={handleSubmit}>
          <div className='form-grid'>
            <div className='form-field'><label className='field-label'>Full Name *</label><input type='text' value={form.name} onChange={e => set('name', e.target.value)} placeholder='e.g. Kushan Sharma' /></div>
            <div className='form-field full'><label className='field-label'>Language *</label><div className='chip-select'>{LANGS.map(l => <Chip key={l} field='language_preference' val={l} />)}</div></div>
            <div className='form-field'><label className='field-label'>State / UT *</label><select value={form.state} onChange={e => set('state', e.target.value)}><option value=''>Select state</option>{STATES.map(s => <option key={s}>{s}</option>)}</select></div>
            <div className='form-field'><label className='field-label'>Occupation *</label><select value={form.occupation} onChange={e => set('occupation', e.target.value)}><option value=''>Select occupation</option>{OCCUPATIONS.map(o => <option key={o}>{o}</option>)}</select></div>
            <div className='form-field full'><label className='field-label'>Category *</label><div className='chip-select'>{CASTES.map(c => <Chip key={c} field='caste_category' val={c} />)}</div></div>
            <div className='form-field full'><label className='field-label'>Gender *</label><div className='chip-select'>{['Male','Female','Other'].map(g => <Chip key={g} field='gender' val={g} />)}</div></div>
            <div className='form-field'><label className='field-label'>Age *</label><input type='number' value={form.age} onChange={e => set('age', e.target.value)} placeholder='e.g. 28' min='1' max='120' /></div>
            <div className='form-field'><label className='field-label'>Annual Income *</label><select value={form.income_bracket} onChange={e => set('income_bracket', e.target.value)}><option value=''>Select range</option>{INCOMES.map(i => <option key={i}>{i}</option>)}</select></div>
            <div className='form-field'><label className='field-label'>Aadhaar last 4 (optional)</label><input type='text' value={form.aadhaar} onChange={e => set('aadhaar', e.target.value)} placeholder='XXXX' maxLength={4} /></div>
          </div>
          {error && <div className='form-error'>{error}</div>}
          <div className='form-footer'>
            <button type='button' className='btn-secondary' onClick={onClose}>Cancel</button>
            <button type='submit' className='btn-primary' disabled={loading}>{loading ? 'Checking...' : 'Find My Schemes'}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
