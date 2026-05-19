# musicapp/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path("", views.music_home, name="music_home"),
    path("search/", views.music_search, name="music_search"),
    path("track/", views.track_detail, name="music_track_detail"),
    path("artist/<str:channel_id>/", views.artist_detail, name="music_artist_detail"),
    path("artist/<str:channel_id>/all-tracks/", views.artist_all_tracks_json, name="music_artist_all_tracks"),
    path("album/", views.album_detail, name="music_album_detail"),
    path("playlist/", views.playlist_detail, name="music_playlist_detail"),
    path("downloads/", views.music_downloads, name="music_downloads"),

    # JSON APIs
    path("api/start-download/", views.start_music_download, name="music_start_download"),
    path("api/downloads/", views.get_music_downloads_json, name="music_downloads_json"),
    path("api/track-formats/", views.get_track_formats_json, name="music_track_formats"),
    path("api/album-tracks/", views.get_album_tracks_json, name="music_album_tracks_json"),
    path("api/resolve-track/", views.resolve_spotify_track_api, name="music_resolve_track"),
]
