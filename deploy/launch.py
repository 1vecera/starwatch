"""Deploy Starwatch: static app on S3 + CloudFront, sign-in and edge rules on Cloudflare.

Every step is idempotent and records resource handles in a local, Git-ignored state file.
Secrets come only from environment variables and go straight to AWS Secrets Manager or
Cloudflare Worker secrets; nothing secret is printed or written to disk.

    uv run --with boto3 python deploy/launch.py --config <config.json> keys cert cloudfront cloudflare worker site verify
"""

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3

HERE = Path(__file__).resolve().parent
HEADER = "x-starwatch-cloudflare-origin"
PROVIDER_ENV = {
    "GITHUB_ID": ["STARWATCH_GITHUB_ID", "GITHUB_CLIENT_ID"],
    "GITHUB_SECRET": ["STARWATCH_GITHUB_SECRET", "GITHUB_CLIENT_SECRET"],
    "GOOGLE_ID": ["STARWATCH_GOOGLE_ID", "GOOGLE_CLIENT_ID"],
    "GOOGLE_SECRET": ["STARWATCH_GOOGLE_SECRET", "GOOGLE_CLIENT_SECRET"],
    "FACEBOOK_ID": ["STARWATCH_FACEBOOK_ID", "FACEBOOK_APP_ID"],
    "FACEBOOK_SECRET": ["STARWATCH_FACEBOOK_SECRET", "FACEBOOK_APP_SECRET"],
}
# Files that must never be published even if they sit in the web folder.
SKIP = {".DS_Store"}
SKIP_PREFIXES = ("tmp/", "walkthrough-shots/")


