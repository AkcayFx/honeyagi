import asyncio
from datetime import datetime, timezone
import httpx
from .db import digest


CHECKS = {
    "content-security-policy": ("CSP missing", "medium", "Define a Content-Security-Policy suited to the application."),
    "x-content-type-options": ("MIME sniffing protection missing or invalid", "low", "Set X-Content-Type-Options: nosniff."),
    "referrer-policy": ("Referrer policy missing", "low", "Set Referrer-Policy, for example strict-origin-when-cross-origin."),
}


def analyse(status, headers):
    # A header configuration observation is not proof of an exploitable vulnerability.
    if not 200 <= status < 300:
        return [], "inconclusive: response was not successful; redirects are never followed"
    findings = []
    for name, (title, severity, recommendation) in CHECKS.items():
        missing = not headers.get(name, "").strip()
        if name == "x-content-type-options":
            missing = headers.get(name, "").strip().lower() != "nosniff"
        if missing:
            findings.append({"id": name, "title": title, "severity": severity,
                             "observation": f"Header observed: {headers.get(name) or '(absent)'}",
                             "recommendation": recommendation,
                             "confidence": "header observation; exploitability not assessed"})
    return findings, "observed"


class HeaderChecker:
    def __init__(self, timeout=5.0, transport=None):
        self.timeout, self.transport = timeout, transport

    async def run(self, target):
        async def fetch():
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), trust_env=False,
                                         follow_redirects=False, transport=self.transport) as client:
                async with client.stream("GET", target, headers={"User-Agent": "AssessmentLab/0.1"}) as response:
                    # Do not consume the body or retain cookies/authentication/server headers.
                    if sum(len(k) + len(v) for k, v in response.headers.multi_items()) > 32768:
                        raise ValueError("Response headers exceed the 32 KiB limit")
                    headers = {name: response.headers[name][:4096] for name in CHECKS if name in response.headers}
                    return response.status_code, headers
        status, headers = await asyncio.wait_for(fetch(), timeout=self.timeout)
        findings, conclusion = analyse(status, headers)
        evidence = {"target": target, "method": "GET", "status_code": status,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "headers": headers, "findings": findings, "conclusion": conclusion,
                    "limits": {"redirects_followed": False, "body_read": False, "timeout_seconds": self.timeout},
                    "coverage": "Presence of CSP and Referrer-Policy; exact nosniff value. No CSP semantic or exploit testing; HSTS omitted on HTTP lab."}
        evidence["sha256"] = digest(evidence)
        return evidence


def compare(previous, current):
    if previous["conclusion"] != "observed" or current["conclusion"] != "observed":
        return {"result": "inconclusive", "still_observed": [], "no_longer_observed": [], "new_observations": []}
    old = {f["id"] for f in previous["findings"]}
    new = {f["id"] for f in current["findings"]}
    return {"result": "compared", "still_observed": sorted(old & new),
            "no_longer_observed": sorted(old - new), "new_observations": sorted(new - old)}
