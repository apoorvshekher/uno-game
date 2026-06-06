'use strict';

// ── State ──────────────────────────────────────────────────────────────────────
let gameId       = null;
let gameState    = null;
let pendingWildCardIndex = null;
let pendingWildCardEl    = null;
let unoCalled    = false;
let prevTurnIdx  = null;

// Online mode
let isOnlineMode    = false;
let myPlayerId      = null;
let wsConnection    = null;
let currentRoomCode = null;
let isRoomHost      = false;

// ── Persisted session (survives refresh / tab close → reconnect) ─────────────────
const SESSION_KEY = 'uno.session';

function saveSession() {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({
      playerId: myPlayerId, roomCode: currentRoomCode, isHost: isRoomHost,
    }));
  } catch (_) { /* storage may be unavailable */ }
}

function clearSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch (_) {}
}

function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

// Tear down any online session and return to the setup screen.
function backToSetup() {
  if (wsConnection) { try { wsConnection.close(); } catch (_) {} }
  wsConnection    = null;
  isOnlineMode    = false;
  myPlayerId      = null;
  currentRoomCode = null;
  isRoomHost      = false;
  clearSession();
  winnerOverlay.hidden = true;
  waitingScreen.hidden = true;
  gameScreen.hidden    = true;
  setupScreen.hidden   = false;
  window.scrollTo(0, 0);
}

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
const hdrRoom       = $('hdr-room');
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

const waitingScreen = $('waiting-screen');

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

// ── Mode tabs ──────────────────────────────────────────────────────────────────

document.querySelectorAll('.mode-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mode-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const isOnline = btn.dataset.mode === 'online';
    $('setup-form').hidden  = isOnline;
    $('online-panel').hidden = !isOnline;
  });
});

// ── Online lobby ───────────────────────────────────────────────────────────────

$('join-toggle-btn').addEventListener('click', () => {
  const row = $('join-code-row');
  row.hidden = !row.hidden;
});

$('create-room-btn').addEventListener('click', async () => {
  const name = $('online-name').value.trim() || 'Player';
  $('create-room-btn').disabled = true;
  try {
    const data = await api('POST', '/api/room/new', { name });
    myPlayerId      = data.player_id;
    currentRoomCode = data.room_code;
    isRoomHost      = true;
    isOnlineMode    = true;
    saveSession();
    showWaitingRoom(data.room_code);
    connectWS(data.room_code, data.player_id);
  } catch (err) {
    alert('Could not create room: ' + err.message);
  } finally {
    $('create-room-btn').disabled = false;
  }
});

$('confirm-join-btn').addEventListener('click', async () => {
  const name = $('online-name').value.trim() || 'Player';
  const code = $('room-code-input').value.trim().toUpperCase();
  if (!code) { alert('Enter a room code.'); return; }
  $('confirm-join-btn').disabled = true;
  try {
    const data = await api('POST', `/api/room/${code}/join`, { name });
    myPlayerId      = data.player_id;
    currentRoomCode = data.room_code;
    isRoomHost      = false;
    isOnlineMode    = true;
    saveSession();
    showWaitingRoom(data.room_code);
    connectWS(data.room_code, data.player_id);
  } catch (err) {
    alert('Could not join room: ' + err.message);
  } finally {
    $('confirm-join-btn').disabled = false;
  }
});

function showWaitingRoom(code) {
  setupScreen.hidden   = true;
  waitingScreen.hidden = false;
  $('room-code-big').textContent = code;
  $('start-online-btn').hidden = !isRoomHost;
}

