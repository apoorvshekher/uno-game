'use strict';

// ── State ──────────────────────────────────────────────────────────────────────
let gameId       = null;
let gameState    = null;
let pendingWildCardIndex = null;
let pendingWildCardEl    = null;
let unoCalled    = false;
let prevTurnIdx  = null;

// ── DOM refs ───────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const setupScreen   = $('setup-screen');
const gameScreen    = $('game-screen');
const setupForm     = $('setup-form');
const playerFields  = $('player-fields');
const addHumanBtn   = $('add-human');
const cpuBtns       = document.querySelectorAll('.cpu-btn');
const playerHint    = $('player-count-hint');
const startBtn      = $('start-btn');
const quitBtn       = $('quit-btn');
const hdrTurn       = $('hdr-turn');
const hdrDirection  = $('hdr-direction');
const hdrDrawPile   = $('hdr-draw-pile');
const unoFlash      = $('uno-flash');
const opponentsArea = $('opponents-area');
const boardArea     = $('board-area');
const discardPile   = $('discard-pile');
const drawPileBtn   = $('draw-pile-btn');
const drawCountEl   = $('draw-count');
const activeColorBadge = $('active-color-badge');
const messageBar    = $('message-bar');
const playerLabel   = $('player-label');
const handArea      = $('hand-area');
const actionBar     = $('action-bar');
const drawBtn       = $('draw-btn');

const passOverlay   = $('pass-overlay');
const passTitle     = $('pass-title');
const passSub       = $('pass-sub');
const passReadyBtn  = $('pass-ready-btn');

const colorPicker   = $('color-picker');
const colorBtns     = document.querySelectorAll('.color-btn');

const winnerOverlay = $('winner-overlay');
const winnerName    = $('winner-name');
const playAgainBtn  = $('play-again-btn');

// ── Setup screen logic ─────────────────────────────────────────────────────────

let selectedCpu = 2;

cpuBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    selectedCpu = parseInt(btn.dataset.n);
    cpuBtns.forEach(b => b.classList.toggle('selected', b === btn));
    updateHint();
  });
});

addHumanBtn.addEventListener('click', () => {
  const rows = playerFields.querySelectorAll('.player-row');
  if (rows.length >= 4) return;
  const n = rows.length + 1;
  const row = document.createElement('div');
  row.className = 'player-row';
  row.innerHTML = `
    <span class="player-num">${n}</span>
    <input type="text" class="player-name" placeholder="Player ${n}" value="Player ${n}" maxlength="16">
    <button type="button" class="btn btn-sm btn-outline remove-player" style="padding:.3rem .6rem">✕</button>
  `;
  row.querySelector('.remove-player').addEventListener('click', () => {
    row.remove();
    renumberPlayers();
    updateHint();
  });
  playerFields.appendChild(row);
  updateHint();
  if (rows.length >= 3) addHumanBtn.disabled = true;
});

function renumberPlayers() {
  playerFields.querySelectorAll('.player-row').forEach((row, i) => {
    row.querySelector('.player-num').textContent = i + 1;
    addHumanBtn.disabled = false;
  });
}

function updateHint() {
  const humans = playerFields.querySelectorAll('.player-row').length;
  const total  = humans + selectedCpu;
  if (total < 2) {
    playerHint.textContent = 'Need at least 2 players total.';
    startBtn.disabled = true;
  } else if (total > 10) {
    playerHint.textContent = 'Maximum 10 players total.';
    startBtn.disabled = true;
  } else {
    playerHint.textContent = `${total} players total (${humans} human, ${selectedCpu} CPU).`;
    startBtn.disabled = false;
  }
}
updateHint();

setupForm.addEventListener('submit', async e => {
  e.preventDefault();
  const names = [...playerFields.querySelectorAll('.player-name')].map(i => i.value.trim() || 'Player');
  const players = names.map(name => ({ name, is_human: true }));
  for (let i = 0; i < selectedCpu; i++) players.push({ name: `CPU-${i + 1}`, is_human: false });

  startBtn.disabled = true;
  startBtn.textContent = 'Dealing…';
  try {
    const state = await api('POST', '/api/game/new', { players });
    gameId = state.game_id;
    transitionToGame(state);
  } catch (err) {
    alert('Failed to start game: ' + err.message);
    startBtn.disabled = false;
    startBtn.textContent = 'Deal Cards';
  }
});

