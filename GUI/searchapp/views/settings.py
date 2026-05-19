# settings.py — Views for settings editor, config save/reload and service ZIP upload.

import os
import sys
import json
import shutil
import zipfile
import importlib
import logging

from django.shortcuts import render
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from VibraVid.utils import config_manager

logger = logging.getLogger(__name__)


def settings_editor(request: HttpRequest) -> HttpResponse:
    conf_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "Conf")
    config_path = os.path.join(conf_dir, "config.json")
    login_path = os.path.join(conf_dir, "login.json")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_content = f.read()
    except Exception as e:
        config_content = f"# Errore nella lettura del file: {e}"

    try:
        with open(login_path, "r", encoding="utf-8") as f:
            login_content = f.read()
    except Exception as e:
        login_content = f"# Errore nella lettura del file: {e}"

    return render(
        request,
        "searchapp/settings_editor.html",
        {"config_content": config_content, "login_content": login_content},
    )


@require_http_methods(["POST"])
@csrf_exempt
def save_settings(request: HttpRequest) -> JsonResponse:
    try:
        data = json.loads(request.body.decode("utf-8"))
        file_type = data.get("file_type")  # 'config' or 'login'
        content = data.get("content", "").strip()

        if not file_type or not content:
            return JsonResponse({"success": False, "error": "Parametri mancanti"}, status=400)

        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            return JsonResponse({"success": False, "error": f"JSON non valido: {str(e)}"}, status=400)

        conf_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "Conf")
        if file_type == "config":
            file_path = os.path.join(conf_dir, "config.json")
        elif file_type == "login":
            file_path = os.path.join(conf_dir, "login.json")
        else:
            return JsonResponse({"success": False, "error": "Tipo di file non valido"}, status=400)

        backup_path = file_path + ".backup"
        if os.path.exists(file_path):
            try:
                shutil.copy2(file_path, backup_path)
            except Exception as e:
                print(f"Backup failed: {e}")

        with open(file_path, "w", encoding="utf-8") as f:
            formatted = json.dumps(json.loads(content), indent=4, ensure_ascii=False)
            f.write(formatted)

        return JsonResponse({"success": True, "message": f"{file_type}.json salvato con successo"})

    except Exception as e:
        return JsonResponse({"success": False, "error": f"Errore nel salvataggio: {str(e)}"}, status=500)


