import { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';

const API = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Parse legacy CHIPS:[...] format (fallback)
function parseChips(text = '') {
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
      'Welcome to WelfareBot!\n\nI help you discover government welfare schemes.\n\nWhat is your name?',
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
    axios.get(API + '/health')
      .then(() => setIsOnline(true))
      .catch(() => setIsOnline(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const addMsg = useCallback((role, text, chips = []) => {
    setMessages(prev => [
      ...prev,
      {
        id: Date.now() + Math.random(),
        role,
        text,
        chips,
        timestamp: new Date(),
      },
    ]);
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

    if (!userName && msgCount.current <= 2) {
      onNameCapture(t);
    }

    try {
      const res = await axios.post(
        API + '/chat',
        { session_id: sessionId, message: t },
        { timeout: 30000 }
      );

      const { reply, show_form_choice, open_form, clear_session, chips: backendChips } = res.data;

      const { clean, chips: parsedChips } = parseChips(reply || '');
      const chips = backendChips?.length ? backendChips : parsedChips;

      if (clear_session) {
        resetChat();
        return;
      }

      addMsg('bot', clean, chips);

      if (open_form) {
        onOpenForm(userName || t);
      }

      if (show_form_choice) {
        // just show chips, do nothing else
      }

    } catch (err) {
      const msg =
        err.code === 'ECONNABORTED'
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

    if (chip.includes('Fill Form')) {
      onOpenForm(userName);
      return;
    }

    sendMessage(chip);
  }, [sendMessage, onOpenForm, userName]);

  const lastBotChips = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'bot' && messages[i].chips?.length) {
        return messages[i].chips;
      }
    }
    return null;
  })();

  return (
    <div className="chat-root">
      <header className="chat-header">
        <div className="bot-name">WelfareBot</div>
        <div className={`bot-status ${isOnline ? 'online' : 'offline'}`}>
          {isOnline ? 'Online' : 'Offline'}
        </div>
      </header>

      <div className="chat-body">
        {messages.map(msg => (
          <div key={msg.id} className={`msg-row ${msg.role}`}>
            <div className="msg-bubble">
              {msg.text}
            </div>

            {msg.chips?.length && (
              <div className="chip-row">
                {msg.chips.map((c, i) => (
                  <button key={i} onClick={() => handleChipClick(c)}>
                    {c}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

        <div ref={bottomRef} />
      </div>

      <div className="chat-input">
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendMessage(input)}
          placeholder="Type a message..."
        />
        <button onClick={() => sendMessage(input)}>
          Send
        </button>
      </div>
    </div>
  );
}