const state = {
  topTracks: [],
  recommendations: [],
  blockedRecommendationIds: [],
  isAddingPlaylist: false,
};

const DEFAULT_AVATAR = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="84" height="84" viewBox="0 0 84 84"%3E%3Cdefs%3E%3ClinearGradient id="g" x1="0" y1="0" x2="1" y2="1"%3E%3Cstop offset="0" stop-color="%2332485f"/%3E%3Cstop offset="1" stop-color="%231b2736"/%3E%3C/linearGradient%3E%3C/defs%3E%3Ccircle cx="42" cy="42" r="42" fill="url(%23g)"/%3E%3Ccircle cx="42" cy="33" r="14" fill="%23d8e6f3"/%3E%3Cpath d="M18 70c4-12 14-18 24-18s20 6 24 18" fill="%23d8e6f3"/%3E%3C/svg%3E';

// Helper function to get element by ID
function $(id) {
  return document.getElementById(id);
}

// Show a message to the user
function showMessage(text, type = 'info') {
  const msg = $('message');
  msg.innerHTML = text;
  msg.className = `message ${type}`;
  msg.hidden = false;

  if (type === 'error') {
    showErrorPopup(htmlToPlainText(text));
  }
}

// Clear any displayed message
function clearMessage() {
  const msg = $('message');
  msg.hidden = true;
  msg.textContent = '';
  msg.className = 'message';
}

function setPlaylistLoading(isLoading) {
  state.isAddingPlaylist = isLoading;
  const doneBtn = $('modal-done-btn');
  const cancelBtn = $('modal-cancel-btn');
  const createBtn = $('create-playlist-btn');

  if (doneBtn) {
    doneBtn.disabled = isLoading;
    doneBtn.classList.toggle('button-loading', isLoading);
    doneBtn.textContent = isLoading ? 'Adding Tracks...' : 'Add to Playlist';
  }

  if (cancelBtn) {
    cancelBtn.disabled = isLoading;
  }

  if (createBtn) {
    createBtn.disabled = isLoading;
  }
}

function htmlToPlainText(html) {
  const temp = document.createElement('div');
  temp.innerHTML = html;
  return (temp.textContent || temp.innerText || '').trim();
}

function showBlockedTracksPopup(payload = {}) {
  const overlay = $('blocked-popup');
  const summary = $('blocked-popup-summary');
  const list = $('blocked-popup-list');
  if (!overlay || !summary || !list) {
    return;
  }

  const addedCount = Number.isFinite(payload.added_count) ? payload.added_count : 0;
  const blockedTracks = Array.isArray(payload.blocked_tracks) ? payload.blocked_tracks : [];
  const blockedCount = blockedTracks.length;
  summary.innerHTML = `Added to playlist: <strong>${addedCount}</strong><br/>Blocked by Spotify: <strong>${blockedCount}</strong>`;

  list.innerHTML = '';
  if (blockedCount === 0) {
    const empty = document.createElement('div');
    empty.className = 'sub';
    empty.textContent = 'No blocked song details were returned.';
    list.appendChild(empty);
  } else {
    blockedTracks.forEach((track) => {
      const item = document.createElement('div');
      item.className = 'blocked-item';

      const img = document.createElement('img');
      img.src = track.album_cover || DEFAULT_AVATAR;
      img.alt = track.album_name || 'Album artwork';
      item.appendChild(img);

      const meta = document.createElement('div');
      meta.className = 'meta';

      const title = document.createElement('div');
      title.className = 'title';
      title.textContent = track.name || 'Unknown Song';
      meta.appendChild(title);

      const artist = document.createElement('div');
      artist.className = 'sub';
      artist.textContent = (track.artists || []).join(', ') || 'Unknown Artist';
      meta.appendChild(artist);

      const album = document.createElement('div');
      album.className = 'sub';
      album.textContent = track.album_name || 'Unknown Album';
      meta.appendChild(album);

      const link = document.createElement('a');
      link.className = 'link';
      link.href = track.spotify_url || '#';
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'Open in Spotify';
      meta.appendChild(link);

      item.appendChild(meta);
      list.appendChild(item);
    });
  }

  overlay.style.display = 'flex';
}

function hideBlockedTracksPopup() {
  const overlay = $('blocked-popup');
  if (!overlay) {
    return;
  }
  overlay.style.display = 'none';
}