@require_http_methods(["POST"])
def reload_config(request: HttpRequest) -> JsonResponse:
    try:
        file_type = None
        if request.content_type and "application/json" in request.content_type:
            try:
                data = json.loads(request.body.decode("utf-8"))
                file_type = data.get("file_type")
            except Exception:
                file_type = None

        if file_type == "login":
            config_manager.reload_login_only()
            message = "Login ricaricato"
        elif file_type == "config":
            config_manager.reload_config_only()
            message = "Config ricaricata"
        else:
            config_manager.reload()
            message = "Config ricaricata"
        return JsonResponse({"success": True, "message": message})
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Errore nel reload: {str(e)}"}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def upload_service_zip(request: HttpRequest) -> JsonResponse:
    """Handle ZIP file upload to install a new service plugin."""
    uploaded = request.FILES.get("service_zip")
    if not uploaded:
        return JsonResponse({"success": False, "error": "Nessun file ZIP caricato."}, status=400)

    if not uploaded.name.lower().endswith(".zip"):
        return JsonResponse({"success": False, "error": "Il file deve essere un archivio .zip"}, status=400)

    # searchapp/views/settings.py → up 4 levels to project root
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    services_dir = os.path.join(base_dir, "VibraVid", "services")

    if not os.path.isdir(services_dir):
        return JsonResponse({"success": False, "error": f"Directory dei servizi non trovata: {services_dir}"}, status=500)

    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="vv_service_upload_")
    errors = []
    installed_services = []

    try:
        zip_path = os.path.join(tmp_dir, uploaded.name)
        with open(zip_path, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile:
            return JsonResponse({"success": False, "error": "File ZIP non valido o corrotto."}, status=400)

        extracted_items = [d for d in os.listdir(tmp_dir) if os.path.isdir(os.path.join(tmp_dir, d))]

        service_folders = []
        for item in extracted_items:
            item_path = os.path.join(tmp_dir, item)
            init_file = os.path.join(item_path, "__init__.py")
            if os.path.isfile(init_file):
                service_folders.append(item)
            else:
                for sub in os.listdir(item_path):
                    sub_path = os.path.join(item_path, sub)
                    if os.path.isdir(sub_path) and os.path.isfile(os.path.join(sub_path, "__init__.py")):
                        service_folders.append(os.path.join(item, sub))

        if not service_folders:
            return JsonResponse({
                "success": False,
                "error": "Nessun servizio valido trovato nello ZIP. Ogni servizio deve contenere __init__.py con 'indice' e '_useFor'.",
            }, status=400)

        import ast as _ast

        for svc_rel in service_folders:
            svc_path = os.path.join(tmp_dir, svc_rel)
            svc_name = os.path.basename(svc_rel).lower()
            init_path = os.path.join(svc_path, "__init__.py")

            if svc_name.startswith("_") or svc_name in {"base", "_base"}:
                errors.append(f"'{svc_name}': nome riservato, non può essere installato come servizio")
                continue

            syntax_error = None
            for root, _, files in os.walk(svc_path):
                for fname in files:
                    if not fname.endswith(".py"):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh:
                            src = fh.read()
                        _ast.parse(src, filename=fname)
                    except SyntaxError as se:
                        rel = os.path.relpath(fpath, svc_path)
                        syntax_error = f"{rel}:{se.lineno}: {se.msg}"
                        break
                    except Exception as ex:
                        rel = os.path.relpath(fpath, svc_path)
                        syntax_error = f"{rel}: impossibile leggere ({ex})"
                        break
                if syntax_error:
                    break
            if syntax_error:
                errors.append(f"'{svc_name}': errore di sintassi nel plugin → {syntax_error}")
                continue

            try:
                with open(init_path, "r", encoding="utf-8") as f:
                    content = f.read()

                has_indice = False
                has_usefor = False
                for line in content.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("indice =") or stripped.startswith("indice="):
                        has_indice = True
                    if stripped.startswith("_useFor =") or stripped.startswith("_useFor="):
                        has_usefor = True

                if not has_indice:
                    errors.append(f"'{svc_name}': manca la dichiarazione 'indice' in __init__.py")
                    continue
                if not has_usefor:
                    errors.append(f"'{svc_name}': manca la dichiarazione '_useFor' in __init__.py")
                    continue

            except Exception as e:
                errors.append(f"'{svc_name}': errore nella lettura di __init__.py: {e}")
                continue

            dest_path = os.path.join(services_dir, svc_name)
            if os.path.exists(dest_path):
                shutil.rmtree(dest_path)

            shutil.copytree(svc_path, dest_path)
            installed_services.append(svc_name)

        if installed_services:
            try:
                for svc in installed_services:
                    prefix = f"VibraVid.services.{svc}"
                    for mod_name in [m for m in sys.modules if m == prefix or m.startswith(prefix + ".")]:
                        del sys.modules[mod_name]

                from VibraVid.services._base import site_loader
                importlib.reload(site_loader)
            except Exception as e:
                errors.append(f"Reload CLI services: {e}")

            try:
                for mod_name in [m for m in sys.modules if m.startswith("GUI.searchapp.api.") and not m.endswith(".base")]:
                    del sys.modules[mod_name]

                from GUI.searchapp import api as gui_api_module
                gui_api_module._INITIALIZED = False
                gui_api_module._initialize_registry()
            except Exception as e:
                errors.append(f"Reload GUI API registry: {e}")

        try:
            from GUI.searchapp import api as gui_api_module
            available_sites = sorted(gui_api_module.get_available_sites())
            load_errors_list = gui_api_module.get_load_errors()
        except Exception:
            available_sites = []
            load_errors_list = []

        result = {
            "success": len(installed_services) > 0,
            "installed": installed_services,
            "errors": errors,
            "available_sites_now": available_sites,
            "load_errors": load_errors_list,
            "message": (
                f"Installati {len(installed_services)} servizi: {', '.join(installed_services)}"
                if installed_services
                else "Nessun servizio installato."
            ),
        }
        return JsonResponse(result, status=200 if installed_services else 400)

    except Exception as e:
        return JsonResponse({"success": False, "error": f"Errore durante l'installazione: {e}"}, status=500)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@require_http_methods(["GET"])
def registry_status(request: HttpRequest) -> JsonResponse:
    """Diagnostic endpoint: report what the GUI service registry currently knows."""
    from GUI.searchapp import api as gui_api_module

    api_dir = os.path.dirname(gui_api_module.__file__)
    static_stubs = sorted(
        f[:-3]
        for f in os.listdir(api_dir)
        if f.endswith(".py") and f not in ("base.py", "__init__.py")
    )

    # searchapp/views/settings.py → up 4 levels to project root
    services_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
        "VibraVid",
        "services",
    )
    services_on_disk = []
    if os.path.isdir(services_dir):
        for entry in sorted(os.listdir(services_dir)):
            full = os.path.join(services_dir, entry)
            if entry.startswith("_") or entry.startswith("."):
                continue
            if os.path.isdir(full) and os.path.isfile(os.path.join(full, "__init__.py")):
                services_on_disk.append(entry.lower())

    loaded = sorted(gui_api_module.get_available_sites())
    missing_from_dropdown = sorted(set(services_on_disk) - set(loaded))

    return JsonResponse({
        "loaded_in_dropdown": loaded,
        "services_on_disk": services_on_disk,
        "static_gui_stubs": static_stubs,
        "missing_from_dropdown": missing_from_dropdown,
        "load_errors": gui_api_module.get_load_errors(),
        "db_dir": os.environ.get("DJANGO_DB_DIR", "<unset>"),
        "hint": (
            "Se 'loaded_in_dropdown' contiene solo mostraguarda ma "
            "'services_on_disk' ne contiene di più, guarda 'load_errors' "
            "per vedere perché gli altri non caricano."
        ),
    })
