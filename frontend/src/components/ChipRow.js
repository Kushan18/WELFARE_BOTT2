import React from 'react';
import './ChipRow.css';
export default function ChipRow({ chips, onChipClick, disabled }) {
  if (!chips?.length) return null;
  return (
    <div className='chip-row'>
      {chips.map((chip, i) => (
        <button key={i} className='chip' onClick={() => onChipClick(chip)} disabled={disabled}>{chip}</button>
      ))}
    </div>
  );
}