function connectWS(roomCode, playerId) {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  wsConnection = new WebSocket(`${proto}//${location.host}/ws/${roomCode}/${playerId}`);

  wsConnection.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'room_state') {
      // Fresh-load reconnect into a still-waiting room: reveal the lobby first.
      if (isOnlineMode && gameScreen.hidden && waitingScreen.hidden) {
        showWaitingRoom(msg.room_code);
      }
      updateWaitingRoom(msg);
    } else if (msg.type === 'game_state') {
      // Reveal the board, whether arriving from the waiting room or a fresh-load reconnect.
      if (gameScreen.hidden) {
        waitingScreen.hidden = true;
        setupScreen.hidden   = true;
        gameScreen.hidden    = false;
        window.scrollTo(0, 0);
      }
      render(msg.state);
      animateCpuPlays(msg.state).then(() => animateDrawCards(msg.state.messages || []));
    } else if (msg.type === 'error') {
      showError(msg.message);
    }
  };

  wsConnection.onclose = ev => {
    // 4004 = room or seat no longer exists (e.g. abandoned room was cleaned up).
    if (ev && ev.code === 4004) {
      clearSession();
      if (!gameScreen.hidden && setupScreen.hidden) backToSetup();
      return;
    }
    // Best-effort: try to reconnect once from the persisted session before giving up.
    if (!gameScreen.hidden && !reconnectAttempted && loadSession()) {
      reconnectAttempted = true;
      showError('Connection lost — reconnecting…');
      setTimeout(() => connectWS(roomCode, playerId), 1500);
    } else if (!gameScreen.hidden) {
      showError('Connection lost — please refresh.');
    }
  };

  // A successful message resets the one-shot reconnect guard.
  wsConnection.addEventListener('open', () => { reconnectAttempted = false; });
}

let reconnectAttempted = false;

function updateWaitingRoom(msg) {
  const list = $('waiting-players-list');
  list.innerHTML = '';
  msg.players.forEach(p => {
    const row = document.createElement('div');
    row.className = 'waiting-player-row';
    row.innerHTML = `
      <div class="waiting-dot ${p.connected ? '' : 'offline'}"></div>
      <span class="waiting-player-name">${esc(p.name)}</span>
      ${p.player_id === msg.host_id ? '<span class="waiting-host-badge">Host</span>' : ''}
    `;
    list.appendChild(row);
  });
  const hint = $('waiting-hint');
  if (isRoomHost) {
    const startBtn = $('start-online-btn');
    if (msg.players.length >= 2) {
      startBtn.disabled = false;
      hint.textContent = `${msg.players.length} players connected`;
    } else {
      startBtn.disabled = true;
      hint.textContent = 'Waiting for at least 1 more player…';
    }
  } else {
    hint.textContent = 'Waiting for the host to start…';
  }
}

$('start-online-btn').addEventListener('click', () => {
  if (wsConnection) wsConnection.send(JSON.stringify({ type: 'start_game' }));
});

$('copy-code-btn').addEventListener('click', () => {
  navigator.clipboard.writeText(currentRoomCode || '').then(() => {
    $('copy-code-btn').textContent = 'Copied!';
    setTimeout(() => { $('copy-code-btn').textContent = 'Copy'; }, 1500);
  });
});

$('leave-room-btn').addEventListener('click', () => {
  backToSetup();
});