function showErrorPopup(message, title = 'Error') {
  const overlay = $('error-popup');
  const titleEl = $('error-popup-title');
  const messageEl = $('error-popup-message');
  if (!overlay || !titleEl || !messageEl) {
    return;
  }

  titleEl.textContent = title;
  messageEl.textContent = message || 'Something went wrong.';
  overlay.style.display = 'flex';
}

function hideErrorPopup() {
  const overlay = $('error-popup');
  if (!overlay) {
    return;
  }
  overlay.style.display = 'none';
}

// Update UI based on login state
function setLoggedIn(isLoggedIn, profile = {}) {
  $('login-btn').hidden = isLoggedIn;
  $('logout-btn').hidden = !isLoggedIn;
  $('top-tracks-btn').disabled = !isLoggedIn;
  $('recommendations-btn').disabled = !isLoggedIn;
  $('create-playlist-btn').disabled = !isLoggedIn;

  const profileInfo = $('profile-info');
  if (isLoggedIn) {
    profileInfo.hidden = false;
    const displayName = profile.display_name || 'Spotify user';
    $('profile-name').textContent = displayName;
    const img = $('profile-img');
    if (profile.image_url) {
      img.src = profile.image_url;
      img.hidden = false;
    } else {
      img.src = DEFAULT_AVATAR;
      img.hidden = false;
    }
  } else {
    profileInfo.hidden = true;
  }
}

// Normalize a track object from Spotify API
function normalizeTrack(track) {
  if (!track || typeof track !== 'object') {
    return {
      id: '',
      uri: '',
      name: 'Unknown',
      artists: [],
      album_name: '',
      album_cover: '',
      preview_url: null,
    };
  }

  return {
    id: track.id,
    uri: track.uri,
    name: track.name,
    artists: (track.artists || []).map((a) => a.name),
    album_name: track.album?.name || '',
    album_cover: (track.album?.images || [])[0]?.url || '',
    preview_url: track.preview_url,
  };
}

// Build a track card HTML element
function buildTrackCard(track, options = {}) {
  const card = document.createElement('div');
  card.className = 'track-card';

  // Album cover image
  const img = document.createElement('img');
  img.src = track.album_cover || '';
  img.alt = track.album_name || 'Album cover';
  img.className = 'track-cover';
  card.appendChild(img);

  // Track details
  const details = document.createElement('div');
  details.className = 'track-details';

  const title = document.createElement('div');
  title.className = 'track-title';
  title.textContent = track.name || 'Unknown';
  details.appendChild(title);

  const artist = document.createElement('div');
  artist.className = 'track-meta';
  artist.textContent = track.artists?.join(', ') || 'Unknown Artist';
  details.appendChild(artist);

  const album = document.createElement('div');
  album.className = 'track-meta small';
  album.textContent = track.album_name || '';
  details.appendChild(album);

  // Spotify embedded player for recommendation listening.
  if (options.embedPlayer && track.id) {
    const embed = document.createElement('iframe');
    embed.className = 'track-embed';
    embed.src = `https://open.spotify.com/embed/track/${encodeURIComponent(track.id)}?utm_source=generator`;
    embed.width = '100%';
    embed.height = '80';
    embed.style.border = '0';
    embed.allow = 'autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture';
    embed.loading = 'lazy';
    details.appendChild(embed);
  }

  // Fallback preview audio player when embed is not enabled.
  if (!options.embedPlayer && track.preview_url) {
    const audio = document.createElement('audio');
    audio.controls = true;
    audio.src = track.preview_url;
    audio.className = 'track-audio';
    details.appendChild(audio);
  }

  // Checkbox for recommended tracks
  if (options.showCheckbox) {
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'track-checkbox';
    checkbox.value = track.uri || track.id;
    checkbox.dataset.spotifyId = track.id;

    const wrapper = document.createElement('label');
    wrapper.className = 'track-checkbox-wrapper';
    wrapper.appendChild(checkbox);
    wrapper.appendChild(document.createTextNode(' Add'));

    details.appendChild(wrapper);
  }

  card.appendChild(details);
  return card;
}

