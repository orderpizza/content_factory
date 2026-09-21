"""Production destination readiness checks; live checks are explicit opt-in."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
import json
import os

from .delivery import (
    DeliveryConfigurationError,
    DeliveryError,
    JsonHttpTransport,
    R2TransientRelay,
)
from .store import WorkflowStore
from common.timestamps import utc_now


class CapabilityReadinessMonitor:
    def __init__(
        self,
        store: WorkflowStore,
        *,
        transport: JsonHttpTransport | None = None,
        relay_factory: Callable[[Mapping[str, Any]], R2TransientRelay] | None = None,
    ):
        self.store = store
        self.transport = transport or JsonHttpTransport()
        self.relay_factory = relay_factory or (lambda config: R2TransientRelay(config))

    def run(
        self, *, live: bool, confirm_r2_probe: bool = False, only_due: bool = False
    ) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            "SELECT d.social_destination_id,d.platform,d.provider_account_id,d.secret_ref,"
            "d.config_json,r.status readiness_status,r.valid_until "
            "FROM social_destinations d JOIN capability_readiness r "
            "ON r.social_destination_id=d.social_destination_id "
            "WHERE d.enabled=1 ORDER BY d.social_destination_id"
        ).fetchall()
        results = []
        for row in rows:
            moment = utc_now()
            if only_due and row["valid_until"] > moment:
                results.append({
                    "destination_id": int(row["social_destination_id"]),
                    "platform": row["platform"], "status": row["readiness_status"],
                    "reasons": [], "cached": True,
                })
                continue
            status, reasons, facts = self._check(dict(row), live=live,
                                                  confirm_r2_probe=confirm_r2_probe)
            check_id = self.store.record_destination_readiness(
                int(row["social_destination_id"]), status=status, reasons=reasons, facts=facts,
                valid_for=timedelta(hours=6) if status == "ready" else timedelta(minutes=15),
            )
            results.append({"destination_id": int(row["social_destination_id"]),
                            "platform": row["platform"], "status": status,
                            "reasons": reasons, "check_id": check_id, "cached": False})
        return results

    def _check(
        self, row: dict[str, Any], *, live: bool, confirm_r2_probe: bool
    ) -> tuple[str, list[str], dict[str, Any]]:
        config = json.loads(row["config_json"])
        secret_name = str(row["secret_ref"])
        missing = [secret_name] if not os.getenv(secret_name) else []
        if row["platform"] == "instagram":
            for name in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
                if not os.getenv(name):
                    missing.append(name)
        facts: dict[str, Any] = {
            "check_version": "production_readiness_v1",
            "live": live,
            "configured_secret_refs": [secret_name]
                + (["R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]
                   if row["platform"] == "instagram" else []),
            "resolved_secret_refs": sorted(set(
                [name for name in [secret_name, "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]
                 if os.getenv(name)]
            )),
        }
        if missing:
            return "blocked", ["missing local secret references: " + ", ".join(sorted(set(missing)))], facts
        if not live:
            return "unknown", ["live provider/account readiness has not been explicitly requested"], facts
        try:
            if row["platform"] == "instagram":
                if not confirm_r2_probe:
                    return "blocked", ["Instagram readiness requires the explicit transient R2 probe"], facts
                self._check_instagram(row, config, facts)
                facts["r2"] = self.relay_factory(config).probe()
            elif row["platform"] == "x":
                self._check_x(row, config, facts)
            else:
                return "blocked", ["unsupported platform"], facts
        except (DeliveryConfigurationError, DeliveryError) as error:
            facts["failure_category"] = (
                error.category if isinstance(error, DeliveryError) else "configuration"
            )
            return "blocked", [str(error)], facts
        except Exception as error:
            facts["failure_category"] = "unexpected"
            return "blocked", [f"readiness check failed ({type(error).__name__})"], facts
        return "ready", [], facts

    def _check_instagram(
        self, row: dict[str, Any], config: Mapping[str, Any], facts: dict[str, Any]
    ) -> None:
        version = str(config["graph_api_version"])
        token = str(os.environ[row["secret_ref"]])
        result = self.transport.request_json(
            "GET",
            f"https://graph.facebook.com/{version}/{row['provider_account_id']}?fields=id,username",
            headers={"Authorization": "Bearer " + token}, timeout=20, stage="meta_readiness",
        )
        if str(result.get("id", "")) != str(row["provider_account_id"]):
            raise DeliveryError("account_mismatch", "Meta returned a different account ID", False,
                                "meta_readiness")
        facts["provider_account_id"] = str(result["id"])
        facts["provider_username"] = str(result.get("username") or "")[:200]
        facts["graph_api_version"] = version

    def _check_x(
        self, row: dict[str, Any], config: Mapping[str, Any], facts: dict[str, Any]
    ) -> None:
        token = str(os.environ[row["secret_ref"]])
        origin = str(config["api_origin"]).rstrip("/")
        result = self.transport.request_json(
            "GET", origin + "/2/users/me?user.fields=id,username",
            headers={"Authorization": "Bearer " + token}, timeout=20, stage="x_readiness",
        )
        data = result.get("data")
        if not isinstance(data, dict) or str(data.get("id", "")) != str(row["provider_account_id"]):
            raise DeliveryError("account_mismatch", "X returned a different account ID", False,
                                "x_readiness")
        facts["provider_account_id"] = str(data["id"])
        facts["provider_username"] = str(data.get("username") or "")[:200]
        facts["api_origin"] = origin