// ── Local game form ────────────────────────────────────────────────────────────

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
  if (isOnlineMode && state.room_code) {
    hdrRoom.textContent = `🔑 ${state.room_code}`;
    hdrRoom.hidden = false;
  } else {
    hdrRoom.hidden = true;
  }

  // Reset UNO called flag on new turn
  if (prevTurnIdx !== state.current_player_index) {
    unoCalled  = false;
    prevTurnIdx = state.current_player_index;
  }

  // Player panel — show everyone (including yourself) so the rotation is clear
  const selfIndex = isOnlineMode
    ? state.players.findIndex(p => p.is_viewer)
    : (cp.is_human ? state.current_player_index : -1);
  opponentsArea.innerHTML = '';
  state.players.forEach((p, i) => {
    const isSelf = i === selfIndex;
    // `connected` only meaningful for online human seats; CPUs/self are always "present".
    const isAway = isOnlineMode && p.is_human && !isSelf && p.connected === false;
    const box = document.createElement('div');
    box.className = 'opponent-box'
      + (p.is_current ? ' current' : '')
      + (isSelf ? ' self' : '')
      + (isAway ? ' disconnected' : '');
    box.dataset.playerName = p.name;
    const isUno  = p.card_count === 1;
    const icon   = p.is_human ? '👤' : '🤖';
    const avatar = p.name.charAt(0).toUpperCase();
    box.innerHTML = `
      <div class="opp-avatar">${avatar}</div>
      <div class="opp-info">
        <div class="opp-name">${esc(p.name)}${isSelf ? ' (You)' : ''} ${icon}</div>
        <div class="opp-meta">
          <div class="opp-count ${isUno ? 'uno' : ''}">
            ${isUno ? '🔴 UNO!' : p.card_count + (p.card_count === 1 ? ' card' : ' cards')}
          </div>
          ${isAway ? '<div class="opp-away">📴 away</div>' : ''}
        </div>
      </div>
      ${p.is_current ? '<div class="opp-turn-pip"></div>' : ''}
    `;
    if (p.uno_vulnerable && !isSelf) {
      const catchBtn = document.createElement('button');
      catchBtn.className = 'btn-catch';
      catchBtn.textContent = 'Catch!';
      catchBtn.addEventListener('click', () => onCatchUno(p.index, p.name));
      box.appendChild(catchBtn);
    }
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

  // Whose hand to show + whether actions are enabled
  const handPlayer = isOnlineMode
    ? state.players.find(p => p.is_viewer) || null
    : (cp.is_human ? cp : null);
  const isMyTurn = isOnlineMode ? !!state.is_my_turn : !!handPlayer;

  if (handPlayer) {
    if (isMyTurn) {
      playerLabel.innerHTML = `Your turn, <span>${esc(handPlayer.name)}</span>!`;
    } else {
      playerLabel.innerHTML = `<span>${esc(handPlayer.name)}</span> — waiting for <span>${esc(cp.name)}</span>…`;
    }

    handArea.innerHTML = '';
    handPlayer.hand.forEach((card, i) => {
      const playable = isMyTurn && card.playable;
      const el = makeCard(card, playable);
      el.dataset.cardIndex = i;
      if (playable) {
        el.addEventListener('click', () => onCardClick(i, card, el));
      }
      handArea.appendChild(el);
    });

    actionBar.innerHTML = '';
    if (isMyTurn) {
      drawBtn.style.display = '';
      if (state.pending_draw > 0) {
        const hasDraw = handPlayer.hand.some(c => c.playable && (c.card_type === 'Draw Two' || c.card_type === 'Wild Draw Four'));
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

      if (handPlayer.hand.length <= 2) {
        const unoBtn = document.createElement('button');
        unoBtn.className = 'btn btn-uno';
        unoBtn.textContent = unoCalled ? '✓ UNO!' : '🔴 UNO!';
        if (unoCalled) unoBtn.style.animation = 'none';
        unoBtn.addEventListener('click', async () => {
          if (unoCalled) return;
          unoCalled = true;
          showUnoFlash();
          unoBtn.textContent = '✓ UNO!';
          unoBtn.style.animation = 'none';
          if (isOnlineMode) {
            wsConnection.send(JSON.stringify({ type: 'call_uno' }));
          } else if (gameId) {
            await api('POST', `/api/game/${gameId}/call_uno`).catch(() => {});
          }
        });
        actionBar.appendChild(unoBtn);
      }
    }

    playerLabel.style.display = '';
    handArea.style.display = '';
    actionBar.style.display = '';
  } else {
    // Local CPU turn
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
  if (isOnlineMode) {
    wsConnection.send(JSON.stringify({ type: 'draw' }));
    return;
  }
  drawBtn.disabled = true;
  try {
    const state = await api('POST', `/api/game/${gameId}/draw`);
    render(state);
    await animateCpuPlays(state);
    await animateDrawCards(state.messages || []);
    handlePassScreenIfNeeded(state);
  } catch (err) {
    showError(err.message);
  } finally {
    drawBtn.disabled = false;
  }
});

drawPileBtn.addEventListener('click', () => drawBtn.click());

async function doPlay(cardIndex, chosenColor, cardEl) {
  if (isOnlineMode) {
    const msg = { type: 'play', card_index: cardIndex };
    if (chosenColor) msg.chosen_color = chosenColor;
    wsConnection.send(JSON.stringify(msg));
    if (cardEl) animateCardToDiscard(cardEl);
    return;
  }
  const body = { card_index: cardIndex };
  if (chosenColor) body.chosen_color = chosenColor;
  try {
    const [state] = await Promise.all([
      api('POST', `/api/game/${gameId}/play`, body),
      cardEl ? animateCardToDiscard(cardEl) : Promise.resolve(),
    ]);
    render(state);
    await animateCpuPlays(state);
    await animateDrawCards(state.messages || []);
    handlePassScreenIfNeeded(state);
  } catch (err) {
    showError(err.message);
  }
}

// ── Pass-device overlay ────────────────────────────────────────────────────────

function handlePassScreenIfNeeded(state, initial = false) {
  if (isOnlineMode) return;  // each player is on their own device
  if (state.winner) return;
  const cp = state.players[state.current_player_index];
  if (!cp.is_human) return;
  if (state.human_count <= 1 && !initial) return;
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
  if (isOnlineMode) {
    // Go back to waiting room so host can restart
    gameScreen.hidden    = true;
    waitingScreen.hidden = false;
    window.scrollTo(0, 0);
    return;
  }
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
  if (isOnlineMode) {
    backToSetup();
    return;
  }
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

// ── Catch UNO ─────────────────────────────────────────────────────────────────

async function onCatchUno(targetIndex, targetName) {
  if (isOnlineMode) {
    wsConnection.send(JSON.stringify({ type: 'catch_uno', target_index: targetIndex }));
    return;
  }
  try {
    const state = await api('POST', `/api/game/${gameId}/catch/${targetIndex}`);
    render(state);
    await animateDrawCards(state.messages || []);
  } catch (err) {
    showError(err.message);
  }
}

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
    const box = findOpponentBox(name);
    if (!box) continue;
    await flyCard(box, topCardEl, discardPile);
  }
}

async function animateDrawCards(messages) {
  for (const msg of messages) {
    const multi  = msg.match(/^(.+?) draws (\d+) cards/);
    const single = msg.match(/^(.+?) draws a card/);
    const name   = (multi || single)?.[1];
    const count  = multi ? parseInt(multi[2]) : single ? 1 : 0;
    if (!name || count === 0) continue;

    const box = findOpponentBox(name);
    if (!box) continue; // viewer drawing — skip box animation

    for (let i = 0; i < Math.min(count, 4); i++) {
      flyCard(drawPileBtn, drawPileBtn, box);
      await new Promise(r => setTimeout(r, 90));
    }
    await new Promise(r => setTimeout(r, 420));
  }
}

function findOpponentBox(playerName) {
  return [...opponentsArea.querySelectorAll('.opponent-box')]
    .find(b => b.dataset.playerName === playerName) || null;
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

// ── Auto-reconnect on load ───────────────────────────────────────────────────────
// If a previous online session is saved (refresh / accidental tab close), reclaim the
// seat. The server re-attaches the existing player_id and replies with room_state
// (lobby) or game_state (live board), which the WS handlers route to the right screen.
(function initReconnect() {
  const s = loadSession();
  if (!s || !s.playerId || !s.roomCode) return;
  myPlayerId      = s.playerId;
  currentRoomCode = s.roomCode;
  isRoomHost      = !!s.isHost;
  isOnlineMode    = true;
  connectWS(s.roomCode, s.playerId);
})();