// Render a list of tracks to a container
function renderTrackList(tracks, containerId, options = {}) {
  const container = $(containerId);
  if (!container) {
    console.error('Container not found:', containerId);
    return;
  }
  
  container.innerHTML = '';
  
  if (!tracks || tracks.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'No tracks to show yet.';
    container.appendChild(empty);
    return;
  }

  tracks.forEach((track) => {
    const card = buildTrackCard(track, options);
    container.appendChild(card);
  });
}

// Fetch user profile from backend
async function fetchProfile() {
  clearMessage();
  const res = await fetch('/profile', { credentials: 'same-origin' });
  if (!res.ok) {
    setLoggedIn(false);
    return;
  }
  const data = await res.json();
  if (!data.logged_in) {
    setLoggedIn(false);
    return;
  }
  setLoggedIn(true, data);
}

// Fetch user's top tracks from Spotify
async function fetchTopTracks() {
  clearMessage();
  console.log('Fetching top tracks...');

  try {
    const res = await fetch('/top-tracks', { credentials: 'same-origin' });
    console.log('Top tracks response status:', res.status);
    
    if (!res.ok) {
      const errorText = await res.text();
      console.error('Top tracks error:', errorText);
      showMessage('Unable to load top tracks. Try logging in again.', 'error');
      return;
    }

    const data = await res.json();
    console.log('Top tracks data:', data);
    
    const items = Array.isArray(data?.tracks) ? data.tracks : [];
    console.log('Extracted items:', items.length);

    if (items.length === 0) {
      showMessage('No top tracks returned. Listen to more music on Spotify!', 'info');
      renderTrackList([], 'top-tracks');
      return;
    }

    state.topTracks = items.map(normalizeTrack);
    console.log('Normalized top tracks:', state.topTracks);
    renderTrackList(state.topTracks, 'top-tracks');
    showMessage(`Loaded ${state.topTracks.length} top tracks!`, 'success');
  } catch (err) {
    console.error('Error fetching top tracks:', err);
    showMessage('Error loading top tracks. Check console.', 'error');
  }
}

// Fetch recommendations based on user's top tracks
async function fetchRecommendations(options = {}) {
  const {
    silent = false,
    excludeTrackIds = [],
  } = options;

  if (!silent) {
    clearMessage();
  }
  console.log('Fetching recommendations...');

  // Check if we have top tracks to use as seeds
  if (!state.topTracks || state.topTracks.length === 0) {
    showMessage('Please get your top tracks first to get recommendations.', 'warning');
    return;
  }

  try {
    // Build query parameter with valid top track IDs as seeds.
    const seedTrackIds = state.topTracks
      .map((t) => t?.id)
      .filter((id) => typeof id === 'string' && id.trim().length > 0);

    if (seedTrackIds.length === 0) {
      showMessage('Could not build recommendation seeds from your top tracks.', 'error');
      return;
    }

    const allExcluded = Array.from(new Set([
      ...state.blockedRecommendationIds,
      ...(Array.isArray(excludeTrackIds) ? excludeTrackIds : []),
    ])).filter((id) => typeof id === 'string' && id.trim().length > 0);

    const trackIds = seedTrackIds.join(',');
    let url = `/recommendations?track_ids=${encodeURIComponent(trackIds)}`;
    if (allExcluded.length > 0) {
      url += `&exclude_track_ids=${encodeURIComponent(allExcluded.join(','))}`;
    }
    
    console.log('Recommendations URL:', url);
    const res = await fetch(url, { credentials: 'same-origin' });
    console.log('Recommendations response status:', res.status);
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      console.error('Recommendations error:', error);
      const detail = error.detail ? ` (${error.detail})` : '';
      showMessage((error.message || error.error || 'Unable to load recommendations. Try logging in again.') + detail, 'error');
      return;
    }

    const data = await res.json();
    console.log('Recommendations data:', data);
    
    const tracks = Array.isArray(data?.tracks) ? data.tracks : [];
    console.log('Extracted recommendations:', tracks.length);

    if (tracks.length === 0) {
      showMessage('No recommendations available. Try again.', 'info');
      renderTrackList([], 'recommended-tracks', { showCheckbox: true, embedPlayer: true });
      return;
    }

    state.recommendations = tracks.map(normalizeTrack);
    console.log('Normalized recommendations:', state.recommendations);
    renderTrackList(state.recommendations, 'recommended-tracks', { showCheckbox: true, embedPlayer: true });
    if (!silent) {
      showMessage(`Found ${tracks.length} recommendations based on your top tracks!`, 'success');
    }
  } catch (err) {
    console.error('Error fetching recommendations:', err);
    if (!silent) {
      showMessage('Error loading recommendations. Check console.', 'error');
    }
  }
}

