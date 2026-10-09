"""Build brief, graph and alert projections from the same retained evidence records."""

from __future__ import annotations

import hashlib

from ..models import Brief
from .base import RunContext, Step, StepResult
from .evidence import evidence_overlap
from .write import dated


def graph_data(ctx: RunContext) -> dict:
    nodes, edges = [{"id": "subject", "kind": "subject", "label": ctx.subject}], []
    accounts = {}
    for account in ctx.accounts:
        node_id = "account:" + hashlib.sha256(account.url.encode()).hexdigest()[:12]
        accounts[account.url] = node_id
        nodes.append(
            {
                "id": node_id,
                "kind": "account",
                "label": account.handle or account.platform,
                "platform": account.platform,
                "url": account.url,
                "match_basis": account.match_basis,
                "status": account.status,
                "profile": ctx.profiles.get(account.url),
            }
        )
        edges.append({"source": "subject", "target": node_id, "relation": "account"})
    for item in ctx.items:
        image = next((m for m in item.media if m.kind == "image"), None)
        nodes.append(
            {
                "id": item.id,
                "kind": "post",
                "platform": item.platform,
                "label": item.text[:140],
                "url": item.url,
                "published_at": item.published_at,
                "collected_at": item.collected_at,
                "metrics": item.metrics,
                "places": item.places,
                "thumb": f"/runs/{ctx.run_id}/{image.path}" if image else None,
            }
        )
        edges.append(
            {
                "source": accounts.get(item.account_url, "subject"),
                "target": item.id,
                "relation": "published",
            }
        )
    if ctx.brief:
        for section in ctx.brief.sections:
            for claim in section.items:
                if claim.kind not in ("fact", "inference"):
                    continue
                nodes.append(
                    {
                        "id": claim.id,
                        "kind": "claim",
                        "claim_kind": claim.kind,
                        "label": claim.text,
                        "confidence": claim.confidence,
                        "evidence": [e.model_dump() for e in claim.evidence],
                        "based_on": claim.based_on,
                        "section": section.title,
                    }
                )
                for evidence in claim.evidence:
                    edges.append(
                        {
                            "source": evidence.item_id,
                            "target": claim.id,
                            "relation": "supports",
                        }
                    )
                for fact_id in claim.based_on:
                    edges.append({"source": fact_id, "target": claim.id, "relation": "basis"})
    return {
        "run_id": ctx.run_id,
        "mode": ctx.mode,
        "source_run_id": ctx.source_run_id,
        "nodes": nodes,
        "edges": edges,
        "rejected": [r.model_dump() for r in ctx.rejected],
        "coverage": [c.model_dump() for c in ctx.coverage.values()],
        "profiles": list(ctx.profiles.values()),
        "topics": ctx.store.read_json(ctx.run_id, "topics.json") or [],
        "places": ctx.store.read_json(ctx.run_id, "places.json") or [],
    }


def alert_data(ctx: RunContext) -> dict:
    # A goal change is not a new observation. Compare with a previous collected snapshot only.
    origin = ctx.source_run_id or ctx.run_id
    origin_manifest = ctx.store.read_json(origin, "manifest.json") or {}
    observation = origin_manifest.get("started_at", ctx.started_at)
    prior = next(
        (
            r
            for r in ctx.store.list(limit=1000)
            if r["id"] != origin
            and r["mode"] == "live"
            and r["subject"] == ctx.subject
            and r["anchor"] == ctx.anchor
            and r["status"] == "finished"
            and r["created_at"] < observation
        ),
        None,
    )
    posts = [i for i in ctx.items if i.kind in ("post", "video") and dated(i.published_at)]
    latest = max(posts, key=lambda i: i.published_at, default=None)
    known = {i["id"] for i in (ctx.store.read_json(prior["id"], "items.json") or [])} if prior else set()
    new = [i for i in posts if prior and i.id not in known and i.published_at >= prior["created_at"]]
    trigger = max(new, key=lambda i: i.published_at, default=None)
    selected = trigger or latest
    return {
        "run_id": ctx.run_id,
        "mode": ctx.mode,
        "source_run_id": ctx.source_run_id,
        "status": "new" if trigger else ("no_change" if prior else "baseline"),
        "is_new": bool(trigger),
        "previous_run_id": prior["id"] if prior else None,
        "observed_at": observation,
        "goal_preset": "G2",
        "trigger_url": selected.url if selected else None,
        "item": selected.model_dump() if selected else None,
        "note": "New retained post since the previous collection"
        if trigger
        else (
            "No new dated post since the previous collection"
            if prior
            else "First retained snapshot; newest post is a preview, not a new-post detection"
        ),
    }


class Render(Step):
    id = "render"
    label = "Render"
    group = "downstream"

    async def run(self, ctx: RunContext) -> StepResult:
        if ctx.brief is None:
            return StepResult("skipped", note="No verified brief is available")
        graph, alert = graph_data(ctx), alert_data(ctx)
        ctx.save_json("network.json", graph)
        ctx.save_json("alert.json", alert)
        ctx.save_json(
            "render.json",
            {
                "run_id": ctx.run_id,
                "mode": ctx.mode,
                "source_run_id": ctx.source_run_id,
                "brief": f"/api/runs/{ctx.run_id}/brief",
                "network": f"/api/runs/{ctx.run_id}/network",
                "alert": f"/api/runs/{ctx.run_id}/alert",
                "coverage": [c.model_dump() for c in ctx.coverage.values()],
                "costs": ctx.costs.model_dump(),
                "limitations": ctx.brief.limitations,
            },
        )
        comparisons = []
        for other in ctx.store.list(limit=1000):
            if other["id"] == ctx.run_id or other["subject"] != ctx.subject or other["anchor"] != ctx.anchor:
                continue
            raw = ctx.store.read_json(other["id"], "brief.json")
            if (
                raw
                and raw["goal"]["preset"] != ctx.goal.preset
                and raw["run"].get("source_run_id") == ctx.source_run_id
            ):
                comparison = evidence_overlap(ctx.brief, Brief.model_validate(raw))
                comparison["other_run_id"] = other["id"]
                comparisons.append(comparison)
        ctx.save_json("evidence-overlap.json", comparisons)
        await ctx.data(
            self.id,
            network=graph,
            alert=alert,
            overlap=comparisons,
            costs=ctx.costs.model_dump(),
            summary=f"{len(graph['nodes'])} evidence nodes; alert {alert['status']}",
        )
        return StepResult(
            "done",
            count=len(graph["nodes"]),
            note="Brief, network, alert and citation-overlap projections saved",
        )
