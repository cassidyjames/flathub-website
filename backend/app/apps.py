import json
import re

import gi

from . import db, schemas, search, utils

gi.require_version("AppStream", "1.0")
from gi.repository import AppStream

clean_html_re = re.compile("<.*?>")
all_main_categories = schemas.get_main_categories()


def add_to_search(appid: str, app: dict) -> dict:
    search_description = re.sub(clean_html_re, "", app["description"])

    search_keywords = app.get("keywords")

    project_license = app.get("project_license", "")

    categories = app.get("categories", [])
    main_categories = [
        category for category in categories if category in all_main_categories
    ]
    sub_categories = [
        category for category in categories if category not in all_main_categories
    ]

    # order of the dict is important for attritbute ranking
    return {
        "id": utils.get_clean_app_id(appid),
        "name": app["name"],
        "summary": app["summary"],
        "keywords": search_keywords,
        "project_license": project_license,
        "is_free_license": AppStream.license_is_free_license(project_license),
        "app_id": appid,
        "description": search_description,
        "icon": app["icon"],
        "categories": categories,
        "main_categories": main_categories,
        "sub_categories": sub_categories,
        "developer_name": app.get("developer_name"),
        "project_group": app.get("project_group"),
        "verification_verified": app.get("metadata", {}).get(
            "flathub::verification::verified", False
        ),
        "verification_method": app.get("metadata", {}).get(
            "flathub::verification::method", None
        ),
        "verification_login_name": app.get("metadata", {}).get(
            "flathub::verification::login_name", None
        ),
        "verification_login_provider": app.get("metadata", {}).get(
            "flathub::verification::login_provider", None
        ),
        "verification_login_is_organization": app.get("metadata", {}).get(
            "flathub::verification::login_is_organization", None
        ),
        "verification_website": app.get("metadata", {}).get(
            "flathub::verification::website", None
        ),
        "verification_timestamp": app.get("metadata", {}).get(
            "flathub::verification::timestamp", None
        ),
        "runtime": app.get("bundle", {}).get("runtime", None),
    }


def load_appstream():
    apps = utils.appstream2dict("repo")

    current_apps = {app[5:] for app in db.redis_conn.smembers("apps:index")}
    current_developers = db.redis_conn.smembers("developers:index")
    current_projectgroups = db.redis_conn.smembers("projectgroups:index")

    with db.redis_conn.pipeline() as p:
        p.delete("developers:index", *current_developers)
        p.delete("projectgroups:index", *current_projectgroups)

        search_apps = []
        for appid in apps:
            redis_key = f"apps:{appid}"

            search_apps.append(add_to_search(appid, apps[appid]))

            if developer_name := apps[appid].get("developer_name"):
                p.sadd("developers:index", developer_name)

            if project_group := apps[appid].get("project_group"):
                p.sadd("projectgroups:index", project_group)

            p.set(redis_key, json.dumps(apps[appid]))

            if categories := apps[appid].get("categories"):
                for category in categories:
                    p.sadd(f"categories:{category}", redis_key)

        search.create_or_update_apps(search_apps)

        apps_to_delete_from_search = []
        for appid in current_apps - set(apps):
            p.delete(
                f"apps:{appid}",
                f"summary:{appid}",
                f"app_stats:{appid}",
            )
            apps_to_delete_from_search.append(utils.get_clean_app_id(appid))
        search.delete_apps(apps_to_delete_from_search)

        new_apps = set(apps) - current_apps
        if not len(new_apps):
            new_apps = None

        p.delete("apps:index")
        p.sadd("apps:index", *[f"apps:{appid}" for appid in apps])
        p.execute()

    return new_apps


def list_appstream():
    apps = {app[5:] for app in db.redis_conn.smembers("apps:index")}
    return sorted(apps)


def get_recently_updated(limit: int = 100):
    zset = db.redis_conn.zrevrange("recently_updated_zset", 0, limit - 1)
    return [appid for appid in zset if db.redis_conn.exists(f"apps:{appid}")]


def get_recently_added(limit: int = 100):
    zset = db.redis_conn.zrevrange("new_apps_zset", 0, limit - 1)
    return [appid for appid in zset if db.redis_conn.exists(f"apps:{appid}")]
