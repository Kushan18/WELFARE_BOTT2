import React, { useState, useEffect } from 'react';
import Chat from './components/Chat';
import ProfileModal from './components/ProfileModal';

function genSession() { return 'sess_' + Math.random().toString(36).substring(2, 15); }

export default function App() {
  const [sessionId] = useState(() => {
    const existing = localStorage.getItem('wb_session_id');
    if (existing) return existing;
    const id = genSession();
    localStorage.setItem('wb_session_id', id);
    return id;
  });
  const [userName, setUserName] = useState(() => localStorage.getItem('wb_user_name') || '');
  const [showModal, setShowModal] = useState(false);
  const [prefillName, setPrefillName] = useState('');

  useEffect(() => { if (userName) localStorage.setItem('wb_user_name', userName); }, [userName]);

  const handleOpenForm = (name) => { setPrefillName(name || userName); setShowModal(true); };

  return (
    <div style={{ height: '100%' }}>
      <Chat sessionId={sessionId} userName={userName} onNameCapture={setUserName} onOpenForm={handleOpenForm} />
      {showModal && <ProfileModal sessionId={sessionId} prefillName={prefillName} onClose={() => setShowModal(false)} />}
    </div>
  );
}
