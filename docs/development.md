# Local development

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). Development targets Windows
x64; the serving container targets Linux x64. Commands below run from the
repository root.

## Install and check

```powershell
uv sync --locked --all-extras
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest -q
```

The [tests](https://github.com/ericchansen/foundry-aks-agent/tree/main/tests) replace
the Azure OpenAI HTTP transport, not the Pydantic AI agent or instrumentation.
They assert one model request, rejected unauthenticated requests, model failures,
and matching agent/trace IDs on framework-generated spans.

These local contracts do not prove Azure model access or Foundry ingestion.
For offline Bicep compilation, follow the additional
[infrastructure validation instructions](infrastructure.md#offline-validation).

## Repository map

| Location | Responsibility |
| --- | --- |
| [`src/foundry_aks_agent/`](https://github.com/ericchansen/foundry-aks-agent/tree/main/src/foundry_aks_agent) | FastAPI endpoint, Pydantic agent, telemetry, CLI, registration |
| [`deploy/`](https://github.com/ericchansen/foundry-aks-agent/tree/main/deploy) | Restricted pod, ClusterIP service, service account, configuration |
| [`infra/`](https://github.com/ericchansen/foundry-aks-agent/tree/main/infra) | Staged Bicep and operator helpers |
| [`tests/`](https://github.com/ericchansen/foundry-aks-agent/tree/main/tests) | Runtime, deployment, and infrastructure contracts |
| [`docs/`](https://github.com/ericchansen/foundry-aks-agent/tree/main/docs) | Markdown guides and editable SVG diagrams |
| [`docs_theme/`](https://github.com/ericchansen/foundry-aks-agent/tree/main/docs_theme) | Small, script-free documentation theme |

## Runtime dependencies

The [project manifest](https://github.com/ericchansen/foundry-aks-agent/blob/main/pyproject.toml)
and committed `uv.lock` are the dependency sources of truth. The runtime pins
Pydantic AI 2.31.1 and explicitly uses version 5 instrumentation. Research about
newer releases is not an upgrade requirement. See
[Pydantic instrumentation](https://ai.pydantic.dev/logfire/).

The `admin` extra contains the Foundry registration SDK. It stays outside the
serving image; the CLI calls the existing runtime rather than running an agent
on the operator's machine. For cloud execution, continue with
[configuration](configuration.md) and [deployment](deployment.md).

## Work on these docs

The site uses [MkDocs](https://www.mkdocs.org/) with a local theme, no browser
JavaScript, and no remote fonts. Its pinned
[`requirements.txt`](requirements.txt) is separate from the runtime lockfile
and registration dependencies. `--no-project` keeps these commands out of the
runtime environment.

```powershell
uv run --no-project --with-requirements docs/requirements.txt mkdocs serve --dev-addr 127.0.0.1:8001
```

Open the URL printed by MkDocs. To check the static output, including internal
Markdown links and anchors:

```powershell
uv run --no-project --with-requirements docs/requirements.txt mkdocs build --strict
```

The generated `site/` directory is ignored. Edit the Markdown source, not the
generated HTML. Navigation lives in
[`mkdocs.yml`](https://github.com/ericchansen/foundry-aks-agent/blob/main/mkdocs.yml).
Keep diagrams as self-contained SVG with accessible titles/descriptions, exact
labels, and separately labeled request/telemetry paths. Use solid arrows by
default; dotted or dashed lines must encode a distinction explained in the diagram.
The design follows
[nice-deck's precise-diagram guidance](https://github.com/ericchansen/nice-deck/blob/main/.github/skills/_shared/nice-deck/references/architecture-diagrams.md).

## GitHub Pages publishing

The [docs workflow](https://github.com/ericchansen/foundry-aks-agent/blob/main/.github/workflows/docs.yml)
builds pull requests without deployment permissions and publishes only from
`main`. To enable the first deployment, choose **Settings > Pages > Build and
deployment > Source > GitHub Actions** in the repository's
[Pages settings](https://github.com/ericchansen/foundry-aks-agent/settings/pages).
See [GitHub's custom workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

After merge and a successful deployment, the public address is
[ericchansen.github.io/foundry-aks-agent](https://ericchansen.github.io/foundry-aks-agent/).
Publishing the documentation never deploys or exposes the agent runtime.