class Deploy:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.cfg = json.loads(self.config_path.read_text())
        self.state_path = Path(self.cfg["state_file"])
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.aws = boto3.Session(region_name=self.cfg["aws_region"])
        self.host = self.cfg["host"]

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2) + "\n")

    # ---------- Cloudflare API ----------
    def cf(self, path, method="GET", payload=None, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if payload is not None else None)
        headers = {"Content-Type": content_type}
        if os.environ.get("CLOUDFLARE_API_TOKEN"):
            headers["Authorization"] = "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"]
        else:
            headers["X-Auth-Key"] = os.environ["CLOUDFLARE_GLOBAL_API_KEY"]
            headers["X-Auth-Email"] = os.environ.get("CLOUDFLARE_EMAIL") or os.environ["DAS_ITEM_CLOUDFLARE_ACCESS_TOKEN__EMAIL"]
        request = urllib.request.Request("https://api.cloudflare.com/client/v4" + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                errors = [(e.get("code"), e.get("message")) for e in json.load(exc).get("errors", [])]
            except ValueError:
                errors = []
            raise RuntimeError(f"Cloudflare {method} {path}: HTTP {exc.code} {errors}") from None
        if not result.get("success"):
            raise RuntimeError(f"Cloudflare {method} {path}: {result.get('errors')}")
        return result.get("result")

    @property
    def zone(self):
        if "zone_id" not in self.state:
            self.state["zone_id"] = self.cf(f"/zones?name={self.cfg['cloudflare_zone']}")[0]["id"]
            self.save()
        return self.state["zone_id"]

    # ---------- keys ----------
    def keys(self):
        """Session-signing and origin keys live in Secrets Manager; generated once."""
        sm = self.aws.client("secretsmanager")
        name = self.cfg["secret_name"]
        try:
            values = json.loads(sm.get_secret_value(SecretId=name)["SecretString"])
        except sm.exceptions.ResourceNotFoundException:
            values = {"session": secrets.token_hex(32), "origin": secrets.token_hex(32)}
            sm.create_secret(Name=name, SecretString=json.dumps(values), Tags=[{"Key": "Project", "Value": "Starwatch"}])
            print("keys: created", name)
        return values

    def legacy_origin(self):
        arn = self.cfg.get("legacy_secret_arn")
        if not arn:
            return ""
        values = json.loads(self.aws.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"])
        return values.get("cloudflare_origin", "")

    # ---------- certificate ----------
    def cert(self):
        acm = self.aws.client("acm", region_name="us-east-1")
        arn = self.state.get("cert_arn")
        if not arn:
            arn = acm.request_certificate(DomainName=self.host, ValidationMethod="DNS", IdempotencyToken="starwatch",
                                          Tags=[{"Key": "Project", "Value": "Starwatch"}])["CertificateArn"]
            self.state["cert_arn"] = arn
            self.save()
        for _ in range(60):
            cert = acm.describe_certificate(CertificateArn=arn)["Certificate"]
            if cert["Status"] == "ISSUED":
                print("cert: issued")
                return arn
            options = cert.get("DomainValidationOptions", [])
            record = options[0].get("ResourceRecord") if options else None
            if record and not self.state.get("cert_dns"):
                name = record["Name"].rstrip(".")
                existing = self.cf(f"/zones/{self.zone}/dns_records?name={name}")
                if not existing:
                    self.cf(f"/zones/{self.zone}/dns_records", "POST", {"type": "CNAME", "name": name, "content": record["Value"].rstrip("."),
                                                                         "proxied": False, "comment": "ACM validation for Starwatch"})
                self.state["cert_dns"] = name
                self.save()
                print("cert: validation record added")
            time.sleep(10)
        raise RuntimeError("certificate not issued yet; rerun the cert step")

    # ---------- CloudFront ----------
    def cloudfront(self):
        keys = self.keys()
        cfront = self.aws.client("cloudfront")
        name = self.cfg["cloudfront_function"]
        code = ((HERE / "aws/gate.js").read_text().replace("__SESSION_KEY__", keys["session"]).replace("__ORIGIN_KEY__", keys["origin"]))
        legacy = self.legacy_origin()
        if legacy:
            code = code.replace("__LEGACY_ORIGIN_KEY__", legacy)
        described = cfront.describe_function(Name=name, Stage="DEVELOPMENT")
        updated = cfront.update_function(Name=name, IfMatch=described["ETag"], FunctionCode=code.encode(),
                                         FunctionConfig={"Comment": "Starwatch: Cloudflare-only origin, public welcome, signed session",
                                                         "Runtime": "cloudfront-js-2.0"})
        cfront.publish_function(Name=name, IfMatch=updated["ETag"])
        print("cloudfront: gate published", "(legacy host kept)" if legacy else "")
        result = cfront.get_distribution_config(Id=self.cfg["distribution_id"])
        config = result["DistributionConfig"]
        aliases = set(config.get("Aliases", {}).get("Items", []))
        cert_arn = self.state.get("cert_arn")
        if self.host not in aliases and cert_arn:
            aliases.add(self.host)
            config["Aliases"] = {"Quantity": len(aliases), "Items": sorted(aliases)}
            config["ViewerCertificate"] = {"ACMCertificateArn": cert_arn, "SSLSupportMethod": "sni-only",
                                           "MinimumProtocolVersion": "TLSv1.2_2021", "Certificate": cert_arn, "CertificateSource": "acm"}
            config["Comment"] = "Starwatch: private S3 app behind Cloudflare sign-in"
            cfront.update_distribution(Id=self.cfg["distribution_id"], IfMatch=result["ETag"], DistributionConfig=config)
            print("cloudfront: alias", self.host, "added")
        self.state["cloudfront_domain"] = cfront.get_distribution(Id=self.cfg["distribution_id"])["Distribution"]["DomainName"]
        self.save()

    # ---------- Cloudflare rules ----------
    def ruleset(self, phase, ref, rule):
        """Create or replace one rule (matched by ref) in a zone phase entrypoint."""
        try:
            entry = self.cf(f"/zones/{self.zone}/rulesets/phases/{phase}/entrypoint")
            rules = [r for r in entry.get("rules", []) if r.get("ref") != ref]
        except RuntimeError:
            rules = []
        keep = [{k: v for k, v in r.items() if k in ("action", "action_parameters", "expression", "description", "enabled", "ref", "ratelimit")} for r in rules]
        self.cf(f"/zones/{self.zone}/rulesets/phases/{phase}/entrypoint", "PUT", {"rules": keep + [dict(rule, ref=ref)]})

    def cloudflare(self):
        keys = self.keys()
        host_expr = f'(http.host eq "{self.host}")'
        target = self.state.get("cloudfront_domain") or self.cfg["cloudfront_domain"]
        records = self.cf(f"/zones/{self.zone}/dns_records?name={self.host}")
        record = {"type": "CNAME", "name": self.host, "content": target, "proxied": True, "comment": "Starwatch app (CloudFront origin)"}
        if records and (records[0]["type"] != "CNAME" or records[0]["content"] != target):
            self.cf(f"/zones/{self.zone}/dns_records/{records[0]['id']}", "DELETE")
            records = []
        if not records:
            self.cf(f"/zones/{self.zone}/dns_records", "POST", record)
        print("cloudflare: DNS ->", target)
        self.ruleset("http_request_late_transform", "starwatch_origin_header", {
            "description": "Starwatch: private origin header for CloudFront", "expression": host_expr, "action": "rewrite",
            "action_parameters": {"headers": {HEADER: {"operation": "set", "value": keys["origin"]}}}})
        self.ruleset("http_request_cache_settings", "starwatch_no_edge_cache", {
            "description": "Starwatch: never cache signed-in content at Cloudflare", "expression": host_expr,
            "action": "set_cache_settings", "action_parameters": {"cache": False}})
        self.ruleset("http_config_settings", "starwatch_strict_tls", {
            "description": "Starwatch: strict TLS to CloudFront", "expression": host_expr,
            "action": "set_config", "action_parameters": {"ssl": "strict"}})
        try:
            self.ruleset("http_ratelimit", "starwatch_auth_rate", {
                "description": "Starwatch: slow down sign-in floods",
                "expression": f'{host_expr} and starts_with(http.request.uri.path, "/auth/")', "action": "block",
                "ratelimit": {"characteristics": ["ip.src", "cf.colo.id"], "period": 10, "requests_per_period": 20, "mitigation_timeout": 10}})
        except RuntimeError as exc:
            print("cloudflare: rate limit rule skipped:", str(exc)[:160])
        print("cloudflare: transform, cache, TLS and rate rules set")

    # ---------- Worker ----------
    def worker(self):
        keys = self.keys()
        subprocess.run(["npm", "run", "--silent", "build"], cwd=HERE / "edge", check=True)
        source = (HERE / "edge/dist/worker.mjs").read_text()
        account, script = self.cfg["cloudflare_account"], self.cfg["worker_name"]
        boundary = "----starwatch" + secrets.token_hex(8)
        meta = {"main_module": "worker.mjs", "compatibility_date": "2026-09-01", "keep_bindings": ["secret_text"],
                "observability": {"enabled": True},
                "bindings": [{"type": "plain_text", "name": "PUBLIC_HOST", "text": self.host},
                             {"type": "plain_text", "name": "SESSION_TTL", "text": "604800"}]}
        body = b""
        for name, ctype, content, filename in (("metadata", "application/json", json.dumps(meta), None),
                                               ("worker.mjs", "application/javascript+module", source, "worker.mjs")):
            disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
            body += f"--{boundary}\r\nContent-Disposition: {disposition}\r\nContent-Type: {ctype}\r\n\r\n".encode() + content.encode() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        self.cf(f"/accounts/{account}/workers/scripts/{script}", "PUT", body, f"multipart/form-data; boundary={boundary}")
        self.cf(f"/accounts/{account}/workers/scripts/{script}/subdomain", "POST", {"enabled": False, "previews_enabled": False})
        self.put_secret("SESSION_KEY", keys["session"])
        pushed = []
        for binding, names in PROVIDER_ENV.items():
            value = next((os.environ[n] for n in names if os.environ.get(n)), None)
            if value:
                self.put_secret(binding, value.strip())
                pushed.append(binding)
        present = sorted(s["name"] for s in self.cf(f"/accounts/{account}/workers/scripts/{script}/secrets"))
        print("worker: deployed; secrets pushed now:", pushed, "present:", present)
        wanted = [f"{self.host}/{p}" for p in ("login*", "auth/*", "privacy*", "data-deletion*")]
        routes = self.cf(f"/zones/{self.zone}/workers/routes")
        for route in routes:
            if route["pattern"].startswith(self.host + "/") and route["pattern"] not in wanted:
                self.cf(f"/zones/{self.zone}/workers/routes/{route['id']}", "DELETE")
        existing = {r["pattern"] for r in routes}
        for pattern in wanted:
            if pattern not in existing:
                self.cf(f"/zones/{self.zone}/workers/routes", "POST", {"pattern": pattern, "script": script})
        print("worker: routes", wanted)

    def put_secret(self, name, value):
        self.cf(f"/accounts/{self.cfg['cloudflare_account']}/workers/scripts/{self.cfg['worker_name']}/secrets", "PUT",
                {"name": name, "text": value, "type": "secret_text"})

    # ---------- site ----------
    def site(self):
        """Upload changed files (sha256 in object metadata), remove retired pages, invalidate."""
        web = Path(self.cfg["web_root"]).resolve()
        s3 = self.aws.client("s3")
        bucket = self.cfg["bucket"]
        remote = {}
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                remote[obj["Key"]] = obj["Size"]
        files = []
        for path in sorted(web.rglob("*")):
            if not path.is_file():
                continue
            key = path.relative_to(web).as_posix()
            if path.name in SKIP or key.startswith(SKIP_PREFIXES + tuple(self.cfg.get("exclude_prefixes", []))):
                continue
            files.append((key, path))

        def upload(item):
            key, path = item
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if key in remote and remote[key] == len(data):
                try:
                    if s3.head_object(Bucket=bucket, Key=key)["Metadata"].get("sha256") == digest:
                        return None
                except s3.exceptions.ClientError:
                    pass
            kind = "text/javascript" if path.suffix in (".js", ".mjs") else (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            if kind.startswith("text/") or kind in ("application/json", "image/svg+xml", "application/manifest+json"):
                kind += "; charset=utf-8"
            cache = "public, max-age=300" if path.suffix in (".html", ".js", ".css", ".json", ".webmanifest") else "public, max-age=86400"
            s3.upload_file(str(path), bucket, key, ExtraArgs={"ContentType": kind, "CacheControl": cache, "ServerSideEncryption": "AES256",
                                                               "Metadata": {"sha256": digest}})
            return key

        with ThreadPoolExecutor(8) as pool:
            changed = [k for k in pool.map(upload, files) if k]
        retired = [k for k in self.cfg.get("retire", []) if k in remote]
        for key in retired:
            s3.delete_object(Bucket=bucket, Key=key)
        paths = sorted({"/" + k for k in changed + retired} | {"/"})
        if paths:
            batch = paths if len(paths) <= 200 else ["/*"]
            self.aws.client("cloudfront").create_invalidation(DistributionId=self.cfg["distribution_id"], InvalidationBatch={
                "Paths": {"Quantity": len(batch), "Items": batch}, "CallerReference": f"site-{time.time_ns()}"})
        print(f"site: {len(changed)} uploaded, {len(retired)} retired, {len(files)} checked; invalidated {min(len(paths), 200)} paths")

    # ---------- verify ----------
    def verify(self):
        keys = self.keys()
        base = f"https://{self.host}"
        payload = f"v1.{int(time.time()) + 300}.{secrets.token_hex(16)}"
        session = "__Host-sw-session=" + payload + "." + hmac.new(keys["session"].encode(), payload.encode(), hashlib.sha256).hexdigest()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)

        def get(path, cookie=None, rng=None, origin=base):
            headers = {"User-Agent": "starwatch-verify"}
            if cookie:
                headers["Cookie"] = cookie
            if rng:
                headers["Range"] = rng
            try:
                with opener.open(urllib.request.Request(origin + path, headers=headers), timeout=30) as r:
                    return r.status, r.headers, r.read(200)
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers, b""

        checks = [
            ("welcome is public", get("/")[0] == 200),
            ("privacy is public", get("/privacy")[0] == 200),
            ("login page renders", get("/login")[0] == 200),
            ("atlas redirects to login", get("/atlas.html")[0] == 302 and get("/atlas.html")[1].get("location", "").startswith("/login")),
            ("data denied anonymously", get("/data/real.js")[0] == 401),
            ("data allowed with session", get("/data/real.js", session)[0] == 200),
            ("forged session refused", get("/data/real.js", session[:-1] + ("0" if session[-1] != "0" else "1"))[0] == 401),
            ("direct CloudFront refused", get("/atlas.html", session, origin="https://" + self.state.get("cloudfront_domain", self.cfg["cloudfront_domain"]))[0] == 403),
        ]
        media = self.cfg.get("verify_media")
        if media:
            status, headers, _ = get(media, session, "bytes=0-1023")
            checks.append(("video range served", status == 206 and headers.get("content-range", "").startswith("bytes 0-1023/")))
            checks.append(("video denied anonymously", get(media, None, "bytes=0-15")[0] == 401))
        for name, ok in checks:
            print(("PASS " if ok else "FAIL ") + name)
        if not all(ok for _, ok in checks):
            raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="JSON config (see deploy/config.example.json)")
    parser.add_argument("steps", nargs="+", choices=["keys", "cert", "cloudfront", "cloudflare", "worker", "site", "verify"])
    args = parser.parse_args()
    deploy = Deploy(args.config)
    for step in args.steps:
        result = getattr(deploy, step)()
        if step == "keys":
            print("keys: present", sorted(result))


if __name__ == "__main__":
    main()