// ── Game transitions ───────────────────────────────────────────────────────────

function transitionToGame(state) {
  gameState = state;
  setupScreen.hidden = true;
  gameScreen.hidden  = false;
  window.scrollTo(0, 0);
  render(state);
  handlePassScreenIfNeeded(state, /* initial */ true);
}

// ── Rendering ──────────────────────────────────────────────────────────────────

function render(state) {
  gameState = state;

  // Header
  const cp = state.players[state.current_player_index];
  hdrTurn.textContent      = `▶ ${cp.name}'s turn`;
  hdrDirection.textContent = state.direction === 1 ? '→' : '←';
  hdrDrawPile.textContent  = `🂠 ${state.draw_pile_size}`;

  // Reset UNO called flag on new turn
  if (prevTurnIdx !== state.current_player_index) {
    unoCalled  = false;
    prevTurnIdx = state.current_player_index;
  }

  // Opponents
  const humanIdx = firstHumanIndex(state);
  opponentsArea.innerHTML = '';
  state.players.forEach((p, i) => {
    if (p.is_human && i === humanIdx) return; // current viewer — shown in player area
    const box = document.createElement('div');
    box.className = 'opponent-box' + (p.is_current ? ' current' : '');
    const cardBacks = Math.min(p.card_count, 8);
    const isUno = p.card_count === 1;
    box.innerHTML = `
      <div class="opp-name">${esc(p.name)} ${p.is_human ? '👤' : '🤖'}</div>
      <div class="opp-cards">${'<div class="card-back"></div>'.repeat(cardBacks)}</div>
      <div class="opp-count ${isUno ? 'uno' : ''}">${isUno ? '🔴 UNO!' : p.card_count + ' cards'}</div>
      ${p.is_current ? '<div style="font-size:.7rem;color:var(--accent);font-weight:700">▶ TURN</div>' : ''}
    `;
    opponentsArea.appendChild(box);
  });

  // Discard pile — show top card
  discardPile.innerHTML = '<div class="pile-label">DISCARD</div>';
  discardPile.appendChild(makeCard(state.top_card, false));

  // Active color badge
  activeColorBadge.textContent = state.active_color;
  activeColorBadge.style.background = state.active_color_hex;
  activeColorBadge.style.color = state.active_color === 'Yellow' ? '#78350f' : 'white';

  // Draw pile
  drawCountEl.textContent = state.draw_pile_size;

  // Messages
  if (state.messages && state.messages.length) {
    messageBar.innerHTML = state.messages
      .map(m => `<span class="msg-item">▸ ${esc(m)}</span>`)
      .join(' ');
  }

  // Current player hand
  if (cp.is_human && cp.hand.length) {
    playerLabel.innerHTML = `Your turn, <span>${esc(cp.name)}</span>!`;
    handArea.innerHTML = '';
    cp.hand.forEach((card, i) => {
      const el = makeCard(card, card.playable);
      el.dataset.cardIndex = i;
      if (card.playable) {
        el.addEventListener('click', () => onCardClick(i, card, el));
      }
      handArea.appendChild(el);
    });

    // Draw button + optional UNO button
    drawBtn.style.display = '';
    actionBar.innerHTML = '';
    if (state.pending_draw > 0) {
      const hasDraw = cp.hand.some(c => c.playable && (c.card_type === 'Draw Two' || c.card_type === 'Wild Draw Four'));
      const badge = document.createElement('span');
      badge.className = 'pending-draw-badge';
      badge.textContent = `Must draw ${state.pending_draw} cards!`;
      actionBar.appendChild(drawBtn);
      actionBar.appendChild(badge);
      drawBtn.textContent = hasDraw ? `Stack or Draw ${state.pending_draw}` : `Draw ${state.pending_draw}`;
    } else {
      actionBar.appendChild(drawBtn);
      drawBtn.textContent = 'Draw Card';
    }

    // UNO button — show when 1 or 2 cards remain
    if (cp.hand.length <= 2) {
      const unoBtn = document.createElement('button');
      unoBtn.className = 'btn btn-uno';
      unoBtn.textContent = unoCalled ? '✓ UNO!' : '🔴 UNO!';
      if (unoCalled) unoBtn.style.animation = 'none';
      unoBtn.addEventListener('click', () => {
        unoCalled = true;
        showUnoFlash();
        unoBtn.textContent = '✓ UNO!';
        unoBtn.style.animation = 'none';
      });
      actionBar.appendChild(unoBtn);
    }

    playerLabel.style.display = '';
    handArea.style.display = '';
    actionBar.style.display = '';
  } else {
    // CPU turn — hide hand area
    playerLabel.innerHTML = `🤖 <span>${esc(cp.name)}</span> is thinking…`;
    handArea.innerHTML = '';
    actionBar.innerHTML = '';
  }

  // Winner
  if (state.winner) {
    winnerName.textContent = state.winner;
    winnerOverlay.hidden = false;
  }
}

