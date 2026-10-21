"""Debug a LinkedIn member access token against official LinkedIn endpoints.

Usage:
  set LINKEDIN_ACCESS_TOKEN=...
  python backend/scripts/debug_linkedin_identity.py

Optional env vars:
  LINKEDIN_CLIENT_ID
  LINKEDIN_CLIENT_SECRET
  LINKEDIN_API_VERSION   defaults to 202501
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

import requests


OIDC_CONFIG_URL = "https://www.linkedin.com/oauth/.well-known/openid-configuration"
ME_URL = "https://api.linkedin.com/v2/me"
IDENTITY_ME_URL = "https://api.linkedin.com/rest/identityMe"
INTROSPECT_URL = "https://www.linkedin.com/oauth/v2/introspectToken"


def _safe_get(payload: Any, *path: str) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _localized_string(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    localized = value.get("localized")
    if isinstance(localized, dict) and localized:
        first = next(iter(localized.values()), "")
        return str(first or "").strip()
    val = value.get("value")
    return str(val or "").strip()


def _response_payload(resp: requests.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception:
        body = {"raw_text": resp.text[:4000]}
    return {
        "status_code": resp.status_code,
        "ok": resp.ok,
        "headers": {
            "content-type": resp.headers.get("content-type"),
            "x-restli-id": resp.headers.get("x-restli-id"),
            "linkedin-version": resp.request.headers.get("LinkedIn-Version"),
        },
        "body": body,
    }


def _call(
    session: requests.Session,
    name: str,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    timeout: int,
) -> dict[str, Any]:
    try:
        response = session.request(method, url, headers=headers, data=data, timeout=timeout)
    except Exception as exc:
        return {
            "endpoint": name,
            "url": url,
            "ok": False,
            "error": str(exc),
        }
    payload = _response_payload(response)
    payload["endpoint"] = name
    payload["url"] = url
    return payload


def _normalize_userinfo(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    return {
        "provider_user_id": body.get("sub"),
        "display_name": body.get("name"),
        "given_name": body.get("given_name"),
        "family_name": body.get("family_name"),
        "email": body.get("email"),
        "image_url": body.get("picture"),
    }


def _normalize_v2_me(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    first = body.get("localizedFirstName") or _localized_string(body.get("firstName"))
    last = body.get("localizedLastName") or _localized_string(body.get("lastName"))
    display_name = " ".join(part for part in [first, last] if part).strip()
    vanity = str(body.get("vanityName") or "").strip()
    profile_url = f"https://www.linkedin.com/in/{vanity}" if vanity else ""
    return {
        "provider_user_id": body.get("id"),
        "display_name": display_name,
        "headline": body.get("localizedHeadline") or _localized_string(body.get("headline")),
        "profile_url": profile_url,
        "image_urn": _safe_get(body, "profilePicture", "displayImage"),
    }


def _normalize_identity_me(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    basic = body.get("basicInfo") or {}
    first = _localized_string(basic.get("firstName"))
    last = _localized_string(basic.get("lastName"))
    display_name = " ".join(part for part in [first, last] if part).strip()
    current_position = body.get("primaryCurrentPosition") or {}
    education = body.get("mostRecentEducation") or {}
    return {
        "provider_user_id": body.get("id"),
        "display_name": display_name,
        "email": basic.get("primaryEmailAddress"),
        "profile_url": basic.get("profileUrl"),
        "image_url": _safe_get(basic, "profilePicture", "croppedImage", "downloadUrl"),
        "headline": _localized_string(basic.get("headline")) or _localized_string(current_position.get("title")),
        "organization": _localized_string(current_position.get("companyName")),
        "education_school": _localized_string(education.get("schoolName")),
        "education_degree": _localized_string(education.get("degreeName")),
    }


def _merged_summary(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    userinfo = _normalize_userinfo(_safe_get(results, "userinfo", "body"))
    v2_me = _normalize_v2_me(_safe_get(results, "v2_me", "body"))
    identity_me = _normalize_identity_me(_safe_get(results, "identity_me", "body"))
    merged: dict[str, Any] = {}
    for source in (userinfo, identity_me, v2_me):
        for key, value in source.items():
            if value not in (None, "", []):
                merged.setdefault(key, value)
    return {
        "userinfo": userinfo,
        "v2_me": v2_me,
        "identity_me": identity_me,
        "merged": merged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug LinkedIn token-backed identity endpoints.")
    parser.add_argument("--token-env", default="LINKEDIN_ACCESS_TOKEN")
    parser.add_argument("--client-id-env", default="LINKEDIN_CLIENT_ID")
    parser.add_argument("--client-secret-env", default="LINKEDIN_CLIENT_SECRET")
    parser.add_argument("--api-version", default=os.getenv("LINKEDIN_API_VERSION", "202501"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--raw", action="store_true", help="Include raw endpoint payloads in the final JSON.")
    args = parser.parse_args()

    token = (os.getenv(args.token_env) or "").strip()
    if not token:
        print(json.dumps({"error": f"Missing env var: {args.token_env}"}))
        return 1

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": "PersonaOn-LinkedIn-Debug/1.0"})

    results: dict[str, dict[str, Any]] = {}

    oidc = _call(session, "oidc_config", "GET", OIDC_CONFIG_URL, timeout=args.timeout)
    results["oidc_config"] = oidc

    userinfo_endpoint = _safe_get(oidc, "body", "userinfo_endpoint")
    if userinfo_endpoint:
        results["userinfo"] = _call(session, "userinfo", "GET", userinfo_endpoint, timeout=args.timeout)
    else:
        results["userinfo"] = {
            "endpoint": "userinfo",
            "ok": False,
            "error": "userinfo_endpoint missing from OIDC configuration",
        }

    results["v2_me"] = _call(
        session,
        "v2_me",
        "GET",
        ME_URL,
        headers={"X-RestLi-Protocol-Version": "2.0.0"},
        timeout=args.timeout,
    )

    results["identity_me"] = _call(
        session,
        "identity_me",
        "GET",
        IDENTITY_ME_URL,
        headers={"LinkedIn-Version": args.api_version},
        timeout=args.timeout,
    )

    client_id = (os.getenv(args.client_id_env) or "").strip()
    client_secret = (os.getenv(args.client_secret_env) or "").strip()
    if client_id and client_secret:
        results["introspect"] = _call(
            session,
            "introspect",
            "POST",
            INTROSPECT_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"client_id": client_id, "client_secret": client_secret, "token": token},
            timeout=args.timeout,
        )

    output = {
        "token_env": args.token_env,
        "token_length": len(token),
        "api_version": args.api_version,
        "summary": _merged_summary(results),
        "endpoints": results if args.raw else {
            key: {
                "ok": value.get("ok"),
                "status_code": value.get("status_code"),
                "error": value.get("error"),
            }
            for key, value in results.items()
        },
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
