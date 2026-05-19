# Re-export all view functions so existing imports (urls.py, etc.) keep working
# without any change.

from .core import (
    download_executor,
    scheduled_downloads,
    scheduled_downloads_lock,
    cancelled_scheduled_downloads,
    set_max_download_slots,
    _acquire_download_slot,
    _release_download_slot,
    _add_scheduled_download,
    _remove_scheduled_download,
    _cancel_scheduled_download,
    _is_scheduled_cancelled,
    _get_scheduled_downloads,
    _enrich_active_downloads_with_series,
    _prune_scheduled_downloads,
    _extract_series_base_title,
    _same_series,
    shutdown_downloads,
    _submit_download_task,
    _run_download_in_thread,
    _media_item_to_display_dict,
    _to_bool,
    _is_recent_webhook,
    _mark_native_webhook_seen,
)

from .search_video import search_home, search
from .series import series_metadata, series_detail
from .downloads import (
    start_download,
    download_dashboard,
    get_downloads_json,
    kill_download,
    kill_and_clear_queue,
    clear_download_history,
)
from .watchlist import (
    watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    update_watchlist_item,
    update_all_watchlist,
    update_watchlist_auto,
    run_watchlist_auto_now,
    watchlist_status,
    clear_watchlist,
    set_watchlist_polling_interval,
)
from .settings import (
    settings_editor,
    save_settings,
    reload_config,
    upload_service_zip,
    registry_status,
)
from .arr import (
    seerr_webhook,
    sonarr_webhook,
    radarr_webhook,
    arr_status,
    arr_trigger_sync,
)
