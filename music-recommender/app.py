import os
import re
import sqlite3
import time
from typing import Optional, Tuple
from urllib.parse import urlencode

from flask import Flask, request, redirect, session, jsonify, render_template
import requests
import spotipy

# Flask app configuration
app = Flask(
    __name__,
    static_folder='static',
    template_folder='templates',
)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'change-this')

# Spotify credentials (must be supplied via environment variables)
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIFY_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:5000/callback')

# Database config
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'database', 'recommend.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'database', 'schema.sql')

# Spotify scopes for OAuth
SPOTIFY_SCOPES = 'user-top-read user-read-recently-played playlist-modify-public playlist-modify-private'


def get_db():
    """Return a DB connection (SQLite)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize or migrate the local SQLite database."""
    conn = get_db()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())

    # Lightweight migration for older DB files created before expires_at existed.
    columns = {
        row['name']
        for row in conn.execute('PRAGMA table_info(users)').fetchall()
    }
    if 'expires_at' not in columns:
        conn.execute('ALTER TABLE users ADD COLUMN expires_at INTEGER')

    conn.commit()
    conn.close()


init_db()


def get_seed_artists_from_tracks(sp: spotipy.Spotify, seed_track_ids: list[str]) -> list[str]:
    """Extract artist IDs from seed tracks to widen recommendation coverage."""
    if not seed_track_ids:
        return []

    artist_ids = []
    seen = set()

    # Spotify API accepts up to 50 IDs per tracks() call.
    # Some accounts/markets return 403 for this endpoint with certain IDs;
    # treat it as a soft failure so recommendation flow can continue.
    try:
        track_details = sp.tracks(seed_track_ids[:50], market='from_token').get('tracks') or []
    except Exception as e:
        app.logger.warning('Unable to resolve seed artists from track IDs: %s', str(e))
        return []

    for track in track_details:
        if not track:
            continue
        for artist in track.get('artists') or []:
            aid = artist.get('id')
            if aid and aid not in seen:
                seen.add(aid)
                artist_ids.append(aid)

    return artist_ids