function firstHumanIndex(state) {
  return state.players.findIndex(p => p.is_human);
}

// ── Card element factory ───────────────────────────────────────────────────────

function makeCard(card, playable) {
  const el = document.createElement('div');
  el.className = 'card' + (playable === false ? ' not-playable' : '');
  el.dataset.color = card.color;
  el.dataset.type  = card.card_type;

  // Oval background (skip for wild — gradient already decorative)
  if (card.color !== 'Wild') {
    const oval = document.createElement('div');
    oval.className = 'oval';
    el.appendChild(oval);
  }

  const symbol = document.createElement('div');
  symbol.className = 'symbol';
  symbol.textContent = card.symbol;
  el.appendChild(symbol);

  const tl = document.createElement('div');
  tl.className = 'corner corner-tl';
  tl.textContent = card.symbol;
  el.appendChild(tl);

  const br = document.createElement('div');
  br.className = 'corner corner-br';
  br.textContent = card.symbol;
  el.appendChild(br);

  return el;
}

// ── Actions ────────────────────────────────────────────────────────────────────

async function onCardClick(cardIndex, card, cardEl) {
  if (card.card_type === 'Wild' || card.card_type === 'Wild Draw Four') {
    pendingWildCardIndex = cardIndex;
    pendingWildCardEl    = cardEl;
    colorPicker.hidden = false;
    return;
  }
  await doPlay(cardIndex, null, cardEl);
}

colorBtns.forEach(btn => {
  btn.addEventListener('click', async () => {
    colorPicker.hidden = true;
    if (pendingWildCardIndex !== null) {
      const idx = pendingWildCardIndex;
      const el  = pendingWildCardEl;
      pendingWildCardIndex = null;
      pendingWildCardEl    = null;
      await doPlay(idx, btn.dataset.color, el);
    }
  });
});

drawBtn.addEventListener('click', async () => {
  drawBtn.disabled = true;
  try {
    const state = await api('POST', `/api/game/${gameId}/draw`);
    render(state);
    await animateCpuPlays(state);
    handlePassScreenIfNeeded(state);
  } catch (err) {
    showError(err.message);
  } finally {
    drawBtn.disabled = false;
  }
});

drawPileBtn.addEventListener('click', () => drawBtn.click());

async function doPlay(cardIndex, chosenColor, cardEl) {
  const body = { card_index: cardIndex };
  if (chosenColor) body.chosen_color = chosenColor;
  try {
    const [state] = await Promise.all([
      api('POST', `/api/game/${gameId}/play`, body),
      cardEl ? animateCardToDiscard(cardEl) : Promise.resolve(),
    ]);
    render(state);
    await animateCpuPlays(state);
    handlePassScreenIfNeeded(state);
  } catch (err) {
    showError(err.message);
  }
}

// ── Pass-device overlay ────────────────────────────────────────────────────────

