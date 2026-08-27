import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { DeckRoot } from './deck/DeckRoot';
import './styles/deck.css';
import './styles/print.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <DeckRoot />
  </StrictMode>,
);