def fallback_recommendations_from_artists(
    sp: spotipy.Spotify,
    artist_ids: list[str],
    seed_track_ids: list[str],
    country: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Fallback recommendation strategy using each seed artist's top tracks."""
    # Without a reliable user country this endpoint frequently returns 403.
    if not country:
        return []

    recommendations = []
    seen_track_ids = set(seed_track_ids)

    for artist_id in artist_ids:
        try:
            top_resp = sp.artist_top_tracks(artist_id, country=country or 'US')
        except Exception as e:
            app.logger.warning('Artist top tracks fallback failed for %s: %s', artist_id, str(e))
            continue

        for track in top_resp.get('tracks') or []:
            tid = track.get('id')
            if not tid or tid in seen_track_ids:
                continue
            seen_track_ids.add(tid)
            recommendations.append(track)
            if len(recommendations) >= limit:
                return recommendations

    return recommendations


def get_user_top_artist_ids(sp: spotipy.Spotify, limit: int = 20) -> list[str]:
    """Fetch artist IDs from the current user's top tracks as a safe fallback seed source."""
    artist_ids = []
    seen = set()

    try:
        top_resp = sp.current_user_top_tracks(limit=limit, time_range='medium_term')
    except Exception as e:
        app.logger.warning('Failed to fetch user top tracks for fallback artists: %s', str(e))
        return []

    for track in top_resp.get('items') or []:
        for artist in track.get('artists') or []:
            aid = artist.get('id')
            if aid and aid not in seen:
                seen.add(aid)
                artist_ids.append(aid)

    return artist_ids


def get_user_country(sp: spotipy.Spotify) -> Optional[str]:
    """Return current Spotify account country code if available."""
    try:
        me = sp.current_user()
    except Exception as e:
        app.logger.warning('Unable to fetch user profile country: %s', str(e))
        return None

    country = me.get('country')
    if isinstance(country, str) and len(country) == 2:
        return country.upper()
    return None


def collect_expanded_fallback_tracks(
    sp: spotipy.Spotify,
    seed_track_ids: list[str],
    limit: int = 50,
) -> list[dict]:
    """Build a larger fallback pool using top tracks across time ranges + recently played."""
    seed_set = set(seed_track_ids)
    collected = []
    seen = set(seed_set)

    def add_track(track: Optional[dict]) -> None:
        if not track:
            return
        tid = track.get('id')
        if not tid or tid in seen:
            return
        seen.add(tid)
        collected.append(track)

    # Top tracks across time windows tends to return the largest unique pool.
    for time_range in ('short_term', 'medium_term', 'long_term'):
        try:
            top_resp = sp.current_user_top_tracks(limit=50, time_range=time_range)
            for track in top_resp.get('items') or []:
                add_track(track)
                if len(collected) >= limit:
                    return collected
        except Exception as e:
            app.logger.warning('Expanded fallback top-tracks failed for %s: %s', time_range, str(e))

    # Add recently played unique tracks if we still need more.
    try:
        recent_resp = sp.current_user_recently_played(limit=50)
        for item in recent_resp.get('items') or []:
            add_track(item.get('track'))
            if len(collected) >= limit:
                return collected
    except Exception as e:
        app.logger.warning('Expanded fallback recently-played failed: %s', str(e))

    return collected


def collect_featured_playlist_uris(sp: spotipy.Spotify, country: Optional[str], limit: int = 30) -> list[str]:
    """Collect candidate track URIs from Spotify featured playlists for the user's market."""
    uris = []
    seen = set()

    try:
        featured = sp.featured_playlists(country=country, limit=5)
        playlists = (featured.get('playlists') or {}).get('items') or []
    except Exception as e:
        app.logger.warning('Failed to fetch featured playlists fallback: %s', str(e))
        return []

    for pl in playlists:
        playlist_id = pl.get('id')
        if not playlist_id:
            continue
        try:
            tracks_resp = sp.playlist_items(
                playlist_id,
                limit=50,
                fields='items(track(uri,id,is_playable,available_markets))',
                market=country,
            )
        except Exception as e:
            app.logger.warning('Featured playlist items fetch failed for %s: %s', playlist_id, str(e))
            continue

        for item in tracks_resp.get('items') or []:
            track = item.get('track') or {}
            uri = track.get('uri')
            if not isinstance(uri, str) or not uri.startswith('spotify:track:'):
                continue

            if country:
                is_playable = track.get('is_playable')
                markets = track.get('available_markets')
                if is_playable is False:
                    continue
                if isinstance(markets, list) and markets and country not in markets:
                    continue

            if uri in seen:
                continue
            seen.add(uri)
            uris.append(uri)
            if len(uris) >= limit:
                return uris

    return uris


def parse_track_ids_param(value: str) -> list[str]:
    """Parse a comma-separated track ID string into a deduplicated list."""
    items = []
    seen = set()
    # Spotify IDs are base62 and usually 22 chars. Accept only that shape.
    pattern = re.compile(r'^[A-Za-z0-9]{22}$')
    for raw in (value or '').split(','):
        tid = raw.strip()
        if not tid or tid in seen or not pattern.match(tid):
            continue
        seen.add(tid)
        items.append(tid)
    return items


def validate_recommendation_tracks(
    sp: spotipy.Spotify,
    candidate_tracks: list[dict],
    user_country: Optional[str],
) -> list[dict]:
    """Return only tracks that look playable/addable for the current user's market."""
    if not candidate_tracks:
        return []

    ordered_ids = []
    id_to_track = {}
    for track in candidate_tracks:
        if not isinstance(track, dict):
            continue
        tid = track.get('id')
        if not tid or tid in id_to_track:
            continue
        id_to_track[tid] = track
        ordered_ids.append(tid)

    if not ordered_ids:
        return []

    validated_ids = set()
    market = user_country or 'from_token'

    for i in range(0, len(ordered_ids), 50):
        chunk_ids = ordered_ids[i:i + 50]
        detailed_tracks = None
        try:
            detailed_tracks = sp.tracks(chunk_ids, market=market).get('tracks') or []
        except Exception as e:
            # Avoid per-track retries here; that can trigger rate limits quickly.
            app.logger.warning('Batch track validation failed, using heuristic fallback: %s', str(e))

        # If batch lookup failed, apply lightweight heuristic checks from existing payload.
        if detailed_tracks is None:
            for tid in chunk_ids:
                detail = id_to_track.get(tid) or {}
                if detail.get('is_playable') is False:
                    continue
                restrictions = detail.get('restrictions')
                if isinstance(restrictions, dict) and restrictions.get('reason'):
                    continue
                markets = detail.get('available_markets')
                if user_country and isinstance(markets, list) and markets and user_country not in markets:
                    continue
                validated_ids.add(tid)
            continue

        for detail in detailed_tracks or []:
            if not detail:
                continue
            tid = detail.get('id')
            if not tid:
                continue

            # Keep only tracks that are likely addable for the account market.
            if detail.get('is_playable') is False:
                continue
            restrictions = detail.get('restrictions')
            if isinstance(restrictions, dict) and restrictions.get('reason'):
                continue
            markets = detail.get('available_markets')
            if user_country and isinstance(markets, list) and markets and user_country not in markets:
                continue

            validated_ids.add(tid)

    return [id_to_track[tid] for tid in ordered_ids if tid in validated_ids]


def get_track_ids_from_items(items: list[dict]) -> set[str]:
    """Extract track IDs from a list of Spotify track-like dicts."""
    ids = set()
    for item in items or []:
        if isinstance(item, dict):
            tid = item.get('id')
            if tid:
                ids.add(tid)
    return ids


def build_selected_track_lookup(payload_tracks: list[dict]) -> dict:
    """Build lookup keyed by URI for selected track metadata sent by frontend."""
    lookup = {}
    for item in payload_tracks or []:
        if not isinstance(item, dict):
            continue
        uri = item.get('uri')
        if not isinstance(uri, str) or not uri.startswith('spotify:track:'):
            continue
        lookup[uri] = {
            'id': item.get('id') if isinstance(item.get('id'), str) else None,
            'name': item.get('name') if isinstance(item.get('name'), str) else None,
            'artists': item.get('artists') if isinstance(item.get('artists'), list) else [],
            'album_name': item.get('album_name') if isinstance(item.get('album_name'), str) else '',
            'album_cover': item.get('album_cover') if isinstance(item.get('album_cover'), str) else '',
            'spotify_url': item.get('spotify_url') if isinstance(item.get('spotify_url'), str) else '',
        }
    return lookup


def build_blocked_track_detail(uri: str, selected_lookup: dict) -> dict:
    """Build a display-ready blocked track detail object for frontend popup UI."""
    info = selected_lookup.get(uri) or {}
    track_id = None
    parts = uri.split(':') if isinstance(uri, str) else []
    if len(parts) == 3 and parts[0] == 'spotify' and parts[1] == 'track':
        track_id = parts[2]

    spotify_url = info.get('spotify_url') or (f'https://open.spotify.com/track/{track_id}' if track_id else '')
    artists = info.get('artists') if isinstance(info.get('artists'), list) else []

    return {
        'uri': uri,
        'id': info.get('id') or track_id,
        'name': info.get('name') or 'Unknown Track',
        'artists': artists,
        'album_name': info.get('album_name') or '',
        'album_cover': info.get('album_cover') or '',
        'spotify_url': spotify_url,
        'reason': 'blocked_by_spotify',
    }


def looks_playable_in_market(track: dict, country: Optional[str]) -> bool:
    """Heuristic check for whether a track is likely addable in the user's market."""
    if not isinstance(track, dict):
        return False
    if track.get('is_playable') is False:
        return False
    restrictions = track.get('restrictions')
    if isinstance(restrictions, dict) and restrictions.get('reason'):
        return False
    markets = track.get('available_markets')
    if country and isinstance(markets, list) and markets and country not in markets:
        return False
    uri = track.get('uri')
    return isinstance(uri, str) and uri.startswith('spotify:track:')


def find_alternative_track_uri(
    sp: spotipy.Spotify,
    metadata: dict,
    country: Optional[str],
    used_uris: set[str],
) -> Optional[str]:
    """Find a market-available alternative track URI for a blocked track."""
    name = (metadata or {}).get('name')
    artists = (metadata or {}).get('artists') or []
    if not isinstance(name, str) or not name.strip():
        return None

    artist_name = None
    for a in artists:
        if isinstance(a, str) and a.strip():
            artist_name = a.strip()
            break

    query = f'track:"{name.strip()}"'
    if artist_name:
        query += f' artist:"{artist_name}"'

    try:
        resp = sp.search(
            q=query,
            type='track',
            limit=20,
            market=country,
        )
    except Exception as e:
        app.logger.warning('Alternative search failed for %s: %s', name, str(e))
        return None

    for item in ((resp.get('tracks') or {}).get('items') or []):
        if not looks_playable_in_market(item, country):
            continue
        uri = item.get('uri')
        if uri in used_uris:
            continue
        return uri

    return None


def enrich_recommendations_pool(
    sp: spotipy.Spotify,
    rec_items: list[dict],
    seed_track_ids: list[str],
    excluded_track_ids: set[str],
    user_country: Optional[str],
    target_limit: int,
) -> list[dict]:
    """Top up recommendation list to target_limit while honoring exclusions and uniqueness."""
    deduped = []
    seen = set(excluded_track_ids)

    for track in rec_items:
        tid = track.get('id') if isinstance(track, dict) else None
        if not tid or tid in seen:
            continue
        seen.add(tid)
        deduped.append(track)

    if len(deduped) >= target_limit:
        return deduped[:target_limit]

    # First top-up: user's broader listening pool.
    try:
        block_list = list(seen.union(seed_track_ids))
        extras = collect_expanded_fallback_tracks(sp, block_list, limit=120)
        for track in extras:
            tid = track.get('id') if isinstance(track, dict) else None
            if not tid or tid in seen:
                continue

            if user_country:
                markets = track.get('available_markets')
                if isinstance(markets, list) and markets and user_country not in markets:
                    continue

            seen.add(tid)
            deduped.append(track)
            if len(deduped) >= target_limit:
                return deduped[:target_limit]
    except Exception as e:
        app.logger.warning('Recommendation top-up from expanded pool failed: %s', str(e))

    # Second top-up: featured playlist tracks converted to full track objects.
    try:
        featured_uris = collect_featured_playlist_uris(sp, user_country, limit=120)
        featured_ids = []
        for uri in featured_uris:
            parts = uri.split(':')
            if len(parts) == 3 and parts[2] and parts[2] not in seen:
                featured_ids.append(parts[2])
        if featured_ids:
            market = user_country or 'from_token'
            tracks_resp = sp.tracks(featured_ids[:50], market=market)
            for track in tracks_resp.get('tracks') or []:
                if not track:
                    continue
                tid = track.get('id')
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                deduped.append(track)
                if len(deduped) >= target_limit:
                    return deduped[:target_limit]
    except Exception as e:
        app.logger.warning('Recommendation top-up from featured tracks failed: %s', str(e))

    return deduped[:target_limit]


def save_tokens(spotify_id: str, access_token: str, refresh_token: str, display_name: Optional[str] = None, expires_at: Optional[int] = None):
    """Persist access/refresh tokens and expiry for a user."""
    conn = get_db()
    c = conn.cursor()
    c.execute(
        '''
        INSERT INTO users (spotify_id, display_name, access_token, refresh_token, expires_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(spotify_id) DO UPDATE SET
            display_name = excluded.display_name,
            access_token = excluded.access_token,
            refresh_token = excluded.refresh_token,
            expires_at = excluded.expires_at
        ''',
        (spotify_id, display_name, access_token, refresh_token, expires_at),
    )
    conn.commit()
    conn.close()


def get_saved_tokens(spotify_id: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """Return (access_token, refresh_token, expires_at) for a given Spotify user id."""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT access_token, refresh_token, expires_at FROM users WHERE spotify_id = ?', (spotify_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None, None, None
    return row['access_token'], row['refresh_token'], row['expires_at']


def refresh_access_token(refresh_token: str) -> Tuple[Optional[str], Optional[int]]:
    """Refresh the access token using the refresh token."""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        app.logger.error('Missing Spotify credentials!')
        return None, None

    data = {'grant_type': 'refresh_token', 'refresh_token': refresh_token}
    auth = (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)

    try:
        resp = requests.post('https://accounts.spotify.com/api/token', data=data, auth=auth, timeout=10)
    except requests.exceptions.RequestException as e:
        app.logger.error('Network error during token refresh: %s', str(e))
        return None, None

    if resp.status_code != 200:
        app.logger.error('Failed to refresh token: %s - %s', resp.status_code, resp.text[:200])
        return None, None

    body = resp.json()
    access_token = body.get('access_token')
    expires_in = body.get('expires_in')

    if not access_token:
        return None, None

    expires_at = int(time.time() + int(expires_in)) if expires_in else None
    return access_token, expires_at


def get_access_token() -> Optional[str]:
    """Return a valid access token for the current session's Spotify user."""
    spotify_id = session.get('spotify_id')
    if not spotify_id:
        return None

    access_token, refresh_token, expires_at = get_saved_tokens(spotify_id)
    now = int(time.time())
    slack = 60  # Refresh 60 seconds before expiry

    if access_token and expires_at and (expires_at - slack) > now:
        return access_token

    if refresh_token:
        new_token, new_expires_at = refresh_access_token(refresh_token)
        if new_token:
            save_tokens(spotify_id, new_token, refresh_token, session.get('display_name'), new_expires_at)
            return new_token

    return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login')
def login():
    """Redirect user to Spotify OAuth login."""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return 'Missing Spotify client credentials', 500

    # Allow logging in with a different Spotify account without changing app credentials.
    # This forces Spotify to show the account chooser/consent screen.
    session.clear()

    params = {
        'response_type': 'code',
        'client_id': SPOTIFY_CLIENT_ID,
        'scope': SPOTIFY_SCOPES,
        'redirect_uri': REDIRECT_URI,
        'show_dialog': 'true',
    }
    auth_url = f"https://accounts.spotify.com/authorize?{urlencode(params)}"
    return redirect(auth_url)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


@app.route('/callback')
def callback():
    """Handle Spotify OAuth callback and store tokens."""
    code = request.args.get('code')
    if not code:
        return 'Missing authorization code', 400

    data = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT_URI}
    auth_header = (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)

    token_response = requests.post('https://accounts.spotify.com/api/token', data=data, auth=auth_header)
    if token_response.status_code != 200:
        return 'Failed to get access token from Spotify', 500

    tokens = token_response.json()
    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')

    if not access_token or not refresh_token:
        return 'Invalid token response from Spotify', 500

    profile_resp = requests.get(
        'https://api.spotify.com/v1/me',
        headers={'Authorization': f'Bearer {access_token}'},
    )
    if profile_resp.status_code != 200:
        return 'Failed to fetch Spotify profile', 500

    profile = profile_resp.json()
    spotify_id = profile.get('id')
    display_name = profile.get('display_name') or ''

    session['spotify_id'] = spotify_id
    session['display_name'] = display_name

    expires_in = tokens.get('expires_in')
    expires_at = int(time.time() + int(expires_in)) if expires_in else None
    save_tokens(spotify_id, access_token, refresh_token, display_name, expires_at)

    return redirect('/')


@app.route('/profile')
def profile():
    """Return basic user profile info for the UI."""
    token = get_access_token()
    if not token:
        return jsonify({'logged_in': False})

    headers = {'Authorization': f'Bearer {token}'}
    resp = requests.get('https://api.spotify.com/v1/me', headers=headers)
    if resp.status_code != 200:
        return jsonify({'logged_in': False}), 401

    data = resp.json()
    image_url = data.get('images', [{}])[0].get('url') if data.get('images') else None

    return jsonify({
        'logged_in': True,
        'display_name': data.get('display_name'),
        'spotify_id': data.get('id'),
        'image_url': image_url,
    })


@app.route('/top-tracks')
def top_tracks():
    """
    Return the user's top tracks based on recently played.
    
    Logic:
    1. Fetch recently played tracks via current_user_recently_played()
    2. Count frequency of each track
    3. If most tracks appear only once, sort by recency (newest first)
    4. Otherwise, sort by frequency (most played first)
    5. Return top 10 ranked tracks
    """
    token = get_access_token()
    if not token:
        return jsonify({'error': 'not_logged_in'}), 401

    sp = spotipy.Spotify(auth=token)

    recent_items = []
    try:
        # Fetch recently played tracks (limit=50 to get more data for frequency analysis)
        recent_resp = sp.current_user_recently_played(limit=50)
        recent_items = recent_resp.get('items') or []
    except Exception as e:
        app.logger.warning('Failed to fetch recently played tracks, trying top tracks: %s', str(e))

    if not recent_items:
        try:
            top_resp = sp.current_user_top_tracks(limit=20, time_range='medium_term')
            top_items = top_resp.get('items') or []
            return jsonify({'tracks': top_items[:10]})
        except Exception as e:
            app.logger.error('Failed to fetch top tracks fallback: %s', str(e))
            return jsonify({'error': 'spotify_request_failed', 'detail': str(e)}), 500

    # Count frequency of each track and track its most recent play time
    track_freq = {}
    track_data = {}
    play_order = 0
    
    for entry in recent_items:
        track = entry.get('track')
        if not track:
            continue
        
        track_id = track.get('id')
        if not track_id:
            continue
        
        # Count this track
        if track_id in track_freq:
            track_freq[track_id] += 1
        else:
            track_freq[track_id] = 1
            track_data[track_id] = {
                'track': track,
                'first_play_order': play_order  # Lower = more recent
            }
        
        play_order += 1

    app.logger.info('Found %d unique tracks in recently played', len(track_freq))

    # Determine if we should sort by frequency or recency
    # Count how many tracks have frequency > 1
    multi_play_count = sum(1 for freq in track_freq.values() if freq > 1)
    
    # If most tracks appear only once, sort by recency
    if multi_play_count == 0 or multi_play_count < len(track_freq) * 0.2:
        # Sort by recency (first_play_order ascending = most recent first)
        app.logger.info('Sorting by recency (most plays are unique)')
        sorted_tracks = sorted(
            track_data.items(),
            key=lambda x: x[1]['first_play_order']
        )
    else:
        # Sort by frequency, then by recency for ties
        app.logger.info('Sorting by frequency (multiple plays detected)')
        sorted_tracks = sorted(
            track_data.items(),
            key=lambda x: (-track_freq[x[0]], x[1]['first_play_order'])
        )

    # Extract track objects and limit to top 10
    items = [track_data['track'] for track_id, track_data in sorted_tracks[:10]]

    return jsonify({'tracks': items})


@app.route('/recommendations')
def recommendations():
    """
    Return track recommendations based on provided seed track IDs.
    
    Query Parameters:
    - track_ids: Comma-separated list of Spotify track IDs to use as seeds
    
    Logic:
    1. Accept seed track IDs from frontend (the top tracks)
    2. Use first 5 tracks as seeds for recommendations
    3. Return up to 50 recommendations based on audio features and artists
    """
    token = get_access_token()
    if not token:
        return jsonify({'error': 'not_logged_in', 'message': 'Please log in again'}), 401

    # Get track IDs from query parameters
    track_ids_param = request.args.get('track_ids', '').strip()
    if not track_ids_param:
        return jsonify({'error': 'missing_seed_tracks', 'message': 'Please get your top tracks first'}), 400

    seed_track_ids = parse_track_ids_param(track_ids_param)
    if not seed_track_ids:
        return jsonify({'error': 'invalid_seed_tracks'}), 400

    excluded_track_ids = set(parse_track_ids_param(request.args.get('exclude_track_ids', '')))
    target_limit = 50

    sp = spotipy.Spotify(auth=token)
    user_country = get_user_country(sp)

    # Prefer the Spotify recommendation endpoint and fall back to artist-based retrieval.
    # Spotify allows at most 5 combined seeds across tracks/artists/genres.
    final_seed_tracks = seed_track_ids[:5]
    app.logger.info('Using %d seed tracks for recommendations', len(final_seed_tracks))

    rec_items = []
    try:
        # Prefer top-artist seeds from the user's own profile to avoid extra /tracks lookups.
        seed_artists = get_user_top_artist_ids(sp, limit=20)
        # Keep within max seed count of 5.
        track_seed_count = min(3, len(final_seed_tracks))
        artist_seed_count = min(5 - track_seed_count, len(seed_artists))

        rec_params = {
            'seed_tracks': final_seed_tracks[:track_seed_count],
            'seed_artists': seed_artists[:artist_seed_count],
            'limit': 50,
        }
        if user_country:
            rec_params['market'] = user_country
        # Remove empty params to avoid API errors.
        rec_params = {k: v for k, v in rec_params.items() if v}

        app.logger.info('Calling Spotify recommendations API with params: %s', rec_params)
        rec_resp = sp.recommendations(**rec_params)
        rec_items = rec_resp.get('tracks') or []
        app.logger.info('Primary recommendations count: %d', len(rec_items))
    except Exception as e:
        app.logger.warning('Primary recommendations failed: %s', str(e))

    # If Spotify recommendations fail or return empty, fallback to artist top tracks.
    if not rec_items:
        try:
            # Prefer previously resolved seed artists, otherwise derive artist seeds
            # from the user's own top tracks without using the /tracks batch lookup.
            if 'seed_artists' not in locals() or not seed_artists:
                seed_artists = get_user_top_artist_ids(sp, limit=20)
            rec_items = fallback_recommendations_from_artists(
                sp,
                seed_artists,
                seed_track_ids,
                country=user_country,
                limit=50,
            )
            app.logger.info('Fallback recommendations count: %d', len(rec_items))
        except Exception as e:
            app.logger.error('Fallback recommendations failed: %s', str(e))
            return jsonify({'error': 'spotify_request_failed', 'detail': str(e)}), 500

    # Final safety net: if still empty, return user's top tracks minus seed tracks.
    if not rec_items:
        try:
            rec_items = collect_expanded_fallback_tracks(sp, seed_track_ids, limit=50)
            app.logger.info('Expanded safety net count: %d', len(rec_items))
        except Exception as e:
            app.logger.warning('Top-tracks safety net failed: %s', str(e))

    # Keep only tracks that are available in the user's market (when metadata exists).
    if user_country and rec_items:
        filtered = []
        for track in rec_items:
            markets = track.get('available_markets')
            if not isinstance(markets, list) or not markets:
                filtered.append(track)
                continue
            if user_country in markets:
                filtered.append(track)
        rec_items = filtered

    # Exclude blocked/previously rejected tracks from refresh requests.
    if excluded_track_ids:
        rec_items = [t for t in rec_items if t.get('id') not in excluded_track_ids]

    rec_items = enrich_recommendations_pool(
        sp=sp,
        rec_items=rec_items,
        seed_track_ids=seed_track_ids,
        excluded_track_ids=excluded_track_ids,
        user_country=user_country,
        target_limit=target_limit,
    )

    rec_items = validate_recommendation_tracks(sp, rec_items, user_country)

    # One more top-up pass if strict validation dropped too many tracks.
    if len(rec_items) < target_limit:
        topup_excluded = excluded_track_ids.union(get_track_ids_from_items(rec_items))
        topup_items = enrich_recommendations_pool(
            sp=sp,
            rec_items=[],
            seed_track_ids=seed_track_ids,
            excluded_track_ids=topup_excluded,
            user_country=user_country,
            target_limit=target_limit,
        )
        rec_items = validate_recommendation_tracks(sp, rec_items + topup_items, user_country)
        rec_items = rec_items[:target_limit]

    return jsonify({'tracks': rec_items})


@app.route('/create-playlist', methods=['POST'])
def create_playlist():
    """Create a new playlist and add selected track URIs."""
    token = get_access_token()
    if not token:
        return jsonify({'error': 'not_logged_in'}), 401

    payload = request.get_json(silent=True) or {}
    playlist_name = payload.get('name') or 'My Recommendations'
    uris = payload.get('uris') or []
    selected_tracks = payload.get('selected_tracks') or []
    selected_lookup = build_selected_track_lookup(selected_tracks)

    if not isinstance(uris, list) or not uris:
        return jsonify({'error': 'missing_track_uris'}), 400

    normalized_uris = []
    seen_uris = set()
    for value in uris:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        if cleaned.startswith('spotify:track:'):
            if cleaned not in seen_uris:
                normalized_uris.append(cleaned)
                seen_uris.add(cleaned)
        elif len(cleaned) >= 20 and ':' not in cleaned:
            candidate = f'spotify:track:{cleaned}'
            if candidate not in seen_uris:
                normalized_uris.append(candidate)
                seen_uris.add(candidate)

    if not normalized_uris:
        return jsonify({'error': 'missing_track_uris'}), 400

    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    sp = spotipy.Spotify(auth=token)
    user_country = get_user_country(sp)

    # Create the playlist
    create_resp = requests.post(
        'https://api.spotify.com/v1/me/playlists',
        json={'name': playlist_name, 'public': False},
        headers=headers,
    )
    if create_resp.status_code not in (200, 201):
        app.logger.error('Playlist creation failed: %s %s', create_resp.status_code, create_resp.text[:300])
        status = 403 if create_resp.status_code == 403 else 500
        detail = create_resp.text[:300]
        message = 'Failed to create playlist in Spotify.'
        if create_resp.status_code == 403:
            message = 'Spotify denied playlist creation. Please log out and log in again to refresh permissions.'
        return jsonify({'error': 'playlist_creation_failed', 'message': message, 'detail': detail}), status

    playlist = create_resp.json()
    playlist_id = playlist.get('id')
    playlist_url = playlist.get('external_urls', {}).get('spotify')

    if not playlist_id:
        return jsonify({'error': 'playlist_creation_failed'}), 500

    # Add tracks to the playlist.
    # Some tracks can be blocked by market/copyright rules and return 403.
    # In that case, retry one-by-one so we can still add the tracks that are allowed.
    added_count = 0
    skipped_count = 0
    substituted_count = 0
    skipped_uris = []
    blocked_tracks = []
    added_uris = set()

    for i in range(0, len(normalized_uris), 100):
        chunk = normalized_uris[i:i + 100]
        add_resp = requests.post(
            f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
            json={'uris': chunk},
            headers=headers,
        )
        if add_resp.status_code in (200, 201):
            added_count += len(chunk)
            for uri in chunk:
                added_uris.add(uri)
            continue

        app.logger.warning('Chunk add failed (%s), retrying per track: %s', add_resp.status_code, add_resp.text[:200])

        # Retry each track so we can skip only blocked items.
        for uri in chunk:
            single_resp = requests.post(
                f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
                json={'uris': [uri]},
                headers=headers,
            )
            if single_resp.status_code in (200, 201):
                added_count += 1
                added_uris.add(uri)
            else:
                alternative_uri = find_alternative_track_uri(
                    sp=sp,
                    metadata=selected_lookup.get(uri, {}),
                    country=user_country,
                    used_uris=added_uris,
                )

                if alternative_uri:
                    alt_resp = requests.post(
                        f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
                        json={'uris': [alternative_uri]},
                        headers=headers,
                    )
                    if alt_resp.status_code in (200, 201):
                        added_count += 1
                        substituted_count += 1
                        added_uris.add(alternative_uri)
                        app.logger.info('Substituted blocked %s with %s', uri, alternative_uri)
                        continue

                skipped_count += 1
                skipped_uris.append(uri)
                blocked_tracks.append(build_blocked_track_detail(uri, selected_lookup))
                app.logger.warning(
                    'Skipping blocked track %s (%s): %s',
                    uri,
                    single_resp.status_code,
                    single_resp.text[:180],
                )

    if added_count == 0:
        # Last fallback: seed the playlist with user's top tracks so it isn't empty.
        # This keeps UX functional when recommended tracks are market-blocked.
        fallback_added = 0
        try:
            top_resp = sp.current_user_top_tracks(limit=30, time_range='short_term')
            top_uris = [
                t.get('uri')
                for t in (top_resp.get('items') or [])
                if t and isinstance(t.get('uri'), str) and t.get('uri').startswith('spotify:track:')
            ]
            for uri in top_uris[:20]:
                single_resp = requests.post(
                    f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
                    json={'uris': [uri]},
                    headers=headers,
                )
                if single_resp.status_code in (200, 201):
                    fallback_added += 1
                if fallback_added >= 10:
                    break
        except Exception as e:
            app.logger.warning('Top-track fallback playlist fill failed: %s', str(e))

        # Secondary fallback: add tracks from featured playlists in user's market.
        if fallback_added == 0:
            try:
                featured_uris = collect_featured_playlist_uris(sp, user_country, limit=30)
                for uri in featured_uris:
                    single_resp = requests.post(
                        f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks',
                        json={'uris': [uri]},
                        headers=headers,
                    )
                    if single_resp.status_code in (200, 201):
                        fallback_added += 1
                    if fallback_added >= 10:
                        break
            except Exception as e:
                app.logger.warning('Featured-playlist fallback fill failed: %s', str(e))

        if fallback_added > 0:
            return jsonify({
                'status': 'ok',
                'playlist_id': playlist_id,
                'playlist_url': playlist_url,
                'name': playlist_name,
                'added_count': fallback_added,
                'skipped_count': skipped_count,
                'substituted_count': substituted_count,
                'skipped_uris': skipped_uris[:10],
                'blocked_tracks': blocked_tracks,
                'message': 'Selected recommendations were blocked in your market. Added songs from your top tracks instead.',
                'used_fallback_tracks': True,
            })

        return jsonify({
            'error': 'tracks_add_failed',
            'message': 'Spotify blocked all selected tracks for your account/market. Try different songs.',
            'detail': f'skipped={skipped_count}',
            'skipped_uris': skipped_uris[:50],
            'blocked_tracks': blocked_tracks,
            'playlist_id': playlist_id,
            'playlist_url': playlist_url,
        }), 403

    return jsonify({
        'status': 'ok',
        'playlist_id': playlist_id,
        'playlist_url': playlist_url,
        'name': playlist_name,
        'added_count': added_count,
        'skipped_count': skipped_count,
        'substituted_count': substituted_count,
        'skipped_uris': skipped_uris[:10],
        'blocked_tracks': blocked_tracks,
    })


if __name__ == '__main__':
    app.run(debug=True)