function handlePassScreenIfNeeded(state, initial = false) {
  if (state.winner) return;
  const cp = state.players[state.current_player_index];
  if (!cp.is_human) return;
  if (state.human_count <= 1 && !initial) return; // single human, no pass needed
  if (state.human_count <= 1) return;

  // Multiple humans: show pass screen before revealing hand
  passTitle.textContent = `Pass to ${cp.name}`;
  passSub.textContent   = `Other players — look away! Then hand the device to ${cp.name}.`;
  // Hide the hand in the DOM until they click ready
  handArea.innerHTML = '';
  actionBar.innerHTML = '';
  passOverlay.hidden = false;
}

passReadyBtn.addEventListener('click', () => {
  passOverlay.hidden = true;
  render(gameState); // re-render to show hand
});

// ── Winner / quit ──────────────────────────────────────────────────────────────

playAgainBtn.addEventListener('click', () => {
  winnerOverlay.hidden = true;
  gameScreen.hidden    = true;
  setupScreen.hidden   = false;
  window.scrollTo(0, 0);
  gameId = null;
  gameState = null;
  startBtn.disabled   = false;
  startBtn.textContent = 'Deal Cards';
});

quitBtn.addEventListener('click', () => {
  if (!confirm('Quit the current game?')) return;
  if (gameId) api('DELETE', `/api/game/${gameId}`).catch(() => {});
  winnerOverlay.hidden = true;
  gameScreen.hidden    = true;
  setupScreen.hidden   = false;
  window.scrollTo(0, 0);
  gameId = null;
  gameState = null;
  startBtn.disabled    = false;
  startBtn.textContent = 'Deal Cards';
});

// ── Card fly animation ─────────────────────────────────────────────────────────

function flyCard(fromEl, cloneSource, toEl) {
  const from  = fromEl.getBoundingClientRect();
  const to    = toEl.getBoundingClientRect();
  const clone = cloneSource.cloneNode(true);

  clone.className = cloneSource.className + ' card-flying';
  clone.style.left      = (from.left + from.width  / 2 - to.width  / 2) + 'px';
  clone.style.top       = (from.top  + from.height / 2 - to.height / 2) + 'px';
  clone.style.width     = to.width  + 'px';
  clone.style.height    = to.height + 'px';
  clone.style.transform = 'rotate(0deg) scale(0.7)';
  document.body.appendChild(clone);

  requestAnimationFrame(() => requestAnimationFrame(() => {
    clone.style.left      = to.left + 'px';
    clone.style.top       = to.top  + 'px';
    clone.style.transform = `rotate(${(Math.random() * 24 - 12).toFixed(1)}deg) scale(1)`;
  }));

  return new Promise(resolve => setTimeout(() => { clone.remove(); resolve(); }, 380));
}

function animateCardToDiscard(cardEl) {
  return flyCard(cardEl, cardEl, discardPile);
}

async function animateCpuPlays(state) {
  const topCardEl = discardPile.querySelector('.card');
  if (!topCardEl) return;

  const plays = (state.messages || []).filter(m => / played /.test(m));
  for (const msg of plays) {
    const name = msg.match(/^(.+?) played /)?.[1];
    if (!name) continue;
    const box = [...opponentsArea.querySelectorAll('.opponent-box')]
      .find(b => b.querySelector('.opp-name')?.textContent.includes(name));
    if (!box) continue;
    await flyCard(box, topCardEl, discardPile);
  }
}

// ── UNO flash ──────────────────────────────────────────────────────────────────

function showUnoFlash() {
  unoFlash.hidden = false;
  const txt = unoFlash.querySelector('.uno-flash-text');
  txt.style.animation = 'none';
  void txt.offsetWidth; // reflow to restart animation
  txt.style.animation = '';
  clearTimeout(unoFlash._timer);
  unoFlash._timer = setTimeout(() => { unoFlash.hidden = true; }, 1200);
}

// ── API helper ─────────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// ── Utils ──────────────────────────────────────────────────────────────────────

function esc(str) {
  return String(str).replace(/[&<>"']/g, c =>
    ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])
  );
}

function showError(msg) {
  const bar = messageBar;
  const el  = document.createElement('span');
  el.className = 'msg-item';
  el.style.color = '#ef4444';
  el.textContent = '✗ ' + msg;
  bar.prepend(el);
  setTimeout(() => el.remove(), 4000);
}
