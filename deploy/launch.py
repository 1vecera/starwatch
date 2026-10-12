"""Deploy Starwatch: a public static app on S3 + CloudFront, fronted by Cloudflare.

Every step is idempotent and records resource handles in a local, Git-ignored state file.
Secrets come only from environment variables or AWS Secrets Manager; nothing secret is printed or written to disk.

    uv run --with boto3 python deploy/launch.py --config <config.json> keys cert cloudfront cloudflare redirects site verify
"""

import argparse
import hashlib
import json
import mimetypes
import os
import secrets
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3

HERE = Path(__file__).resolve().parent
HEADER = "x-starwatch-cloudflare-origin"
# Files that must never be published even if they sit in the web folder.
SKIP = {".DS_Store"}
SKIP_PREFIXES = ("tmp/", "walkthrough-shots/")
# Rules from the signed-in setup that the public site no longer needs.
RETIRED_RULES = {"http_request_cache_settings": "starwatch_no_edge_cache", "http_ratelimit": "starwatch_auth_rate"}


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
        """The private origin key lives in Secrets Manager; generated once."""
        sm = self.aws.client("secretsmanager")
        name = self.cfg["secret_name"]
        try:
            values = json.loads(sm.get_secret_value(SecretId=name)["SecretString"])
        except sm.exceptions.ResourceNotFoundException:
            values = {"origin": secrets.token_hex(32)}
            sm.create_secret(Name=name, SecretString=json.dumps(values), Tags=[{"Key": "Project", "Value": "Starwatch"}])
            print("keys: created", name)
        return values

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
        code = (HERE / "aws/gate.js").read_text().replace("__ORIGIN_KEY__", keys["origin"])
        described = cfront.describe_function(Name=name, Stage="DEVELOPMENT")
        updated = cfront.update_function(Name=name, IfMatch=described["ETag"], FunctionCode=code.encode(),
                                         FunctionConfig={"Comment": "Starwatch: public app, Cloudflare-only origin",
                                                         "Runtime": "cloudfront-js-2.0"})
        cfront.publish_function(Name=name, IfMatch=updated["ETag"])
        print("cloudfront: gate published")
        result = cfront.get_distribution_config(Id=self.cfg["distribution_id"])
        config = result["DistributionConfig"]
        aliases = config.get("Aliases", {}).get("Items", [])
        cert_arn = self.state.get("cert_arn")
        # The distribution answers only for the current host; earlier hosts are redirected at Cloudflare.
        if cert_arn and (aliases != [self.host] or config["ViewerCertificate"].get("ACMCertificateArn") != cert_arn):
            config["Aliases"] = {"Quantity": 1, "Items": [self.host]}
            config["ViewerCertificate"] = {"ACMCertificateArn": cert_arn, "SSLSupportMethod": "sni-only",
                                           "MinimumProtocolVersion": "TLSv1.2_2021", "Certificate": cert_arn, "CertificateSource": "acm"}
            config["Comment"] = "Starwatch: public app on a private S3 bucket, behind Cloudflare"
            cfront.update_distribution(Id=self.cfg["distribution_id"], IfMatch=result["ETag"], DistributionConfig=config)
            print("cloudfront: alias set to", self.host, "(was", aliases, ")")
        self.state["cloudfront_domain"] = cfront.get_distribution(Id=self.cfg["distribution_id"])["Distribution"]["DomainName"]
        self.save()

    # ---------- Cloudflare rules ----------
    def zone_of(self, host):
        """The zone id for a hostname, by its longest matching zone name."""
        parts = host.split(".")
        for i in range(len(parts) - 1):
            found = self.cf(f"/zones?name={'.'.join(parts[i:])}")
            if found:
                return found[0]["id"]
        raise RuntimeError(f"no Cloudflare zone for {host}")

    def ruleset(self, phase, ref, rule, zone=None):
        """Create or replace one rule (matched by ref) in a zone phase entrypoint; rule=None removes it."""
        zone = zone or self.zone
        try:
            entry = self.cf(f"/zones/{zone}/rulesets/phases/{phase}/entrypoint")
            rules = entry.get("rules", [])
        except RuntimeError:
            rules = []
        if rule is None and not any(r.get("ref") == ref for r in rules):
            return False
        keep = [{k: v for k, v in r.items() if k in ("action", "action_parameters", "expression", "description", "enabled", "ref", "ratelimit")}
                for r in rules if r.get("ref") != ref]
        self.cf(f"/zones/{zone}/rulesets/phases/{phase}/entrypoint", "PUT", {"rules": keep + ([dict(rule, ref=ref)] if rule else [])})
        return True

    def cloudflare(self):
        keys = self.keys()
        host_expr = f'(http.host eq "{self.host}")'
        target = self.state.get("cloudfront_domain") or self.cfg["cloudfront_domain"]
        records = self.cf(f"/zones/{self.zone}/dns_records?name={self.host}")
        record = {"type": "CNAME", "name": self.host, "content": target, "proxied": True, "comment": "Starwatch app (CloudFront origin)"}
        if records and (records[0]["type"] != "CNAME" or records[0]["content"] != target or not records[0]["proxied"]):
            self.cf(f"/zones/{self.zone}/dns_records/{records[0]['id']}", "DELETE")
            records = []
        if not records:
            self.cf(f"/zones/{self.zone}/dns_records", "POST", record)
        print("cloudflare: DNS ->", target)
        self.ruleset("http_request_late_transform", "starwatch_origin_header", {
            "description": "Starwatch: private origin header for CloudFront", "expression": host_expr, "action": "rewrite",
            "action_parameters": {"headers": {HEADER: {"operation": "set", "value": keys["origin"]}}}})
        self.ruleset("http_config_settings", "starwatch_strict_tls", {
            "description": "Starwatch: strict TLS to CloudFront", "expression": host_expr,
            "action": "set_config", "action_parameters": {"ssl": "strict"}})
        for phase, ref in RETIRED_RULES.items():
            if self.ruleset(phase, ref, None):
                print("cloudflare: removed", ref)
        print("cloudflare: origin header and strict TLS set; static files use Cloudflare's default cache")

    # ---------- earlier hostnames ----------
    def redirects(self):
        """Send every earlier hostname to the current one (301, path and query kept) and retire its edge pieces."""
        account = self.cfg["cloudflare_account"]
        for old in self.cfg.get("redirect_hosts", []):
            zone = self.zone_of(old)
            expr = f'(http.host eq "{old}")'
            self.ruleset("http_request_dynamic_redirect", "starwatch_moved", {
                "description": f"Starwatch moved to {self.host}", "expression": expr, "action": "redirect",
                "action_parameters": {"from_value": {"status_code": 301, "preserve_query_string": True,
                                                     "target_url": {"expression": f'concat("https://{self.host}", http.request.uri.path)'}}}}, zone)
            for route in self.cf(f"/zones/{zone}/workers/routes"):
                if route["pattern"].startswith(old + "/"):
                    self.cf(f"/zones/{zone}/workers/routes/{route['id']}", "DELETE")
                    print("redirects: route removed", route["pattern"])
            for phase, ref in [("http_request_late_transform", "starwatch_origin_header"), ("http_config_settings", "starwatch_strict_tls"), *RETIRED_RULES.items()]:
                if self.ruleset(phase, ref, None, zone):
                    print("redirects: removed", ref, "from", old)
            for app in self.cf(f"/accounts/{account}/access/apps"):
                if app.get("domain") == old:
                    self.cf(f"/accounts/{account}/access/apps/{app['id']}", "DELETE")
                    print("redirects: Access application removed for", old)
            print("redirects:", old, "->", self.host)
        scripts = {w["id"] for w in self.cf(f"/accounts/{account}/workers/scripts")}
        for name in self.cfg.get("retire_workers", []):
            if name in scripts:
                self.cf(f"/accounts/{account}/workers/scripts/{name}", "DELETE")
                print("redirects: Worker deleted", name)

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
        base = f"https://{self.host}"

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)

        def get(path, rng=None, origin=base):
            headers = {"User-Agent": "starwatch-verify"}
            if rng:
                headers["Range"] = rng
            try:
                with opener.open(urllib.request.Request(origin + path, headers=headers), timeout=30) as r:
                    return r.status, r.headers, r.read(200)
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers, b""

        checks = [("welcome is public", get("/")[0] == 200)]
        for path in ("/atlas.html", "/spotlight.html", "/pulse.html", "/radar.html", "/data.html", "/about.html", "/privacy.html",
                     "/data/real.js", "/data/results2026.js", "/data/stats.js"):
            checks.append((f"{path} is public", get(path)[0] == 200))
        status, headers, _ = get("/login")
        checks.append(("old sign-in path goes home", status == 301 and headers.get("location") == "/"))
        checks.append(("direct CloudFront refused", get("/atlas.html", origin="https://" + self.state.get("cloudfront_domain", self.cfg["cloudfront_domain"]))[0] == 403))
        media = self.cfg.get("verify_media")
        if media:
            status, headers, _ = get(media, "bytes=0-1023")
            checks.append(("video range served", status == 206 and headers.get("content-range", "").startswith("bytes 0-1023/")))
        for old in self.cfg.get("redirect_hosts", []):
            status, headers, _ = get("/atlas.html?city=554782", origin=f"https://{old}")
            checks.append((f"{old} redirects", status == 301 and headers.get("location") == f"{base}/atlas.html?city=554782"))
        for name, ok in checks:
            print(("PASS " if ok else "FAIL ") + name)
        if not all(ok for _, ok in checks):
            raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, help="JSON config (see deploy/config.example.json)")
    parser.add_argument("steps", nargs="+", choices=["keys", "cert", "cloudfront", "cloudflare", "redirects", "site", "verify"])
    args = parser.parse_args()
    deploy = Deploy(args.config)
    for step in args.steps:
        result = getattr(deploy, step)()
        if step == "keys":
            print("keys: present", sorted(result))


if __name__ == "__main__":
    main()
