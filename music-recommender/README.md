# Music Recommender

A simple Flask application that recommends songs based on your Spotify listening history.

## Features

- **Top Tracks**: View your most played songs on Spotify
- **Recommendations**: Get song recommendations based on your top tracks
- **Playlist Creation**: Create a new Spotify playlist with your selected recommendations

## Project Structure

```
music-recommender/
├── app.py                 # Main Flask server
├── templates/
│   └── index.html         # Frontend HTML
├── static/
│   ├── app.js             # Frontend JavaScript
│   └── style.css          # Styles
├── database/
│   ├── schema.sql
│   └── recommend.db       # created at runtime
├── requirements.txt
└── README.md
```

## Setup

### 1. Create a Spotify Developer App

1. Go to https://developer.spotify.com/dashboard/
2. Create a new app
3. Add `http://127.0.0.1:5000/callback` as a Redirect URI
4. Copy your **Client ID** and **Client Secret**

### 2. Install Dependencies

```powershell
cd "c:\Users\Bryce\Documents\Programming Language Final\music-recommender"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Set Environment Variables

```powershell
$env:SPOTIFY_CLIENT_ID="your-client-id-here"
$env:SPOTIFY_CLIENT_SECRET="your-client-secret-here"
$env:FLASK_SECRET_KEY="any-secret-key"
$env:SPOTIFY_REDIRECT_URI="http://127.0.0.1:5000/callback"
```

### 4. Run the App

```powershell
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## How to Use

1. **Login**: Click "Login with Spotify" and authorize the app
2. **Get Top Tracks**: Click "Get My Top Tracks" to see your most played songs
3. **Get Recommendations**: Click "Get Recommendations" to see songs recommended based on your top tracks
4. **Create Playlist**: 
   - Select recommended songs using the checkboxes
   - Click "Create Playlist"
   - Enter a playlist name in the popup
   - Click "Done" to create the playlist in your Spotify account

## How Recommendations Work

The app uses Spotify's recommendation engine with seeds from your top tracks:

1. Fetches your top 10 tracks from Spotify
2. Extracts track IDs and artist IDs from your top tracks
3. Uses these as seeds for Spotify's recommendation API
4. Returns 20 recommended songs that match your taste

## Troubleshooting

- **Missing credentials error**: Make sure you set the environment variables before running the app
- **Login fails**: Verify the Redirect URI in your Spotify Dashboard matches exactly
- **No recommendations**: Listen to more music on Spotify to build your listening history
- **Token expired**: Click Logout and login again to get fresh tokens

## Requirements

- Python 3.8+
- Flask
- Spotipy (Spotify API wrapper)
- Requests
- SQLite (included with Python)