function extractTrackIdsFromUris(uris) {
  if (!Array.isArray(uris)) {
    return [];
  }

  const ids = [];
  const seen = new Set();
  uris.forEach((uri) => {
    if (typeof uri !== 'string') {
      return;
    }
    const match = uri.match(/^spotify:track:([A-Za-z0-9]+)$/);
    if (!match) {
      return;
    }
    const id = match[1];
    if (!seen.has(id)) {
      seen.add(id);
      ids.push(id);
    }
  });
  return ids;
}

// Get URIs of selected tracks
function getSelectedTrackUris() {
  const checkboxes = Array.from(document.querySelectorAll('#recommended-tracks input[type="checkbox"]:checked'));
  return checkboxes.map((c) => c.value);
}

function getSelectedTracks() {
  const checkboxes = Array.from(document.querySelectorAll('#recommended-tracks input[type="checkbox"]:checked'));
  return checkboxes.map((checkbox) => {
    const trackId = checkbox.dataset.spotifyId || '';
    const track = state.recommendations.find((t) => t.id === trackId) || {};
    return {
      uri: checkbox.value,
      id: track.id || trackId,
      name: track.name || '',
      artists: Array.isArray(track.artists) ? track.artists : [],
      album_name: track.album_name || '',
      album_cover: track.album_cover || '',
      spotify_url: track.id ? `https://open.spotify.com/track/${track.id}` : '',
    };
  });
}

// Show the playlist creation modal
function showPlaylistModal() {
  const selectedUris = getSelectedTrackUris();
  
  if (selectedUris.length === 0) {
    showMessage('Please select at least one recommended song first.', 'warning');
    return;
  }
  
  $('playlist-name-input').value = '';
  $('playlist-modal').style.display = 'flex';
  $('playlist-name-input').focus();
}

// Hide the playlist creation modal
function hidePlaylistModal() {
  $('playlist-modal').style.display = 'none';
}

