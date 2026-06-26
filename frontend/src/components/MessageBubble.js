import React from 'react';
import './MessageBubble.css';

function formatTime(d) { return new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }

export default function MessageBubble({ message }) {
  const isBot = message.role === 'bot';
  return (
    <div className={`msg-row ${isBot ? 'bot' : 'user'}`}>
      {isBot && <div className='msg-avatar'>WB</div>}
      <div className={`msg-bubble ${isBot ? 'bot' : 'user'}`}>
        <div className='msg-text'>{message.text}</div>
        <div className='msg-time'>{formatTime(message.timestamp)}</div>
      </div>
    </div>
  );
}
