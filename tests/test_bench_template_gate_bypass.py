"""Every template-promotion call site goes through the gate (gate-bypass guard).

The novelty gate is only worth having if there is no second door. ``update_template``
is the low-level writer and is legitimately used by two kinds of caller:

- one-shot data scripts that publish a *known* version out of band
  (``publish_legal_template_v2.py``, ``publish_gov_template_v2.py``,
  ``migrate_template_layers.py``) — these predate the gate and carry their own
  review, and
- the gate itself.

Everything else — the admin form, any future web route — must call
``promote_template_via_gate``. A new unmarked call site fails this test, which is
the cheapest possible way to notice that somebody opened a second door.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("src", "scripts")

#: Files allowed to call the raw writer, each with the reason it is not a door.
ALLOWED = {
    "src/bench/templates.py": "the writer itself",
    "src/bench/template_readiness.py": "the gate, which must call the writer",
    "scripts/publish_legal_template_v2.py": "one-shot published-version script (pre-gate, reviewed)",
    "scripts/publish_gov_template_v2.py": "one-shot published-version script (pre-gate, reviewed)",
    "scripts/migrate_template_layers.py": "additive schema stamp, no vocabulary change",
    "scripts/register_legal_domain.py": "retro-registration of the first template",
    "scripts/register_layered_templates.py": "first-version creation only (no promotion)",
    "scripts/import_protocol_ontology.py": "read-only import; new upstream version is not a promotion",
}

_CALL = re.compile(r"\b(?:templates|bench_templates)\.update_template\s*\(")

#: A call site that exists **to be refused**: it invokes the writer with a machine
#: identity precisely so the hard-stop guard fires. Adding such a file to ALLOWED
#: would be wrong — that dict means "may promote without the gate", while this
#: means "may try and must be stopped". The marker is explicit so a real second
#: door cannot get in by looking vaguely like a probe.
_REFUSAL_PROBE = re.compile(r"#\s*gate-probe:\s*\S+")
_PROBE_CALL = re.compile(
    r"update_template\([^)]*created_by\s*=\s*(?:agent|fleet|extract)", re.S
)


def _is_refusal_probe(text: str) -> bool:
    """The file says it probes the gate **and** passes a machine identity to it.

    Both halves are required: the comment alone would let anyone opt out with a
    one-line marker, and the machine-identity argument alone could be a typo in a
    real promotion. Together they describe exactly one thing — an attempt the
    hard-stop guard must refuse.
    """
    return bool(_REFUSAL_PROBE.search(text)) and bool(_PROBE_CALL.search(text))


def test_no_unmarked_update_template_call_sites():
    offenders: list[str] = []
    for directory in SCAN_DIRS:
        for path in (REPO_ROOT / directory).rglob("*.py"):
            rel = str(path.relative_to(REPO_ROOT))
            if rel in ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if _CALL.search(text) and not _is_refusal_probe(text):
                offenders.append(rel)
    assert not offenders, (
        "these call sites write a new template version without passing the "
        "novelty gate; use promote_template_via_gate, or add the file to "
        f"ALLOWED with a reason: {sorted(offenders)}"
    )


def test_every_allowlisted_file_still_exists():
    """A stale allowlist entry is a guard that quietly stopped covering anything."""
    missing = [rel for rel in ALLOWED if not (REPO_ROOT / rel).exists()]
    assert not missing, f"allowlist names files that no longer exist: {missing}"


def test_a_comment_alone_cannot_opt_out():
    """The marker without a machine-identity call is not a probe.

    Otherwise anyone could add `# gate-probe: x` to a real second door and this
    guard would wave it through — the comment is the cheap half to fake.
    """
    text = (
        "# gate-probe: whatever\n"
        "templates.update_template(conn, name='t', schema={}, created_by='lead-1')\n"
    )
    assert not _is_refusal_probe(text)


def test_the_real_probe_shape_is_recognised():
    text = (
        "# gate-probe: change_template_version\n"
        "templates.update_template(conn, name='t', schema={},\n"
        "                          created_by=agent)\n"
    )
    assert _is_refusal_probe(text)
