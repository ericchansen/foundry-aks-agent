"""Documentation contracts that do not require a browser or Azure access."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"


@pytest.mark.parametrize(
    ("filename", "nodes", "edges"),
    [
        (
            "architecture.svg",
            {"node-cli", "node-agent", "node-model", "node-insights", "node-foundry"},
            {"edge-port-forward", "edge-model-call", "edge-span-export", "edge-project-traces"},
        ),
        (
            "trace-chain.svg",
            {"node-request", "node-agent", "node-model"},
            {"edge-request-agent", "edge-agent-model"},
        ),
    ],
)
def test_diagrams_are_accessible_self_contained_and_keep_their_topology(filename, nodes, edges):
    source = (ROOT / "docs" / "assets" / filename).read_text(encoding="utf-8")
    assert "<!DOCTYPE" not in source and "<!ENTITY" not in source
    diagram = ET.fromstring(source)
    assert diagram.tag == f"{SVG}svg"
    assert diagram.get("viewBox") and diagram.get("role") == "img"
    assert diagram.find(f"{SVG}title").text
    assert diagram.find(f"{SVG}desc").text
    ids = [element.get("id") for element in diagram.iter() if element.get("id")]
    assert len(ids) == len(set(ids))
    assert set(diagram.get("aria-labelledby").split()) <= set(ids)
    assert {value for value in ids if value.startswith("node-")} == nodes
    assert {value for value in ids if value.startswith("edge-")} == edges
    assert set(re.findall(r"url\(#([^)]+)\)", source)) <= set(ids)
    for element in diagram.iter():
        assert element.tag not in {f"{SVG}script", f"{SVG}foreignObject"}
        for key, value in element.attrib.items():
            assert not key.lower().startswith("on")
            if key.endswith("href"):
                assert value.startswith("#") and value[1:] in ids


def test_navigation_covers_every_guide():
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))
    guides = set()
    for item in config["nav"]:
        for value in item.values():
            if isinstance(value, str):
                guides.add(value)
            else:
                guides.update(path for child in value for path in child.values())
    assert guides == {path.name for path in (ROOT / "docs").glob("*.md")}
    assert config["strict"] is True
    assert config["validation"]["links"]["anchors"] == "warn"


def test_pages_deployment_is_restricted_to_main():
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    )
    assert workflow["permissions"] == {"contents": "read"}
    assert "permissions" not in workflow["jobs"]["build"]
    deploy = workflow["jobs"]["deploy"]
    assert deploy["if"] == "github.ref == 'refs/heads/main'"
    assert deploy["needs"] == "build"
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["environment"]["name"] == "github-pages"