// Create a new playlist with selected tracks
async function createPlaylist(payloadOverride = null) {
  if (state.isAddingPlaylist) {
    return;
  }

  clearMessage();

  const uris = Array.isArray(payloadOverride?.uris)
    ? payloadOverride.uris
    : getSelectedTrackUris();
  const selectedTracks = Array.isArray(payloadOverride?.selected_tracks)
    ? payloadOverride.selected_tracks
    : getSelectedTracks();
  if (uris.length === 0) {
    showMessage('Please select at least one recommended song first.', 'warning');
    return;
  }

  const name = typeof payloadOverride?.name === 'string'
    ? payloadOverride.name
    : ($('playlist-name-input').value.trim() || 'My Recommendations');
  const payload = { name, uris, selected_tracks: selectedTracks };
  setPlaylistLoading(true);
  
  let res;
  try {
    res = await fetch('/create-playlist', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    console.error('Playlist request failed:', error);
    showMessage('Network error while creating playlist. Please retry.', 'error');
    setPlaylistLoading(false);
    return;
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    const detail = error.detail ? ` (${error.detail})` : '';

    if (error.error === 'tracks_add_failed') {
      const blockedUris = Array.isArray(error.skipped_uris) && error.skipped_uris.length > 0
        ? error.skipped_uris
        : uris;
      const blockedIds = extractTrackIdsFromUris(blockedUris);

      if (blockedIds.length > 0) {
        state.blockedRecommendationIds = Array.from(new Set([
          ...state.blockedRecommendationIds,
          ...blockedIds,
        ]));
      }

      await fetchRecommendations({ silent: true, excludeTrackIds: blockedIds });
      hidePlaylistModal();
      showBlockedTracksPopup({
        added_count: 0,
        blocked_tracks: Array.isArray(error.blocked_tracks) ? error.blocked_tracks : [],
      });
      showMessage('Spotify blocked your selected songs. Recommendations were refreshed with new options.', 'warning');
      setPlaylistLoading(false);
      return;
    }

    showMessage((error.message || error.error || 'Playlist creation failed.') + detail, 'error');
    setPlaylistLoading(false);
    return;
  }

  const data = await res.json();
  if (data.status !== 'ok') {
    const detail = data.detail ? ` (${data.detail})` : '';
    setRetryButton(true, payload);
    showMessage((data.message || data.error || 'Playlist creation failed.') + detail, 'error');
    setPlaylistLoading(false);
    return;
  }

  setPlaylistLoading(false);
  setRetryButton(false);
  hidePlaylistModal();
  const url = data.playlist_url;
  const addedCount = Number.isFinite(data.added_count) ? data.added_count : uris.length;
  const skippedCount = Number.isFinite(data.skipped_count) ? data.skipped_count : 0;
  const substitutedCount = Number.isFinite(data.substituted_count) ? data.substituted_count : 0;

  if (data.message && data.used_fallback_tracks) {
    showMessage(
      `${data.message} Added ${addedCount} song(s). <a href="${url}" target="_blank">Open in Spotify</a>`,
      'warning',
    );
    return;
  }

  if (skippedCount > 0) {
    const skippedIds = extractTrackIdsFromUris(data.skipped_uris || []);
    if (skippedIds.length > 0) {
      state.blockedRecommendationIds = Array.from(new Set([
        ...state.blockedRecommendationIds,
        ...skippedIds,
      ]));
      await fetchRecommendations({ silent: true, excludeTrackIds: skippedIds });
    }

    showBlockedTracksPopup(data);

    showMessage(
      `Created playlist "${data.name}". Added ${addedCount} song(s), skipped ${skippedCount} blocked song(s), auto-substituted ${substitutedCount} song(s). Recommendations were refreshed with replacements. <a href="${url}" target="_blank">Open in Spotify</a>`,
      'warning',
    );
    return;
  }

  if (substitutedCount > 0) {
    showMessage(
      `Created playlist "${data.name}"! Added ${addedCount} song(s), including ${substitutedCount} market-available substitutes. <a href="${url}" target="_blank">Open in Spotify</a>`,
      'success',
    );
    return;
  }

  showMessage(`Created playlist "${data.name}"! Added ${addedCount} song(s). <a href="${url}" target="_blank">Open in Spotify</a>`, 'success');
}

async function retryCreatePlaylist() {
  return;
}

// Set up event listeners
function hookEvents() {
  // Login button
  $('login-btn').addEventListener('click', () => {
    window.location.href = '/login';
  });

  // Logout button
  $('logout-btn').addEventListener('click', () => {
    window.location.href = '/logout';
  });

  // Get Top Tracks button
  $('top-tracks-btn').addEventListener('click', () => {
    fetchTopTracks();
  });

  // Get Recommendations button
  $('recommendations-btn').addEventListener('click', () => {
    fetchRecommendations();
  });

  // Create Playlist button - shows the modal
  $('create-playlist-btn').addEventListener('click', () => {
    showPlaylistModal();
  });

  // Modal Cancel button - closes modal without creating playlist
  $('modal-cancel-btn').addEventListener('click', () => {
    hidePlaylistModal();
  });
  
  // Modal Done button - creates the playlist
  $('modal-done-btn').addEventListener('click', () => {
    createPlaylist();
  });

  // Enter key in playlist name input creates playlist
  $('playlist-name-input').addEventListener('keyup', (event) => {
    if (event.key === 'Enter') {
      createPlaylist();
    }
  });

  // Click outside modal content closes it
  $('playlist-modal').addEventListener('click', (event) => {
    if (event.target === $('playlist-modal')) {
      hidePlaylistModal();
    }
  });

  $('blocked-popup-close').addEventListener('click', () => {
    hideBlockedTracksPopup();
  });

  $('blocked-popup').addEventListener('click', (event) => {
    if (event.target === $('blocked-popup')) {
      hideBlockedTracksPopup();
    }
  });

  $('error-popup-close').addEventListener('click', () => {
    hideErrorPopup();
  });

  $('error-popup').addEventListener('click', (event) => {
    if (event.target === $('error-popup')) {
      hideErrorPopup();
    }
  });
}

// Initialize app when page loads
window.addEventListener('DOMContentLoaded', async () => {
  hookEvents();
  await fetchProfile();
});
