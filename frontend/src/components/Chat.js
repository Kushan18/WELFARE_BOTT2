import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import MessageBubble from './MessageBubble';
import ChipRow from './ChipRow';
import './Chat.css';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Backward-compatible parser: backend now returns a `chips` array, but older
// responses embedded chips inside the text as CHIPS:[...]. Support both.
function parseChips(text) {
  const match = text.match(/CHIPS:\[([^\]]+)\]/);
  if (!match) return { clean: text, chips: [] };
  const clean = text.replace(/CHIPS:\[[^\]]+\]/, '').trim();
  const chips = match[1]
    .split(',')
    .map(c => c.trim().replace(/^['"]|['"]$/g, ''));
  return { clean, chips };
}

function welcomeMessage() {
  return {
    id: 'welcome',
    role: 'bot',
    text:
      'Welcome to WelfareBot! We help Indian citizens discover government welfare schemes they may be eligible for.\n\nTo get started, what is your name?',
    chips: ['Start Over'],
    timestamp: new Date(),
  };
}

export default function Chat({ sessionId, userName, onNameCapture, onOpenForm }) {
  const [messages, setMessages] = useState([welcomeMessage()]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [isOnline, setIsOnline] = useState(true);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const msgCount = useRef(1);

  useEffect(() => {
    axios.get(API + '/health').then(() => setIsOnline(true)).catch(() => setIsOnline(false));
  }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, loading]);

  const addMsg = useCallback((role, text, chips = []) => {
    setMessages(prev => [...prev, { id: Date.now() + Math.random(), role, text, chips, timestamp: new Date() }]);
  }, []);

  const resetChat = useCallback(() => {
    setMessages([welcomeMessage()]);
    msgCount.current = 1;
  }, []);

  const sendMessage = useCallback(async (text) => {
    const t = (text || '').trim();
    if (!t || loading) return;
    addMsg('user', t);
    setInput('');
    setLoading(true);
    msgCount.current += 1;
    if (!userName && msgCount.current <= 2) onNameCapture(t);
    try {
      const res = await axios.post(API + '/chat', { session_id: sessionId, message: t }, { timeout: 30000 });
      const { reply, chips: backendChips, show_form_choice, open_form, clear_session } = res.data;
      const { clean, chips: parsedChips } = parseChips(reply || '');
      const chips = (backendChips && backendChips.length) ? backendChips : parsedChips;
      if (clear_session) {
        resetChat();
        if (clean) addMsg('bot', clean, chips);
        return;
      }
      addMsg('bot', clean, chips);
      // Only open the form modal when the backend explicitly signals it
      // (e.g. the user picked "Fill Form"), never automatically.
      if (open_form) onOpenForm(userName || t);
      else if (show_form_choice) { /* show choice as chips only; do not auto-open */ }
    } catch (err) {
      const msg = err.code === 'ECONNABORTED'
        ? 'Request timed out - please try again.'
        : 'Something went wrong. Is the backend running?';
      addMsg('bot', msg, ['Start Over']);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [loading, sessionId, userName, addMsg, onNameCapture, onOpenForm, resetChat]);

  const handleChipClick = useCallback((chip) => {
    if (!chip) return;
    if (chip === 'Fill Form' || chip.includes('Fill Form')) { onOpenForm(userName); return; }
    sendMessage(chip);
  }, [onOpenForm, userName, sendMessage]);

  const lastChips = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'bot' && messages[i].chips?.length > 0) return { idx: i, chips: messages[i].chips };
    }
    return null;
  })();

  return (
    <div className='chat-root'>
      <header className='chat-header'>
        <div className='chat-header-left'>
          <div className='bot-avatar'>WB</div>
          <div>
            <div className='bot-name'>WelfareBot</div>
            <div className={`bot-status ${isOnline ? 'online' : 'offline'}`}>
              <span className='status-dot' />{isOnline ? 'Online' : 'Offline - start backend'}
            </div>
          </div>
        </div>
      </header>
      <div className='chat-messages'>
        {messages.map((msg, idx) => (
          <React.Fragment key={msg.id}>
            <MessageBubble message={msg} />
            {lastChips && lastChips.idx === idx && (
              <ChipRow chips={lastChips.chips} onChipClick={handleChipClick} disabled={loading} />
            )}
          </React.Fragment>
        ))}
        {loading && <div className='typing-indicator'><span /><span /><span /></div>}
        <div ref={bottomRef} />
      </div>
      <form className='chat-input-bar' onSubmit={e => { e.preventDefault(); sendMessage(input); }}>
        <input ref={inputRef} className='chat-input' type='text' value={input} onChange={e => setInput(e.target.value)} placeholder={loading ? 'WelfareBot is typing...' : 'Type a message...'} disabled={loading} autoComplete='off' />
        <button className='btn-send' type='submit' disabled={loading || !input.trim()}>
          <svg width='20' height='20' viewBox='0 0 24 24' fill='none'><path d='M22 2L11 13' stroke='currentColor' strokeWidth='2' strokeLinecap='round' strokeLinejoin='round'/><path d='M22 2L15 22L11 13L2 9L22 2Z' stroke='currentColor' strokeWidth='2' strokeLinecap='round' strokeLinejoin='round'/></svg>
        </button>
      </form>
    </div>
  );
}
