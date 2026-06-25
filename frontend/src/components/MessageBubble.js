import React from 'react';
import './MessageBubble.css';

function formatTime(d) { return new Date(d).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }

export default function MessageBubble({ message }) {
  const isBot = message.role === 'bot';
  return (
    <div className={msg-row \}>
      {isBot && <div className='msg-avatar'>??</div>}
      <div className={msg-bubble \}>
        <div className='msg-text'>{message.text}</div>
        <div className='msg-time'>{formatTime(message.timestamp)}</div>
      </div>
    </div>
  );
}
