# 06.06.25

from django.urls import path

from .views import (
    # Search (video)
    search_home, search,
    # Download management
    start_download, download_dashboard, get_downloads_json,
    kill_download, kill_and_clear_queue, clear_download_history,
    # Series
    series_metadata, series_detail,
    # Watchlist
    watchlist, add_to_watchlist, remove_from_watchlist, update_watchlist_item,
    update_all_watchlist, update_watchlist_auto, run_watchlist_auto_now,
    watchlist_status, clear_watchlist, set_watchlist_polling_interval,
    # Settings
    settings_editor, save_settings, reload_config, upload_service_zip, registry_status,
    # ARR
    seerr_webhook, sonarr_webhook, radarr_webhook, arr_status, arr_trigger_sync,
)

urlpatterns = [
    path("", search_home, name="search_home"),
    path("search/", search, name="search"),
    path("download/", start_download, name="start_download"),
    path("series-metadata/", series_metadata, name="series_metadata"),
    path("series-detail/", series_detail, name="series_detail"),

    # Download
    path("downloads/", download_dashboard, name="download_dashboard"),
    path("api/get-downloads/", get_downloads_json, name="get_downloads_json"),
    path("api/kill-download/", kill_download, name="kill_download"),
    path("api/kill-and-clear-queue/", kill_and_clear_queue, name="kill_and_clear_queue"),
    path("api/clear-history/", clear_download_history, name="clear_download_history"),

    # Watchlist
    path("watchlist/", watchlist, name="watchlist"),
    path("watchlist/add/", add_to_watchlist, name="add_to_watchlist"),
    path("watchlist/remove/<int:item_id>/", remove_from_watchlist, name="remove_from_watchlist"),
    path("watchlist/update/<int:item_id>/", update_watchlist_item, name="update_watchlist_item"),
    path("watchlist/update-all/", update_all_watchlist, name="update_all_watchlist"),
    path("watchlist/auto/<int:item_id>/", update_watchlist_auto, name="update_watchlist_auto"),
    path("watchlist/auto-run/", run_watchlist_auto_now, name="run_watchlist_auto_now"),
    path("watchlist/auto-interval/", set_watchlist_polling_interval, name="set_watchlist_polling_interval"),
    path("watchlist/clear/", clear_watchlist, name="clear_watchlist"),
    path("api/watchlist-status/", watchlist_status, name="watchlist_status"),

    # Settings
    path("settings/", settings_editor, name="settings_editor"),
    path("api/save-settings/", save_settings, name="save_settings"),
    path("api/reload-config/", reload_config, name="reload_config"),
    path("api/upload-service/", upload_service_zip, name="upload_service_zip"),
    path("api/registry-status/", registry_status, name="registry_status"),

    # ARR Integration
    path("api/arr/webhook/seerr/", seerr_webhook, name="seerr_webhook"),
    path("api/arr/webhook/sonarr/", sonarr_webhook, name="sonarr_webhook"),
    path("api/arr/webhook/radarr/", radarr_webhook, name="radarr_webhook"),
    path("api/arr/status/", arr_status, name="arr_status"),
    path("api/arr/trigger-sync/", arr_trigger_sync, name="arr_trigger_sync"),
]